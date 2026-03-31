from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import models

from core.models import User


class Hospital(models.Model):
    name = models.CharField(max_length=160, unique=True)
    code = models.SlugField(max_length=80, unique=True)
    owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_hospitals",
    )
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class HospitalAccess(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
        LEFT = "left", "Left"

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        DOCTOR = "doctor", "Doctor"
        NURSE = "nurse", "Nurse"
        RECEPTIONIST = "receptionist", "Receptionist"
        LAB_TECHNICIAN = "lab_technician", "Lab Technician"
        PHARMACIST = "pharmacist", "Pharmacist"
        COUNSELOR = "counselor", "Counselor"
        EMERGENCY_OPERATOR = "emergency_operator", "Emergency Operator"
        PATIENT = "patient", "Patient"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hospital_accesses")
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="accesses")
    role = models.CharField(max_length=30, choices=Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    can_switch = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_hospital_accesses",
    )
    revoked_reason = models.CharField(max_length=200, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    left_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ("user", "hospital", "role")

    def __str__(self) -> str:
        return f"{self.user} @ {self.hospital} ({self.get_role_display()})"

    @property
    def is_active_access(self) -> bool:
        return self.status == self.Status.ACTIVE


class HospitalInvitation(models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="invitations")
    role = models.CharField(max_length=30, choices=HospitalAccess.Role.choices)
    code = models.CharField(max_length=48, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="issued_invitations"
    )
    invitee_name = models.CharField(max_length=160, blank=True)
    invitee_email = models.EmailField(blank=True)
    note = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="redeemed_invitations"
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.hospital.name} · {self.get_role_display()} · {self.code}"


class Patient(models.Model):
    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        OTHER = "other", "Other"
        UNSPECIFIED = "unspecified", "Unspecified"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="patient")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="patients")
    patient_number = models.CharField(max_length=30, unique=True, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, default=Gender.UNSPECIFIED)
    insurance_provider = models.CharField(max_length=120, blank=True)
    insurance_number = models.CharField(max_length=80, blank=True)
    medical_history = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    is_deceased = models.BooleanField(default=False)
    deceased_at = models.DateTimeField(null=True, blank=True)
    deceased_recorded_hospital = models.ForeignKey(
        Hospital,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_patient_deaths",
    )
    deceased_recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_patient_deaths",
    )
    deceased_notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.patient_number and self.user_id:
            hospital_code = "GEN"
            if self.hospital_id and self.hospital and self.hospital.code:
                hospital_code = "".join(ch for ch in self.hospital.code.upper() if ch.isalnum())[:6] or "GEN"
            self.patient_number = f"BH-{hospital_code}-PT-{date.today():%y%m}-{self.user_id:06d}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.user.get_full_name() or self.user.username

    @property
    def age_years(self):
        if not self.user.date_of_birth:
            return None
        today = date.today()
        years = today.year - self.user.date_of_birth.year
        if (today.month, today.day) < (self.user.date_of_birth.month, self.user.date_of_birth.day):
            years -= 1
        return max(years, 0)

    @property
    def age_group(self):
        age = self.age_years
        if age is None:
            return "Unknown"
        if age <= 17:
            return "0-17"
        if age <= 34:
            return "18-34"
        if age <= 49:
            return "35-49"
        if age <= 64:
            return "50-64"
        return "65+"


class Doctor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="doctor")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="doctors")
    specialization = models.CharField(max_length=100)
    department = models.CharField(max_length=120, blank=True)
    license_number = models.CharField(max_length=50, unique=True)
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2)
    available_days = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self) -> str:
        return f"Dr. {self.user.get_full_name() or self.user.username}"


