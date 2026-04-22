import json
from datetime import datetime, timedelta

from django import forms
from django.db.models import Q
from django.utils import timezone

from core.models import User

from .models import (
    Admission,
    Allergy,
    AdvanceDirective,
    AppointmentReminder,
    Appointment,
    Bed,
    BedTransfer,
    CarePlan,
    CaregiverAccess,
    ChronicCondition,
    ConditionCatalog,
    ConsentForm,
    Doctor,
    DoctorTask,
    Document,
    DocumentCategory,
    DischargeSummary,
    Equipment,
    Hospital,
    HospitalAccess,
    HospitalInvitation,
    Immunization,
    InternalReferral,
    LabTestRequest,
    LabTestResult,
    LabPanel,
    LabQualityControlLog,
    MedicalRecord,
    MedicalImage,
    MedicationAdministrationRecord,
    OperatingRoom,
    Patient,
    PatientCondition,
    PatientFeedback,
    FamilyMedicalHistory,
    PharmacyTask,
    Room,
    ShiftAssignment,
    ShiftHandover,
    StaffProfile,
    SupplyRequest,
    SurgicalCase,
    SurgicalHistory,
    VitalSign,
    WalkInEncounter,
    Ward,
    EmergencyIncident,
)


class AppointmentForm(forms.ModelForm):
    appointment_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    appointment_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"})
    )

    class Meta:
        model = Appointment
        fields = ["doctor", "appointment_date", "appointment_time", "reason"]
        widgets = {
            "doctor": forms.Select(attrs={"class": "form-select", "data-autocomplete": "doctor"}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital is not None:
            self.fields["doctor"].queryset = Doctor.objects.filter(hospital=hospital).select_related("user")
        self.fields["doctor"].label_from_instance = (
            lambda doctor: f"{doctor} • {doctor.hospital.name if doctor.hospital else 'BayAfya'}"
        )
        self._hospital = hospital

    def clean(self):
        cleaned_data = super().clean()
        appointment_date = cleaned_data.get("appointment_date")
        doctor = cleaned_data.get("doctor")
        appointment_time = cleaned_data.get("appointment_time")
        if appointment_date and appointment_date < timezone.localdate():
            raise forms.ValidationError("Appointments cannot be booked in the past.")
        if doctor and appointment_date and appointment_time:
            weekday = appointment_date.strftime("%A").lower()
            available_days = {day.strip().lower() for day in doctor.available_days.split(",") if day.strip()}
            if available_days and weekday not in available_days:
                raise forms.ValidationError("The selected doctor is not available on that day.")
            if doctor.start_time and appointment_time < doctor.start_time:
                raise forms.ValidationError("The selected time is earlier than the doctor's start time.")
            if doctor.end_time and appointment_time > doctor.end_time:
                raise forms.ValidationError("The selected time is later than the doctor's end time.")
            conflicting = Appointment.objects.filter(
                doctor=doctor,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
            ).exclude(status=Appointment.Status.CANCELLED)
            if self.instance.pk:
                conflicting = conflicting.exclude(pk=self.instance.pk)
            if self._hospital is not None:
                conflicting = conflicting.filter(hospital=self._hospital)
            if conflicting.exists():
                raise forms.ValidationError("This doctor already has an appointment at the selected date and time.")
        return cleaned_data


class FollowUpAppointmentForm(forms.ModelForm):
    appointment_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    appointment_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"})
    )

    class Meta:
        model = Appointment
        fields = ["patient", "doctor", "appointment_date", "appointment_time", "reason"]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "doctor": forms.Select(attrs={"class": "form-select", "data-autocomplete": "doctor"}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Post-discharge review, wound check, medication review, or continuity follow-up"}),
        }

    def __init__(self, *args, hospital=None, current_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        patient_qs = Patient.objects.select_related("user")
        doctor_qs = Doctor.objects.select_related("user")
        if hospital is not None:
            patient_qs = patient_qs.filter(hospital=hospital)
            doctor_qs = doctor_qs.filter(hospital=hospital)
        self.fields["patient"].queryset = patient_qs.order_by("user__last_name", "user__first_name")
        self.fields["doctor"].queryset = doctor_qs.order_by("user__first_name", "user__last_name")
        self.fields["patient"].label_from_instance = lambda patient: f"{patient} • {patient.patient_number or patient.age_group}"
        self.fields["doctor"].label_from_instance = (
            lambda doctor: f"{doctor} • {doctor.hospital.name if doctor.hospital else 'BayAfya'}"
        )
        if current_patient is not None:
            self.fields["patient"].initial = current_patient.pk
        self._hospital = hospital

    def clean(self):
        cleaned_data = super().clean()
        appointment_date = cleaned_data.get("appointment_date")
        appointment_time = cleaned_data.get("appointment_time")
        doctor = cleaned_data.get("doctor")
        if appointment_date and appointment_date < timezone.localdate():
            raise forms.ValidationError("Follow-up appointments cannot be booked in the past.")
        if doctor and appointment_date and appointment_time:
            weekday = appointment_date.strftime("%A").lower()
            available_days = {day.strip().lower() for day in doctor.available_days.split(",") if day.strip()}
            if available_days and weekday not in available_days:
                raise forms.ValidationError("The selected doctor is not available on that day.")
            if doctor.start_time and appointment_time < doctor.start_time:
                raise forms.ValidationError("The selected time is earlier than the doctor's start time.")
            if doctor.end_time and appointment_time > doctor.end_time:
                raise forms.ValidationError("The selected time is later than the doctor's end time.")
            conflicting = Appointment.objects.filter(
                doctor=doctor,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
            ).exclude(status=Appointment.Status.CANCELLED)
            if self.instance.pk:
                conflicting = conflicting.exclude(pk=self.instance.pk)
            if self._hospital is not None:
                conflicting = conflicting.filter(hospital=self._hospital)
            if conflicting.exists():
                raise forms.ValidationError("This doctor already has an appointment at the selected date and time.")
        return cleaned_data


class MedicalRecordForm(forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = [
            "patient",
            "subjective",
            "objective",
            "assessment",
            "plan",
            "diagnosis",
            "prescription",
            "notes",
        ]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "subjective": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Symptoms, history, and patient-reported concerns"}),
            "objective": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Vitals, exam findings, and observable clinical data"}),
            "assessment": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Clinical impression and differential thinking"}),
            "plan": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Orders, follow-up, counseling, and next steps"}),
            "diagnosis": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "prescription": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, hospital=None, current_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital is not None:
            self.fields["patient"].queryset = Patient.objects.filter(hospital=hospital).select_related("user")
        if current_patient is not None:
            self.fields["patient"].initial = current_patient.pk


class WalkInIntakeForm(forms.Form):
    existing_patient = forms.ModelChoiceField(
        queryset=Patient.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
    )
    first_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    phone = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    gender = forms.ChoiceField(
        required=False,
        choices=Patient.Gender.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    symptoms = forms.CharField(widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))
    current_state = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Patient.objects.select_related("user")
        if hospital is not None:
            queryset = queryset.filter(hospital=hospital)
        self.fields["existing_patient"].queryset = queryset.order_by("user__last_name", "user__first_name")

    def clean(self):
        cleaned_data = super().clean()
        existing_patient = cleaned_data.get("existing_patient")
        if not existing_patient and not (cleaned_data.get("first_name") and cleaned_data.get("last_name")):
            raise forms.ValidationError("Select an existing patient or provide at least the first and last name.")
        dob = cleaned_data.get("date_of_birth")
        if dob and dob > timezone.localdate():
            raise forms.ValidationError("Date of birth cannot be in the future.")
        return cleaned_data


class NurseTriageForm(forms.Form):
    symptoms = forms.CharField(widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))
    current_state = forms.CharField(widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))
    triage_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    temperature_c = forms.DecimalField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.1"}))
    pulse_rate = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    respiratory_rate = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    systolic_bp = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    diastolic_bp = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    oxygen_saturation = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 100}))
    is_critical_override = forms.BooleanField(required=False)


