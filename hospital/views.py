import hashlib
import secrets
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from core.assistant import analyze_walk_in_severity
from core.models import User
from core.models import Notification
from core.models import AssistantAccessGrant
from core.permissions import doctor_required, patient_required
from core.services import broadcast_hospital_update, send_user_notification
from .billing import (
    STANDARD_RATES,
    ensure_admission_bill,
    ensure_bed_transfer_bill,
    ensure_consultation_bill,
    ensure_discharge_bill,
    ensure_lab_bill,
    ensure_pharmacy_bill,
    ensure_walk_in_registration_bill,
    ensure_walk_in_triage_bill,
)

from .forms import (
    AdmissionForm,
    AdvanceDirectiveForm,
    AppointmentForm,
    BedTransferForm,
    CarePlanForm,
    CaregiverAccessForm,
    DischargeSummaryForm,
    DoctorTaskForm,
    EmergencyIncidentForm,
    FollowUpAppointmentForm,
    HospitalInvitationForm,
    InternalReferralForm,
    LabQualityControlLogForm,
    MedicalRecordForm,
    NurseTriageForm,
    PatientConditionForm,
    PatientDeathRecordForm,
    PatientFeedbackForm,
    PharmacyTaskUpdateForm,
    ShiftHandoverForm,
    ShiftAssignmentForm,
    eligible_shift_staff_queryset,
    format_shift_staff_label,
    scheduled_shift_hours_for_week,
    SupplyRequestForm,
    SupplyRequestStatusForm,
    SurgicalCaseForm,
    WalkInConsultationForm,
    WalkInIntakeForm,
    WalkInLabResultForm,
)
from core.forms import AssistantAccessGrantForm
from .models import (
    Admission,
    AdvanceDirective,
    Appointment,
    Bed,
    BedTransfer,
    Billing,
    CarePlan,
    CaregiverAccess,
    ConditionCatalog,
    Doctor,
    DoctorTask,
    DischargeSummary,
    HospitalAccess,
    HospitalInvitation,
    Hospital,
    InternalReferral,
    LabQualityControlLog,
    LabTestRequest,
    LabTestResult,
    MedicalRecord,
    OperatingRoom,
    Patient,
    PatientCondition,
    PatientFeedback,
    PatientVisit,
    PharmacyTask,
    QueueTicket,
    ShiftHandover,
    ShiftAssignment,
    StaffProfile,
    SupplyRequest,
    SurgicalCase,
    VitalSign,
    WalkInEncounter,
    WalkInEvent,
    Ward,
    EmergencyIncident,
)
from mental_health.models import TherapySession, WellnessResource
from telemedicine.models import VideoConsultation
from ambulance.models import AmbulanceRequest
from pharmacy.models import Medicine


OWNER_ROLES = {HospitalAccess.Role.OWNER, HospitalAccess.Role.ADMIN}
STAFF_INVITER_ROLES = {
    HospitalAccess.Role.DOCTOR,
    HospitalAccess.Role.NURSE,
    HospitalAccess.Role.RECEPTIONIST,
    HospitalAccess.Role.LAB_TECHNICIAN,
    HospitalAccess.Role.EMERGENCY_OPERATOR,
}
STAFF_ROLES = {
    User.Role.DOCTOR,
    User.Role.NURSE,
    User.Role.RECEPTIONIST,
    User.Role.LAB_TECHNICIAN,
    User.Role.PHARMACIST,
    User.Role.COUNSELOR,
}


def _notify_hospital_admins(hospital, title, message, exclude_user=None):
    if not hospital:
        return
    recipients = HospitalAccess.objects.select_related("user").filter(
        hospital=hospital,
        role__in=[HospitalAccess.Role.OWNER, HospitalAccess.Role.ADMIN],
    )
    for access in recipients:
        if exclude_user and access.user_id == exclude_user.id:
            continue
        Notification.objects.create(user=access.user, title=title, message=message)


def _notify_hospital_roles(hospital, roles, title, message, exclude_user=None):
    if not hospital:
        return
    recipients = HospitalAccess.objects.select_related("user").filter(
        hospital=hospital,
        role__in=roles,
    )
    for access in recipients:
        if exclude_user and access.user_id == exclude_user.id:
            continue
        Notification.objects.create(user=access.user, title=title, message=message)


def _log_walk_in_event(encounter, stage, note, actor=None):
    if not encounter:
        return
    WalkInEvent.objects.create(
        encounter=encounter,
        actor=actor,
        stage=stage,
        note=note,
    )


def _walk_in_queryset(hospital):
    queryset = WalkInEncounter.objects.select_related(
        "patient__user",
        "hospital",
        "attending_doctor__user",
        "registered_by",
        "triaged_by",
    )
    if hospital:
        queryset = queryset.filter(hospital=hospital)
    return queryset


def _walk_in_dashboard_context(hospital):
    encounters = _walk_in_queryset(hospital)
    lab_requests = LabTestRequest.objects.select_related("patient__user", "requested_by__user", "walk_in_encounter")
    pharmacy_tasks = PharmacyTask.objects.select_related("patient__user", "walk_in_encounter")
    if hospital:
        lab_requests = lab_requests.filter(hospital=hospital)
        pharmacy_tasks = pharmacy_tasks.filter(hospital=hospital)

    return {
        "walk_in_summary": {
            "waiting_triage": encounters.filter(status=WalkInEncounter.Status.WAITING_TRIAGE).count(),
            "waiting_doctor": encounters.filter(
                status__in=[
                    WalkInEncounter.Status.TRIAGED,
                    WalkInEncounter.Status.WAITING_DOCTOR,
                    WalkInEncounter.Status.LAB_READY,
                ]
            ).count(),
            "critical": encounters.filter(is_critical=True).exclude(status__in=[WalkInEncounter.Status.COMPLETED, WalkInEncounter.Status.CANCELLED]).count(),
            "awaiting_lab": lab_requests.filter(status__in=[LabTestRequest.Status.REQUESTED, LabTestRequest.Status.IN_PROGRESS]).count(),
            "awaiting_pharmacy": pharmacy_tasks.filter(status__in=[PharmacyTask.Status.PENDING, PharmacyTask.Status.IN_PROGRESS]).count(),
        },
        "walk_in_waiting_triage": encounters.filter(status=WalkInEncounter.Status.WAITING_TRIAGE).order_by("arrived_at")[:12],
        "walk_in_doctor_queue": encounters.filter(
            status__in=[
                WalkInEncounter.Status.TRIAGED,
                WalkInEncounter.Status.WAITING_DOCTOR,
                WalkInEncounter.Status.LAB_READY,
                WalkInEncounter.Status.IN_CONSULTATION,
                WalkInEncounter.Status.ADMISSION_REVIEW,
            ]
        ).order_by("-is_critical", "-severity_index", "arrived_at")[:12],
        "walk_in_lab_queue": lab_requests.filter(
            walk_in_encounter__isnull=False,
            status__in=[LabTestRequest.Status.REQUESTED, LabTestRequest.Status.IN_PROGRESS],
        ).order_by("-requested_at")[:12],
        "walk_in_pharmacy_queue": pharmacy_tasks.filter(
            status__in=[PharmacyTask.Status.PENDING, PharmacyTask.Status.IN_PROGRESS]
        ).order_by("-created_at")[:12],
        "walk_in_recent_events": WalkInEvent.objects.select_related("encounter__patient__user", "actor")
        .filter(encounter__hospital=hospital if hospital else None)[:10]
        if hospital
        else WalkInEvent.objects.select_related("encounter__patient__user", "actor")[:10],
        "walk_in_billing_rates": {
            "registration": STANDARD_RATES["walk_in_registration"],
            "triage": STANDARD_RATES["walk_in_triage"],
            "admission": STANDARD_RATES["admission"],
            "bed_transfer": STANDARD_RATES["bed_transfer"],
            "discharge": STANDARD_RATES["discharge"],
            "pharmacy_base": STANDARD_RATES["pharmacy_base"],
        },
    }


def _staff_can_manage_walk_ins(role):
    return role in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.DOCTOR,
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
        HospitalAccess.Role.PHARMACIST,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    }


def _resolve_or_create_walk_in_patient(*, cleaned_data, hospital):
    existing_patient = cleaned_data.get("existing_patient")
    if existing_patient:
        if existing_patient.is_deceased:
            raise ValidationError("This patient has been recorded as deceased and cannot be re-entered into active care workflows.")
        if hospital and not HospitalAccess.objects.filter(
            user=existing_patient.user,
            hospital=hospital,
            role=HospitalAccess.Role.PATIENT,
            status=HospitalAccess.Status.ACTIVE,
        ).exists():
            HospitalAccess.objects.update_or_create(
                user=existing_patient.user,
                hospital=hospital,
                role=HospitalAccess.Role.PATIENT,
                defaults={
                    "is_primary": False,
                    "status": HospitalAccess.Status.ACTIVE,
                },
            )
        if hospital and existing_patient.hospital_id != hospital.id and existing_patient.hospital_id is None:
            existing_patient.hospital = hospital
            existing_patient.save(update_fields=["hospital"])
        return existing_patient, False

    email = (cleaned_data.get("email") or "").strip().lower()
    phone = (cleaned_data.get("phone") or "").strip()
    first_name = (cleaned_data.get("first_name") or "").strip()
    last_name = (cleaned_data.get("last_name") or "").strip()
    date_of_birth = cleaned_data.get("date_of_birth")

    matched_user = None
    if email:
        matched_user = User.objects.filter(email__iexact=email).first()
    if matched_user is None and phone:
        matched_user = User.objects.filter(phone=phone).first()
    if matched_user is None and first_name and last_name and date_of_birth:
        matched_user = User.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name,
            date_of_birth=date_of_birth,
            role=User.Role.PATIENT,
        ).first()

    if matched_user:
        patient, _ = Patient.objects.get_or_create(user=matched_user, defaults={"hospital": hospital})
        if patient.is_deceased:
            raise ValidationError("This patient has been recorded as deceased and cannot be re-entered into active care workflows.")
        if hospital and not HospitalAccess.objects.filter(
            user=matched_user,
            hospital=hospital,
            role=HospitalAccess.Role.PATIENT,
            status=HospitalAccess.Status.ACTIVE,
        ).exists():
            HospitalAccess.objects.update_or_create(
                user=matched_user,
                hospital=hospital,
                role=HospitalAccess.Role.PATIENT,
                defaults={
                    "is_primary": False,
                    "status": HospitalAccess.Status.ACTIVE,
                },
            )
        return patient, False

    username_seed = slugify(f"{first_name}-{last_name}")[:18] or "patient"
    username = username_seed
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{username_seed[:14]}-{suffix}"
    user = User.objects.create(
        username=username,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        date_of_birth=date_of_birth,
        role=User.Role.PATIENT,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    patient, _ = Patient.objects.get_or_create(
        user=user,
        defaults={
            "hospital": hospital,
            "gender": cleaned_data.get("gender") or Patient.Gender.UNSPECIFIED,
        },
    )
    if hospital and patient.hospital_id is None:
        patient.hospital = hospital
        patient.save(update_fields=["hospital"])
    if hospital:
        HospitalAccess.objects.update_or_create(
            user=user,
            hospital=hospital,
            role=HospitalAccess.Role.PATIENT,
            defaults={
                "is_primary": False,
                "status": HospitalAccess.Status.ACTIVE,
            },
        )
    return patient, True


def _walk_in_patient_lookup(hospital):
    lookup = {}
    queryset = Patient.objects.select_related("user", "hospital")
    if hospital:
        queryset = queryset.filter(hospital=hospital)
    for patient in queryset.order_by("user__last_name", "user__first_name"):
        lookup[str(patient.pk)] = {
            "first_name": patient.user.first_name or "",
            "last_name": patient.user.last_name or "",
            "email": patient.user.email or "",
            "phone": patient.user.phone or "",
            "date_of_birth": patient.user.date_of_birth.isoformat() if patient.user.date_of_birth else "",
            "gender": patient.gender or "",
            "patient_number": patient.patient_number or "",
            "insurance": patient.insurance_provider or "",
            "history": patient.medical_history or "",
            "age_group": patient.age_group,
        }
    return lookup


def _walk_in_role_panel(active_access, hospital, request):
    current_patient = _current_patient_from_session(request, hospital)
    current_walk_in = None
    walk_in_id = request.session.get("clinical_walk_in_id")
    if walk_in_id:
        current_walk_in = WalkInEncounter.objects.select_related("patient__user", "attending_doctor__user").filter(pk=walk_in_id).first()
    role = active_access.role if active_access else ""
    panel = {
        "title": "Current workflow focus",
        "summary": "Use the active queue and patient context to move care to the next stage without losing billing or audit visibility.",
        "bullets": [
            "Open the active patient context before creating new downstream tasks.",
            "Each stage should leave a clear operational and billing trace.",
        ],
        "current_patient": current_patient,
        "current_walk_in": current_walk_in,
    }
    role_map = {
        HospitalAccess.Role.RECEPTIONIST: (
            "Reception focus",
            "Capture identity once, prevent duplicates, and move the patient into triage with complete contact and symptom details.",
            [
                "Existing patients should be selected from the directory so their chart details auto-carry into intake.",
                "Registration charges should be created at intake so the patient can pay immediately or at the end.",
            ],
        ),
        HospitalAccess.Role.NURSE: (
            "Triage focus",
            "Record symptoms, vitals, and current state precisely so severity ranking and downstream billing stay accurate.",
            [
                "Critical cases should be escalated ahead of routine order.",
                "Triage and vital-sign capture should create a visible clinical and billing step.",
            ],
        ),
        HospitalAccess.Role.DOCTOR: (
            "Consultation focus",
            "Use one consultation entry point to create diagnosis, medication handoff, lab requests, admission review, and the linked fees.",
            [
                "Telemedicine should mirror the consultation workflow, with lab collection routed back to in-person service points.",
                "Consultation, lab, pharmacy, and admission charges should remain linked to the same patient journey.",
            ],
        ),
        HospitalAccess.Role.LAB_TECHNICIAN: (
            "Laboratory focus",
            "Complete tests against the originating request so the result, doctor review, and corresponding bill stay tied together.",
            [
                "Only finalized tests should complete the lab billing step.",
                "Walk-in and telemedicine-originated requests should converge into the same in-person lab queue.",
            ],
        ),
        HospitalAccess.Role.PHARMACIST: (
            "Pharmacy focus",
            "Dispense against the requested medication instructions and keep the resulting charge visible in the same patient journey.",
            [
                "Telemedicine prescriptions should be fulfillment-ready from the pharmacy side.",
                "A completed dispensing step should close only the pharmacy portion, not hide other open care tasks.",
            ],
        ),
        HospitalAccess.Role.EMERGENCY_OPERATOR: (
            "Emergency routing focus",
            "Monitor the critical queue and keep rapid handoffs visible across triage, doctor review, and admission control.",
            [
                "Critical flags should change queue priority immediately.",
                "Operational visibility should remain shared across the whole hospital team.",
            ],
        ),
    }
    if role in role_map:
        panel["title"], panel["summary"], panel["bullets"] = role_map[role]
    return panel


def _doctor_workspace_context(request, *, doctor, hospital, accesses):
    hospital_ids = _access_hospital_ids(
        accesses,
        roles=[HospitalAccess.Role.DOCTOR, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER],
    )
    if not hospital_ids and doctor.hospital_id:
        hospital_ids = [doctor.hospital_id]

    affiliated_hospitals = Hospital.objects.filter(id__in=hospital_ids).order_by("name")
    focus_hospitals = Hospital.objects.filter(id=hospital.id) if hospital else affiliated_hospitals
    current_patient = _current_patient_from_session(request, hospital)

    appointments_all = Appointment.objects.filter(
        doctor=doctor,
        hospital__in=affiliated_hospitals,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
    ).select_related("patient__user", "hospital")
    focused_appointments = appointments_all.filter(hospital__in=focus_hospitals)
    medical_records_all = MedicalRecord.objects.filter(doctor=doctor, hospital__in=affiliated_hospitals).select_related("patient__user", "hospital")
    focused_records = medical_records_all.filter(hospital__in=focus_hospitals)
    walk_in_queue = _walk_in_queryset(hospital).filter(
        Q(attending_doctor=doctor)
        | Q(
            attending_doctor__isnull=True,
            status__in=[
                WalkInEncounter.Status.TRIAGED,
                WalkInEncounter.Status.WAITING_DOCTOR,
                WalkInEncounter.Status.LAB_READY,
                WalkInEncounter.Status.ADMISSION_REVIEW,
            ],
        )
    ).order_by("-is_critical", "-severity_index", "arrived_at")
    active_admissions = Admission.objects.filter(
        attending_doctor=doctor,
        hospital__in=affiliated_hospitals,
        status=Admission.Status.ACTIVE,
    ).select_related("patient__user", "ward", "bed", "hospital")
    surgery_cases = SurgicalCase.objects.filter(
        surgeon=doctor,
        hospital__in=affiliated_hospitals,
    ).select_related("patient__user", "hospital", "operating_room")
    consultations = VideoConsultation.objects.filter(
        appointment__doctor=doctor,
        appointment__hospital__in=affiliated_hospitals,
    ).select_related("appointment__patient__user", "appointment__hospital")
    pending_lab_requests = LabTestRequest.objects.filter(
        requested_by=doctor,
        hospital__in=affiliated_hospitals,
    ).select_related("patient__user", "hospital")
    pending_lab_reviews = LabTestResult.objects.filter(
        reviewed_by__isnull=True,
        request__requested_by=doctor,
        request__hospital__in=affiliated_hospitals,
    ).select_related("request__patient__user", "request__hospital", "request")
    doctor_tasks = DoctorTask.objects.filter(
        Q(created_by=request.user) | Q(assigned_to=request.user),
        hospital__in=affiliated_hospitals,
    ).select_related("patient__user", "hospital", "assigned_to")
    care_plans = CarePlan.objects.filter(
        doctor=doctor,
        hospital__in=affiliated_hospitals,
    ).select_related("patient__user", "hospital")
    referrals_outbound = InternalReferral.objects.filter(
        referring_doctor=doctor,
        source_hospital__in=affiliated_hospitals,
    ).select_related("patient__user", "target_doctor__user", "target_hospital")
    referrals_inbound = InternalReferral.objects.filter(
        target_doctor=doctor,
        target_hospital__in=affiliated_hospitals,
    ).select_related("patient__user", "referring_doctor__user", "source_hospital")

    active_patient_ids = []
    for patient_id in list(active_admissions.values_list("patient_id", flat=True)[:40]) + list(walk_in_queue.values_list("patient_id", flat=True)[:40]) + list(focused_appointments.values_list("patient_id", flat=True)[:40]):
        if patient_id and patient_id not in active_patient_ids:
            active_patient_ids.append(patient_id)
    active_patients = Patient.objects.filter(id__in=active_patient_ids).select_related("user", "hospital")

    critical_alerts = []
    for item in walk_in_queue[:3]:
        critical_alerts.append(
            {
                "label": item.patient.user.get_full_name() or item.patient.user.username,
                "detail": f"{item.get_severity_band_display()} walk-in at {item.hospital.name if item.hospital_id else 'current hospital'} with severity {item.severity_index}/100.",
                "tone": "danger" if item.is_critical else "warning",
            }
        )
    for admission in active_admissions.filter(ward__ward_type__in=[Ward.WardType.ICU, Ward.WardType.EMERGENCY])[:2]:
        critical_alerts.append(
            {
                "label": admission.patient.user.get_full_name() or admission.patient.user.username,
                "detail": f"Active {admission.ward.get_ward_type_display()} admission in {admission.hospital.name if admission.hospital_id else 'current hospital'}.",
                "tone": "warning",
            }
        )
    for result in pending_lab_reviews[:2]:
        critical_alerts.append(
            {
                "label": result.request.patient.user.get_full_name() or result.request.patient.user.username,
                "detail": f"Result ready for {result.request.test_name}. Doctor review pending.",
                "tone": "primary",
            }
        )

    network_hospitals = []
    for site in affiliated_hospitals:
        network_hospitals.append(
            {
                "name": site.name,
                "appointments": appointments_all.filter(hospital=site).count(),
                "active_admissions": active_admissions.filter(hospital=site).count(),
                "walk_ins": walk_in_queue.filter(hospital=site).count(),
                "tasks": doctor_tasks.filter(hospital=site, status__in=[DoctorTask.Status.OPEN, DoctorTask.Status.IN_PROGRESS]).count(),
            }
        )

    affiliated_hospital_choices = affiliated_hospitals.exclude(id=hospital.id if hospital else None)
    task_form = DoctorTaskForm(hospital=hospital, doctor_user=request.user)
    care_plan_form = CarePlanForm(hospital=hospital, current_patient=current_patient)
    referral_form = InternalReferralForm(hospital=hospital, current_patient=current_patient)
    referral_form.set_hospital_queryset(affiliated_hospital_choices)

    return {
        "doctor": doctor,
        "current_hospital": hospital,
        "current_patient": current_patient,
        "assistant_watch_items": _doctor_watch_items(request, current_patient, walk_in_queue, pending_lab_reviews),
        "appointments": focused_appointments.order_by("appointment_date", "appointment_time"),
        "walk_in_queue": walk_in_queue.order_by("-arrived_at", "-id")[:12],
        "medical_records": focused_records.order_by("-created_at")[:12],
        "records_form": MedicalRecordForm(hospital=hospital, current_patient=current_patient),
        "consult_form": WalkInConsultationForm(),
        "doctor_task_form": task_form,
        "care_plan_form": care_plan_form,
        "internal_referral_form": referral_form,
        "doctor_tasks": doctor_tasks.order_by("status", "due_at", "-created_at"),
        "care_plans": care_plans.order_by("status", "-updated_at"),
        "referrals_outbound": referrals_outbound.order_by("status", "-created_at"),
        "referrals_inbound": referrals_inbound.order_by("status", "-created_at"),
        "active_admissions": active_admissions.order_by("-admitted_at"),
        "pending_lab_requests": pending_lab_requests.order_by("-requested_at"),
        "pending_lab_reviews": pending_lab_reviews.order_by("-completed_at"),
        "surgery_cases": surgery_cases.order_by("scheduled_start"),
        "telemedicine_consultations": consultations.order_by("-start_time", "-id"),
        "active_patients": active_patients,
        "critical_alerts": critical_alerts[:6],
        "network_hospitals": network_hospitals,
        "stats": {
            "appointments": appointments_all.count(),
            "records": medical_records_all.count(),
            "labs": pending_lab_requests.count(),
            "walk_ins": walk_in_queue.count(),
            "tasks": doctor_tasks.filter(status__in=[DoctorTask.Status.OPEN, DoctorTask.Status.IN_PROGRESS]).count(),
            "referrals": referrals_outbound.exclude(status=InternalReferral.Status.CLOSED).count() + referrals_inbound.exclude(status=InternalReferral.Status.CLOSED).count(),
            "admissions": active_admissions.count(),
            "telemedicine": consultations.exclude(status=VideoConsultation.Status.COMPLETED).count(),
            "hospitals": affiliated_hospitals.count(),
        },
    }


def _patient_workspace_context(request, *, patient, hospital, accesses):
    hospital_ids = _access_hospital_ids(accesses, roles=[HospitalAccess.Role.PATIENT])
    if not hospital_ids and patient.hospital_id:
        hospital_ids = [patient.hospital_id]
    affiliated_hospitals = Hospital.objects.filter(id__in=hospital_ids).order_by("name")
    focus_hospitals = Hospital.objects.filter(id=hospital.id) if hospital else affiliated_hospitals

    appointments = Appointment.objects.filter(
        patient=patient,
        hospital__in=focus_hospitals,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
    ).select_related("doctor__user", "hospital")
    medical_records = MedicalRecord.objects.filter(patient=patient, hospital__in=focus_hospitals).select_related("doctor__user", "hospital")
    billings = Billing.objects.filter(patient=patient, hospital__in=focus_hospitals)
    admissions = Admission.objects.filter(patient=patient, hospital__in=focus_hospitals).select_related("ward", "bed", "attending_doctor__user", "hospital")
    vitals = VitalSign.objects.filter(patient=patient, hospital__in=focus_hospitals)
    lab_requests = LabTestRequest.objects.filter(patient=patient, hospital__in=focus_hospitals).select_related("hospital")
    lab_results = LabTestResult.objects.filter(request__patient=patient, request__hospital__in=focus_hospitals).select_related("request", "request__hospital")
    visits = patient.visits.filter(hospital__in=focus_hospitals)
    care_plans = CarePlan.objects.filter(patient=patient, hospital__in=focus_hospitals).select_related("doctor__user", "hospital")
    telemedicine_consultations = VideoConsultation.objects.filter(appointment__patient=patient, appointment__hospital__in=focus_hospitals).select_related("appointment__doctor__user", "appointment__hospital")
    caregiver_accesses = CaregiverAccess.objects.filter(patient=patient, hospital__in=focus_hospitals).order_by("-created_at")
    advance_directives = AdvanceDirective.objects.filter(patient=patient, hospital__in=focus_hospitals).order_by("-created_at")
    feedback_entries = PatientFeedback.objects.filter(patient=patient, hospital__in=focus_hospitals).select_related("doctor__user", "hospital")
    notifications = Notification.objects.filter(user=request.user)[:8]
    therapy_sessions = TherapySession.objects.filter(patient=request.user).order_by("-scheduled_time")[:8]

    care_team = []
    for doctor in list(appointments.values_list("doctor__user__first_name", "doctor__user__last_name", "doctor__specialization", "hospital__name")[:6]):
        full_name = " ".join(part for part in doctor[:2] if part).strip() or "Assigned doctor"
        care_team.append({"name": f"Dr. {full_name}", "role": doctor[2] or "Doctor", "hospital": doctor[3] or "BayAfya"})
    for admission in admissions[:4]:
        name = admission.attending_doctor.user.get_full_name() or admission.attending_doctor.user.username
        care_team.append({"name": f"Dr. {name}", "role": "Attending doctor", "hospital": admission.hospital.name if admission.hospital_id else "BayAfya"})
    unique_care_team = []
    seen_team = set()
    for item in care_team:
        key = (item["name"], item["role"], item["hospital"])
        if key not in seen_team:
            seen_team.add(key)
            unique_care_team.append(item)

    reminders = []
    for item in appointments.filter(status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED]).order_by("appointment_date", "appointment_time")[:4]:
        reminders.append({"title": "Upcoming appointment", "detail": f"{item.doctor} on {item.appointment_date} at {item.appointment_time}.", "tone": "primary"})
    for bill in billings.filter(paid=False)[:3]:
        reminders.append({"title": "Outstanding billing", "detail": f"{bill.description or bill.get_billing_type_display()} - {bill.amount}.", "tone": "warning"})
    for request_item in lab_requests.filter(status__in=[LabTestRequest.Status.REQUESTED, LabTestRequest.Status.IN_PROGRESS])[:3]:
        reminders.append({"title": "Pending laboratory follow-up", "detail": f"{request_item.test_name} is still {request_item.get_status_display().lower()}.", "tone": "warning"})
    for consultation in telemedicine_consultations.exclude(status=VideoConsultation.Status.COMPLETED)[:2]:
        reminders.append({"title": "Virtual care follow-up", "detail": f"Telemedicine session with {consultation.appointment.doctor} is still active.", "tone": "primary"})

    portal_updates = []
    for item in lab_results[:3]:
        portal_updates.append({"title": f"Lab result ready: {item.request.test_name}", "detail": item.completed_at.strftime("%Y-%m-%d %H:%M") if item.completed_at else "Available now"})
    for admission in admissions[:2]:
        portal_updates.append({"title": f"Admission status: {admission.get_status_display()}", "detail": f"{admission.ward.name} at {admission.hospital.name if admission.hospital_id else 'current hospital'}"})
    for note in notifications[:3]:
        portal_updates.append({"title": note.title, "detail": note.message})

    walk_in_journey = _patient_walk_in_journey(patient, focus_hospitals)

    return {
        "patient": patient,
        "current_hospital": hospital,
        "assistant_watch_items": _patient_watch_items(request, patient, appointments, billings, lab_results, admissions),
        "appointments": appointments.order_by("appointment_date", "appointment_time"),
        "medical_records": medical_records.order_by("-created_at"),
        "billings": billings.order_by("-created_at"),
        "admissions": admissions.order_by("-admitted_at"),
        "vitals": vitals.order_by("-recorded_at"),
        "lab_requests": lab_requests.order_by("-requested_at"),
        "lab_results": lab_results.order_by("-completed_at"),
        "visits": visits.order_by("-created_at")[:5],
        "care_plans": care_plans.order_by("status", "-updated_at"),
        "telemedicine_consultations": telemedicine_consultations.order_by("-start_time", "-id"),
        "caregiver_accesses": caregiver_accesses,
        "advance_directives": advance_directives,
        "feedback_entries": feedback_entries,
        "notifications": notifications,
        "therapy_sessions": therapy_sessions,
        "care_team": unique_care_team[:8],
        "patient_reminders": reminders[:8],
        "portal_updates": portal_updates[:8],
        "walk_in_journey": walk_in_journey,
        "caregiver_form": CaregiverAccessForm(),
        "directive_form": AdvanceDirectiveForm(),
        "feedback_form": PatientFeedbackForm(hospital=hospital),
        "resources": WellnessResource.objects.all()[:6],
        "stats": {
            "appointments": appointments.count(),
            "records": medical_records.count(),
            "billing_items": billings.count(),
            "care_plans": care_plans.count(),
            "lab_results": lab_results.count(),
            "hospitals": affiliated_hospitals.count(),
        },
    }