class StaffProfile(models.Model):
    class Role(models.TextChoices):
        NURSE = "nurse", "Nurse"
        RECEPTIONIST = "receptionist", "Receptionist"
        LAB_TECHNICIAN = "lab_technician", "Lab Technician"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="staff_profiles")
    employee_id = models.CharField(max_length=40, unique=True)
    role = models.CharField(max_length=30, choices=Role.choices)
    department = models.CharField(max_length=120, blank=True)
    shift_start = models.TimeField(null=True, blank=True)
    shift_end = models.TimeField(null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    certification_expires_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.employee_id and self.user_id:
            prefix = {
                self.Role.NURSE: "NUR",
                self.Role.RECEPTIONIST: "REC",
                self.Role.LAB_TECHNICIAN: "LAB",
            }.get(self.role, "STF")
            self.employee_id = f"{prefix}-{self.user_id:05d}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_role_display()} - {self.user.get_full_name() or self.user.username}"


class Ward(models.Model):
    class WardType(models.TextChoices):
        GENERAL = "general", "General"
        ICU = "icu", "ICU"
        MATERNITY = "maternity", "Maternity"
        PEDIATRIC = "pediatric", "Pediatric"
        EMERGENCY = "emergency", "Emergency"

    name = models.CharField(max_length=120, unique=True)
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="wards", null=True, blank=True)
    ward_type = models.CharField(max_length=30, choices=WardType.choices)
    location = models.CharField(max_length=120, blank=True)
    capacity = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.name

    @property
    def available_beds_count(self) -> int:
        return self.beds.filter(is_occupied=False).count()


class Bed(models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="beds", null=True, blank=True)
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds")
    bed_number = models.CharField(max_length=30)
    is_isolation = models.BooleanField(default=False)
    is_occupied = models.BooleanField(default=False)
    current_patient = models.ForeignKey(
        Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name="occupied_beds"
    )

    class Meta:
        unique_together = ("ward", "bed_number")

    def __str__(self) -> str:
        return f"{self.ward.name} - Bed {self.bed_number}"


class Admission(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRANSFERRED = "transferred", "Transferred"
        DISCHARGED = "discharged", "Discharged"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="admissions")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="admissions")
    attending_doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="admissions")
    ward = models.ForeignKey(Ward, on_delete=models.PROTECT, related_name="admissions")
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="admissions")
    admission_reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    admitted_at = models.DateTimeField(auto_now_add=True)
    discharged_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-admitted_at"]

    def clean(self):
        super().clean()
        if self.bed_id and self.ward_id and self.bed.ward_id != self.ward_id:
            raise ValidationError("Selected bed does not belong to the chosen ward.")

    def __str__(self) -> str:
        patient_name = str(self.patient) if self.patient_id else "Patient"
        ward_name = self.ward.name if self.ward_id else "Ward"
        bed_number = self.bed.bed_number if self.bed_id else "-"
        return f"{patient_name} • {ward_name} / Bed {bed_number}"


class BedTransfer(models.Model):
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name="transfers")
    from_bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="bed_transfers_from")
    to_bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="bed_transfers_to")
    reason = models.TextField(blank=True)
    transferred_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        patient_name = str(self.admission.patient) if self.admission_id else "Patient"
        return f"{patient_name} • {self.from_bed} → {self.to_bed}"


class DischargeSummary(models.Model):
    admission = models.OneToOneField(Admission, on_delete=models.CASCADE, related_name="discharge_summary")
    final_diagnosis = models.TextField()
    summary = models.TextField()
    follow_up_plan = models.TextField(blank=True)
    prepared_by = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="discharge_summaries")
    created_at = models.DateTimeField(auto_now_add=True)


class QueueTicket(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        CALLED = "called", "Called"
        SEEN = "seen", "Seen"

    appointment = models.OneToOneField("Appointment", on_delete=models.CASCADE, related_name="queue_ticket")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="queue_tickets")
    ticket_number = models.CharField(max_length=20, unique=True)
    estimated_wait_minutes = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    called_at = models.DateTimeField(null=True, blank=True)
    seen_at = models.DateTimeField(null=True, blank=True)