class WalkInConsultationForm(forms.Form):
    diagnosis = forms.CharField(widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))
    prescription = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    lab_test_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    lab_priority = forms.ChoiceField(
        required=False,
        choices=[("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    lab_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    pharmacy_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    refer_for_admission = forms.BooleanField(required=False)


class DoctorTaskForm(forms.ModelForm):
    due_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )

    class Meta:
        model = DoctorTask
        fields = ["patient", "assigned_to", "title", "details", "priority", "due_at"]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "assigned_to": forms.Select(attrs={"class": "form-select", "data-autocomplete": "staff"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "details": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "priority": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, hospital=None, doctor_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        patient_qs = Patient.objects.select_related("user")
        staff_qs = User.objects.filter(role__in=[User.Role.DOCTOR, User.Role.NURSE, User.Role.LAB_TECHNICIAN, User.Role.PHARMACIST, User.Role.RECEPTIONIST, User.Role.COUNSELOR])
        if hospital is not None:
            patient_qs = patient_qs.filter(hospital=hospital)
            staff_qs = staff_qs.filter(hospital_accesses__hospital=hospital).distinct()
        self.fields["patient"].queryset = patient_qs
        self.fields["assigned_to"].queryset = staff_qs.order_by("first_name", "last_name", "username")
        if doctor_user is not None:
            self.fields["assigned_to"].initial = doctor_user.pk


class CarePlanForm(forms.ModelForm):
    next_review_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = CarePlan
        fields = ["patient", "title", "goals", "milestones", "timeline", "care_team", "status", "next_review_on"]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "goals": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "milestones": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "timeline": forms.TextInput(attrs={"class": "form-control"}),
            "care_team": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nurse, dietitian, physiotherapist"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, hospital=None, current_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Patient.objects.select_related("user")
        if hospital is not None:
            queryset = queryset.filter(hospital=hospital)
        self.fields["patient"].queryset = queryset
        if current_patient is not None:
            self.fields["patient"].initial = current_patient.pk


class InternalReferralForm(forms.ModelForm):
    due_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )

    class Meta:
        model = InternalReferral
        fields = ["patient", "target_hospital", "target_doctor", "specialty", "reason", "priority", "due_at"]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "target_hospital": forms.Select(attrs={"class": "form-select"}),
            "target_doctor": forms.Select(attrs={"class": "form-select", "data-autocomplete": "doctor"}),
            "specialty": forms.TextInput(attrs={"class": "form-control"}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "priority": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, hospital=None, current_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        patient_qs = Patient.objects.select_related("user")
        if hospital is not None:
            patient_qs = patient_qs.filter(hospital=hospital)
        self.fields["patient"].queryset = patient_qs
        self.fields["target_hospital"].queryset = Hospital.objects.none()
        self.fields["target_doctor"].queryset = Doctor.objects.select_related("user").order_by("user__first_name", "user__last_name")
        if current_patient is not None:
            self.fields["patient"].initial = current_patient.pk

    def set_hospital_queryset(self, hospitals):
        self.fields["target_hospital"].queryset = hospitals
        self.fields["target_doctor"].queryset = Doctor.objects.filter(hospital__in=hospitals).select_related("user").order_by("user__first_name", "user__last_name")


class WalkInLabResultForm(forms.ModelForm):
    class Meta:
        model = LabTestResult
        fields = ["result_summary", "attachment"]
        widgets = {
            "result_summary": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "attachment": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }


class PharmacyTaskUpdateForm(forms.ModelForm):
    class Meta:
        model = PharmacyTask
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
        }


class PatientConditionForm(forms.ModelForm):
    diagnosed_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    resolved_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = PatientCondition
        fields = [
            "patient",
            "condition",
            "condition_name",
            "severity",
            "diagnosed_at",
            "resolved_at",
            "notes",
        ]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "condition": forms.Select(attrs={"class": "form-select"}),
            "condition_name": forms.TextInput(attrs={"class": "form-control"}),
            "severity": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, hospital=None, current_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital is not None:
            self.fields["patient"].queryset = Patient.objects.filter(hospital=hospital).select_related("user")
        self.fields["condition"].queryset = ConditionCatalog.objects.filter(is_active=True)
        if current_patient is not None:
            self.fields["patient"].initial = current_patient.pk


class SurgicalCaseForm(forms.ModelForm):
    scheduled_start = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"})
    )
    scheduled_end = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )

    class Meta:
        model = SurgicalCase
        fields = [
            "patient",
            "surgeon",
            "operating_room",
            "procedure_name",
            "procedure_code",
            "priority",
            "scheduled_start",
            "scheduled_end",
            "estimated_duration_minutes",
            "anesthesia_type",
            "pre_op_assessment",
            "notes",
        ]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "surgeon": forms.Select(attrs={"class": "form-select", "data-autocomplete": "doctor"}),
            "operating_room": forms.Select(attrs={"class": "form-select"}),
            "procedure_name": forms.TextInput(attrs={"class": "form-control"}),
            "procedure_code": forms.TextInput(attrs={"class": "form-control"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "estimated_duration_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 15}),
            "anesthesia_type": forms.TextInput(attrs={"class": "form-control"}),
            "pre_op_assessment": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, hospital=None, current_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital is not None:
            self.fields["patient"].queryset = Patient.objects.filter(hospital=hospital).select_related("user")
            self.fields["surgeon"].queryset = Doctor.objects.filter(hospital=hospital).select_related("user")
            self.fields["operating_room"].queryset = OperatingRoom.objects.filter(hospital=hospital).select_related("ward")
        else:
            self.fields["operating_room"].queryset = OperatingRoom.objects.all().select_related("ward")
        if current_patient is not None:
            self.fields["patient"].initial = current_patient.pk

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("scheduled_start") and cleaned_data.get("scheduled_end"):
            if cleaned_data["scheduled_end"] < cleaned_data["scheduled_start"]:
                raise forms.ValidationError("The surgery end time cannot be earlier than the start time.")
        return cleaned_data


class HospitalInvitationForm(forms.ModelForm):
    role = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = HospitalInvitation
        fields = ["role", "invitee_name", "invitee_email", "expires_at", "note"]
        widgets = {
            "invitee_name": forms.TextInput(attrs={"class": "form-control", "data-entity-search": "patient"}),
            "invitee_email": forms.EmailInput(attrs={"class": "form-control"}),
            "expires_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, allowed_roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_roles = allowed_roles or [choice[0] for choice in HospitalInvitation._meta.get_field("role").choices if choice[0] != "owner"]
        choices = [
            choice
            for choice in HospitalInvitation._meta.get_field("role").choices
            if choice[0] in allowed_roles and choice[0] != "owner"
        ]
        self.allowed_roles = [choice[0] for choice in choices]
        self.fields["role"].choices = choices
        self.fields["invitee_name"].widget.attrs["data-entity-search"] = "patient" if self.allowed_roles == [HospitalAccess.Role.PATIENT] else "any"
        if len(choices) == 1:
            self.fields["role"].initial = choices[0][0]
            self.fields["role"].widget = forms.HiddenInput()

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role not in self.allowed_roles:
            raise forms.ValidationError("This invitation type is not available for your current access level.")
        return role

    def clean_invitee_name(self):
        return " ".join((self.cleaned_data.get("invitee_name") or "").split())

    def clean_invitee_email(self):
        return (self.cleaned_data.get("invitee_email") or "").strip().lower()


class AdmissionForm(forms.ModelForm):
    class Meta:
        model = Admission
        fields = ["patient", "attending_doctor", "ward", "bed", "admission_reason", "notes"]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "attending_doctor": forms.Select(attrs={"class": "form-select", "data-autocomplete": "doctor"}),
            "ward": forms.Select(attrs={"class": "form-select"}),
            "bed": forms.Select(attrs={"class": "form-select"}),
            "admission_reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, hospital=None, current_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        ward_queryset = Ward.objects.all()
        bed_queryset = Bed.objects.select_related("ward")
        if hospital is not None:
            self.fields["patient"].queryset = Patient.objects.filter(hospital=hospital).select_related("user")
            self.fields["attending_doctor"].queryset = Doctor.objects.filter(hospital=hospital).select_related("user")
            ward_queryset = Ward.objects.filter(hospital=hospital)
            bed_queryset = Bed.objects.filter(hospital=hospital, is_occupied=False).select_related("ward")
        selected_ward = None
        bound_data = self.data if self.is_bound else None
        if bound_data:
            selected_ward = bound_data.get("ward") or None
        elif self.instance.pk and self.instance.ward_id:
            selected_ward = str(self.instance.ward_id)
        self.fields["ward"].queryset = ward_queryset
        if selected_ward:
            self.fields["bed"].queryset = bed_queryset.filter(ward_id=selected_ward)
        else:
            self.fields["bed"].queryset = bed_queryset
        self.fields["patient"].label_from_instance = lambda patient: f"{patient} • {patient.patient_number or patient.age_group}"
        self.fields["attending_doctor"].label_from_instance = lambda doctor: str(doctor)
        self.fields["ward"].label_from_instance = lambda ward: f"{ward.name} • {ward.get_ward_type_display()} • {ward.available_beds_count} open"
        self.fields["bed"].label_from_instance = lambda bed: f"{bed.ward.name} • Bed {bed.bed_number}{' • Isolation' if bed.is_isolation else ''}"
        self.fields["bed"].widget.attrs["data-bed-options"] = json.dumps(
            [
                {
                    "value": str(bed.pk),
                    "label": self.fields["bed"].label_from_instance(bed),
                    "ward": str(bed.ward_id),
                }
                for bed in bed_queryset
            ]
        )
        self.fields["ward"].widget.attrs["data-bed-filter-target"] = self["bed"].auto_id
        if current_patient is not None:
            self.fields["patient"].initial = current_patient.pk


class BedTransferForm(forms.ModelForm):
    target_ward = forms.ModelChoiceField(
        queryset=Ward.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = BedTransfer
        fields = ["admission", "target_ward", "to_bed", "reason"]
        widgets = {
            "admission": forms.Select(attrs={"class": "form-select"}),
            "to_bed": forms.Select(attrs={"class": "form-select"}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        admission_queryset = Admission.objects.filter(status=Admission.Status.ACTIVE).select_related("patient__user", "ward", "bed")
        bed_queryset = Bed.objects.filter(is_occupied=False).select_related("ward")
        ward_queryset = Ward.objects.all()
        if hospital is not None:
            admission_queryset = admission_queryset.filter(hospital=hospital)
            bed_queryset = bed_queryset.filter(hospital=hospital)
            ward_queryset = ward_queryset.filter(hospital=hospital)
        self.fields["admission"].queryset = admission_queryset
        self.fields["target_ward"].queryset = ward_queryset
        selected_ward = None
        bound_data = self.data if self.is_bound else None
        if bound_data:
            selected_ward = bound_data.get("target_ward") or None
        if selected_ward:
            self.fields["to_bed"].queryset = bed_queryset.filter(ward_id=selected_ward)
        else:
            self.fields["to_bed"].queryset = bed_queryset
        self.fields["admission"].label_from_instance = lambda admission: (
            f"{admission.patient} • {admission.ward.name} / Bed {admission.bed.bed_number} • "
            f"{admission.attending_doctor} • {admission.admitted_at:%Y-%m-%d}"
        )
        self.fields["target_ward"].label_from_instance = lambda ward: f"{ward.name} • {ward.get_ward_type_display()}"
        self.fields["to_bed"].label_from_instance = lambda bed: (
            f"{bed.ward.name} • Bed {bed.bed_number}{' • Isolation' if bed.is_isolation else ''}"
        )
        self.fields["to_bed"].widget.attrs["data-bed-options"] = json.dumps(
            [
                {
                    "value": str(bed.pk),
                    "label": self.fields["to_bed"].label_from_instance(bed),
                    "ward": str(bed.ward_id),
                }
                for bed in bed_queryset
            ]
        )
        self.fields["target_ward"].widget.attrs["data-bed-filter-target"] = self["to_bed"].auto_id
        self.fields["admission"].widget.attrs["data-admission-ward-map"] = json.dumps(
            [{"value": str(admission.pk), "ward": str(admission.ward_id)} for admission in admission_queryset]
        )

    def clean(self):
        cleaned_data = super().clean()
        target_ward = cleaned_data.get("target_ward")
        to_bed = cleaned_data.get("to_bed")
        admission = cleaned_data.get("admission")
        if admission and not admission.bed_id:
            raise forms.ValidationError("The selected admission does not currently have a bed to transfer from.")
        if to_bed and target_ward and to_bed.ward_id != target_ward.id:
            self.add_error("to_bed", "Select a bed that belongs to the selected target ward.")
        if to_bed and admission and admission.bed_id == to_bed.id:
            self.add_error("to_bed", "Choose a different bed from the patient's current bed.")
        return cleaned_data


class DischargeSummaryForm(forms.ModelForm):
    class Meta:
        model = DischargeSummary
        fields = ["admission", "final_diagnosis", "summary", "follow_up_plan"]
        widgets = {
            "admission": forms.Select(attrs={"class": "form-select"}),
            "final_diagnosis": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "summary": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "follow_up_plan": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital is not None:
            self.fields["admission"].queryset = Admission.objects.filter(
                hospital=hospital, status=Admission.Status.ACTIVE
            ).select_related("patient__user", "ward", "bed")
        self.fields["admission"].label_from_instance = lambda admission: (
            f"{admission.patient} • {admission.ward.name} / Bed {admission.bed.bed_number} • "
            f"{admission.attending_doctor}"
        )


class CaregiverAccessForm(forms.ModelForm):
    class Meta:
        model = CaregiverAccess
        fields = ["caregiver_name", "caregiver_email", "relationship", "can_view_updates", "can_view_billing", "note"]
        widgets = {
            "caregiver_name": forms.TextInput(attrs={"class": "form-control"}),
            "caregiver_email": forms.EmailInput(attrs={"class": "form-control"}),
            "relationship": forms.TextInput(attrs={"class": "form-control"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class AdvanceDirectiveForm(forms.ModelForm):
    class Meta:
        model = AdvanceDirective
        fields = ["directive_type", "summary", "document", "is_active"]
        widgets = {
            "directive_type": forms.Select(attrs={"class": "form-select"}),
            "summary": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "document": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PatientFeedbackForm(forms.ModelForm):
    class Meta:
        model = PatientFeedback
        fields = ["staff_member", "rating", "service_area", "comments"]
        widgets = {
            "staff_member": forms.Select(attrs={"class": "form-select", "data-autocomplete": "staff"}),
            "rating": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5}),
            "service_area": forms.TextInput(attrs={"class": "form-control"}),
            "comments": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = User.objects.filter(
            role__in=[
                User.Role.DOCTOR,
                User.Role.NURSE,
                User.Role.RECEPTIONIST,
                User.Role.LAB_TECHNICIAN,
                User.Role.PHARMACIST,
                User.Role.COUNSELOR,
                User.Role.EMERGENCY_OPERATOR,
                User.Role.ADMIN,
            ]
        )
        if hospital is not None:
            queryset = queryset.filter(hospital_accesses__hospital=hospital).distinct()
        self.fields["staff_member"].queryset = queryset.order_by("first_name", "last_name", "username")
        self.fields["staff_member"].required = False
        self.fields["staff_member"].label_from_instance = lambda user: f"{user.get_full_name() or user.username} • {user.get_role_display()}"


class AllergyForm(forms.ModelForm):
    identified_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = Allergy
        fields = ["allergen", "reaction_type", "severity", "identified_at", "notes"]
        widgets = {
            "allergen": forms.TextInput(attrs={"class": "form-control", "placeholder": "Penicillin, peanuts, latex"}),
            "reaction_type": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rash, anaphylaxis, wheezing"}),
            "severity": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Clinical precautions, trigger pattern, rescue plan"}),
        }


class ImmunizationForm(forms.ModelForm):
    administered_on = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    next_due_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = Immunization
        fields = ["vaccine_name", "dose_number", "manufacturer", "batch_number", "administered_on", "next_due_on", "notes"]
        widgets = {
            "vaccine_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Tetanus booster, Hepatitis B"}),
            "dose_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Dose 2, Booster"}),
            "manufacturer": forms.TextInput(attrs={"class": "form-control"}),
            "batch_number": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Adverse effects, next dose advice, clinic notes"}),
        }


class ChronicConditionForm(forms.ModelForm):
    onset_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = ChronicCondition
        fields = ["condition", "name", "primary_doctor", "onset_date", "status", "management_plan", "monitoring_notes"]
        widgets = {
            "condition": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Hypertension, CKD, epilepsy"}),
            "primary_doctor": forms.Select(attrs={"class": "form-select", "data-autocomplete": "doctor"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "management_plan": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Medication, monitoring cadence, care owner"}),
            "monitoring_notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Control status, escalations, home monitoring"}),
        }

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["condition"].queryset = ConditionCatalog.objects.filter(is_active=True)
        doctor_queryset = Doctor.objects.select_related("user")
        if hospital is not None:
            doctor_queryset = doctor_queryset.filter(hospital=hospital)
        self.fields["primary_doctor"].queryset = doctor_queryset.order_by("user__first_name", "user__last_name")
        self.fields["primary_doctor"].required = False


class FamilyMedicalHistoryForm(forms.ModelForm):
    class Meta:
        model = FamilyMedicalHistory
        fields = ["condition", "condition_name", "relative", "relationship", "age_at_onset", "notes"]
        widgets = {
            "condition": forms.Select(attrs={"class": "form-select"}),
            "condition_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Diabetes, breast cancer, stroke"}),
            "relative": forms.TextInput(attrs={"class": "form-control", "placeholder": "Mother, father, sibling"}),
            "relationship": forms.TextInput(attrs={"class": "form-control", "placeholder": "Maternal aunt, paternal grandfather"}),
            "age_at_onset": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Pattern, age notes, genetic concern"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["condition"].queryset = ConditionCatalog.objects.filter(is_active=True)
        self.fields["condition"].required = False


class SurgicalHistoryForm(forms.ModelForm):
    procedure_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = SurgicalHistory
        fields = ["procedure_name", "procedure_date", "surgeon_name", "facility_name", "outcome", "complications", "notes"]
        widgets = {
            "procedure_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Appendectomy, C-section, ORIF"}),
            "surgeon_name": forms.TextInput(attrs={"class": "form-control"}),
            "facility_name": forms.TextInput(attrs={"class": "form-control"}),
            "outcome": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Recovered well, prolonged stay, outpatient follow-up"}),
            "complications": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Bleeding, infection, none"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class ConsentFormRecordForm(forms.ModelForm):
    signed_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )

    class Meta:
        model = ConsentForm
        fields = ["title", "procedure_name", "status", "document", "signed_by_name", "signed_relationship", "witnessed_by", "signed_at", "expires_at", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Procedure consent, blood transfusion consent"}),
            "procedure_name": forms.TextInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "document": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "signed_by_name": forms.TextInput(attrs={"class": "form-control"}),
            "signed_relationship": forms.TextInput(attrs={"class": "form-control"}),
            "witnessed_by": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["category", "title", "file", "summary", "is_sensitive"]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Discharge summary, referral letter, insurer note"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "summary": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Quick note for what this document contains"}),
            "is_sensitive": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = DocumentCategory.objects.all().order_by("name")
        self.fields["category"].required = False


class MedicalImageForm(forms.ModelForm):
    captured_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )

    class Meta:
        model = MedicalImage
        fields = ["title", "modality", "image", "dicom_identifier", "study_uid", "captured_at", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Chest X-ray, MRI brain, CT angiography"}),
            "modality": forms.Select(attrs={"class": "form-select"}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "dicom_identifier": forms.TextInput(attrs={"class": "form-control"}),
            "study_uid": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Technique notes, interpretation summary, imaging request context"}),
        }


class ShiftHandoverForm(forms.ModelForm):
    shift_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = ShiftHandover
        fields = ["shift_date", "summary", "risks", "pending_tasks"]
        widgets = {
            "summary": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "risks": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "pending_tasks": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class ShiftAssignmentForm(forms.ModelForm):
    DEFAULT_WEEKLY_LIMIT_HOURS = 48
    start_at = forms.DateTimeField(
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local", "class": "form-control"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
    )
    end_at = forms.DateTimeField(
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local", "class": "form-control"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
    )

    class Meta:
        model = ShiftAssignment
        fields = ["staff", "start_at", "end_at", "notes"]
        widgets = {
            "staff": forms.Select(
                attrs={
                    "class": "form-select",
                    "data-autocomplete": "staff",
                    "data-shift-staff-select": "1",
                }
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        start_at = None
        end_at = None
        if self.is_bound:
            try:
                start_value = self.data.get("start_at") or None
                start_at = timezone.make_aware(datetime.fromisoformat(start_value)) if start_value else None
            except (TypeError, ValueError):
                start_at = None
            try:
                end_value = self.data.get("end_at") or None
                end_at = timezone.make_aware(datetime.fromisoformat(end_value)) if end_value else None
            except (TypeError, ValueError):
                end_at = None
        start_at = start_at or self.initial.get("start_at") or timezone.localtime(timezone.now() + timedelta(hours=1)).replace(second=0, microsecond=0)
        end_at = end_at or self.initial.get("end_at") or (start_at + timedelta(hours=8) if start_at else None)
        eligible_queryset = eligible_shift_staff_queryset(
            hospital=hospital,
            start_at=start_at,
            end_at=end_at,
            exclude_assignment_id=self.instance.pk,
            weekly_limit_hours=self.DEFAULT_WEEKLY_LIMIT_HOURS,
        )
        self.fields["staff"].queryset = eligible_queryset
        self.fields["staff"].label_from_instance = (
            lambda staff: format_shift_staff_label(
                staff,
                start_at=start_at,
                weekly_limit_hours=self.DEFAULT_WEEKLY_LIMIT_HOURS,
            )
        )
        self.fields["start_at"].label = "Shift start"
        self.fields["end_at"].label = "Shift end"
        self.fields["start_at"].initial = start_at
        self.fields["end_at"].initial = end_at

    def clean(self):
        cleaned = super().clean()
        staff = cleaned.get("staff")
        start_at = cleaned.get("start_at")
        end_at = cleaned.get("end_at")
        if start_at and end_at and end_at <= start_at:
            raise forms.ValidationError("Shift end must be later than the shift start.")
        if start_at and start_at < timezone.now():
            raise forms.ValidationError("Shift assignments cannot start in the past.")
        if staff and start_at and end_at:
            conflicts = ShiftAssignment.objects.filter(
                staff=staff,
                start_at__lt=end_at,
                end_at__gt=start_at,
            )
            if self.instance.pk:
                conflicts = conflicts.exclude(pk=self.instance.pk)
            if conflicts.exists():
                raise forms.ValidationError("This staff member already has an overlapping shift in the selected period.")
            proposed_hours = max(0, (end_at - start_at).total_seconds() / 3600)
            weekly_hours = scheduled_shift_hours_for_week(
                staff,
                start_at,
                exclude_assignment_id=self.instance.pk,
            )
            if weekly_hours + proposed_hours > self.DEFAULT_WEEKLY_LIMIT_HOURS:
                remaining = max(self.DEFAULT_WEEKLY_LIMIT_HOURS - weekly_hours, 0)
                raise forms.ValidationError(
                    f"This shift would exceed the weekly limit for {staff.user.get_full_name() or staff.user.username}. Remaining assignable hours this week: {remaining:.1f}."
                )
        return cleaned


def shift_week_bounds(shift_point):
    shift_point = timezone.localtime(shift_point) if shift_point else timezone.localtime(timezone.now())
    week_start_date = shift_point.date() - timedelta(days=shift_point.weekday())
    start = timezone.make_aware(datetime.combine(week_start_date, datetime.min.time()))
    end = start + timedelta(days=7)
    return start, end


def shift_hours_within_window(start_at, end_at, window_start, window_end):
    if not start_at or not end_at:
        return 0
    overlap_start = max(start_at, window_start)
    overlap_end = min(end_at, window_end)
    if overlap_end <= overlap_start:
        return 0
    return max(0, (overlap_end - overlap_start).total_seconds() / 3600)


def shift_assignment_hours(assignment):
    return shift_hours_within_window(assignment.local_start_at, assignment.local_end_at, assignment.local_start_at, assignment.local_end_at)


def scheduled_shift_hours_for_week(staff, shift_point, *, exclude_assignment_id=None):
    week_start, week_end = shift_week_bounds(shift_point)
    assignments = ShiftAssignment.objects.filter(
        staff=staff,
        start_at__lt=week_end,
        end_at__gt=week_start,
    )
    if exclude_assignment_id:
        assignments = assignments.exclude(pk=exclude_assignment_id)
    return sum(shift_hours_within_window(item.local_start_at, item.local_end_at, week_start, week_end) for item in assignments)


def eligible_shift_staff_queryset(
    *,
    hospital,
    start_at,
    end_at=None,
    exclude_assignment_id=None,
    weekly_limit_hours=ShiftAssignmentForm.DEFAULT_WEEKLY_LIMIT_HOURS,
    query="",
):
    queryset = StaffProfile.objects.select_related("user").filter(is_active=True)
    if hospital is not None:
        queryset = queryset.filter(
            Q(user__hospital_accesses__hospital=hospital)
            & Q(user__hospital_accesses__status=HospitalAccess.Status.ACTIVE)
        ).distinct()
    if query:
        queryset = queryset.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(role__icontains=query)
            | Q(department__icontains=query)
            | Q(employee_id__icontains=query)
        ).distinct()

    eligible_ids = []
    for staff in queryset.order_by("role", "user__first_name", "user__last_name", "employee_id"):
        weekly_hours = scheduled_shift_hours_for_week(
            staff,
            start_at,
            exclude_assignment_id=exclude_assignment_id,
        )
        if weekly_hours >= weekly_limit_hours:
            continue
        if start_at and end_at:
            conflicts = ShiftAssignment.objects.filter(
                staff=staff,
                start_at__lt=end_at,
                end_at__gt=start_at,
            )
            if exclude_assignment_id:
                conflicts = conflicts.exclude(pk=exclude_assignment_id)
            if conflicts.exists():
                continue
        eligible_ids.append(staff.pk)
    return queryset.filter(pk__in=eligible_ids).order_by("role", "user__first_name", "user__last_name", "employee_id")


def format_shift_staff_label(staff, *, start_at, weekly_limit_hours=ShiftAssignmentForm.DEFAULT_WEEKLY_LIMIT_HOURS):
    weekly_hours = scheduled_shift_hours_for_week(staff, start_at)
    remaining = max(weekly_limit_hours - weekly_hours, 0)
    return (
        f"{staff.user.get_full_name() or staff.user.username} • "
        f"{staff.get_role_display()} • "
        f"{staff.department or 'General services'} • "
        f"{remaining:.1f}h left this week"
    )


class PatientDeathRecordForm(forms.ModelForm):
    deceased_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )

    class Meta:
        model = Patient
        fields = ["deceased_at", "deceased_notes"]
        widgets = {
            "deceased_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Clinical summary, certifying notes, or any tightly relevant death-record detail.",
                }
            ),
        }

    def clean_deceased_at(self):
        deceased_at = self.cleaned_data.get("deceased_at")
        if deceased_at and deceased_at > timezone.now():
            raise forms.ValidationError("The recorded time of death cannot be in the future.")
        return deceased_at


class SupplyRequestForm(forms.ModelForm):
    class Meta:
        model = SupplyRequest
        fields = ["department", "item_name", "quantity", "priority", "notes"]
        widgets = {
            "department": forms.TextInput(attrs={"class": "form-control"}),
            "item_name": forms.TextInput(attrs={"class": "form-control"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class SupplyRequestStatusForm(forms.ModelForm):
    class Meta:
        model = SupplyRequest
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
        }


class LabQualityControlLogForm(forms.ModelForm):
    class Meta:
        model = LabQualityControlLog
        fields = ["analyzer_name", "reagent_lot", "qc_status", "notes"]
        widgets = {
            "analyzer_name": forms.TextInput(attrs={"class": "form-control"}),
            "reagent_lot": forms.TextInput(attrs={"class": "form-control"}),
            "qc_status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class EmergencyIncidentForm(forms.ModelForm):
    class Meta:
        model = EmergencyIncident
        fields = ["linked_request", "title", "category", "severity", "status", "location", "notes"]
        widgets = {
            "linked_request": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.TextInput(attrs={"class": "form-control"}),
            "severity": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        from ambulance.models import AmbulanceRequest
        from django.db.models import Q

        queryset = AmbulanceRequest.objects.all()
        if hospital is not None:
            queryset = queryset.filter(
                Q(address__icontains=hospital.name)
                | Q(status__in=[
                    AmbulanceRequest.Status.PENDING,
                    AmbulanceRequest.Status.ASSIGNED,
                    AmbulanceRequest.Status.EN_ROUTE,
                    AmbulanceRequest.Status.ARRIVED,
                ])
            )
        self.fields["linked_request"].queryset = queryset.distinct().order_by("-created_at")
        self.fields["linked_request"].required = False