def _operations_workspace_context(request, *, active_access, hospital):
    role = active_access.role if active_access else ""
    hospital_scope = Hospital.objects.filter(id=hospital.id) if hospital else Hospital.objects.none()
    staff_profile = getattr(request.user, "staff_profile", None)
    shift_window, shift_start, shift_end, shift_window_label = _period_bounds(request, "shift_window", default="day")

    supply_requests = SupplyRequest.objects.filter(hospital=hospital).select_related("requested_by").order_by("status", "-created_at") if hospital else SupplyRequest.objects.none()
    handovers = ShiftHandover.objects.filter(hospital=hospital).select_related("staff__user").order_by("-created_at") if hospital else ShiftHandover.objects.none()
    qc_logs = LabQualityControlLog.objects.filter(hospital=hospital).select_related("recorded_by__user").order_by("-recorded_at") if hospital else LabQualityControlLog.objects.none()
    incidents = EmergencyIncident.objects.filter(hospital=hospital).select_related("created_by", "linked_request").order_by("status", "-created_at") if hospital else EmergencyIncident.objects.none()
    doctor_tasks = DoctorTask.objects.filter(hospital=hospital).select_related("patient__user", "assigned_to").order_by("status", "due_at", "-created_at") if hospital else DoctorTask.objects.none()
    care_plans = CarePlan.objects.filter(hospital=hospital).select_related("patient__user", "doctor__user").order_by("status", "-updated_at") if hospital else CarePlan.objects.none()
    shift_assignments = ShiftAssignment.objects.filter(hospital=hospital).select_related("staff__user").order_by("-shift_date", "start_time") if hospital else ShiftAssignment.objects.none()
    low_stock = Medicine.objects.filter(stock_quantity__lte=20).order_by("stock_quantity", "name")[:8]
    active_dispatches = AmbulanceRequest.objects.exclude(status=AmbulanceRequest.Status.COMPLETED).order_by("-created_at")[:8]

    alerts = []
    for item in _scope_queryset(
        VitalSign.objects.filter(
            Q(oxygen_saturation__lt=92) | Q(temperature_c__gte=39) | Q(pulse_rate__gte=120)
        ).select_related("patient__user"),
        hospital,
    )[:5]:
        alerts.append({"title": f"Abnormal vitals: {item.patient}", "detail": f"O2 {item.oxygen_saturation or '-'} · Temp {item.temperature_c or '-'} · Pulse {item.pulse_rate or '-'}", "tone": "warning"})
    for item in _scope_queryset(LabTestRequest.objects.filter(priority__in=["urgent", "stat"], status__in=[LabTestRequest.Status.REQUESTED, LabTestRequest.Status.IN_PROGRESS]).select_related("patient__user"), hospital)[:5]:
        alerts.append({"title": f"Urgent lab request: {item.test_name}", "detail": f"{item.patient} · {item.get_status_display()}", "tone": "primary"})
    for item in _walk_in_queryset(hospital).filter(is_critical=True)[:4]:
        alerts.append({"title": f"Critical walk-in: {item.patient}", "detail": f"{item.ticket_number} · severity {item.severity_index}/100", "tone": "danger"})

    role_title = "Operational workbench"
    role_summary = "Use the current workspace to move care forward without losing visibility across the hospital."
    if role == HospitalAccess.Role.NURSE:
        role_title = "Nursing workbench"
        role_summary = "Track bedside tasks, shift handovers, active care plans, and abnormal clinical signals in one place."
    elif role == HospitalAccess.Role.RECEPTIONIST:
        role_title = "Reception workbench"
        role_summary = "Manage registration flow, queue movement, appointment follow-up, and front-desk financial handoff."
    elif role == HospitalAccess.Role.LAB_TECHNICIAN:
        role_title = "Laboratory workbench"
        role_summary = "Work urgent requests first, keep QC visible, and return structured results to the care team quickly."
    elif role == HospitalAccess.Role.PHARMACIST:
        role_title = "Pharmacy workbench"
        role_summary = "Dispense against clear instructions, watch stock-sensitive items, and keep fulfillment visible."
    elif role == HospitalAccess.Role.EMERGENCY_OPERATOR:
        role_title = "Emergency workbench"
        role_summary = "Coordinate incidents, dispatches, and critical arrivals with real-time hospital context."

    today = timezone.localdate()
    todays_shift_assignments = shift_assignments.filter(shift_date=today)
    filtered_shift_assignments = shift_assignments.filter(shift_date__range=(shift_start, shift_end))
    staff_shift_assignments = (
        filtered_shift_assignments.filter(staff=staff_profile).order_by("shift_date", "start_time")
        if staff_profile
        else ShiftAssignment.objects.none()
    )
    todays_shift_cost = sum(
        (
            max(
                0,
                (
                    datetime.combine(today, item.end_time) - datetime.combine(today, item.start_time)
                ).total_seconds() / 3600,
            )
            * float(item.staff.hourly_rate or 0)
        )
        for item in todays_shift_assignments
        if item.start_time and item.end_time and item.staff
    )

    return {
        "assistant_watch_items": _operations_watch_items(
            request,
            role,
            hospital,
            alerts,
            _walk_in_dashboard_context(hospital)["walk_in_summary"] if hospital else {},
        ),
        "role_workspace": {
            "title": role_title,
            "summary": role_summary,
            "alerts": alerts[:8],
        },
        "nurse_tasks": doctor_tasks.filter(assigned_to=request.user) if role == HospitalAccess.Role.NURSE else doctor_tasks.none(),
        "care_plan_execution": care_plans[:8],
        "shift_handovers": handovers[:8],
        "shift_assignments": shift_assignments[:12],
        "todays_shift_assignments": todays_shift_assignments[:8],
        "filtered_shift_assignments": filtered_shift_assignments[:14],
        "staff_shift_assignments": staff_shift_assignments[:14],
        "shift_window": shift_window,
        "shift_window_label": shift_window_label,
        "shift_window_start": shift_start,
        "shift_window_end": shift_end,
        "todays_shift_cost": round(todays_shift_cost, 2),
        "shift_assignment_form": ShiftAssignmentForm(hospital=hospital),
        "shift_handover_form": ShiftHandoverForm(initial={"shift_date": timezone.localdate()}),
        "supply_requests": supply_requests[:12],
        "open_supply_requests_list": supply_requests.exclude(status__in=[SupplyRequest.Status.FULFILLED, SupplyRequest.Status.CANCELLED])[:8],
        "supply_request_form": SupplyRequestForm(initial={"department": staff_profile.department if staff_profile else role.replace("_", " ").title()}),
        "supply_request_status_form": SupplyRequestStatusForm(),
        "reception_followups": _scope_queryset(Appointment.objects.filter(status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED]).select_related("patient__user", "doctor__user"), hospital).order_by("appointment_date", "appointment_time")[:8],
        "lab_urgent_requests": _scope_queryset(LabTestRequest.objects.select_related("patient__user", "requested_by__user"), hospital).filter(priority__in=["urgent", "stat"]).order_by("-requested_at")[:8],
        "lab_active_queue": _scope_queryset(LabTestRequest.objects.select_related("patient__user", "requested_by__user", "walk_in_encounter"), hospital).filter(status__in=[LabTestRequest.Status.REQUESTED, LabTestRequest.Status.IN_PROGRESS]).order_by("-requested_at")[:8],
        "lab_qc_logs": qc_logs[:8],
        "lab_qc_form": LabQualityControlLogForm(),
        "pharmacy_low_stock": low_stock,
        "pharmacy_queue": _scope_queryset(
            PharmacyTask.objects.select_related("patient__user", "walk_in_encounter", "requested_by").filter(
                status__in=[PharmacyTask.Status.PENDING, PharmacyTask.Status.IN_PROGRESS]
            ),
            hospital,
        ).order_by("-created_at")[:8],
        "emergency_incidents": incidents[:10],
        "open_emergency_incidents": incidents.exclude(status=EmergencyIncident.Status.RESOLVED)[:8],
        "emergency_incident_form": EmergencyIncidentForm(hospital=hospital),
        "active_dispatches": active_dispatches,
        "admission_review_queue": _walk_in_queryset(hospital).filter(status=WalkInEncounter.Status.ADMISSION_REVIEW).order_by("-is_critical", "-last_updated_at")[:8] if hospital else WalkInEncounter.objects.none(),
        "admin_overview": {
            "open_supply_requests": supply_requests.exclude(status__in=[SupplyRequest.Status.FULFILLED, SupplyRequest.Status.CANCELLED]).count(),
            "critical_incidents": incidents.filter(severity=EmergencyIncident.Severity.CRITICAL).exclude(status=EmergencyIncident.Status.RESOLVED).count(),
            "pending_qc_reviews": qc_logs.exclude(qc_status=LabQualityControlLog.Status.PASS).count(),
            "low_stock_items": low_stock.count(),
            "occupied_beds": _scope_queryset(Bed.objects.filter(is_occupied=True), hospital).count(),
        },
    }


def _invitation_roles_for_access(active_access):
    if not active_access:
        return []
    if active_access.role in OWNER_ROLES:
        return [
            HospitalAccess.Role.ADMIN,
            HospitalAccess.Role.DOCTOR,
            HospitalAccess.Role.NURSE,
            HospitalAccess.Role.RECEPTIONIST,
            HospitalAccess.Role.LAB_TECHNICIAN,
            HospitalAccess.Role.PHARMACIST,
            HospitalAccess.Role.COUNSELOR,
            HospitalAccess.Role.EMERGENCY_OPERATOR,
            HospitalAccess.Role.PATIENT,
        ]
    if active_access.role in STAFF_INVITER_ROLES:
        return [HospitalAccess.Role.PATIENT]
    return []


def _active_accesses(request):
    accesses = list(
        HospitalAccess.objects.select_related("hospital").filter(
            user=request.user, hospital__is_active=True, status=HospitalAccess.Status.ACTIVE
        )
    )
    current_hospital_id = request.session.get("current_hospital_id")
    current_access = None
    if current_hospital_id:
        current_access = next((access for access in accesses if access.hospital_id == current_hospital_id), None)
    if current_access is None:
        current_access = next((access for access in accesses if access.is_primary), None)
    if current_access is None and accesses:
        current_access = accesses[0]
    return accesses, current_access, current_access.hospital if current_access else None


def _current_patient_from_session(request, hospital=None):
    patient_id = request.session.get("clinical_patient_id")
    if not patient_id:
        return None
    queryset = Patient.objects.select_related("user", "hospital")
    if hospital:
        queryset = queryset.filter(
            Q(hospital=hospital)
            | Q(appointments__hospital=hospital)
            | Q(medical_records__hospital=hospital)
            | Q(condition_records__hospital=hospital)
        ).distinct()
    return queryset.filter(pk=patient_id).first()


