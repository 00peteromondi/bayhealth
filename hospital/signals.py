from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from core.services import send_user_notification
from core.services import broadcast_hospital_update

from .models import Appointment, Admission, Billing, ConditionCatalog, LabTestResult, MedicalRecord, PatientCondition, PatientVisit, SurgicalCase, WalkInEvent
from .models import LabTestRequest, PharmacyTask, WalkInEncounter


@receiver(post_save, sender=Appointment)
def appointment_notification(sender, instance: Appointment, created: bool, **kwargs):
    if created:
        send_user_notification(
            instance.patient.user,
            "Appointment booked",
            (
                f"Your appointment with {instance.doctor} is booked for "
                f"{instance.appointment_date} at {instance.appointment_time}."
            ),
        )
        send_user_notification(
            instance.doctor.user,
            "New appointment request",
            f"{instance.patient} booked a consultation for {instance.appointment_date}.",
        )
        PatientVisit.objects.get_or_create(
            appointment=instance,
            defaults={
                "patient": instance.patient,
                "hospital": instance.hospital,
                "visit_type": "consultation",
            },
        )
    elif instance.status in {
        Appointment.Status.CONFIRMED,
        Appointment.Status.CANCELLED,
        Appointment.Status.PAST,
    }:
        send_user_notification(
            instance.patient.user,
            "Appointment updated",
            f"Your appointment status is now {instance.get_status_display().lower()}.",
        )
        send_user_notification(
            instance.doctor.user,
            "Appointment updated",
            f"{instance.patient}'s appointment status is now {instance.get_status_display().lower()}.",
        )
    broadcast_hospital_update(
        instance.hospital,
        event_type="appointment_updated",
        payload={
            "patient_id": instance.patient_id,
            "appointment_id": instance.id,
            "status": instance.status,
            "status_label": instance.get_status_display(),
        },
    )


@receiver(post_save, sender=Billing)
def billing_notification(sender, instance: Billing, created: bool, **kwargs):
    if created:
        send_user_notification(
            instance.patient.user,
            "Billing generated",
            f"A billing record of {instance.amount} has been generated for your care episode.",
        )
    broadcast_hospital_update(
        instance.hospital,
        event_type="billing_updated",
        payload={
            "patient_id": instance.patient_id,
            "billing_id": instance.id,
        },
    )


@receiver(post_save, sender=SurgicalCase)
def surgery_notification(sender, instance: SurgicalCase, created: bool, **kwargs):
    if created:
        return
    if instance.status not in {
        SurgicalCase.Status.PAST,
        SurgicalCase.Status.COMPLETED,
        SurgicalCase.Status.CANCELLED,
        SurgicalCase.Status.POSTPONED,
    }:
        return
    send_user_notification(
        instance.patient.user,
        "Surgery updated",
        f"Your surgical case for {instance.procedure_name} is now {instance.get_status_display().lower()}.",
    )
    send_user_notification(
        instance.surgeon.user,
        "Surgery updated",
        f"{instance.patient}'s surgical case for {instance.procedure_name} is now {instance.get_status_display().lower()}.",
    )
    broadcast_hospital_update(
        instance.hospital,
        event_type="surgery_updated",
        payload={
            "patient_id": instance.patient_id,
            "surgery_id": instance.id,
            "status": instance.status,
            "status_label": instance.get_status_display(),
        },
    )


def _extract_condition_fragments(diagnosis: str):
    raw = diagnosis.replace("\n", ",").replace(";", ",").replace("|", ",").replace("/", ",")
    return [fragment.strip(" .-") for fragment in raw.split(",") if fragment.strip(" .-")]


def _resolve_condition_catalog(label: str, notes: str = ""):
    catalog = ConditionCatalog.objects.filter(name__iexact=label).first()
    if catalog:
        return catalog
    for item in ConditionCatalog.objects.filter(is_active=True):
        keywords = [keyword.strip().lower() for keyword in item.keywords.split(",") if keyword.strip()]
        searchable = f"{item.name} {item.description} {item.keywords}".lower()
        if label.lower() in searchable or any(keyword in label.lower() for keyword in keywords):
            return item
    return ConditionCatalog.objects.create(name=label.title(), description=notes[:500])


def _sync_conditions_from_text(*, patient, hospital, recorded_by, source_text: str, notes: str = ""):
    if not source_text:
        return
    fragments = _extract_condition_fragments(source_text)
    for fragment in fragments:
        catalog = _resolve_condition_catalog(fragment, notes)
        PatientCondition.objects.get_or_create(
            patient=patient,
            hospital=hospital,
            condition=catalog,
            condition_name=catalog.name,
            is_active=True,
            defaults={
                "recorded_by": recorded_by,
                "diagnosed_at": timezone.localdate(),
                "notes": notes[:1000],
            },
        )