class WalkInEncounter(models.Model):
    class Status(models.TextChoices):
        WAITING_TRIAGE = "waiting_triage", "Waiting triage"
        TRIAGED = "triaged", "Triaged"
        WAITING_DOCTOR = "waiting_doctor", "Waiting doctor"
        IN_CONSULTATION = "in_consultation", "In consultation"
        AWAITING_LAB = "awaiting_lab", "Awaiting lab"
        LAB_READY = "lab_ready", "Lab ready"
        AWAITING_PHARMACY = "awaiting_pharmacy", "Awaiting pharmacy"
        ADMISSION_REVIEW = "admission_review", "Admission review"
        ADMITTED = "admitted", "Admitted"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class SeverityBand(models.TextChoices):
        LOW = "low", "Low"
        MODERATE = "moderate", "Moderate"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="walk_in_encounters")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="walk_in_encounters")
    registered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="registered_walk_ins"
    )
    triaged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="triaged_walk_ins"
    )
    attending_doctor = models.ForeignKey(
        Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="walk_in_encounters"
    )
    linked_appointment = models.OneToOneField(
        "Appointment", on_delete=models.SET_NULL, null=True, blank=True, related_name="walk_in_encounter"
    )
    medical_record = models.OneToOneField(
        "MedicalRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="walk_in_encounter"
    )
    admission = models.OneToOneField(
        "Admission", on_delete=models.SET_NULL, null=True, blank=True, related_name="walk_in_encounter"
    )
    ticket_number = models.CharField(max_length=24, unique=True, blank=True)
    queue_position = models.PositiveIntegerField(default=0)
    symptoms = models.TextField(blank=True)
    current_state = models.TextField(blank=True)
    triage_notes = models.TextField(blank=True)
    doctor_notes = models.TextField(blank=True)
    lab_summary = models.TextField(blank=True)
    pharmacy_instructions = models.TextField(blank=True)
    severity_index = models.PositiveSmallIntegerField(default=0)
    severity_band = models.CharField(max_length=20, choices=SeverityBand.choices, default=SeverityBand.LOW)
    is_critical = models.BooleanField(default=False)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.WAITING_TRIAGE)
    arrived_at = models.DateTimeField(auto_now_add=True)
    triaged_at = models.DateTimeField(null=True, blank=True)
    consultation_started_at = models.DateTimeField(null=True, blank=True)
    consultation_completed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_critical", "-severity_index", "arrived_at"]
        indexes = [
            models.Index(fields=["hospital", "status", "is_critical", "severity_index"]),
            models.Index(fields=["patient", "arrived_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            hospital_code = "BAY"
            if self.hospital_id and self.hospital and self.hospital.code:
                hospital_code = "".join(ch for ch in self.hospital.code.upper() if ch.isalnum())[:6] or "BAY"
            self.ticket_number = f"WK-{hospital_code}-{date.today():%d%m}-{self.patient_id or 0:04d}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.ticket_number or 'Walk-in'} · {self.patient}"


class WalkInEvent(models.Model):
    encounter = models.ForeignKey(WalkInEncounter, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="walk_in_events")
    stage = models.CharField(max_length=80)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.encounter} - {self.stage}"


class ShiftAssignment(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="shifts")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="shifts")
    shift_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    notes = models.TextField(blank=True)


class ShiftHandover(models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="shift_handovers")
    staff = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="shift_handovers")
    shift_date = models.DateField()
    summary = models.TextField()
    risks = models.TextField(blank=True)
    pending_tasks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SupplyRequest(models.Model):
    class Priority(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_REVIEW = "in_review", "In Review"
        FULFILLED = "fulfilled", "Fulfilled"
        CANCELLED = "cancelled", "Cancelled"

    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="supply_requests")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="supply_requests")
    department = models.CharField(max_length=120, blank=True)
    item_name = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField(default=1)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.ROUTINE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    notes = models.TextField(blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]


class LabQualityControlLog(models.Model):
    class Status(models.TextChoices):
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        REVIEW = "review", "Needs Review"

    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_qc_logs")
    recorded_by = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_qc_logs")
    analyzer_name = models.CharField(max_length=160)
    reagent_lot = models.CharField(max_length=120, blank=True)
    qc_status = models.CharField(max_length=20, choices=Status.choices, default=Status.PASS)
    notes = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]