def _scope_queryset(queryset, hospital):
    if hospital is None or "hospital" not in [field.name for field in queryset.model._meta.fields]:
        return queryset
    return queryset.filter(hospital=hospital)


def _access_hospital_ids(accesses, *, roles):
    if hasattr(accesses, "filter"):
        return list(accesses.filter(role__in=roles).values_list("hospital_id", flat=True))
    return [access.hospital_id for access in accesses if getattr(access, "role", None) in roles]


def _role_allows_clinical_access(access_role):
    return access_role in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.DOCTOR,
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    }


def _role_allows_record_access(access_role):
    return access_role in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.DOCTOR,
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
        HospitalAccess.Role.PHARMACIST,
        HospitalAccess.Role.COUNSELOR,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    }


def _patient_scope_queryset(hospital):
    queryset = Patient.objects.select_related("user", "hospital").all()
    if hospital is None:
        return queryset
    return queryset.filter(
        Q(hospital=hospital)
        | Q(appointments__hospital=hospital)
        | Q(medical_records__hospital=hospital)
        | Q(condition_records__hospital=hospital)
        | Q(admissions__hospital=hospital)
        | Q(visits__hospital=hospital)
        | Q(vitals__hospital=hospital)
        | Q(lab_requests__hospital=hospital)
        | Q(surgical_cases__hospital=hospital)
    ).distinct()


def _patient_history_queryset(patient, hospital=None):
    appointments = Appointment.objects.filter(patient=patient).select_related("doctor__user", "hospital")
    records = MedicalRecord.objects.filter(patient=patient).select_related("doctor__user", "hospital")
    conditions = PatientCondition.objects.filter(patient=patient).select_related("condition", "recorded_by__user", "hospital")
    admissions = Admission.objects.filter(patient=patient).select_related("ward", "bed", "attending_doctor__user", "hospital")
    vitals = VitalSign.objects.filter(patient=patient).select_related("recorded_by", "hospital")
    labs = LabTestRequest.objects.filter(patient=patient).select_related("requested_by__user", "hospital")
    surgeries = SurgicalCase.objects.filter(patient=patient).select_related("surgeon__user", "operating_room", "hospital")
    billings = Billing.objects.filter(patient=patient).select_related("hospital", "appointment")
    visits = PatientVisit.objects.filter(patient=patient).select_related("appointment", "admission", "hospital")

    if hospital:
        appointments = appointments.filter(hospital=hospital)
        records = records.filter(hospital=hospital)
        conditions = conditions.filter(hospital=hospital)
        admissions = admissions.filter(hospital=hospital)
        vitals = vitals.filter(hospital=hospital)
        labs = labs.filter(hospital=hospital)
        surgeries = surgeries.filter(hospital=hospital)
        billings = billings.filter(hospital=hospital)
        visits = visits.filter(hospital=hospital)

    return {
        "appointments": appointments.order_by("-appointment_date", "-appointment_time"),
        "records": records.order_by("-created_at"),
        "conditions": conditions.order_by("-created_at"),
        "admissions": admissions.order_by("-admitted_at"),
        "vitals": vitals.order_by("-recorded_at"),
        "labs": labs.order_by("-requested_at"),
        "surgeries": surgeries.order_by("-scheduled_start"),
        "billings": billings.order_by("-created_at"),
        "visits": visits.order_by("-created_at"),
    }


def _normalize_record_timestamp(value):
    if value is None:
        return timezone.now() - timedelta(days=36500)
    if isinstance(value, datetime):
        return timezone.make_aware(value) if timezone.is_naive(value) else value
    normalized = datetime.combine(value, time.min)
    return timezone.make_aware(normalized)


def _patient_record_feed(history, patient):
    facility_name = patient.hospital.name if patient.hospital else "Shared"
    items = []

    for record in history["records"]:
        items.append(
            {
                "type": "medical_record",
                "title": record.diagnosis or "Clinical record",
                "subtitle": f"{record.doctor or 'Care team'} · {record.created_at:%Y-%m-%d %H:%M}",
                "detail": record.assessment or record.notes or record.plan or record.prescription or "No additional narrative recorded.",
                "status": "Medical record",
                "hospital": record.hospital.name if record.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(record.created_at),
                "url": f"/hospital/records/{record.id}/",
            }
        )

    for condition in history["conditions"]:
        items.append(
            {
                "type": "condition",
                "title": condition.condition_name or (condition.condition.name if condition.condition_id else "Condition recorded"),
                "subtitle": f"{condition.get_severity_display()} · {condition.created_at:%Y-%m-%d}",
                "detail": condition.notes or "Condition history entry.",
                "status": "Condition",
                "hospital": condition.hospital.name if condition.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(condition.created_at),
                "url": "",
            }
        )

    for vital in history["vitals"]:
        items.append(
            {
                "type": "vital",
                "title": "Vital signs",
                "subtitle": f"{vital.recorded_at:%Y-%m-%d %H:%M}",
                "detail": f"T {vital.temperature_c or '-'} · P {vital.pulse_rate or '-'} · BP {vital.systolic_bp or '-'}/{vital.diastolic_bp or '-'} · O2 {vital.oxygen_saturation or '-'}",
                "status": "Observation",
                "hospital": vital.hospital.name if vital.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(vital.recorded_at),
                "url": "",
            }
        )

    for lab in history["labs"]:
        items.append(
            {
                "type": "lab",
                "title": lab.test_name,
                "subtitle": f"{lab.get_status_display()} · {lab.requested_at:%Y-%m-%d %H:%M}",
                "detail": lab.notes or "Laboratory request on file.",
                "status": "Lab",
                "hospital": lab.hospital.name if lab.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(lab.requested_at),
                "url": "",
            }
        )

    for admission in history["admissions"]:
        items.append(
            {
                "type": "admission",
                "title": "Admission episode",
                "subtitle": f"{admission.ward.name if admission.ward else 'Ward pending'} · Bed {admission.bed.bed_number if admission.bed else 'Pending'}",
                "detail": admission.admission_reason or admission.admission_notes or "Inpatient episode recorded.",
                "status": admission.get_status_display(),
                "hospital": admission.hospital.name if admission.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(admission.admitted_at),
                "url": "",
            }
        )

    for surgery in history["surgeries"]:
        items.append(
            {
                "type": "surgery",
                "title": surgery.procedure_name,
                "subtitle": f"{surgery.scheduled_start:%Y-%m-%d %H:%M} · {surgery.get_status_display()}",
                "detail": surgery.notes or surgery.post_op_notes or surgery.anesthesia_type or "Surgical record entry.",
                "status": "Surgery",
                "hospital": surgery.hospital.name if surgery.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(surgery.scheduled_start),
                "url": "",
            }
        )

    for appointment in history["appointments"]:
        scheduled_at = datetime.combine(appointment.appointment_date, appointment.appointment_time or time.min)
        items.append(
            {
                "type": "appointment",
                "title": "Appointment",
                "subtitle": f"{appointment.doctor} · {appointment.appointment_date} {appointment.appointment_time}",
                "detail": appointment.reason or "Consultation booking record.",
                "status": appointment.get_status_display(),
                "hospital": appointment.hospital.name if appointment.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(scheduled_at),
                "url": "",
            }
        )

    for billing in history["billings"]:
        items.append(
            {
                "type": "billing",
                "title": billing.description or billing.get_billing_type_display() or "Billing item",
                "subtitle": f"{billing.created_at:%Y-%m-%d %H:%M} · {'Paid' if billing.paid else 'Outstanding'}",
                "detail": f"Amount {billing.amount}",
                "status": "Billing",
                "hospital": billing.hospital.name if billing.hospital else facility_name,
                "timestamp": _normalize_record_timestamp(billing.created_at),
                "url": "",
            }
        )

    return sorted(items, key=lambda item: item["timestamp"], reverse=True)