@receiver(post_save, sender=MedicalRecord)
def record_condition_from_medical_record(sender, instance: MedicalRecord, created: bool, **kwargs):
    PatientCondition.objects.filter(medical_record=instance).delete()
    if not instance.diagnosis:
        return
    fragments = _extract_condition_fragments(instance.diagnosis)
    for fragment in fragments:
        catalog = _resolve_condition_catalog(fragment, instance.notes)
        PatientCondition.objects.create(
            patient=instance.patient,
            hospital=instance.hospital,
            condition=catalog,
            medical_record=instance,
            recorded_by=instance.doctor,
            condition_name=catalog.name,
            diagnosed_at=timezone.localdate(),
            notes=instance.notes,
            is_active=True,
        )
    broadcast_hospital_update(
        instance.hospital,
        event_type="medical_record_updated",
        payload={
            "patient_id": instance.patient_id,
            "medical_record_id": instance.id,
        },
    )


@receiver(post_save, sender=LabTestResult)
def record_condition_from_lab_result(sender, instance: LabTestResult, created: bool, **kwargs):
    request = instance.request
    if request.status != request.Status.COMPLETED:
        request.status = request.Status.COMPLETED
        request.save(update_fields=["status"])
    if request.walk_in_encounter_id:
        encounter = request.walk_in_encounter
        encounter.lab_summary = instance.result_summary
        encounter.status = encounter.Status.LAB_READY
        encounter.save(update_fields=["lab_summary", "status", "last_updated_at"])
        WalkInEvent.objects.create(
            encounter=encounter,
            actor=instance.recorded_by.user if instance.recorded_by_id else None,
            stage="lab_result",
            note=f"Lab result completed for {request.test_name}.",
        )
        if encounter.attending_doctor_id:
            send_user_notification(
                encounter.attending_doctor.user,
                "Walk-in lab result ready",
                f"Lab results for {encounter.patient} are now ready for review.",
            )
    _sync_conditions_from_text(
        patient=request.patient,
        hospital=request.hospital,
        recorded_by=request.requested_by,
        source_text=instance.result_summary,
        notes=f"Lab result: {instance.result_summary[:1000]}",
    )
    send_user_notification(
        request.patient.user,
        "Lab result available",
        f"Results for {request.test_name} are now available in your BayAfya record.",
    )
    broadcast_hospital_update(
        request.hospital,
        event_type="lab_result_updated",
        payload={
            "patient_id": request.patient_id,
            "lab_request_id": request.id,
            "lab_result_id": instance.id,
        },
    )


@receiver(post_save, sender=Admission)
def admission_visit(sender, instance: Admission, created: bool, **kwargs):
    if created:
        PatientVisit.objects.get_or_create(
            admission=instance,
            defaults={
                "patient": instance.patient,
                "hospital": instance.hospital,
                "visit_type": "admission",
                "notes": instance.admission_reason,
            },
        )
    broadcast_hospital_update(
        instance.hospital,
        event_type="admission_updated",
        payload={
            "patient_id": instance.patient_id,
            "admission_id": instance.id,
            "status": instance.status,
            "status_label": instance.get_status_display(),
        },
    )


@receiver(post_save, sender=WalkInEncounter)
def walk_in_updated(sender, instance: WalkInEncounter, created: bool, **kwargs):
    broadcast_hospital_update(
        instance.hospital,
        event_type="walk_in_updated",
        payload={
            "patient_id": instance.patient_id,
            "walk_in_id": instance.id,
            "status": instance.status,
            "status_label": instance.get_status_display(),
            "severity_index": instance.severity_index,
        },
    )


@receiver(post_save, sender=LabTestRequest)
def lab_request_updated(sender, instance: LabTestRequest, created: bool, **kwargs):
    broadcast_hospital_update(
        instance.hospital,
        event_type="lab_request_updated",
        payload={
            "patient_id": instance.patient_id,
            "lab_request_id": instance.id,
            "status": instance.status,
            "status_label": instance.get_status_display(),
        },
    )


@receiver(post_save, sender=PharmacyTask)
def pharmacy_task_updated(sender, instance: PharmacyTask, created: bool, **kwargs):
    broadcast_hospital_update(
        instance.hospital,
        event_type="pharmacy_task_updated",
        payload={
            "patient_id": instance.patient_id,
            "task_id": instance.id,
            "status": instance.status,
            "status_label": instance.get_status_display(),
        },
    )