class EmergencyIncident(models.Model):
    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MODERATE = "moderate", "Moderate"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DISPATCHED = "dispatched", "Dispatched"
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"

    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="emergency_incidents")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="emergency_incidents")
    linked_request = models.ForeignKey("ambulance.AmbulanceRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    title = models.CharField(max_length=180)
    category = models.CharField(max_length=120, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MODERATE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    location = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]


class Certification(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="certifications")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="certifications")
    title = models.CharField(max_length=160)
    expires_on = models.DateField()
    verified = models.BooleanField(default=False)


class VitalSign(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="vitals")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="vitals")
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    pulse_rate = models.PositiveIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveIntegerField(null=True, blank=True)
    systolic_bp = models.PositiveIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveIntegerField(null=True, blank=True)
    oxygen_saturation = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]


class LabTestRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="lab_requests")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_requests")
    walk_in_encounter = models.ForeignKey(
        WalkInEncounter, on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_requests"
    )
    requested_by = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="lab_requests")
    test_name = models.CharField(max_length=160)
    priority = models.CharField(max_length=20, default="routine")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-requested_at"]


class LabTestResult(models.Model):
    request = models.OneToOneField(
        LabTestRequest, on_delete=models.CASCADE, related_name="result"
    )
    recorded_by = models.ForeignKey(
        StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_results"
    )
    reviewed_by = models.ForeignKey(
        Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_lab_results"
    )
    result_summary = models.TextField()
    attachment = models.FileField(upload_to="lab-results/", blank=True, null=True)
    completed_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=120)
    object_type = models.CharField(max_length=120)
    object_id = models.CharField(max_length=64, blank=True)
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True)
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events")
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        PAST = "past", "Past"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="appointments")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="appointments")
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["appointment_date", "appointment_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "appointment_date", "appointment_time"],
                name="unique_doctor_slot",
            )
        ]

    def clean(self):
        super().clean()
        if self.doctor_id and self.patient_id and self.doctor.user_id == self.patient.user_id:
            raise ValidationError("A doctor cannot book an appointment as their own patient.")


class MedicalRecord(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="medical_records")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="medical_records")
    doctor = models.ForeignKey(
        Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="medical_records"
    )
    subjective = models.TextField(blank=True)
    objective = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)
    diagnosis = models.TextField()
    prescription = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class CarePlan(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On Hold"
        COMPLETED = "completed", "Completed"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="care_plans")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="care_plans")
    doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="care_plans")
    title = models.CharField(max_length=180)
    goals = models.TextField()
    milestones = models.TextField(blank=True)
    timeline = models.CharField(max_length=180, blank=True)
    care_team = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    next_review_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-updated_at"]

    def __str__(self) -> str:
        return f"{self.patient} - {self.title}"