def _minutes_ago_label(moment):
    if not moment:
        return "Updated recently"
    delta = max(int((timezone.now() - moment).total_seconds() // 60), 0)
    if delta < 1:
        return "Updated just now"
    if delta == 1:
        return "Updated 1 minute ago"
    if delta < 60:
        return f"Updated {delta} minutes ago"
    hours = delta // 60
    if hours == 1:
        return "Updated 1 hour ago"
    return f"Updated {hours} hours ago"


def _selected_period(request, key, default="day"):
    value = (request.GET.get(key) or default).strip().lower()
    if value not in {"day", "week", "month", "custom"}:
        return default
    return value


def _date_from_query(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _period_bounds(request, key, *, default="day"):
    period = _selected_period(request, key, default=default)
    today = timezone.localdate()
    start = today
    end = today
    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        start = today.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1, day=1)
        else:
            next_month = start.replace(month=start.month + 1, day=1)
        end = next_month - timedelta(days=1)
    elif period == "custom":
        start = _date_from_query(request.GET.get(f"{key}_start")) or today
        end = _date_from_query(request.GET.get(f"{key}_end")) or start
        if end < start:
            start, end = end, start
    label = (
        "Today"
        if period == "day"
        else "This week"
        if period == "week"
        else "This month"
        if period == "month"
        else f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"
    )
    return period, start, end, label


def _mark_patient_deceased(patient, *, actor, hospital=None, deceased_at=None, notes=""):
    recorded_at = deceased_at or timezone.now()
    patient.is_deceased = True
    patient.deceased_at = recorded_at
    patient.deceased_recorded_by = actor
    patient.deceased_recorded_hospital = hospital
    patient.deceased_notes = (notes or "").strip()
    patient.save(
        update_fields=[
            "is_deceased",
            "deceased_at",
            "deceased_recorded_by",
            "deceased_recorded_hospital",
            "deceased_notes",
        ]
    )
    revoked_at = timezone.now()
    HospitalAccess.objects.filter(
        user=patient.user,
        role=HospitalAccess.Role.PATIENT,
    ).update(
        status=HospitalAccess.Status.REVOKED,
        revoked_at=revoked_at,
        revoked_by_id=actor.id,
        revoked_reason="Patient marked deceased",
        left_at=None,
        left_reason="",
    )
    impacted_hospital_ids = set(
        HospitalAccess.objects.filter(user=patient.user, role=HospitalAccess.Role.PATIENT).values_list("hospital_id", flat=True)
    )
    if patient.hospital_id:
        impacted_hospital_ids.add(patient.hospital_id)
    for hospital_id in {item for item in impacted_hospital_ids if item}:
        broadcast_hospital_update(
            Hospital.objects.filter(pk=hospital_id).first(),
            event_type="patient_updated",
            payload={
                "patient_id": patient.id,
                "is_deceased": True,
            },
        )


def _watch_signal_id(scope, title, detail, occurred_at, meta=""):
    stamp = occurred_at.isoformat() if occurred_at else ""
    payload = f"{scope}|{title}|{detail}|{stamp}|{meta}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _dashboard_form_errors(form):
    if not form:
        return {}
    return {
        field: [str(error) for error in errors]
        for field, errors in form.errors.items()
    }


def _async_dashboard_response(request, *, ok, message, status=200, errors=None, extra=None):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        payload = {"ok": ok, "message": message}
        if errors:
            payload["errors"] = errors
        if extra:
            payload.update(extra)
        return JsonResponse(payload, status=status)
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return None


def _dismissed_watch_ids(request):
    return set(request.session.get("dismissed_watch_signal_ids", []))


def _watch_priority_score(item):
    tone_weight = {
        "danger": 300,
        "warning": 220,
        "success": 120,
        "primary": 100,
        "info": 90,
    }.get(item.get("tone", "primary"), 100)
    occurred_at = item.get("occurred_at")
    recency_weight = 0
    if occurred_at:
        age_minutes = max(0, int((timezone.now() - occurred_at).total_seconds() // 60))
        recency_weight = max(0, 180 - min(age_minutes, 180))
    elif item.get("persistent", False):
        recency_weight = 40
    role_hint = item.get("role_hint", "")
    role_weight = 25 if role_hint == "action" else 12 if role_hint == "review" else 0
    return tone_weight + recency_weight + role_weight


def _finalize_watch_items(request, scope, items, *, limit=6):
    dismissed = _dismissed_watch_ids(request)
    cutoff = timezone.now() - timedelta(hours=12)
    finalized = []
    for item in items:
        occurred_at = item.get("occurred_at")
        persistent = item.get("persistent", False)
        if occurred_at and occurred_at < cutoff:
            continue
        if occurred_at is None and not persistent:
            continue
        signal_id = _watch_signal_id(scope, item.get("title", ""), item.get("detail", ""), occurred_at, item.get("meta", ""))
        if signal_id in dismissed:
            continue
        item = {**item, "id": signal_id}
        finalized.append(item)
    finalized.sort(
        key=lambda item: (
            _watch_priority_score(item),
            item.get("occurred_at") or timezone.make_aware(timezone.datetime.min, timezone.get_current_timezone()),
        ),
        reverse=True,
    )
    return finalized[:limit]


def _sweep_overdue_appointments_and_surgeries(hospital):
    if not hospital:
        return {"appointments": 0, "surgeries": 0}
    now = timezone.localtime()
    today = now.date()
    current_time = now.time()
    updates = {"appointments": 0, "surgeries": 0}

    overdue_appointments = Appointment.objects.select_related("patient__user", "doctor__user", "hospital").filter(
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED]
    )
    if hospital:
        overdue_appointments = overdue_appointments.filter(hospital=hospital)
    overdue_appointments = overdue_appointments.filter(
        Q(appointment_date__lt=today) | Q(appointment_date=today, appointment_time__lte=current_time)
    )
    for appointment in overdue_appointments:
        appointment.status = Appointment.Status.PAST
        appointment.save(update_fields=["status"])
        updates["appointments"] += 1
        broadcast_hospital_update(
            appointment.hospital,
            event_type="appointment_updated",
            payload={
                "appointment_id": appointment.id,
                "status": appointment.status,
                "status_label": appointment.get_status_display(),
                "patient_id": appointment.patient_id,
                "doctor_id": appointment.doctor_id,
            },
        )
        if appointment.patient_id:
            send_user_notification(
                appointment.patient.user,
                "Appointment marked past",
                f"Your appointment with {appointment.doctor} on {appointment.appointment_date} at {appointment.appointment_time} is now marked as past.",
            )
        if appointment.doctor_id:
            send_user_notification(
                appointment.doctor.user,
                "Appointment marked past",
                f"Your appointment with {appointment.patient} on {appointment.appointment_date} at {appointment.appointment_time} is now marked as past.",
            )

    overdue_surgeries = SurgicalCase.objects.select_related("patient__user", "surgeon__user", "hospital").filter(
        status__in=[SurgicalCase.Status.SCHEDULED, SurgicalCase.Status.PRE_OP]
    )
    if hospital:
        overdue_surgeries = overdue_surgeries.filter(hospital=hospital)
    overdue_surgeries = overdue_surgeries.filter(scheduled_start__lte=now)
    for surgery in overdue_surgeries:
        SurgicalCase.objects.filter(pk=surgery.pk).update(status=SurgicalCase.Status.PAST)
        surgery.status = SurgicalCase.Status.PAST
        updates["surgeries"] += 1
        broadcast_hospital_update(
            surgery.hospital,
            event_type="surgery_updated",
            payload={
                "patient_id": surgery.patient_id,
                "surgery_id": surgery.id,
                "status": surgery.status,
                "status_label": surgery.get_status_display(),
            },
        )
        if surgery.patient_id:
            send_user_notification(
                surgery.patient.user,
                "Surgery status updated",
                f"Your surgical case for {surgery.procedure_name} is now past scheduled time and marked as {surgery.get_status_display().lower()}.",
            )
        if surgery.surgeon_id:
            send_user_notification(
                surgery.surgeon.user,
                "Surgery status updated",
                f"{surgery.patient}'s surgical case for {surgery.procedure_name} is now marked as {surgery.get_status_display().lower()}.",
            )

    return updates


def _hospital_watch_items(request, hospital):
    watch = []
    if not hospital:
        return watch

    recent_walk_in = WalkInEncounter.objects.filter(hospital=hospital).order_by("-last_updated_at").first()
    recent_surgery = SurgicalCase.objects.filter(hospital=hospital).order_by("-created_at", "-scheduled_start").first()
    recent_lab = LabTestResult.objects.filter(request__hospital=hospital).select_related("request__patient__user", "request").order_by("-completed_at").first()
    critical_incident = EmergencyIncident.objects.filter(hospital=hospital, status=EmergencyIncident.Status.OPEN).order_by("-created_at").first()

    if critical_incident:
        watch.append(
            {
                "tone": "danger",
                "title": "Open emergency incident",
                "detail": f"{critical_incident.title} is still open. Emergency coordination may need immediate follow-through.",
                "meta": _minutes_ago_label(critical_incident.created_at),
                "occurred_at": critical_incident.created_at,
                "role_hint": "action",
            }
        )
    if recent_walk_in:
        watch.append(
            {
                "tone": "warning" if recent_walk_in.is_critical else "primary",
                "title": "Latest walk-in movement",
                "detail": f"Latest walk-in: {recent_walk_in.patient} is {recent_walk_in.get_status_display().lower()} with severity {recent_walk_in.severity_index}/100.",
                "meta": _minutes_ago_label(recent_walk_in.last_updated_at or recent_walk_in.arrived_at),
                "occurred_at": recent_walk_in.last_updated_at or recent_walk_in.arrived_at,
                "role_hint": "review",
            }
        )
    if recent_surgery:
        watch.append(
            {
                "tone": "success" if recent_surgery.status == SurgicalCase.Status.COMPLETED else "primary",
                "title": "Surgery board update",
                "detail": f"{recent_surgery.procedure_name} for {recent_surgery.patient} is now {recent_surgery.get_status_display().lower()}.",
                "meta": _minutes_ago_label(recent_surgery.created_at),
                "occurred_at": recent_surgery.created_at,
            }
        )
    if recent_lab:
        watch.append(
            {
                "tone": "primary",
                "title": "Lab completion",
                "detail": f"{recent_lab.request.test_name} was completed for {recent_lab.request.patient}. Care-team review may be due.",
                "meta": _minutes_ago_label(recent_lab.completed_at),
                "occurred_at": recent_lab.completed_at,
                "role_hint": "review",
            }
        )
    return _finalize_watch_items(request, f"hospital:{hospital.id}", watch, limit=6)


def _doctor_watch_items(request, current_patient, walk_in_queue, pending_lab_reviews):
    watch = []
    if current_patient:
        latest_vitals = VitalSign.objects.filter(patient=current_patient).order_by("-recorded_at").first()
        latest_record = MedicalRecord.objects.filter(patient=current_patient).order_by("-created_at").first()
        if latest_vitals and (
            (latest_vitals.oxygen_saturation is not None and latest_vitals.oxygen_saturation < 92)
            or (latest_vitals.temperature_c is not None and latest_vitals.temperature_c >= 39)
            or (latest_vitals.pulse_rate is not None and latest_vitals.pulse_rate >= 120)
        ):
            watch.append(
                {
                    "tone": "danger",
                    "title": "Current chart pattern",
                    "detail": f"Have you noticed that {current_patient}'s latest vitals show O2 {latest_vitals.oxygen_saturation or '-'}, temp {latest_vitals.temperature_c or '-'}, pulse {latest_vitals.pulse_rate or '-'}? That pattern may need immediate review.",
                    "meta": _minutes_ago_label(latest_vitals.recorded_at),
                    "occurred_at": latest_vitals.recorded_at,
                    "role_hint": "action",
                }
            )
        elif latest_record and latest_record.assessment:
            watch.append(
                {
                    "tone": "primary",
                    "title": "Chart continuity note",
                    "detail": f"Current chart context for {current_patient} already contains an assessment trail. Consider aligning the next step with the latest documented plan.",
                    "meta": _minutes_ago_label(latest_record.created_at),
                    "occurred_at": latest_record.created_at,
                }
            )
    next_walk_in = walk_in_queue.first()
    if next_walk_in:
        watch.append(
            {
                "tone": "warning" if next_walk_in.is_critical else "primary",
                "title": "Next queue patient",
                "detail": f"{next_walk_in.patient} is next in the doctor queue with severity {next_walk_in.severity_index}/100 and status {next_walk_in.get_status_display().lower()}.",
                "meta": _minutes_ago_label(next_walk_in.last_updated_at or next_walk_in.arrived_at),
                "occurred_at": next_walk_in.last_updated_at or next_walk_in.arrived_at,
                "role_hint": "action",
            }
        )
    next_lab = pending_lab_reviews.first()
    if next_lab:
        watch.append(
            {
                "tone": "primary",
                "title": "Lab review ready",
                "detail": f"{next_lab.request.test_name} for {next_lab.request.patient} is ready and still awaiting your review.",
                "meta": _minutes_ago_label(next_lab.completed_at),
                "occurred_at": next_lab.completed_at,
                "role_hint": "action",
            }
        )
    return _finalize_watch_items(request, f"doctor:{request.user.id}", watch, limit=6)


def _patient_watch_items(request, patient, appointments, billings, lab_results, admissions):
    watch = []
    now = timezone.localtime()
    today = now.date()
    current_time = now.time()
    latest_lab = lab_results.first()
    if latest_lab:
        watch.append(
            {
                "tone": "primary",
                "title": "Lab result ready",
                "detail": f"You have a completed lab result for {latest_lab.request.test_name}. It may help to review it together with your clinician's latest plan.",
                "meta": _minutes_ago_label(latest_lab.completed_at),
                "occurred_at": latest_lab.completed_at,
                "role_hint": "review",
            }
        )
    unpaid_bill = billings.filter(paid=False).order_by("-created_at").first()
    if unpaid_bill:
        watch.append(
            {
                "tone": "warning",
                "title": "Outstanding billing",
                "detail": f"There is an unpaid billing item for {unpaid_bill.get_billing_type_display().lower()}. Settling it may prevent delays in the next step of care.",
                "meta": _minutes_ago_label(unpaid_bill.created_at),
                "occurred_at": unpaid_bill.created_at,
                "role_hint": "action",
            }
        )
    next_visit = (
        appointments.filter(status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED])
        .filter(Q(appointment_date__gt=today) | Q(appointment_date=today, appointment_time__gt=current_time))
        .order_by("appointment_date", "appointment_time")
        .first()
    )
    if next_visit:
        watch.append(
            {
                "tone": "primary",
                "title": "Upcoming appointment",
                "detail": f"Your next appointment with {next_visit.doctor} is scheduled for {next_visit.appointment_date} at {next_visit.appointment_time}.",
                "meta": "Upcoming",
                "persistent": True,
                "role_hint": "review",
            }
        )
    active_admission = admissions.filter(status=Admission.Status.ACTIVE).first()
    if active_admission:
        watch.append(
            {
                "tone": "warning",
                "title": "Active admission",
                "detail": f"Your admission remains active in {active_admission.ward.name}. BayAfya will continue surfacing discharge and follow-up steps as they become available.",
                "meta": _minutes_ago_label(active_admission.admitted_at),
                "occurred_at": active_admission.admitted_at,
            }
        )
    return _finalize_watch_items(request, f"patient:{patient.id}", watch, limit=6)


def _patient_walk_in_journey(patient, focus_hospitals):
    encounter = (
        WalkInEncounter.objects.filter(patient=patient, hospital__in=focus_hospitals)
        .select_related("hospital", "admission__ward", "admission__bed")
        .prefetch_related("events")
        .order_by("-arrived_at")
        .first()
    )
    if not encounter:
        return None

    status_index = {
        WalkInEncounter.Status.WAITING_TRIAGE: 1,
        WalkInEncounter.Status.TRIAGED: 2,
        WalkInEncounter.Status.WAITING_DOCTOR: 3,
        WalkInEncounter.Status.IN_CONSULTATION: 3,
        WalkInEncounter.Status.AWAITING_LAB: 4,
        WalkInEncounter.Status.LAB_READY: 4,
        WalkInEncounter.Status.AWAITING_PHARMACY: 5,
        WalkInEncounter.Status.ADMISSION_REVIEW: 5,
        WalkInEncounter.Status.ADMITTED: 6,
        WalkInEncounter.Status.COMPLETED: 6,
        WalkInEncounter.Status.CANCELLED: 6,
    }
    active_step = status_index.get(encounter.status, 1)
    steps = [
        {"label": "Registered", "detail": f"Arrived at {encounter.hospital.name if encounter.hospital_id else 'BayAfya'} with ticket {encounter.ticket_number}.", "icon": "bi-person-plus", "step": 1},
        {"label": "Triage", "detail": encounter.triage_notes or "Nursing triage captures symptoms, vitals, and severity scoring.", "icon": "bi-heart-pulse", "step": 2},
        {"label": "Doctor review", "detail": encounter.doctor_notes or encounter.current_state or "Clinical review and treatment planning happen here.", "icon": "bi-person-badge", "step": 3},
        {"label": "Tests and results", "detail": encounter.lab_summary or "Lab requests and in-person results are tracked at this stage when needed.", "icon": "bi-beaker", "step": 4},
        {"label": "Medication or disposition", "detail": encounter.pharmacy_instructions or "BayAfya tracks pharmacy handoff, discharge planning, or admission review here.", "icon": "bi-capsule-pill", "step": 5},
        {"label": "Admission or discharge", "detail": encounter.admission.ward.name + (f" · Bed {encounter.admission.bed.bed_number}" if encounter.admission_id and encounter.admission.bed_id else "") if encounter.status == WalkInEncounter.Status.ADMITTED and encounter.admission_id else ("This encounter is completed." if encounter.status == WalkInEncounter.Status.COMPLETED else "Final ward placement or discharge instructions appear here."), "icon": "bi-hospital", "step": 6},
    ]
    for item in steps:
        item["is_complete"] = item["step"] < active_step
        item["is_active"] = item["step"] == active_step

    events = []
    for event in encounter.events.all()[:5]:
        actor_name = event.actor.get_full_name() or event.actor.username if event.actor_id else "BayAfya"
        events.append(
            {
                "title": event.stage,
                "detail": event.note or "Care activity recorded.",
                "meta": f"{actor_name} · {event.created_at:%Y-%m-%d %H:%M}",
            }
        )

    return {
        "encounter": encounter,
        "current_stage": encounter.get_status_display(),
        "current_state": encounter.current_state or encounter.doctor_notes or encounter.symptoms or "BayAfya is tracking this care journey live.",
        "steps": steps,
        "events": events,
    }


def _operations_watch_items(request, role, hospital, alerts, walk_in_summary):
    watch = []
    if role in {"", None} and alerts:
        first_alert = alerts[0]
        watch.append(
            {
                "tone": first_alert.get("tone", "primary"),
                "title": "Hospital flow signal",
                "detail": f"{first_alert['title']}: {first_alert['detail']}",
                "meta": "Live signal",
                "persistent": True,
            }
        )
    if role == HospitalAccess.Role.RECEPTIONIST and walk_in_summary.get("waiting_triage"):
        watch.append(
            {
                "tone": "warning",
                "title": "Front-desk queue pressure",
                "detail": f"{walk_in_summary['waiting_triage']} patients are still waiting for triage. Front-desk pacing may need adjustment.",
                "meta": "Queue focus",
                "persistent": True,
                "role_hint": "action",
            }
        )
    if role == HospitalAccess.Role.NURSE and walk_in_summary.get("critical"):
        watch.append(
            {
                "tone": "danger",
                "title": "Critical bedside queue",
                "detail": f"{walk_in_summary['critical']} critical walk-ins are currently in the flow. Bedside review should stay prioritized.",
                "meta": "Critical queue",
                "persistent": True,
                "role_hint": "action",
            }
        )
    if role == HospitalAccess.Role.LAB_TECHNICIAN:
        urgent_request = _scope_queryset(
            LabTestRequest.objects.filter(priority__in=["urgent", "stat"], status__in=[LabTestRequest.Status.REQUESTED, LabTestRequest.Status.IN_PROGRESS]),
            hospital,
        ).order_by("-requested_at").first()
        if urgent_request:
            watch.append(
                {
                    "tone": "warning",
                    "title": "Urgent laboratory request",
                    "detail": f"{urgent_request.test_name} for {urgent_request.patient} is flagged {urgent_request.priority.upper()} and still in progress.",
                    "meta": _minutes_ago_label(urgent_request.requested_at),
                    "occurred_at": urgent_request.requested_at,
                    "role_hint": "action",
                }
            )
    if role == HospitalAccess.Role.PHARMACIST:
        pending_task = PharmacyTask.objects.filter(patient__hospital=hospital, status__in=[PharmacyTask.Status.PENDING, PharmacyTask.Status.IN_PROGRESS]).order_by("-created_at").first() if hospital else None
        if pending_task:
            watch.append(
                {
                    "tone": "primary",
                    "title": "Dispensing still pending",
                    "detail": f"Dispensing for {pending_task.patient} remains {pending_task.get_status_display().lower()}.",
                    "meta": _minutes_ago_label(pending_task.created_at),
                    "occurred_at": pending_task.created_at,
                    "role_hint": "action",
                }
            )
    if role == HospitalAccess.Role.EMERGENCY_OPERATOR:
        incident = EmergencyIncident.objects.filter(hospital=hospital, status=EmergencyIncident.Status.OPEN).order_by("-created_at").first() if hospital else None
        if incident:
            watch.append(
                {
                    "tone": "danger",
                    "title": "Emergency response still open",
                    "detail": f"{incident.title} remains open and may still require coordinated hospital response.",
                    "meta": _minutes_ago_label(incident.created_at),
                    "occurred_at": incident.created_at,
                    "role_hint": "action",
                }
            )
    scope = f"operations:{hospital.id if hospital else 'global'}:{role or request.user.role}"
    return _finalize_watch_items(request, scope, watch, limit=6)


def _patient_condition_analytics(hospital):
    queryset = PatientCondition.objects.select_related("patient__user", "condition", "hospital")
    if hospital:
        queryset = queryset.filter(hospital=hospital)
    active_queryset = queryset.filter(is_active=True)
    condition_counter = Counter()
    severity_counter = Counter()
    age_group_counter = Counter()
    patient_condition_counter = Counter()
    recent_items = []

    for item in active_queryset.select_related("patient__user", "condition", "hospital")[:250]:
        label = item.condition_name or (item.condition.name if item.condition_id else "Unspecified condition")
        condition_counter[label] += 1
        severity_counter[item.severity] += 1
        age_group_counter[item.patient.age_group] += 1
        patient_condition_counter[item.patient_id] += 1
        recent_items.append(item)

    top_conditions = [
        {"label": label, "value": value, "patients": value}
        for label, value in condition_counter.most_common(8)
    ]
    age_groups = [
        {"label": label, "value": value}
        for label, value in age_group_counter.most_common()
    ]
    severity_breakdown = [
        {"label": label.title(), "value": value}
        for label, value in severity_counter.items()
    ]
    high_touch_patients = []
    patient_ids = [patient_id for patient_id, _ in patient_condition_counter.most_common(8)]
    if patient_ids:
        patient_map = {
            patient.id: patient
            for patient in Patient.objects.filter(id__in=patient_ids).select_related("user", "hospital")
        }
        for patient_id in patient_ids:
            patient = patient_map.get(patient_id)
            if patient:
                high_touch_patients.append(
                    {
                        "patient": patient,
                        "condition_count": patient_condition_counter[patient_id],
                    }
                )

    return {
        "active_conditions_total": active_queryset.count(),
        "top_conditions": top_conditions,
        "age_groups": age_groups,
        "severity_breakdown": severity_breakdown,
        "recent_conditions": recent_items[:8],
        "high_touch_patients": high_touch_patients,
    }


def _reporting_window(request):
    period = (request.GET.get("period") or "week").strip().lower()
    start = request.GET.get("start")
    end = request.GET.get("end")
    today = timezone.localdate()
    if period == "day":
        return period, today, today
    if period == "month":
        return period, today - timedelta(days=30), today
    if period == "custom" and start and end:
        try:
            return period, timezone.datetime.fromisoformat(start).date(), timezone.datetime.fromisoformat(end).date()
        except ValueError:
            return "week", today - timedelta(days=7), today
    return "week", today - timedelta(days=7), today


def _condition_reporting(hospital, start_date, end_date):
    queryset = PatientCondition.objects.select_related("patient__user", "condition", "hospital").filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )
    if hospital:
        queryset = queryset.filter(hospital=hospital)
    top_counter = Counter()
    daily_counter = Counter()
    for item in queryset:
        label = item.condition_name or (item.condition.name if item.condition_id else "Unspecified condition")
        top_counter[label] += 1
        daily_counter[item.created_at.date().isoformat()] += 1
    lab_results = LabTestResult.objects.filter(
        completed_at__date__gte=start_date,
        completed_at__date__lte=end_date,
    )
    if hospital:
        lab_results = lab_results.filter(request__hospital=hospital)
    return {
        "entries_total": queryset.count(),
        "top_conditions": [{"label": label, "value": value} for label, value in top_counter.most_common(10)],
        "daily_breakdown": [{"label": label, "value": value} for label, value in sorted(daily_counter.items())],
        "lab_results_total": lab_results.count(),
    }


def _surgery_overview(hospital):
    queryset = SurgicalCase.objects.select_related("patient__user", "surgeon__user", "operating_room", "hospital")
    if hospital:
        queryset = queryset.filter(hospital=hospital)
    upcoming = queryset.filter(status__in=[SurgicalCase.Status.SCHEDULED, SurgicalCase.Status.PRE_OP, SurgicalCase.Status.IN_SURGERY])
    room_queryset = OperatingRoom.objects.select_related("ward")
    if hospital:
        room_queryset = room_queryset.filter(hospital=hospital)
    return {
        "upcoming_cases": upcoming.order_by("scheduled_start")[:10],
        "scheduled_count": upcoming.count(),
        "completed_count": queryset.filter(status__in=[SurgicalCase.Status.COMPLETED, SurgicalCase.Status.PAST]).count(),
        "cancelled_count": queryset.filter(status=SurgicalCase.Status.CANCELLED).count(),
        "operating_rooms": room_queryset.order_by("room_number"),
    }


def _hospital_admin_context(request, hospital):
    staff_accesses = (
        HospitalAccess.objects.select_related("user", "hospital")
        .filter(hospital=hospital)
        .order_by("-pk")
        if hospital
        else HospitalAccess.objects.none()
    )
    active_staff_accesses = staff_accesses.filter(status=HospitalAccess.Status.ACTIVE)
    invitations = (
        HospitalInvitation.objects.select_related("created_by", "redeemed_by")
        .filter(hospital=hospital)
        .order_by("-created_at")[:8]
        if hospital
        else HospitalInvitation.objects.none()
    )
    recent_staff = active_staff_accesses.filter(role__in=[*OWNER_ROLES, HospitalAccess.Role.DOCTOR, HospitalAccess.Role.NURSE, HospitalAccess.Role.RECEPTIONIST, HospitalAccess.Role.LAB_TECHNICIAN, HospitalAccess.Role.EMERGENCY_OPERATOR])[:8]
    operations_context = _operations_workspace_context(request, active_access=getattr(request, "_active_access", None), hospital=hospital) if hospital else {"admin_overview": {"open_supply_requests": 0, "critical_incidents": 0, "pending_qc_reviews": 0, "occupied_beds": 0}}
    admin_stat_cards = [
        {"label": "Staff", "value": active_staff_accesses.filter(role__in=[*OWNER_ROLES, HospitalAccess.Role.DOCTOR, HospitalAccess.Role.NURSE, HospitalAccess.Role.RECEPTIONIST, HospitalAccess.Role.LAB_TECHNICIAN, HospitalAccess.Role.PHARMACIST, HospitalAccess.Role.COUNSELOR, HospitalAccess.Role.EMERGENCY_OPERATOR]).count(), "metric": "staff", "icon": "bi-people"},
        {"label": "Patients", "value": _patient_scope_queryset(hospital).count(), "metric": "patients", "icon": "bi-person-vcard"},
        {"label": "Appointments", "value": _scope_queryset(Appointment.objects.all(), hospital).count(), "metric": "appointments", "icon": "bi-calendar2-week"},
        {"label": "Records", "value": _scope_queryset(MedicalRecord.objects.all(), hospital).count(), "metric": "records", "icon": "bi-journal-medical"},
        {"label": "Beds", "value": _scope_queryset(Bed.objects.filter(is_occupied=False), hospital).count(), "metric": "beds", "icon": "bi-door-open"},
        {"label": "Conditions", "value": _scope_queryset(PatientCondition.objects.filter(is_active=True), hospital).count(), "metric": "conditions", "icon": "bi-clipboard2-pulse"},
        {"label": "Surgeries", "value": _scope_queryset(SurgicalCase.objects.exclude(status=SurgicalCase.Status.CANCELLED), hospital).count(), "metric": "surgeries", "icon": "bi-scissors"},
    ]
    admin_secondary_stat_cards = [
        {"label": "Open supply requests", "value": operations_context["admin_overview"]["open_supply_requests"], "metric": "open_supply_requests", "icon": "bi-box-seam"},
        {"label": "Critical incidents", "value": operations_context["admin_overview"]["critical_incidents"], "metric": "critical_incidents", "icon": "bi-exclamation-diamond"},
        {"label": "QC reviews", "value": operations_context["admin_overview"]["pending_qc_reviews"], "metric": "pending_qc_reviews", "icon": "bi-beaker"},
        {"label": "Occupied beds", "value": operations_context["admin_overview"]["occupied_beds"], "metric": "occupied_beds", "icon": "bi-hospital"},
    ]
    return {
        "hospital": hospital,
        "assistant_watch_items": _hospital_watch_items(request, hospital),
        "hospital_staff": staff_accesses,
        "active_hospital_staff": active_staff_accesses,
        "hospital_invitations": invitations,
        "recent_staff": recent_staff,
        "admin_stat_cards": admin_stat_cards,
        "admin_secondary_stat_cards": admin_secondary_stat_cards,
        "assistant_access_grants": (
            AssistantAccessGrant.objects.select_related("requester", "patient_user", "approved_by")
            .filter(status=AssistantAccessGrant.Status.APPROVED, hospital_id=getattr(hospital, "id", None))
            .order_by("-created_at")[:8]
            if hospital
            else AssistantAccessGrant.objects.none()
        ),
        "assistant_access_form": AssistantAccessGrantForm(hospital=hospital),
        "hospital_form": HospitalInvitationForm(allowed_roles=_invitation_roles_for_access(request._active_access) if hasattr(request, "_active_access") else None),
        "latest_invitation_code": request.session.pop("latest_invitation_code", None),
        "clinical_insights": _patient_condition_analytics(hospital),
        "surgery_overview": _surgery_overview(hospital),
        "stats": {
            "staff": admin_stat_cards[0]["value"],
            "patients": admin_stat_cards[1]["value"],
            "appointments": admin_stat_cards[2]["value"],
            "records": admin_stat_cards[3]["value"],
            "beds": admin_stat_cards[4]["value"],
            "conditions": admin_stat_cards[5]["value"],
            "surgeries": admin_stat_cards[6]["value"],
        },
    }


def _dashboard_live_metrics_payload(request):
    user = request.user
    accesses, active_access, hospital = _active_accesses(request)
    if user.role == User.Role.PATIENT:
        patient = get_object_or_404(Patient, user=user)
        if patient.is_deceased or not any(access.role == HospitalAccess.Role.PATIENT for access in accesses):
            raise PermissionDenied("This patient account no longer has active facility access.")
    if hospital is None and user.role == User.Role.ADMIN:
        hospital = Hospital.objects.filter(owner=user, is_active=True).first()
    active_role = active_access.role if active_access else user.role
    _sweep_overdue_appointments_and_surgeries(hospital)

    if active_role in OWNER_ROLES or user.role == User.Role.ADMIN:
        admin_context = _hospital_admin_context(request, hospital)
        operations_context = _operations_workspace_context(request, active_access=active_access, hospital=hospital)
        combined_watch = _finalize_watch_items(
            request,
            f"admin-combined:{hospital.id if hospital else 'global'}",
            admin_context["assistant_watch_items"] + operations_context["assistant_watch_items"],
            limit=6,
        )
        return {
            "ok": True,
            "role": "admin",
            "metrics": {
                "staff": admin_context["stats"]["staff"],
                "patients": admin_context["stats"]["patients"],
                "appointments": admin_context["stats"]["appointments"],
                "records": admin_context["stats"]["records"],
                "beds": admin_context["stats"]["beds"],
                "conditions": admin_context["stats"]["conditions"],
                "surgeries": admin_context["stats"]["surgeries"],
                "open_supply_requests": operations_context["admin_overview"]["open_supply_requests"],
                "critical_incidents": operations_context["admin_overview"]["critical_incidents"],
                "pending_qc_reviews": operations_context["admin_overview"]["pending_qc_reviews"],
                "occupied_beds": operations_context["admin_overview"]["occupied_beds"],
            },
            "watch_items": combined_watch,
        }

    if active_role == HospitalAccess.Role.DOCTOR or user.role == User.Role.DOCTOR:
        doctor = get_object_or_404(Doctor, user=user)
        context = _doctor_workspace_context(request, doctor=doctor, hospital=hospital, accesses=accesses)
        return {"ok": True, "role": "doctor", "metrics": context["stats"], "watch_items": context["assistant_watch_items"]}

    if active_role in {
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
        HospitalAccess.Role.PHARMACIST,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    } or user.role in {
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.LAB_TECHNICIAN,
        User.Role.PHARMACIST,
        User.Role.EMERGENCY_OPERATOR,
    }:
        operations_context = _operations_workspace_context(request, active_access=active_access, hospital=hospital)
        return {
            "ok": True,
            "role": "operations",
            "metrics": {
                "beds_available": _scope_queryset(Bed.objects.filter(is_occupied=False), hospital).count(),
                "active_admissions": _scope_queryset(Admission.objects.filter(status=Admission.Status.ACTIVE), hospital).count(),
                "staff_count": _scope_queryset(StaffProfile.objects.all(), hospital).count(),
                "queued_patients": _scope_queryset(QueueTicket.objects.filter(status=QueueTicket.Status.QUEUED), hospital).count(),
                "pending_labs": _scope_queryset(LabTestRequest.objects.filter(status=LabTestRequest.Status.REQUESTED), hospital).count(),
                "open_supply_requests": operations_context["admin_overview"]["open_supply_requests"],
                "critical_incidents": operations_context["admin_overview"]["critical_incidents"],
            },
            "watch_items": operations_context["assistant_watch_items"],
        }

    patient = get_object_or_404(Patient, user=user)
    context = _patient_workspace_context(request, patient=patient, hospital=hospital, accesses=accesses)
    return {"ok": True, "role": "patient", "metrics": context["stats"], "watch_items": context["assistant_watch_items"]}


@login_required
def dashboard(request):
    user = request.user
    accesses, active_access, hospital = _active_accesses(request)
    if user.role == User.Role.PATIENT:
        patient = get_object_or_404(Patient, user=user)
        if patient.is_deceased or not any(access.role == HospitalAccess.Role.PATIENT for access in accesses):
            raise PermissionDenied("This patient account no longer has active facility access.")
    if hospital is None and user.role == User.Role.ADMIN:
        hospital = Hospital.objects.filter(owner=user, is_active=True).first()
    active_role = active_access.role if active_access else user.role
    request._active_access = active_access
    _sweep_overdue_appointments_and_surgeries(hospital)

    if active_role in OWNER_ROLES or user.role == User.Role.ADMIN:
        admin_context = _hospital_admin_context(request, hospital)
        operations_context = _operations_workspace_context(request, active_access=active_access, hospital=hospital)
        context = {
            "hospital_accesses": accesses,
            "current_hospital": hospital,
            "active_access": active_access,
        }
        context.update(admin_context)
        context.update(operations_context)
        context["assistant_watch_items"] = _finalize_watch_items(
            request,
            f"admin-combined:{hospital.id if hospital else 'global'}",
            admin_context.get("assistant_watch_items", []) + operations_context.get("assistant_watch_items", []),
            limit=6,
        )
        return render(request, "hospital/admin_dashboard.html", context)

    if active_role == HospitalAccess.Role.DOCTOR or user.role == User.Role.DOCTOR:
        doctor = get_object_or_404(Doctor, user=user)
        context = _doctor_workspace_context(request, doctor=doctor, hospital=hospital, accesses=accesses)
        return render(request, "hospital/doctor_dashboard.html", context)

    if active_role in {
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
        HospitalAccess.Role.PHARMACIST,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    } or user.role in {
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.LAB_TECHNICIAN,
        User.Role.PHARMACIST,
        User.Role.EMERGENCY_OPERATOR,
    }:
        context = {
            "current_hospital": hospital,
            "active_access": active_access,
            "wards": _scope_queryset(Ward.objects.all(), hospital).count(),
            "beds_available": _scope_queryset(Bed.objects.filter(is_occupied=False), hospital).count(),
            "active_admissions": _scope_queryset(Admission.objects.filter(status=Admission.Status.ACTIVE), hospital).count(),
            "queued_patients": _scope_queryset(QueueTicket.objects.filter(status=QueueTicket.Status.QUEUED), hospital).count(),
            "pending_labs": _scope_queryset(LabTestRequest.objects.filter(status=LabTestRequest.Status.REQUESTED), hospital).count(),
            "recent_vitals": _scope_queryset(VitalSign.objects.select_related("patient__user"), hospital)[:5],
            "recent_lab_requests": _scope_queryset(LabTestRequest.objects.select_related("patient__user", "requested_by__user"), hospital)[:5],
            "staff_count": _scope_queryset(StaffProfile.objects.all(), hospital).count(),
            "walk_in_intake_form": WalkInIntakeForm(hospital=hospital),
            "walk_in_triage_form": NurseTriageForm(),
            "walk_in_lab_result_form": WalkInLabResultForm(),
        }
        context.update(_walk_in_dashboard_context(hospital))
        context.update(_operations_workspace_context(request, active_access=active_access, hospital=hospital))
        return render(request, "hospital/operations_dashboard.html", context)

    patient = get_object_or_404(Patient, user=user)
    context = _patient_workspace_context(request, patient=patient, hospital=hospital, accesses=accesses)
    return render(request, "hospital/patient_dashboard.html", context)


@login_required
def dashboard_live_metrics(request):
    return JsonResponse(_dashboard_live_metrics_payload(request))


@login_required
@require_http_methods(["POST"])
def dismiss_watch_signal(request):
    signal_id = (request.POST.get("signal_id") or "").strip()
    if signal_id:
        dismissed = _dismissed_watch_ids(request)
        dismissed.add(signal_id)
        request.session["dismissed_watch_signal_ids"] = list(dismissed)[-120:]
    return JsonResponse({"ok": True, "signal_id": signal_id})


@login_required
@patient_required
def book_appointment(request):
    patient = get_object_or_404(Patient, user=request.user)
    if patient.is_deceased:
        raise PermissionDenied("This patient record has been marked deceased and cannot book new appointments.")
    _, _, hospital = _active_accesses(request)
    if request.method == "POST":
        form = AppointmentForm(request.POST, hospital=hospital)
        if form.is_valid():
            try:
                with transaction.atomic():
                    appointment = form.save(commit=False)
                    appointment.patient = patient
                    appointment.hospital = hospital
                    appointment.full_clean()
                    appointment.save()
                messages.success(request, "Appointment booked successfully.")
                return redirect("hospital:dashboard")
            except IntegrityError:
                form.add_error(None, "The selected appointment slot is no longer available.")
    else:
        form = AppointmentForm(hospital=hospital)
    return render(request, "hospital/book_appointment.html", {"form": form, "current_hospital": hospital})


@login_required
@doctor_required
def update_appointment_status(request, appointment_id, status):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    _, _, hospital = _active_accesses(request)
    filters = {"pk": appointment_id, "doctor__user": request.user}
    if hospital:
        filters["hospital"] = hospital
    appointment = get_object_or_404(Appointment, **filters)
    if status in Appointment.Status.values:
        appointment.status = status
        appointment.save(update_fields=["status"])
        if appointment.patient_id:
            send_user_notification(
                appointment.patient.user,
                "Appointment updated",
                f"Your appointment with {appointment.doctor} is now marked as {appointment.get_status_display().lower()}.",
            )
        if appointment.doctor_id:
            send_user_notification(
                appointment.doctor.user,
                "Appointment updated",
                f"Your appointment with {appointment.patient} is now marked as {appointment.get_status_display().lower()}.",
            )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "message": "Appointment status updated.",
                    "appointment_id": appointment.pk,
                    "status": appointment.get_status_display(),
                    "status_slug": appointment.status,
                    "metrics": _dashboard_live_metrics_payload(request)["metrics"],
                }
            )
        messages.success(request, "Appointment status updated.")
    return redirect("hospital:dashboard")