class DoctorTask(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="doctor_tasks")
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name="doctor_tasks")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_doctor_tasks")
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_doctor_tasks")
    title = models.CharField(max_length=180)
    details = models.TextField(blank=True)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]
        indexes = [
            models.Index(fields=["assigned_to", "status", "priority"]),
            models.Index(fields=["hospital", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return self.title


class InternalReferral(models.Model):
    class Priority(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent"
        STAT = "stat", "STAT"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        RESPONDED = "responded", "Responded"
        CLOSED = "closed", "Closed"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="internal_referrals")
    source_hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="outgoing_referrals")
    target_hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="incoming_referrals")
    referring_doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_referrals")
    target_doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_referrals")
    specialty = models.CharField(max_length=120, blank=True)
    reason = models.TextField()
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.ROUTINE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    due_at = models.DateTimeField(null=True, blank=True)
    response_notes = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]
        indexes = [
            models.Index(fields=["target_doctor", "status", "priority"]),
            models.Index(fields=["patient", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient} referral"


class Billing(models.Model):
    class BillingType(models.TextChoices):
        GENERAL = "general", "General"
        WALK_IN_REGISTRATION = "walk_in_registration", "Walk-in Registration"
        WALK_IN_TRIAGE = "walk_in_triage", "Walk-in Triage"
        CONSULTATION = "consultation", "Consultation"
        LAB = "lab", "Laboratory"
        PHARMACY = "pharmacy", "Pharmacy"
        ADMISSION = "admission", "Admission"
        BED_TRANSFER = "bed_transfer", "Bed Transfer"
        DISCHARGE = "discharge", "Discharge"
        TELEMEDICINE = "telemedicine", "Telemedicine"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="billings")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="billings")
    appointment = models.OneToOneField(
        "Appointment", on_delete=models.CASCADE, null=True, blank=True, related_name="billing"
    )
    walk_in_encounter = models.ForeignKey(
        WalkInEncounter, on_delete=models.SET_NULL, null=True, blank=True, related_name="billings"
    )
    admission = models.ForeignKey(
        Admission, on_delete=models.SET_NULL, null=True, blank=True, related_name="billings"
    )
    lab_request = models.ForeignKey(
        LabTestRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="billings"
    )
    pharmacy_task = models.ForeignKey(
        "PharmacyTask", on_delete=models.SET_NULL, null=True, blank=True, related_name="billings"
    )
    medical_record = models.ForeignKey(
        "MedicalRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="billings"
    )
    video_consultation = models.ForeignKey(
        "telemedicine.VideoConsultation", on_delete=models.SET_NULL, null=True, blank=True, related_name="billings"
    )
    billing_type = models.CharField(max_length=40, choices=BillingType.choices, default=BillingType.GENERAL)
    description = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)
    invoice_pdf = models.FileField(upload_to="invoices/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PatientVisit(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="visits")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="visits")
    appointment = models.OneToOneField(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True, related_name="visit"
    )
    admission = models.OneToOneField(
        Admission, on_delete=models.SET_NULL, null=True, blank=True, related_name="visit"
    )
    visit_type = models.CharField(max_length=40, default="consultation")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class CaregiverAccess(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="caregiver_accesses")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="caregiver_accesses")
    caregiver_name = models.CharField(max_length=160)
    caregiver_email = models.EmailField(blank=True)
    relationship = models.CharField(max_length=120, blank=True)
    can_view_updates = models.BooleanField(default=True)
    can_view_billing = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} caregiver access"


class AdvanceDirective(models.Model):
    class DirectiveType(models.TextChoices):
        LIVING_WILL = "living_will", "Living will"
        DNR = "dnr", "Do Not Resuscitate"
        MPOA = "medical_power_of_attorney", "Medical Power of Attorney"
        OTHER = "other", "Other directive"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="advance_directives")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="advance_directives")
    directive_type = models.CharField(max_length=40, choices=DirectiveType.choices, default=DirectiveType.OTHER)
    summary = models.TextField()
    document = models.FileField(upload_to="advance-directives/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} - {self.get_directive_type_display()}"


class PatientFeedback(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWED = "reviewed", "Reviewed"
        RESOLVED = "resolved", "Resolved"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="feedback_entries")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedback_entries")
    doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="patient_feedback")
    staff_member = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="patient_feedback_received")
    rating = models.PositiveSmallIntegerField(default=5)
    service_area = models.CharField(max_length=120, blank=True)
    comments = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} feedback"


class PharmacyTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="pharmacy_tasks")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="pharmacy_tasks")
    walk_in_encounter = models.ForeignKey(
        WalkInEncounter, on_delete=models.SET_NULL, null=True, blank=True, related_name="pharmacy_tasks"
    )
    medical_record = models.ForeignKey(
        "MedicalRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="pharmacy_tasks"
    )
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="requested_pharmacy_tasks")
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="completed_pharmacy_tasks")
    instructions = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} pharmacy task"