@login_required
def appointment_center(request):
    accesses, active_access, hospital = _active_accesses(request)
    window, start_date, end_date, window_label = _period_bounds(request, "appointment_window", default="week")
    base_queryset = Appointment.objects.select_related("patient__user", "doctor__user", "hospital")

    if request.user.role == User.Role.PATIENT:
        patient = get_object_or_404(Patient, user=request.user)
        queryset = base_queryset.filter(patient=patient)
        if hospital:
            queryset = queryset.filter(hospital=hospital)
        context_role = "patient"
        owner_label = patient.user.get_full_name() or patient.user.username
    elif request.user.role == User.Role.DOCTOR:
        doctor = get_object_or_404(Doctor, user=request.user)
        queryset = base_queryset.filter(doctor=doctor)
        if hospital:
            queryset = queryset.filter(hospital=hospital)
        elif accesses:
            hospital_ids = _access_hospital_ids(accesses, roles=[HospitalAccess.Role.DOCTOR, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER])
            if hospital_ids:
                queryset = queryset.filter(hospital_id__in=hospital_ids)
        context_role = "doctor"
        owner_label = str(doctor)
    else:
        raise PermissionDenied("This schedule center is currently available to patients and doctors.")

    queryset = queryset.filter(appointment_date__range=(start_date, end_date)).order_by("appointment_date", "appointment_time")
    upcoming = queryset.filter(status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED])
    completed = queryset.filter(status=Appointment.Status.COMPLETED)
    past = queryset.filter(status=Appointment.Status.PAST)
    cancelled = queryset.filter(status=Appointment.Status.CANCELLED)

    return render(
        request,
        "hospital/appointment_center.html",
        {
            "current_hospital": hospital,
            "appointment_window": window,
            "appointment_window_label": window_label,
            "appointment_window_start": start_date,
            "appointment_window_end": end_date,
            "appointments": queryset,
            "upcoming_appointments": upcoming,
            "completed_appointments": completed,
            "past_appointments": past,
            "cancelled_appointments": cancelled,
            "appointment_owner_label": owner_label,
            "appointment_center_role": context_role,
            "summary": {
                "total": queryset.count(),
                "upcoming": upcoming.count(),
                "completed": completed.count(),
                "past": past.count(),
                "cancelled": cancelled.count(),
            },
        },
    )


@login_required
@doctor_required
def create_medical_record(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    doctor = get_object_or_404(Doctor, user=request.user)
    _, _, hospital = _active_accesses(request)
    current_patient = _current_patient_from_session(request, hospital)
    form = MedicalRecordForm(request.POST, hospital=hospital, current_patient=current_patient)
    if form.is_valid():
        record = form.save(commit=False)
        if current_patient is not None:
            record.patient = current_patient
        record.doctor = doctor
        record.hospital = hospital
        record.save()
        walk_in_id = request.session.get("clinical_walk_in_id")
        if walk_in_id:
            walk_in = WalkInEncounter.objects.filter(pk=walk_in_id, patient=record.patient).first()
            if walk_in:
                walk_in.medical_record = record
                walk_in.save(update_fields=["medical_record", "last_updated_at"])
                _log_walk_in_event(
                    walk_in,
                    "record",
                    "Medical record linked from active clinical context.",
                    actor=request.user,
                )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "message": "Medical record saved.",
                    "record": {
                        "patient": str(record.patient),
                        "diagnosis": record.diagnosis or "Clinical note saved.",
                    },
                    "metrics": _dashboard_live_metrics_payload(request)["metrics"],
                }
            )
        messages.success(request, "Medical record saved.")
    elif request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "message": "Please review the medical record details."}, status=400)
    return redirect("hospital:dashboard")


@login_required
@doctor_required
def create_doctor_task(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    _, _, hospital = _active_accesses(request)
    form = DoctorTaskForm(request.POST, hospital=hospital, doctor_user=request.user)
    if form.is_valid():
        task = form.save(commit=False)
        task.hospital = hospital
        task.created_by = request.user
        task.save()
        if task.assigned_to_id and task.assigned_to_id != request.user.id:
            Notification.objects.create(
                user=task.assigned_to,
                title="New doctor task",
                message=f"{request.user.get_full_name() or request.user.username} assigned '{task.title}' in {hospital.name if hospital else 'BayAfya'}.",
            )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "message": "Doctor task created.",
                    "task": {
                        "id": task.id,
                        "title": task.title,
                        "patient": str(task.patient) if task.patient_id else "General task",
                        "hospital": task.hospital.name if task.hospital_id else "",
                        "priority": task.get_priority_display(),
                        "priority_slug": task.priority,
                        "details": task.details or "No extra task details.",
                        "status": task.status,
                    },
                    "metrics": _dashboard_live_metrics_payload(request)["metrics"],
                }
            )
        messages.success(request, "Doctor task created.")
    else:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": "Please review the doctor task details."}, status=400)
        messages.error(request, "Please review the doctor task details.")
    return redirect("hospital:dashboard")


@login_required
@doctor_required
def update_doctor_task_status(request, task_id, status):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    accesses, _, hospital = _active_accesses(request)
    task = get_object_or_404(
        DoctorTask.objects.select_related("hospital"),
        pk=task_id,
    )
    accessible_hospital_ids = set(
        _access_hospital_ids(
            accesses,
            roles=[HospitalAccess.Role.DOCTOR, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER],
        )
    )
    if not accessible_hospital_ids and hospital:
        accessible_hospital_ids = {hospital.id}
    if task.hospital_id and accessible_hospital_ids and task.hospital_id not in accessible_hospital_ids:
        raise PermissionDenied("Task not available in the current hospital context.")
    if request.user.id not in {task.created_by_id, task.assigned_to_id}:
        raise PermissionDenied("Only the task owner or assignee can update this task.")
    if status in DoctorTask.Status.values:
        task.status = status
        task.completed_at = timezone.now() if status == DoctorTask.Status.DONE else None
        task.save(update_fields=["status", "completed_at"])
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "message": "Doctor task updated.",
                    "task": {
                        "id": task.id,
                        "status": task.status,
                        "status_label": task.get_status_display(),
                        "completed": task.status == DoctorTask.Status.DONE,
                    },
                    "metrics": _dashboard_live_metrics_payload(request)["metrics"],
                }
            )
        messages.success(request, "Doctor task updated.")
    return redirect("hospital:dashboard")


@login_required
@doctor_required
def create_care_plan(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    doctor = get_object_or_404(Doctor, user=request.user)
    _, _, hospital = _active_accesses(request)
    current_patient = _current_patient_from_session(request, hospital)
    form = CarePlanForm(request.POST, hospital=hospital, current_patient=current_patient)
    if form.is_valid():
        care_plan = form.save(commit=False)
        care_plan.hospital = hospital
        care_plan.doctor = doctor
        care_plan.save()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "message": "Care plan saved.",
                    "care_plan": {
                        "id": care_plan.id,
                        "title": care_plan.title,
                        "patient": str(care_plan.patient),
                        "timeline": care_plan.timeline or "",
                        "goals": care_plan.goals or "",
                    },
                    "metrics": _dashboard_live_metrics_payload(request)["metrics"],
                }
            )
        messages.success(request, "Care plan saved.")
    else:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": "Please review the care plan details."}, status=400)
        messages.error(request, "Please review the care plan details.")
    return redirect("hospital:dashboard")


@login_required
@doctor_required
def create_internal_referral(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    doctor = get_object_or_404(Doctor, user=request.user)
    accesses, _, hospital = _active_accesses(request)
    affiliated_hospitals = Hospital.objects.filter(
        id__in=_access_hospital_ids(
            accesses,
            roles=[HospitalAccess.Role.DOCTOR, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER],
        )
    )
    current_patient = _current_patient_from_session(request, hospital)
    form = InternalReferralForm(request.POST, hospital=hospital, current_patient=current_patient)
    form.set_hospital_queryset(affiliated_hospitals.exclude(id=hospital.id if hospital else None))
    if form.is_valid():
        referral = form.save(commit=False)
        referral.referring_doctor = doctor
        referral.source_hospital = hospital
        referral.save()
        if referral.target_doctor_id:
            Notification.objects.create(
                user=referral.target_doctor.user,
                title="New internal referral",
                message=f"{doctor} referred {referral.patient} for {referral.specialty or 'specialist review'}.",
            )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "message": "Internal referral created.",
                    "referral": {
                        "id": referral.id,
                        "patient": str(referral.patient),
                        "target_doctor": str(referral.target_doctor) if referral.target_doctor_id else "Hospital specialist",
                        "target_hospital": referral.target_hospital.name if referral.target_hospital_id else "",
                        "reason": referral.reason or "",
                        "priority": referral.get_priority_display(),
                        "priority_slug": referral.priority,
                        "status": referral.get_status_display(),
                    },
                    "metrics": _dashboard_live_metrics_payload(request)["metrics"],
                }
            )
        messages.success(request, "Internal referral created.")
    else:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": "Please review the referral details."}, status=400)
        messages.error(request, "Please review the referral details.")
    return redirect("hospital:dashboard")


@login_required
@doctor_required
def update_internal_referral_status(request, referral_id, status):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    _, _, hospital = _active_accesses(request)
    referral = get_object_or_404(InternalReferral.objects.select_related("referring_doctor__user", "target_doctor__user"), pk=referral_id)
    if hospital and hospital.id not in {referral.source_hospital_id, referral.target_hospital_id}:
        raise PermissionDenied("Referral not available in the current hospital context.")
    allowed_user_ids = {referral.referring_doctor.user_id if referral.referring_doctor_id else None, referral.target_doctor.user_id if referral.target_doctor_id else None}
    if request.user.id not in allowed_user_ids:
        raise PermissionDenied("Only the referring or receiving doctor can update this referral.")
    if status in InternalReferral.Status.values:
        referral.status = status
        if status in {InternalReferral.Status.RESPONDED, InternalReferral.Status.CLOSED}:
            referral.responded_at = timezone.now()
        referral.save(update_fields=["status", "responded_at"])
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "message": "Referral status updated.",
                    "referral": {
                        "id": referral.id,
                        "status": referral.status,
                        "status_label": referral.get_status_display(),
                    },
                    "metrics": _dashboard_live_metrics_payload(request)["metrics"],
                }
            )
        messages.success(request, "Referral status updated.")
    return redirect("hospital:dashboard")