class ConditionCatalog(models.Model):
    name = models.CharField(max_length=180, unique=True)
    icd10_code = models.CharField(max_length=20, blank=True, unique=True, null=True)
    category = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    keywords = models.CharField(max_length=255, blank=True, help_text="Comma-separated keywords for matching.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PatientCondition(models.Model):
    class Severity(models.TextChoices):
        MILD = "mild", "Mild"
        MODERATE = "moderate", "Moderate"
        SEVERE = "severe", "Severe"
        CRITICAL = "critical", "Critical"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="condition_records")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="condition_records")
    condition = models.ForeignKey(ConditionCatalog, on_delete=models.SET_NULL, null=True, blank=True, related_name="patient_links")
    medical_record = models.ForeignKey(MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="condition_links")
    recorded_by = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="condition_records")
    condition_name = models.CharField(max_length=180, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MODERATE)
    diagnosed_at = models.DateField(null=True, blank=True)
    resolved_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["hospital", "is_active", "severity"]),
            models.Index(fields=["hospital", "condition_name"]),
            models.Index(fields=["patient", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self.hospital_id and self.patient_id:
            self.hospital = self.patient.hospital
        if not self.condition_name and self.condition_id:
            self.condition_name = self.condition.name
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.medical_record_id and self.medical_record.patient_id != self.patient_id:
            raise ValidationError("The selected medical record does not belong to the patient.")

    def __str__(self) -> str:
        label = self.condition_name or (self.condition.name if self.condition_id else "Unknown condition")
        return f"{self.patient} - {label}"


class OperatingRoom(models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="operating_rooms")
    ward = models.ForeignKey(Ward, on_delete=models.SET_NULL, null=True, blank=True, related_name="operating_rooms")
    room_number = models.CharField(max_length=30)
    name = models.CharField(max_length=120, blank=True)
    is_available = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("hospital", "room_number")
        ordering = ["room_number"]

    def __str__(self) -> str:
        return self.name or f"OR {self.room_number}"


class SurgicalCase(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PRE_OP = "pre_op", "Pre-op"
        IN_SURGERY = "in_surgery", "In Surgery"
        RECOVERY = "recovery", "Recovery"
        PAST = "past", "Past"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        POSTPONED = "postponed", "Postponed"

    class Priority(models.TextChoices):
        ELECTIVE = "elective", "Elective"
        URGENT = "urgent", "Urgent"
        EMERGENCY = "emergency", "Emergency"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="surgical_cases")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="surgical_cases")
    surgeon = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="surgical_cases")
    operating_room = models.ForeignKey(OperatingRoom, on_delete=models.SET_NULL, null=True, blank=True, related_name="surgical_cases")
    procedure_name = models.CharField(max_length=180)
    procedure_code = models.CharField(max_length=40, blank=True)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.ELECTIVE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField(null=True, blank=True)
    estimated_duration_minutes = models.PositiveIntegerField(default=60)
    anesthesia_type = models.CharField(max_length=120, blank=True)
    pre_op_assessment = models.TextField(blank=True)
    post_op_summary = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_start"]
        indexes = [
            models.Index(fields=["hospital", "status", "scheduled_start"]),
            models.Index(fields=["patient", "scheduled_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient} - {self.procedure_name}"

    def clean(self):
        super().clean()
        if self.hospital_id and self.operating_room_id and self.operating_room.hospital_id != self.hospital_id:
            raise ValidationError("The selected operating room does not belong to the chosen hospital.")
        if self.hospital_id and self.surgeon_id and self.surgeon.hospital_id not in {None, self.hospital_id}:
            raise ValidationError("The selected surgeon is not assigned to the chosen hospital.")
        if self.scheduled_end and self.scheduled_end < self.scheduled_start:
            raise ValidationError("The surgery end time cannot be earlier than the start time.")

    def save(self, *args, **kwargs):
        if self.scheduled_start and not self.scheduled_end and self.estimated_duration_minutes:
            self.scheduled_end = self.scheduled_start + timedelta(minutes=self.estimated_duration_minutes)
        self.full_clean()
        return super().save(*args, **kwargs)