@login_required
@patient_required
def create_caregiver_access(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    _, _, hospital = _active_accesses(request)
    patient = get_object_or_404(Patient, user=request.user)
    form = CaregiverAccessForm(request.POST)
    if form.is_valid():
        access = form.save(commit=False)
        access.patient = patient
        access.hospital = hospital
        access.save()
        messages.success(request, "Caregiver access saved.")
    else:
        messages.error(request, "Please review the caregiver access details.")
    return redirect("hospital:dashboard")


@login_required
@patient_required
def create_advance_directive(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    _, _, hospital = _active_accesses(request)
    patient = get_object_or_404(Patient, user=request.user)
    form = AdvanceDirectiveForm(request.POST, request.FILES)
    if form.is_valid():
        directive = form.save(commit=False)
        directive.patient = patient
        directive.hospital = hospital
        directive.save()
        messages.success(request, "Advance directive saved.")
    else:
        messages.error(request, "Please review the advance directive details.")
    return redirect("hospital:dashboard")


@login_required
@patient_required
def submit_patient_feedback(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    _, _, hospital = _active_accesses(request)
    patient = get_object_or_404(Patient, user=request.user)
    form = PatientFeedbackForm(request.POST, hospital=hospital)
    if form.is_valid():
        feedback = form.save(commit=False)
        feedback.patient = patient
        feedback.hospital = hospital
        if feedback.staff_member_id and not feedback.service_area:
            feedback.service_area = f"{feedback.staff_member.get_role_display()} feedback"
        if feedback.staff_member_id and not feedback.doctor_id:
            matched_doctor = Doctor.objects.filter(user=feedback.staff_member).first()
            if matched_doctor:
                feedback.doctor = matched_doctor
        feedback.save()
        if hospital:
            _notify_hospital_admins(
                hospital,
                "New patient feedback",
                f"{patient} submitted feedback for review.",
            )
        messages.success(request, "Feedback submitted.")
    else:
        messages.error(request, "Please review the feedback details.")
    return redirect("hospital:dashboard")


@login_required
@require_http_methods(["POST"])
def create_shift_handover(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role != HospitalAccess.Role.NURSE:
        raise PermissionDenied("Nurse access is required.")
    staff_profile = getattr(request.user, "staff_profile", None)
    form = ShiftHandoverForm(request.POST)
    if form.is_valid():
        handover = form.save(commit=False)
        handover.hospital = hospital
        handover.staff = staff_profile
        handover.save()
        async_response = _async_dashboard_response(request, ok=True, message="Shift handover recorded.")
        if async_response is not None:
            return async_response
    else:
        async_response = _async_dashboard_response(
            request,
            ok=False,
            message="Please review the handover details.",
            status=400,
            errors=_dashboard_form_errors(form),
        )
        if async_response is not None:
            return async_response
    return redirect("hospital:dashboard")


@login_required
@require_http_methods(["POST"])
def create_shift_assignment(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in OWNER_ROLES:
        raise PermissionDenied("Administrative access is required.")
    form = ShiftAssignmentForm(request.POST, hospital=hospital)
    if form.is_valid():
        assignment = form.save(commit=False)
        assignment.hospital = hospital
        assignment.save()
        staff = assignment.staff
        staff.shift_start = assignment.start_time
        staff.shift_end = assignment.end_time
        staff.save(update_fields=["shift_start", "shift_end"])
        send_user_notification(
            staff.user,
            "Shift assigned",
            f"You are scheduled for {assignment.shift_date} from {assignment.start_time:%H:%M} to {assignment.end_time:%H:%M} at {hospital.name if hospital else 'BayAfya'}.",
        )
        broadcast_hospital_update(
            hospital,
            event_type="shift_assignment_created",
            payload={
                "assignment_id": assignment.id,
                "staff_id": staff.id,
                "user_id": staff.user_id,
                "shift_date": assignment.shift_date.isoformat(),
            },
        )
        async_response = _async_dashboard_response(request, ok=True, message="Shift assigned successfully.")
        if async_response is not None:
            return async_response
    else:
        async_response = _async_dashboard_response(
            request,
            ok=False,
            message="Please review the shift assignment details.",
            status=400,
            errors=_dashboard_form_errors(form),
        )
        if async_response is not None:
            return async_response
    return redirect("hospital:dashboard")


@login_required
def eligible_shift_staff(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in OWNER_ROLES:
        raise PermissionDenied("Administrative access is required.")

    shift_date = request.GET.get("shift_date")
    start_time = request.GET.get("start_time")
    end_time = request.GET.get("end_time")
    query = (request.GET.get("q") or "").strip()

    try:
        shift_date = datetime.strptime(shift_date, "%Y-%m-%d").date() if shift_date else timezone.localdate()
    except (TypeError, ValueError):
        shift_date = timezone.localdate()
    try:
        start_time = datetime.strptime(start_time, "%H:%M").time() if start_time else None
    except (TypeError, ValueError):
        start_time = None
    try:
        end_time = datetime.strptime(end_time, "%H:%M").time() if end_time else None
    except (TypeError, ValueError):
        end_time = None

    staff_queryset = eligible_shift_staff_queryset(
        hospital=hospital,
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
        query=query,
    )

    results = []
    for staff in staff_queryset[:40]:
        weekly_hours = scheduled_shift_hours_for_week(staff, shift_date)
        remaining = max(ShiftAssignmentForm.DEFAULT_WEEKLY_LIMIT_HOURS - weekly_hours, 0)
        results.append(
            {
                "value": str(staff.pk),
                "label": staff.user.get_full_name() or staff.user.username,
                "subtitle": (
                    f"{staff.get_role_display()} • "
                    f"{staff.department or 'General services'} • "
                    f"{remaining:.1f}h left this week"
                ),
                "full_label": format_shift_staff_label(
                    staff,
                    shift_date=shift_date,
                    weekly_limit_hours=ShiftAssignmentForm.DEFAULT_WEEKLY_LIMIT_HOURS,
                ),
            }
        )
    return JsonResponse({"results": results})


@login_required
@require_http_methods(["POST"])
def create_supply_request(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
        HospitalAccess.Role.PHARMACIST,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.OWNER,
    }:
        raise PermissionDenied("Operational staff access is required.")
    form = SupplyRequestForm(request.POST)
    if form.is_valid():
        supply = form.save(commit=False)
        supply.hospital = hospital
        supply.requested_by = request.user
        supply.save()
        async_response = _async_dashboard_response(request, ok=True, message="Supply request submitted.")
        if async_response is not None:
            return async_response
    else:
        async_response = _async_dashboard_response(
            request,
            ok=False,
            message="Please review the supply request details.",
            status=400,
            errors=_dashboard_form_errors(form),
        )
        if async_response is not None:
            return async_response
    return redirect("hospital:dashboard")


@login_required
@require_http_methods(["POST"])
def update_supply_request_status(request, supply_id):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in OWNER_ROLES:
        raise PermissionDenied("Administrative access is required.")
    supply = get_object_or_404(SupplyRequest, pk=supply_id, hospital=hospital)
    form = SupplyRequestStatusForm(request.POST, instance=supply)
    if form.is_valid():
        supply = form.save(commit=False)
        if supply.status == SupplyRequest.Status.FULFILLED:
            supply.fulfilled_at = timezone.now()
        supply.save()
        async_response = _async_dashboard_response(request, ok=True, message="Supply request updated.")
        if async_response is not None:
            return async_response
    else:
        async_response = _async_dashboard_response(
            request,
            ok=False,
            message="Please review the supply request status.",
            status=400,
            errors=_dashboard_form_errors(form),
        )
        if async_response is not None:
            return async_response
    return redirect("hospital:dashboard")


@login_required
@require_http_methods(["POST"])
def create_lab_qc_log(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role != HospitalAccess.Role.LAB_TECHNICIAN:
        raise PermissionDenied("Lab technician access is required.")
    staff_profile = getattr(request.user, "staff_profile", None)
    form = LabQualityControlLogForm(request.POST)
    if form.is_valid():
        qc = form.save(commit=False)
        qc.hospital = hospital
        qc.recorded_by = staff_profile
        qc.save()
        async_response = _async_dashboard_response(request, ok=True, message="Lab QC log recorded.")
        if async_response is not None:
            return async_response
    else:
        async_response = _async_dashboard_response(
            request,
            ok=False,
            message="Please review the QC log details.",
            status=400,
            errors=_dashboard_form_errors(form),
        )
        if async_response is not None:
            return async_response
    return redirect("hospital:dashboard")


@login_required
@require_http_methods(["POST"])
def create_emergency_incident(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {HospitalAccess.Role.EMERGENCY_OPERATOR, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER}:
        raise PermissionDenied("Emergency coordination access is required.")
    form = EmergencyIncidentForm(request.POST, hospital=hospital)
    if form.is_valid():
        incident = form.save(commit=False)
        incident.hospital = hospital
        incident.created_by = request.user
        if incident.status == EmergencyIncident.Status.RESOLVED and not incident.resolved_at:
            incident.resolved_at = timezone.now()
        incident.save()
        async_response = _async_dashboard_response(request, ok=True, message="Emergency incident saved.")
        if async_response is not None:
            return async_response
    else:
        async_response = _async_dashboard_response(
            request,
            ok=False,
            message="Please review the incident details.",
            status=400,
            errors=_dashboard_form_errors(form),
        )
        if async_response is not None:
            return async_response
    return redirect("hospital:dashboard")


@login_required
@require_http_methods(["POST"])
def update_emergency_incident_status(request, incident_id, status):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {HospitalAccess.Role.EMERGENCY_OPERATOR, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER}:
        raise PermissionDenied("Emergency coordination access is required.")
    incident = get_object_or_404(EmergencyIncident, pk=incident_id, hospital=hospital)
    if status in EmergencyIncident.Status.values:
        incident.status = status
        if status == EmergencyIncident.Status.RESOLVED:
            incident.resolved_at = timezone.now()
        incident.save(update_fields=["status", "resolved_at"])
        async_response = _async_dashboard_response(request, ok=True, message="Emergency incident updated.")
        if async_response is not None:
            return async_response
    return redirect("hospital:dashboard")


@login_required
@require_http_methods(["POST"])
def create_invitation(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in OWNER_ROLES | STAFF_INVITER_ROLES:
        raise PermissionDenied("Hospital staff with invitation rights only.")
    allowed_roles = _invitation_roles_for_access(active_access)
    form = HospitalInvitationForm(request.POST, allowed_roles=allowed_roles)
    if form.is_valid() and hospital:
        invitation = form.save(commit=False)
        invitation.hospital = hospital
        invitation.created_by = request.user
        code = secrets.token_hex(4).upper()
        while HospitalInvitation.objects.filter(code=code).exists():
            code = secrets.token_hex(4).upper()
        invitation.code = code
        invitation.save()
        request.session["latest_invitation_code"] = invitation.code
        _notify_hospital_admins(
            hospital,
            "Patient invitation created",
            f"{request.user.get_full_name() or request.user.username} created an invitation for a patient at {hospital.name}.",
            exclude_user=request.user,
        )
        messages.success(request, f"Authorization code generated for {invitation.get_role_display()}.")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "code": invitation.code,
                    "role": invitation.get_role_display(),
                    "hospital": hospital.name,
                }
            )
    else:
        messages.error(request, "Please complete the authorization code form.")
    return redirect("hospital:dashboard")


@login_required
def walk_in_hub(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or not _staff_can_manage_walk_ins(active_access.role):
        raise PermissionDenied("Walk-in workflow access is required.")

    dashboard_context = _walk_in_dashboard_context(hospital)
    role_panel = _walk_in_role_panel(active_access, hospital, request)
    doctor_queue = list(dashboard_context.get("walk_in_doctor_queue") or [])
    active_doctor_queue_id = None
    if role_panel.get("current_walk_in") and any(item.id == role_panel["current_walk_in"].id for item in doctor_queue):
        active_doctor_queue_id = role_panel["current_walk_in"].id
    elif doctor_queue and active_access.role in {HospitalAccess.Role.DOCTOR, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER}:
        active_doctor_queue_id = doctor_queue[0].id

    context = {
        "current_hospital": hospital,
        "active_access": active_access,
        "walk_in_intake_form": WalkInIntakeForm(hospital=hospital),
        "walk_in_triage_form": NurseTriageForm(),
        "walk_in_lab_result_form": WalkInLabResultForm(),
        "consult_form": WalkInConsultationForm(),
        "walk_in_role_panel": role_panel,
        "walk_in_patient_lookup_json": _walk_in_patient_lookup(hospital),
        "active_doctor_queue_id": active_doctor_queue_id,
    }
    context.update(dashboard_context)
    return render(request, "hospital/walk_in_hub.html", context)


@login_required
@require_http_methods(["POST"])
def intake_walk_in(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    }:
        raise PermissionDenied("Reception or admitting staff access is required.")

    form = WalkInIntakeForm(request.POST, hospital=hospital)
    if form.is_valid():
        try:
            with transaction.atomic():
                patient, created = _resolve_or_create_walk_in_patient(cleaned_data=form.cleaned_data, hospital=hospital)
                encounter = WalkInEncounter.objects.filter(
                    patient=patient,
                    hospital=hospital,
                    status__in=[
                        WalkInEncounter.Status.WAITING_TRIAGE,
                        WalkInEncounter.Status.TRIAGED,
                        WalkInEncounter.Status.WAITING_DOCTOR,
                        WalkInEncounter.Status.IN_CONSULTATION,
                        WalkInEncounter.Status.AWAITING_LAB,
                        WalkInEncounter.Status.LAB_READY,
                        WalkInEncounter.Status.AWAITING_PHARMACY,
                        WalkInEncounter.Status.ADMISSION_REVIEW,
                    ],
                ).first()
                if encounter is None:
                    encounter = WalkInEncounter.objects.create(
                        patient=patient,
                        hospital=hospital,
                        registered_by=request.user,
                        symptoms=form.cleaned_data["symptoms"],
                        current_state=form.cleaned_data.get("current_state", ""),
                        status=WalkInEncounter.Status.WAITING_TRIAGE,
                        queue_position=WalkInEncounter.objects.filter(hospital=hospital).exclude(
                            status__in=[WalkInEncounter.Status.COMPLETED, WalkInEncounter.Status.CANCELLED]
                        ).count() + 1,
                    )
                    _log_walk_in_event(
                        encounter,
                        "intake",
                        "Walk-in patient captured at reception and added to the triage queue.",
                        actor=request.user,
                    )
                    ensure_walk_in_registration_bill(encounter=encounter)
                else:
                    encounter.symptoms = form.cleaned_data["symptoms"]
                    encounter.current_state = form.cleaned_data.get("current_state", "")
                    encounter.last_updated_at = timezone.now()
                    encounter.save(update_fields=["symptoms", "current_state", "last_updated_at"])
                    _log_walk_in_event(
                        encounter,
                        "intake_refresh",
                        "Walk-in queue details were refreshed at the front desk.",
                        actor=request.user,
                    )
                    ensure_walk_in_registration_bill(encounter=encounter)
        except ValidationError as exc:
            async_response = _async_dashboard_response(
                request,
                ok=False,
                message=exc.messages[0] if getattr(exc, "messages", None) else "This patient cannot enter the active queue.",
                status=400,
                errors={"__all__": exc.messages if getattr(exc, "messages", None) else [str(exc)]},
            )
            if async_response is not None:
                return async_response
            messages.error(request, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
            return redirect("hospital:walk_in_hub")

        _notify_hospital_roles(
            hospital,
            [HospitalAccess.Role.NURSE],
            "Walk-in ready for triage",
            f"{patient} has been added to the walk-in queue at {hospital.name}.",
            exclude_user=request.user,
        )
        if created:
            _notify_hospital_admins(
                hospital,
                "New patient registered from walk-in",
                f"{patient} was created from the walk-in intake flow at {hospital.name}.",
                exclude_user=request.user,
            )
        async_response = _async_dashboard_response(request, ok=True, message=f"{patient} added to the walk-in queue.")
        if async_response is not None:
            return async_response
        return redirect("hospital:walk_in_hub")

    async_response = _async_dashboard_response(
        request,
        ok=False,
        message="Please complete the walk-in intake details.",
        status=400,
        errors=_dashboard_form_errors(form),
    )
    if async_response is not None:
        return async_response
    return redirect("hospital:walk_in_hub")


@login_required
@require_http_methods(["POST"])
def triage_walk_in(request, encounter_id):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    }:
        raise PermissionDenied("Nursing or emergency triage access is required.")

    filters = {"pk": encounter_id}
    if hospital:
        filters["hospital"] = hospital
    encounter = get_object_or_404(WalkInEncounter.objects.select_related("patient__user"), **filters)
    form = NurseTriageForm(request.POST)
    if form.is_valid():
        vitals_payload = {
            "temperature_c": form.cleaned_data.get("temperature_c"),
            "pulse_rate": form.cleaned_data.get("pulse_rate"),
            "respiratory_rate": form.cleaned_data.get("respiratory_rate"),
            "systolic_bp": form.cleaned_data.get("systolic_bp"),
            "diastolic_bp": form.cleaned_data.get("diastolic_bp"),
            "oxygen_saturation": form.cleaned_data.get("oxygen_saturation"),
        }
        severity = analyze_walk_in_severity(
            user=request.user,
            hospital=hospital,
            patient=encounter.patient,
            symptoms=form.cleaned_data["symptoms"],
            current_state=form.cleaned_data["current_state"],
            triage_notes=form.cleaned_data.get("triage_notes", ""),
            vitals=vitals_payload,
        )
        VitalSign.objects.create(
            patient=encounter.patient,
            hospital=hospital,
            recorded_by=request.user,
            notes=form.cleaned_data.get("triage_notes", ""),
            **vitals_payload,
        )
        encounter.symptoms = form.cleaned_data["symptoms"]
        encounter.current_state = form.cleaned_data["current_state"]
        encounter.triage_notes = "\n".join(
            [item for item in [form.cleaned_data.get("triage_notes", ""), severity.summary, severity.rationale] if item]
        )
        encounter.triaged_by = request.user
        encounter.triaged_at = timezone.now()
        encounter.severity_index = severity.severity_index
        encounter.severity_band = severity.severity_band
        encounter.is_critical = bool(form.cleaned_data.get("is_critical_override")) or severity.severity_band == WalkInEncounter.SeverityBand.CRITICAL
        encounter.status = WalkInEncounter.Status.WAITING_DOCTOR
        encounter.save(
            update_fields=[
                "symptoms",
                "current_state",
                "triage_notes",
                "triaged_by",
                "triaged_at",
                "severity_index",
                "severity_band",
                "is_critical",
                "status",
                "last_updated_at",
            ]
        )
        _log_walk_in_event(
            encounter,
            "triage",
            f"Triage completed with severity index {severity.severity_index}/100 ({severity.severity_band}).",
            actor=request.user,
        )
        ensure_walk_in_triage_bill(encounter=encounter)
        _notify_hospital_roles(
            hospital,
            [HospitalAccess.Role.DOCTOR],
            "Walk-in triage completed",
            f"{encounter.patient} is ready for doctor review with severity {severity.severity_band}.",
            exclude_user=request.user,
        )
        async_response = _async_dashboard_response(request, ok=True, message=f"Triage completed for {encounter.patient}.")
        if async_response is not None:
            return async_response
        return redirect("hospital:walk_in_hub")

    async_response = _async_dashboard_response(
        request,
        ok=False,
        message="Please review the triage details.",
        status=400,
        errors=_dashboard_form_errors(form),
    )
    if async_response is not None:
        return async_response
    return redirect("hospital:walk_in_hub")


@login_required
@require_http_methods(["POST"])
def set_walk_in_context(request, encounter_id):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.DOCTOR,
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
        HospitalAccess.Role.PHARMACIST,
        HospitalAccess.Role.EMERGENCY_OPERATOR,
    }:
        raise PermissionDenied("Workflow access is required.")
    filters = {"pk": encounter_id}
    if hospital:
        filters["hospital"] = hospital
    encounter = get_object_or_404(WalkInEncounter.objects.select_related("patient__user"), **filters)
    request.session["clinical_patient_id"] = encounter.patient_id
    request.session["clinical_walk_in_id"] = encounter.id
    request.session["clinical_appointment_id"] = ""
    if encounter.hospital_id:
        request.session["current_hospital_id"] = encounter.hospital_id
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "message": f"Patient context set for {encounter.patient}.",
                "patient": str(encounter.patient),
                "patient_id": encounter.patient_id,
                "encounter_id": encounter.id,
            }
        )
    messages.success(request, f"Patient context set for {encounter.patient}.")
    return redirect("hospital:walk_in_hub")


@login_required
@doctor_required
@require_http_methods(["POST"])
def consult_walk_in(request, encounter_id):
    _, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.DOCTOR,
    }:
        raise PermissionDenied("Doctor access is required.")

    doctor = get_object_or_404(Doctor, user=request.user)
    filters = {"pk": encounter_id}
    if hospital:
        filters["hospital"] = hospital
    encounter = get_object_or_404(WalkInEncounter.objects.select_related("patient__user"), **filters)
    form = WalkInConsultationForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            encounter.attending_doctor = doctor
            if not encounter.consultation_started_at:
                encounter.consultation_started_at = timezone.now()
            encounter.status = WalkInEncounter.Status.IN_CONSULTATION
            encounter.save(update_fields=["attending_doctor", "consultation_started_at", "status", "last_updated_at"])

            record = MedicalRecord.objects.create(
                patient=encounter.patient,
                hospital=hospital,
                doctor=doctor,
                diagnosis=form.cleaned_data["diagnosis"],
                prescription=form.cleaned_data.get("prescription", ""),
                notes=form.cleaned_data.get("notes", ""),
            )
            encounter.medical_record = record
            encounter.doctor_notes = form.cleaned_data.get("notes", "")
            encounter.consultation_completed_at = timezone.now()

            next_status = WalkInEncounter.Status.COMPLETED
            if form.cleaned_data.get("lab_test_name"):
                LabTestRequest.objects.create(
                    patient=encounter.patient,
                    hospital=hospital,
                    walk_in_encounter=encounter,
                    requested_by=doctor,
                    test_name=form.cleaned_data["lab_test_name"],
                    priority=form.cleaned_data.get("lab_priority") or "routine",
                    notes=form.cleaned_data.get("lab_notes", ""),
                    status=LabTestRequest.Status.REQUESTED,
                )
                next_status = WalkInEncounter.Status.AWAITING_LAB
                _notify_hospital_roles(
                    hospital,
                    [HospitalAccess.Role.LAB_TECHNICIAN],
                    "New walk-in lab request",
                    f"{encounter.patient} has a new lab request: {form.cleaned_data['lab_test_name']}.",
                    exclude_user=request.user,
                )

            pharmacy_text = (form.cleaned_data.get("pharmacy_instructions") or form.cleaned_data.get("prescription") or "").strip()
            if pharmacy_text:
                PharmacyTask.objects.create(
                    patient=encounter.patient,
                    hospital=hospital,
                    walk_in_encounter=encounter,
                    medical_record=record,
                    requested_by=request.user,
                    instructions=pharmacy_text,
                )
                if next_status == WalkInEncounter.Status.COMPLETED:
                    next_status = WalkInEncounter.Status.AWAITING_PHARMACY
                _notify_hospital_roles(
                    hospital,
                    [HospitalAccess.Role.PHARMACIST],
                    "New pharmacy task",
                    f"{encounter.patient} has dispensing instructions waiting in {hospital.name}.",
                    exclude_user=request.user,
                )

            if form.cleaned_data.get("refer_for_admission"):
                next_status = WalkInEncounter.Status.ADMISSION_REVIEW
                _notify_hospital_roles(
                    hospital,
                    [HospitalAccess.Role.NURSE, HospitalAccess.Role.RECEPTIONIST, HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER],
                    "Admission review required",
                    f"{encounter.patient} has been referred for admission after doctor review.",
                    exclude_user=request.user,
                )

            encounter.status = next_status
            encounter.save(
                update_fields=[
                    "medical_record",
                    "doctor_notes",
                    "consultation_completed_at",
                    "status",
                    "last_updated_at",
                ]
            )
            _log_walk_in_event(
                encounter,
                "consultation",
                "Doctor consultation recorded and downstream tasks were generated where required.",
                actor=request.user,
            )
            ensure_consultation_bill(
                patient=encounter.patient,
                hospital=hospital,
                doctor=doctor,
                walk_in_encounter=encounter,
                medical_record=record,
            )

        async_response = _async_dashboard_response(request, ok=True, message=f"Consultation saved for {encounter.patient}.")
        if async_response is not None:
            return async_response
        return redirect("hospital:walk_in_hub")

    async_response = _async_dashboard_response(
        request,
        ok=False,
        message="Please review the consultation details.",
        status=400,
        errors=_dashboard_form_errors(form),
    )
    if async_response is not None:
        return async_response
    return redirect("hospital:walk_in_hub")


@login_required
@require_http_methods(["POST"])
def record_lab_result(request, request_id):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role != HospitalAccess.Role.LAB_TECHNICIAN:
        raise PermissionDenied("Laboratory access is required.")
    filters = {"pk": request_id}
    if hospital:
        filters["hospital"] = hospital
    lab_request = get_object_or_404(LabTestRequest.objects.select_related("patient__user", "walk_in_encounter"), **filters)
    form = WalkInLabResultForm(request.POST, request.FILES)
    if form.is_valid():
        staff_profile = getattr(request.user, "staff_profile", None)
        result = form.save(commit=False)
        result.request = lab_request
        result.recorded_by = staff_profile
        result.save()
        ensure_lab_bill(request=lab_request)
        lab_request.status = LabTestRequest.Status.COMPLETED
        lab_request.save(update_fields=["status"])
        if lab_request.walk_in_encounter_id:
            encounter = lab_request.walk_in_encounter
            encounter.lab_summary = result.result_summary
            encounter.status = WalkInEncounter.Status.LAB_READY
            encounter.save(update_fields=["lab_summary", "status", "last_updated_at"])
            _log_walk_in_event(
                encounter,
                "lab_result",
                f"Lab result recorded for {lab_request.test_name}.",
                actor=request.user,
            )
            if encounter.attending_doctor_id:
                Notification.objects.create(
                    user=encounter.attending_doctor.user,
                    title="Walk-in lab result ready",
                    message=f"Lab results for {encounter.patient} are ready for doctor review.",
                )
        async_response = _async_dashboard_response(request, ok=True, message=f"Lab result recorded for {lab_request.patient}.")
        if async_response is not None:
            return async_response
        return redirect("hospital:walk_in_hub")

    async_response = _async_dashboard_response(
        request,
        ok=False,
        message="Please review the lab result details.",
        status=400,
        errors=_dashboard_form_errors(form),
    )
    if async_response is not None:
        return async_response
    return redirect("hospital:walk_in_hub")


@login_required
@require_http_methods(["POST"])
def update_pharmacy_task(request, task_id):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.PHARMACIST,
    }:
        raise PermissionDenied("Pharmacy access is required.")
    filters = {"pk": task_id}
    if hospital:
        filters["hospital"] = hospital
    task = get_object_or_404(PharmacyTask.objects.select_related("patient__user", "walk_in_encounter", "requested_by"), **filters)
    form = PharmacyTaskUpdateForm(request.POST, instance=task)
    if form.is_valid():
        task = form.save(commit=False)
        if task.status == PharmacyTask.Status.COMPLETED:
            task.completed_by = request.user
            task.completed_at = timezone.now()
        task.save()
        ensure_pharmacy_bill(task=task)
        if task.walk_in_encounter_id and task.status == PharmacyTask.Status.COMPLETED:
            encounter = task.walk_in_encounter
            remaining = encounter.pharmacy_tasks.exclude(status=PharmacyTask.Status.COMPLETED).exists()
            if not remaining and encounter.status == WalkInEncounter.Status.AWAITING_PHARMACY:
                encounter.status = WalkInEncounter.Status.COMPLETED
                encounter.completed_at = timezone.now()
                encounter.save(update_fields=["status", "completed_at", "last_updated_at"])
            _log_walk_in_event(
                encounter,
                "pharmacy",
                "Pharmacy handoff updated.",
                actor=request.user,
            )
            if encounter.attending_doctor_id:
                Notification.objects.create(
                    user=encounter.attending_doctor.user,
                    title="Pharmacy task updated",
                    message=f"Pharmacy task for {encounter.patient} is now {task.get_status_display().lower()}.",
                )
        async_response = _async_dashboard_response(request, ok=True, message=f"Pharmacy task updated for {task.patient}.")
        if async_response is not None:
            return async_response
        return redirect("hospital:walk_in_hub")
    async_response = _async_dashboard_response(
        request,
        ok=False,
        message="Please review the pharmacy task update.",
        status=400,
        errors=_dashboard_form_errors(form),
    )
    if async_response is not None:
        return async_response
    return redirect("hospital:walk_in_hub")


@login_required
def patient_registry(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or not _role_allows_clinical_access(active_access.role):
        raise PermissionDenied("Clinical access is required.")

    search = (request.GET.get("q") or "").strip()
    age_group = (request.GET.get("age_group") or "").strip()
    condition_query = (request.GET.get("condition") or "").strip()
    patients = _patient_scope_queryset(hospital)
    if search:
        patients = patients.filter(
            Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__username__icontains=search)
            | Q(patient_number__icontains=search)
            | Q(emergency_contact_name__icontains=search)
        )
    if condition_query:
        patients = patients.filter(
            Q(condition_records__condition_name__icontains=condition_query)
            | Q(condition_records__condition__name__icontains=condition_query)
        )
    if age_group:
        filtered_ids = [patient.id for patient in patients if patient.age_group == age_group]
        patients = patients.filter(id__in=filtered_ids)

    patients = patients.distinct().order_by("user__last_name", "user__first_name")
    paginator = Paginator(patients, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    condition_metrics = _patient_condition_analytics(hospital)
    summary = {
        "patients": patients.count(),
        "active_conditions": condition_metrics["active_conditions_total"],
        "upcoming_surgeries": _surgery_overview(hospital)["scheduled_count"],
        "admissions": _scope_queryset(Admission.objects.filter(status=Admission.Status.ACTIVE), hospital).count(),
    }
    cards = []
    for patient in page_obj.object_list:
        history = _patient_history_queryset(patient, hospital)
        active_conditions = [
            condition.condition_name or (condition.condition.name if condition.condition_id else "Unspecified condition")
            for condition in history["conditions"].filter(is_active=True)[:3]
        ]
        cards.append(
            {
                "patient": patient,
                "conditions": active_conditions,
                "appointments": history["appointments"].count(),
                "surgeries": history["surgeries"].count(),
                "age_group": patient.age_group,
                "hospital_name": patient.hospital.name if patient.hospital else "Shared record",
            }
        )
    return render(
        request,
        "hospital/patient_registry.html",
        {
            "current_hospital": hospital,
            "summary": summary,
            "patients": cards,
            "page_obj": page_obj,
            "is_paginated": page_obj.paginator.num_pages > 1,
            "search": search,
            "age_group": age_group,
            "condition_query": condition_query,
            "age_groups": ["0-17", "18-34", "35-49", "50-64", "65+", "Unknown"],
        },
    )


@login_required
def patient_detail(request, patient_id):
    accesses, active_access, hospital = _active_accesses(request)
    user = request.user
    if user.role == User.Role.PATIENT:
        patient = get_object_or_404(Patient, pk=patient_id, user=user)
    else:
        if not active_access or not _role_allows_clinical_access(active_access.role):
            raise PermissionDenied("Clinical access is required.")
        patient = get_object_or_404(Patient.objects.select_related("user", "hospital"), pk=patient_id)

    history = _patient_history_queryset(patient, hospital=None)
    consolidated_records = _patient_record_feed(history, patient)
    grouped = defaultdict(lambda: {
        "appointments": 0,
        "records": 0,
        "conditions": 0,
        "surgeries": 0,
        "admissions": 0,
        "labs": 0,
    })

    for item in history["appointments"]:
        key = item.hospital.name if item.hospital else (patient.hospital.name if patient.hospital else "Shared")
        grouped[key]["appointments"] += 1
    for item in history["records"]:
        key = item.hospital.name if item.hospital else (patient.hospital.name if patient.hospital else "Shared")
        grouped[key]["records"] += 1
    for item in history["conditions"]:
        key = item.hospital.name if item.hospital else (patient.hospital.name if patient.hospital else "Shared")
        grouped[key]["conditions"] += 1
    for item in history["surgeries"]:
        key = item.hospital.name if item.hospital else (patient.hospital.name if patient.hospital else "Shared")
        grouped[key]["surgeries"] += 1
    for item in history["admissions"]:
        key = item.hospital.name if item.hospital else (patient.hospital.name if patient.hospital else "Shared")
        grouped[key]["admissions"] += 1
    for item in history["labs"]:
        key = item.hospital.name if item.hospital else (patient.hospital.name if patient.hospital else "Shared")
        grouped[key]["labs"] += 1

    timeline = []
    for item in history["appointments"][:10]:
        timeline.append(
            {
                "title": "Appointment",
                "subtitle": f"{item.doctor} on {item.appointment_date} at {item.appointment_time}",
                "status": item.get_status_display(),
                "hospital": item.hospital.name if item.hospital else "Shared",
                "icon": "bi-calendar2-check",
            }
        )
    for item in history["conditions"][:10]:
        timeline.append(
            {
                "title": item.condition_name or (item.condition.name if item.condition_id else "Condition recorded"),
                "subtitle": item.notes or "Condition monitoring entry",
                "status": item.get_severity_display(),
                "hospital": item.hospital.name if item.hospital else "Shared",
                "icon": "bi-clipboard2-pulse",
            }
        )
    for item in history["surgeries"][:10]:
        timeline.append(
            {
                "title": item.procedure_name,
                "subtitle": f"{item.scheduled_start:%Y-%m-%d %H:%M} with {item.surgeon}",
                "status": item.get_status_display(),
                "hospital": item.hospital.name if item.hospital else "Shared",
                "icon": "bi-scissors",
            }
        )
    for item in history["records"][:10]:
        timeline.append(
            {
                "title": "Clinical record",
                "subtitle": item.diagnosis,
                "status": item.created_at.strftime("%Y-%m-%d"),
                "hospital": item.hospital.name if item.hospital else "Shared",
                "icon": "bi-file-medical",
            }
        )
    timeline = timeline[:12]
    active_admission = history["admissions"].filter(status=Admission.Status.ACTIVE).select_related("ward", "bed", "hospital").first()
    grant_hospital = active_access.hospital if active_access else hospital
    can_manage_patient_access = bool(active_access and active_access.role in OWNER_ROLES)
    can_mark_deceased = bool(active_access and active_access.role in OWNER_ROLES | {HospitalAccess.Role.DOCTOR})
    assistant_access_form = AssistantAccessGrantForm(hospital=grant_hospital) if can_manage_patient_access else None
    death_record_form = PatientDeathRecordForm(instance=patient) if can_mark_deceased and not patient.is_deceased else None
    assistant_access_grants = (
        AssistantAccessGrant.objects.select_related("requester", "approved_by")
        .filter(patient_user=patient.user, hospital_id=getattr(grant_hospital, "id", None))
        .order_by("-created_at")[:6]
        if can_manage_patient_access and grant_hospital
        else []
    )

    return render(
        request,
        "hospital/patient_detail.html",
        {
            "patient": patient,
            "current_hospital": hospital,
            "history": history,
            "consolidated_records": consolidated_records,
            "timeline": timeline,
            "facility_breakdown": [
                {"label": facility, **values}
                for facility, values in grouped.items()
            ],
            "overview_cards": [
                {"label": "Appointments", "value": history["appointments"].count(), "icon": "bi-calendar2-check"},
                {"label": "Records", "value": history["records"].count(), "icon": "bi-journal-medical"},
                {"label": "Conditions", "value": history["conditions"].count(), "icon": "bi-clipboard2-pulse"},
                {"label": "Surgeries", "value": history["surgeries"].count(), "icon": "bi-scissors"},
                {"label": "Labs", "value": history["labs"].count(), "icon": "bi-eyedropper"},
                {"label": "Admissions", "value": history["admissions"].count(), "icon": "bi-hospital"},
            ],
            "active_admission": active_admission,
            "assistant_access_form": assistant_access_form,
            "assistant_access_grants": assistant_access_grants,
            "can_manage_patient_access": can_manage_patient_access,
            "can_mark_deceased": can_mark_deceased,
            "death_record_form": death_record_form,
        },
    )


@login_required
@require_http_methods(["POST"])
def mark_patient_deceased(request, patient_id):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or active_access.role not in OWNER_ROLES | {HospitalAccess.Role.DOCTOR}:
        raise PermissionDenied("Only clinical leaders can record a patient death.")
    patient = get_object_or_404(Patient.objects.select_related("user", "hospital"), pk=patient_id)
    form = PatientDeathRecordForm(request.POST, instance=patient)
    if not form.is_valid():
        messages.error(request, "Please review the death record details.")
        return redirect("hospital:patient_detail", patient_id=patient.id)
    if patient.is_deceased:
        messages.info(request, "This patient has already been marked deceased.")
        return redirect("hospital:patient_detail", patient_id=patient.id)
    _mark_patient_deceased(
        patient,
        actor=request.user,
        hospital=hospital,
        deceased_at=form.cleaned_data.get("deceased_at"),
        notes=form.cleaned_data.get("deceased_notes", ""),
    )
    messages.success(request, f"{patient} has been recorded as deceased across BayAfya.")
    return redirect("hospital:patient_detail", patient_id=patient.id)


@login_required
def records_hub(request):
    accesses, active_access, hospital = _active_accesses(request)
    user = request.user
    patient_filter_id = (request.GET.get("patient") or "").strip()
    search = (request.GET.get("q") or "").strip()
    record_type = (request.GET.get("type") or "all").strip().lower()

    if user.role == User.Role.PATIENT:
        patient = get_object_or_404(Patient.objects.select_related("user", "hospital"), user=user)
        patient_queryset = Patient.objects.filter(pk=patient.pk).select_related("user", "hospital")
    else:
        if not active_access or not _role_allows_record_access(active_access.role):
            raise PermissionDenied("Record access is required.")
        patient_queryset = _patient_scope_queryset(hospital)
        patient = patient_queryset.filter(pk=patient_filter_id).first() if patient_filter_id else None

    medical_records = MedicalRecord.objects.select_related("patient__user", "doctor__user", "hospital")
    lab_requests = LabTestRequest.objects.select_related("patient__user", "requested_by__user", "hospital")
    lab_results = LabTestResult.objects.select_related("request__patient__user", "request__requested_by__user", "request__hospital")
    admissions = Admission.objects.select_related("patient__user", "ward", "bed", "attending_doctor__user", "hospital")
    appointments = Appointment.objects.select_related("patient__user", "doctor__user", "hospital")
    surgeries = SurgicalCase.objects.select_related("patient__user", "surgeon__user", "hospital")

    if hospital and user.role != User.Role.PATIENT:
        medical_records = _scope_queryset(medical_records, hospital)
        lab_requests = _scope_queryset(lab_requests, hospital)
        admissions = _scope_queryset(admissions, hospital)
        appointments = _scope_queryset(appointments, hospital)
        surgeries = _scope_queryset(surgeries, hospital)
        lab_results = lab_results.filter(request__hospital=hospital)

    if patient:
        medical_records = medical_records.filter(patient=patient)
        lab_requests = lab_requests.filter(patient=patient)
        lab_results = lab_results.filter(request__patient=patient)
        admissions = admissions.filter(patient=patient)
        appointments = appointments.filter(patient=patient)
        surgeries = surgeries.filter(patient=patient)

    if search:
        medical_records = medical_records.filter(
            Q(patient__user__first_name__icontains=search)
            | Q(patient__user__last_name__icontains=search)
            | Q(diagnosis__icontains=search)
            | Q(assessment__icontains=search)
            | Q(notes__icontains=search)
        )
        lab_requests = lab_requests.filter(
            Q(patient__user__first_name__icontains=search)
            | Q(patient__user__last_name__icontains=search)
            | Q(test_name__icontains=search)
            | Q(notes__icontains=search)
        )
        lab_results = lab_results.filter(
            Q(request__patient__user__first_name__icontains=search)
            | Q(request__patient__user__last_name__icontains=search)
            | Q(request__test_name__icontains=search)
            | Q(result_summary__icontains=search)
        )
        admissions = admissions.filter(
            Q(patient__user__first_name__icontains=search)
            | Q(patient__user__last_name__icontains=search)
            | Q(reason__icontains=search)
            | Q(admission_notes__icontains=search)
        )
        appointments = appointments.filter(
            Q(patient__user__first_name__icontains=search)
            | Q(patient__user__last_name__icontains=search)
            | Q(reason__icontains=search)
            | Q(doctor__user__first_name__icontains=search)
            | Q(doctor__user__last_name__icontains=search)
        )
        surgeries = surgeries.filter(
            Q(patient__user__first_name__icontains=search)
            | Q(patient__user__last_name__icontains=search)
            | Q(procedure_name__icontains=search)
            | Q(notes__icontains=search)
            | Q(post_op_notes__icontains=search)
        )

    cards = []
    if record_type in {"all", "medical"}:
        for item in medical_records.order_by("-created_at")[:24]:
            cards.append(
                {
                    "kind": "Medical record",
                    "title": item.diagnosis or "Clinical record",
                    "subtitle": f"{item.patient} · {item.created_at:%Y-%m-%d %H:%M}",
                    "detail": item.assessment or item.notes or item.plan or item.prescription or "Detailed record available.",
                    "status": item.doctor or "Care team",
                    "hospital": item.hospital.name if item.hospital else "Shared",
                    "url": f"/hospital/records/{item.id}/",
                    "timestamp": _normalize_record_timestamp(item.created_at),
                }
            )
    if record_type in {"all", "lab"}:
        for item in lab_results.order_by("-completed_at")[:24]:
            cards.append(
                {
                    "kind": "Lab result",
                    "title": item.request.test_name,
                    "subtitle": f"{item.request.patient} · {item.completed_at:%Y-%m-%d %H:%M}",
                    "detail": item.result_summary or "Result available for review.",
                    "status": item.request.get_status_display(),
                    "hospital": item.request.hospital.name if item.request.hospital else "Shared",
                    "url": "",
                    "timestamp": _normalize_record_timestamp(item.completed_at),
                }
            )
        for item in lab_requests.order_by("-requested_at")[:24]:
            cards.append(
                {
                    "kind": "Lab request",
                    "title": item.test_name,
                    "subtitle": f"{item.patient} · {item.requested_at:%Y-%m-%d %H:%M}",
                    "detail": item.notes or "Laboratory request on file.",
                    "status": item.get_status_display(),
                    "hospital": item.hospital.name if item.hospital else "Shared",
                    "url": "",
                    "timestamp": _normalize_record_timestamp(item.requested_at),
                }
            )
    if record_type in {"all", "admission"}:
        for item in admissions.order_by("-admitted_at")[:24]:
            cards.append(
                {
                    "kind": "Admission",
                    "title": str(item.patient),
                    "subtitle": f"{item.ward.name if item.ward else 'Ward pending'} · Bed {item.bed.bed_number if item.bed else 'Pending'}",
                    "detail": item.admission_reason or item.admission_notes or "Admission episode on file.",
                    "status": item.get_status_display(),
                    "hospital": item.hospital.name if item.hospital else "Shared",
                    "url": "",
                    "timestamp": _normalize_record_timestamp(item.admitted_at),
                }
            )
    if record_type in {"all", "appointment"}:
        for item in appointments.order_by("-appointment_date", "-appointment_time")[:24]:
            cards.append(
                {
                    "kind": "Appointment",
                    "title": str(item.patient),
                    "subtitle": f"{item.doctor} · {item.appointment_date} {item.appointment_time}",
                    "detail": item.reason or "Consultation appointment.",
                    "status": item.get_status_display(),
                    "hospital": item.hospital.name if item.hospital else "Shared",
                    "url": "",
                    "timestamp": _normalize_record_timestamp(datetime.combine(item.appointment_date, item.appointment_time or time.min)),
                }
            )
    if record_type in {"all", "surgery"}:
        for item in surgeries.order_by("-scheduled_start")[:24]:
            cards.append(
                {
                    "kind": "Surgery",
                    "title": item.procedure_name,
                    "subtitle": f"{item.patient} · {item.scheduled_start:%Y-%m-%d %H:%M}",
                    "detail": item.notes or item.post_op_notes or item.anesthesia_type or "Surgical episode on file.",
                    "status": item.get_status_display(),
                    "hospital": item.hospital.name if item.hospital else "Shared",
                    "url": "",
                    "timestamp": _normalize_record_timestamp(item.scheduled_start),
                }
            )

    cards.sort(key=lambda item: item["timestamp"], reverse=True)

    return render(
        request,
        "hospital/records_hub.html",
        {
            "current_hospital": hospital,
            "selected_patient": patient,
            "patients": patient_queryset.order_by("user__last_name", "user__first_name")[:100],
            "record_cards": cards[:80],
            "record_type": record_type,
            "search": search,
            "summary": {
                "medical": medical_records.count(),
                "lab": lab_requests.count() + lab_results.count(),
                "admissions": admissions.count(),
                "appointments": appointments.count(),
                "surgeries": surgeries.count(),
            },
        },
    )


@login_required
def medical_record_detail(request, record_id):
    accesses, active_access, hospital = _active_accesses(request)
    user = request.user
    record = get_object_or_404(MedicalRecord.objects.select_related("patient__user", "doctor__user", "hospital"), pk=record_id)
    if user.role == User.Role.PATIENT:
        if record.patient.user_id != user.id:
            raise PermissionDenied("You can only view your own medical records.")
    elif not active_access or not _role_allows_record_access(active_access.role):
        raise PermissionDenied("Record access is required.")

    sibling_records = MedicalRecord.objects.filter(patient=record.patient).exclude(pk=record.pk).select_related("doctor__user", "hospital").order_by("-created_at")[:8]
    history = _patient_history_queryset(record.patient, hospital=None)
    return render(
        request,
        "hospital/medical_record_detail.html",
        {
            "current_hospital": hospital,
            "record": record,
            "patient": record.patient,
            "sibling_records": sibling_records,
            "history": history,
        },
    )


@login_required
def clinical_insights(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or not _role_allows_clinical_access(active_access.role):
        raise PermissionDenied("Clinical access is required.")

    current_patient = _current_patient_from_session(request, hospital)
    analytics = _patient_condition_analytics(hospital)
    report_period, report_start, report_end = _reporting_window(request)
    report_data = _condition_reporting(hospital, report_start, report_end)
    surgery = _surgery_overview(hospital)
    patients = _patient_scope_queryset(hospital)
    admissions = _scope_queryset(Admission.objects.filter(status=Admission.Status.ACTIVE), hospital)
    return render(
        request,
        "hospital/clinical_insights.html",
        {
            "current_hospital": hospital,
            "current_patient": current_patient,
            "analytics": analytics,
            "surgery": surgery,
            "patients": patients[:12],
            "condition_form": PatientConditionForm(hospital=hospital, current_patient=current_patient),
            "reporting": {
                "period": report_period,
                "start": report_start,
                "end": report_end,
                "data": report_data,
            },
            "summary": {
                "patients": patients.count(),
                "active_conditions": analytics["active_conditions_total"],
                "active_admissions": admissions.count(),
                "scheduled_surgeries": surgery["scheduled_count"],
            },
        },
    )


@login_required
def surgery_dashboard(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or not _role_allows_clinical_access(active_access.role):
        raise PermissionDenied("Clinical access is required.")
    _sweep_overdue_appointments_and_surgeries(hospital)

    current_patient = _current_patient_from_session(request, hospital)
    surgery = _surgery_overview(hospital)
    all_cases = SurgicalCase.objects.select_related("patient__user", "surgeon__user", "operating_room", "hospital")
    if hospital:
        all_cases = all_cases.filter(hospital=hospital)
    case_groups = {
        "pre_op": all_cases.filter(status=SurgicalCase.Status.PRE_OP).order_by("-scheduled_start", "-id"),
        "in_surgery": all_cases.filter(status=SurgicalCase.Status.IN_SURGERY).order_by("-scheduled_start", "-id"),
        "recovery": all_cases.filter(status=SurgicalCase.Status.RECOVERY).order_by("-scheduled_start", "-id"),
        "completed": all_cases.filter(status__in=[SurgicalCase.Status.COMPLETED, SurgicalCase.Status.PAST]).order_by("-scheduled_start", "-id"),
    }
    if request.method == "POST":
        if active_access.role not in {HospitalAccess.Role.OWNER, HospitalAccess.Role.ADMIN, HospitalAccess.Role.DOCTOR, HospitalAccess.Role.RECEPTIONIST}:
            raise PermissionDenied("You cannot schedule surgical operations.")
        form = SurgicalCaseForm(request.POST, hospital=hospital, current_patient=current_patient)
        if form.is_valid():
            case = form.save(commit=False)
            if current_patient is not None:
                case.patient = current_patient
            case.hospital = hospital
            if not case.scheduled_end and case.estimated_duration_minutes and case.scheduled_start:
                case.scheduled_end = case.scheduled_start + timedelta(minutes=case.estimated_duration_minutes)
            case.save()
            messages.success(request, "Surgical operation scheduled successfully.")
            return redirect("hospital:surgery_dashboard")
    else:
        form = SurgicalCaseForm(hospital=hospital, current_patient=current_patient)

    return render(
        request,
        "hospital/surgery_dashboard.html",
        {
        "current_hospital": hospital,
        "current_patient": current_patient,
        "form": form,
        "surgery": surgery,
        "cases": surgery["upcoming_cases"],
        "case_groups": case_groups,
    },
    )


@login_required
@require_http_methods(["POST"])
def update_surgery_status(request, case_id, status):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or not _role_allows_clinical_access(active_access.role):
        raise PermissionDenied("Clinical access is required.")
    filters = {"pk": case_id}
    if hospital:
        filters["hospital"] = hospital
    case = get_object_or_404(SurgicalCase, **filters)
    if status not in SurgicalCase.Status.values:
        raise PermissionDenied("Invalid surgical status.")
    if active_access.role not in {HospitalAccess.Role.OWNER, HospitalAccess.Role.ADMIN, HospitalAccess.Role.DOCTOR} and status not in {SurgicalCase.Status.CANCELLED}:
        raise PermissionDenied("You cannot update this surgery state.")
    case.status = status
    case.save(update_fields=["status"])
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "message": "Surgery status updated.", "status": case.get_status_display()})
    messages.success(request, "Surgery status updated.")
    return redirect("hospital:surgery_dashboard")


def _log_admission_workflow_record(*, patient, hospital, doctor=None, diagnosis, notes="", plan=""):
    if patient is None:
        return None
    return MedicalRecord.objects.create(
        patient=patient,
        hospital=hospital,
        doctor=doctor,
        diagnosis=diagnosis,
        notes=notes,
        plan=plan,
    )


@login_required
@require_http_methods(["POST"])
def record_patient_condition(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or not _role_allows_clinical_access(active_access.role):
        raise PermissionDenied("Clinical access is required.")
    current_patient = _current_patient_from_session(request, hospital)
    form = PatientConditionForm(request.POST, hospital=hospital, current_patient=current_patient)
    if form.is_valid():
        condition_record = form.save(commit=False)
        if current_patient is not None:
            condition_record.patient = current_patient
        condition_record.hospital = hospital
        condition_record.recorded_by = getattr(request.user, "doctor", None) if hasattr(request.user, "doctor") else None
        condition_record.save()
        messages.success(request, "Patient condition recorded.")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "Patient condition recorded."})
    else:
        messages.error(request, "Please review the condition details.")
    return redirect("hospital:clinical_insights")


@login_required
def admission_dashboard(request):
    accesses, active_access, hospital = _active_accesses(request)
    if not active_access or not _role_allows_clinical_access(active_access.role):
        raise PermissionDenied("Clinical access is required.")
    _sweep_overdue_appointments_and_surgeries(hospital)

    current_patient = _current_patient_from_session(request, hospital)
    active_admissions = _scope_queryset(Admission.objects.filter(status=Admission.Status.ACTIVE), hospital).select_related(
        "patient__user", "attending_doctor__user", "ward", "bed"
    )
    admission_review_walk_ins = _walk_in_queryset(hospital).filter(
        status=WalkInEncounter.Status.ADMISSION_REVIEW
    ).order_by("-is_critical", "-severity_index", "arrived_at")[:8]
    transfers = _scope_queryset(
        BedTransfer.objects.select_related("admission__patient__user", "from_bed__ward", "to_bed__ward"),
        hospital,
    )[:6]
    recent_discharges = _scope_queryset(
        DischargeSummary.objects.select_related("admission__patient__user", "admission__hospital", "prepared_by__user"),
        hospital,
    )[:6]
    ward_status = _scope_queryset(Ward.objects.prefetch_related("beds"), hospital).order_by("name")
    form = AdmissionForm(hospital=hospital, current_patient=current_patient)
    transfer_form = BedTransferForm(hospital=hospital)
    discharge_form = DischargeSummaryForm(hospital=hospital)
    follow_up_form = FollowUpAppointmentForm(hospital=hospital, current_patient=current_patient)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "admit":
            form = AdmissionForm(request.POST, hospital=hospital, current_patient=current_patient)
            if form.is_valid():
                admission = form.save(commit=False)
                if current_patient is not None:
                    admission.patient = current_patient
                admission.hospital = hospital
                admission.full_clean()
                admission.save()
                ensure_admission_bill(admission=admission)
                admission.bed.is_occupied = True
                admission.bed.current_patient = admission.patient
                admission.bed.save(update_fields=["is_occupied", "current_patient"])
                walk_in_encounter = WalkInEncounter.objects.filter(
                    patient=admission.patient,
                    hospital=hospital,
                    status=WalkInEncounter.Status.ADMISSION_REVIEW,
                ).first()
                if walk_in_encounter:
                    walk_in_encounter.admission = admission
                    walk_in_encounter.status = WalkInEncounter.Status.ADMITTED
                    walk_in_encounter.save(update_fields=["admission", "status", "last_updated_at"])
                    _log_walk_in_event(
                        walk_in_encounter,
                        "admission",
                        "Patient moved from doctor review into admission workflow.",
                        actor=request.user,
                    )
                _log_admission_workflow_record(
                    patient=admission.patient,
                    hospital=hospital,
                    doctor=admission.attending_doctor,
                    diagnosis="Admission initiated",
                    notes=admission.admission_reason or "Patient admitted into inpatient care.",
                    plan=f"Assigned to {admission.ward.name} · Bed {admission.bed.bed_number}.",
                )
                message = "Patient admitted successfully."
                messages.success(request, message)
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"ok": True, "message": message})
                return redirect("hospital:admission_dashboard")
        elif action == "transfer":
            transfer_form = BedTransferForm(request.POST, hospital=hospital)
            if transfer_form.is_valid():
                transfer = transfer_form.save(commit=False)
                admission = transfer.admission
                transfer.from_bed = admission.bed
                previous_bed = admission.bed
                previous_bed.is_occupied = False
                previous_bed.current_patient = None
                previous_bed.save(update_fields=["is_occupied", "current_patient"])
                transfer.to_bed.is_occupied = True
                transfer.to_bed.current_patient = admission.patient
                transfer.to_bed.save(update_fields=["is_occupied", "current_patient"])
                transfer.save()
                admission.bed = transfer.to_bed
                admission.ward = transfer.to_bed.ward
                admission.status = Admission.Status.ACTIVE
                admission.save(update_fields=["bed", "ward", "status"])
                ensure_bed_transfer_bill(admission=admission)
                _log_admission_workflow_record(
                    patient=admission.patient,
                    hospital=hospital,
                    doctor=admission.attending_doctor,
                    diagnosis="Bed transfer completed",
                    notes=transfer.reason or "Patient transferred to a new bed.",
                    plan=f"Moved from {previous_bed.ward.name} · Bed {previous_bed.bed_number} to {transfer.to_bed.ward.name} · Bed {transfer.to_bed.bed_number}.",
                )
                message = "Bed transfer completed."
                messages.success(request, message)
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"ok": True, "message": message})
                return redirect("hospital:admission_dashboard")
        elif action == "discharge":
            if active_access.role not in {HospitalAccess.Role.OWNER, HospitalAccess.Role.ADMIN, HospitalAccess.Role.DOCTOR}:
                raise PermissionDenied("Only senior clinical staff can discharge a patient.")
            discharge_form = DischargeSummaryForm(request.POST, hospital=hospital)
            if discharge_form.is_valid():
                summary = discharge_form.save(commit=False)
                admission = summary.admission
                summary.prepared_by = get_object_or_404(Doctor, user=request.user)
                summary.save()
                admission.status = Admission.Status.DISCHARGED
                admission.discharged_at = timezone.now()
                admission.save(update_fields=["status", "discharged_at"])
                ensure_discharge_bill(admission=admission)
                admission.bed.is_occupied = False
                admission.bed.current_patient = None
                admission.bed.save(update_fields=["is_occupied", "current_patient"])
                _log_admission_workflow_record(
                    patient=admission.patient,
                    hospital=hospital,
                    doctor=summary.prepared_by,
                    diagnosis="Discharge completed",
                    notes=summary.discharge_notes or "Patient discharged from inpatient care.",
                    plan=summary.follow_up_instructions or "Discharge instructions recorded.",
                )
                message = "Discharge summary saved."
                messages.success(request, message)
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"ok": True, "message": message})
                return redirect("hospital:admission_dashboard")
        elif action == "follow_up":
            follow_up_form = FollowUpAppointmentForm(request.POST, hospital=hospital, current_patient=current_patient)
            if follow_up_form.is_valid():
                follow_up = follow_up_form.save(commit=False)
                if current_patient is not None:
                    follow_up.patient = current_patient
                follow_up.hospital = hospital
                if not follow_up.reason:
                    follow_up.reason = "Post-discharge follow-up"
                follow_up.save()
                _log_admission_workflow_record(
                    patient=follow_up.patient,
                    hospital=hospital,
                    doctor=follow_up.doctor,
                    diagnosis="Follow-up scheduled",
                    notes=follow_up.reason or "Post-discharge follow-up scheduled.",
                    plan=f"Appointment booked for {follow_up.appointment_date} at {follow_up.appointment_time}.",
                )
                message = "Follow-up appointment scheduled."
                messages.success(request, message)
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"ok": True, "message": message})
                return redirect("hospital:admission_dashboard")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            context = {
                "current_hospital": hospital,
                "current_patient": current_patient,
                "admission_form": form,
                "transfer_form": transfer_form,
                "discharge_form": discharge_form,
                "follow_up_form": follow_up_form,
                "active_admissions": active_admissions,
                "admission_review_walk_ins": admission_review_walk_ins,
                "transfers": transfers,
                "recent_discharges": recent_discharges,
                "ward_status": ward_status,
                "beds_available": _scope_queryset(Bed.objects.filter(is_occupied=False), hospital).count(),
                "wards": _scope_queryset(Ward.objects.all(), hospital).count(),
                "walk_in_billing_rates": {
                    "admission": STANDARD_RATES["admission"],
                    "bed_transfer": STANDARD_RATES["bed_transfer"],
                    "discharge": STANDARD_RATES["discharge"],
                },
            }
            html = render_to_string("hospital/admission_dashboard.html", context, request=request)
            return JsonResponse(
                {"ok": False, "message": "Please review the admission workflow details.", "html": html},
                status=400,
            )
    context = {
        "current_hospital": hospital,
        "current_patient": current_patient,
        "admission_form": form,
        "transfer_form": transfer_form,
        "discharge_form": discharge_form,
        "follow_up_form": follow_up_form,
        "active_admissions": active_admissions,
        "admission_review_walk_ins": admission_review_walk_ins,
        "transfers": transfers,
        "recent_discharges": recent_discharges,
        "ward_status": ward_status,
        "beds_available": _scope_queryset(Bed.objects.filter(is_occupied=False), hospital).count(),
        "wards": _scope_queryset(Ward.objects.all(), hospital).count(),
        "walk_in_billing_rates": {
            "admission": STANDARD_RATES["admission"],
            "bed_transfer": STANDARD_RATES["bed_transfer"],
            "discharge": STANDARD_RATES["discharge"],
        },
    }
    return render(request, "hospital/admission_dashboard.html", context)


@login_required
@require_http_methods(["POST"])
def set_clinical_context(request, appointment_id):
    _, current_access, _ = _active_accesses(request)
    if not current_access or current_access.role == HospitalAccess.Role.PATIENT:
        raise PermissionDenied("A staff hospital context is required to open a chart.")
    hospital = current_access.hospital
    filters = {"pk": appointment_id}
    if hospital:
        filters["hospital"] = hospital
    appointment = get_object_or_404(Appointment, **filters)
    request.session["clinical_patient_id"] = appointment.patient_id
    request.session["clinical_appointment_id"] = appointment.id
    request.session["clinical_walk_in_id"] = ""
    if appointment.hospital_id:
        request.session["current_hospital_id"] = appointment.hospital_id
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "message": f"Patient context set for {appointment.patient}.",
                "patient": str(appointment.patient),
                "patient_id": appointment.patient_id,
                "appointment_id": appointment.id,
            }
        )
    messages.success(request, f"Patient context set for {appointment.patient}.")
    return redirect("hospital:dashboard")
