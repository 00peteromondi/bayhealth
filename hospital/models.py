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
    revoked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="revoked_invitations"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
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
    class OccupancyStatus(models.TextChoices):
        AVAILABLE = "available", "Available"
        OCCUPIED = "occupied", "Occupied"
        RESERVED = "reserved", "Reserved"
        OUT_OF_SERVICE = "out_of_service", "Out of service"

    class SanitizationState(models.TextChoices):
        CLEAN = "clean", "Clean"
        NEEDS_CLEANING = "needs_cleaning", "Needs cleaning"
        IN_PROGRESS = "in_progress", "Cleaning in progress"
        ISOLATION_CLEANING = "isolation_cleaning", "Isolation cleaning"

    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="beds", null=True, blank=True)
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds")
    bed_number = models.CharField(max_length=30)
    is_isolation = models.BooleanField(default=False)
    is_occupied = models.BooleanField(default=False)
    occupancy_status = models.CharField(
        max_length=20,
        choices=OccupancyStatus.choices,
        default=OccupancyStatus.AVAILABLE,
    )
    sanitization_state = models.CharField(
        max_length=24,
        choices=SanitizationState.choices,
        default=SanitizationState.CLEAN,
    )
    last_cleaned_at = models.DateTimeField(null=True, blank=True)
    current_patient = models.ForeignKey(
        Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name="occupied_beds"
    )

    class Meta:
        unique_together = ("ward", "bed_number")

    def __str__(self) -> str:
        return f"{self.ward.name} - Bed {self.bed_number}"

    def save(self, *args, **kwargs):
        if self.is_occupied and self.occupancy_status == self.OccupancyStatus.AVAILABLE:
            self.occupancy_status = self.OccupancyStatus.OCCUPIED
        if not self.is_occupied and self.occupancy_status == self.OccupancyStatus.OCCUPIED:
            self.occupancy_status = self.OccupancyStatus.AVAILABLE
        super().save(*args, **kwargs)


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


class Allergy(models.Model):
    class Severity(models.TextChoices):
        MILD = "mild", "Mild"
        MODERATE = "moderate", "Moderate"
        SEVERE = "severe", "Severe"
        LIFE_THREATENING = "life_threatening", "Life threatening"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="allergies")
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="recorded_allergies")
    allergen = models.CharField(max_length=160)
    reaction_type = models.CharField(max_length=160, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MODERATE)
    notes = models.TextField(blank=True)
    identified_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "is_active", "severity"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient} allergy - {self.allergen}"


class Immunization(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="immunizations")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="immunizations")
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="recorded_immunizations")
    vaccine_name = models.CharField(max_length=180)
    administered_on = models.DateField()
    batch_number = models.CharField(max_length=80, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    dose_number = models.CharField(max_length=40, blank=True)
    next_due_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-administered_on", "-created_at"]
        indexes = [
            models.Index(fields=["patient", "administered_on"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient} - {self.vaccine_name}"


class ChronicCondition(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        STABLE = "stable", "Stable"
        RESOLVED = "resolved", "Resolved"
        MONITORING = "monitoring", "Monitoring"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="chronic_conditions")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="chronic_conditions")
    condition = models.ForeignKey("ConditionCatalog", on_delete=models.SET_NULL, null=True, blank=True, related_name="chronic_condition_records")
    primary_doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="managed_chronic_conditions")
    name = models.CharField(max_length=180)
    onset_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    management_plan = models.TextField(blank=True)
    monitoring_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-updated_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
        ]

    def save(self, *args, **kwargs):
        if not self.name and self.condition_id:
            self.name = self.condition.name
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.patient} chronic condition - {self.name}"


class FamilyMedicalHistory(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="family_history_records")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="family_history_records")
    condition = models.ForeignKey("ConditionCatalog", on_delete=models.SET_NULL, null=True, blank=True, related_name="family_history_links")
    relative = models.CharField(max_length=120)
    relationship = models.CharField(max_length=80, blank=True)
    condition_name = models.CharField(max_length=180)
    age_at_onset = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]

    def save(self, *args, **kwargs):
        if not self.condition_name and self.condition_id:
            self.condition_name = self.condition.name
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.patient} family history - {self.condition_name}"


class SurgicalHistory(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="surgical_history_entries")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="surgical_history_entries")
    documented_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="documented_surgical_history_entries")
    procedure_name = models.CharField(max_length=180)
    procedure_date = models.DateField(null=True, blank=True)
    surgeon_name = models.CharField(max_length=160, blank=True)
    facility_name = models.CharField(max_length=160, blank=True)
    outcome = models.TextField(blank=True)
    complications = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-procedure_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} surgical history - {self.procedure_name}"


class ConsentForm(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SIGNED = "signed", "Signed"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="consent_forms")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="consent_forms")
    surgical_case = models.ForeignKey("SurgicalCase", on_delete=models.SET_NULL, null=True, blank=True, related_name="consent_forms")
    medical_record = models.ForeignKey("MedicalRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="consent_forms")
    title = models.CharField(max_length=180)
    procedure_name = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    document = models.FileField(upload_to="consent-forms/", blank=True, null=True)
    signed_by_name = models.CharField(max_length=160, blank=True)
    signed_relationship = models.CharField(max_length=120, blank=True)
    witnessed_by = models.CharField(max_length=160, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} consent - {self.title}"


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


class DocumentCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Document(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="documents")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    category = models.ForeignKey(DocumentCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    medical_record = models.ForeignKey(MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_documents")
    title = models.CharField(max_length=180)
    file = models.FileField(upload_to="patient-documents/")
    summary = models.TextField(blank=True)
    is_sensitive = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["patient", "uploaded_at"]),
            models.Index(fields=["hospital", "category"]),
        ]

    def __str__(self) -> str:
        return self.title


class MedicalImage(models.Model):
    class Modality(models.TextChoices):
        XRAY = "xray", "X-ray"
        CT = "ct", "CT"
        MRI = "mri", "MRI"
        ULTRASOUND = "ultrasound", "Ultrasound"
        ECG = "ecg", "ECG"
        OTHER = "other", "Other"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="medical_images")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="medical_images")
    linked_document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="medical_images")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_medical_images")
    title = models.CharField(max_length=180)
    modality = models.CharField(max_length=20, choices=Modality.choices, default=Modality.OTHER)
    image = models.FileField(upload_to="medical-images/")
    dicom_identifier = models.CharField(max_length=120, blank=True)
    study_uid = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-captured_at", "-created_at"]

    def __str__(self) -> str:
        return self.title


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


class MedicationAdministrationRecord(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        ADMINISTERED = "administered", "Administered"
        HELD = "held", "Held"
        MISSED = "missed", "Missed"
        REFUSED = "refused", "Refused"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="medication_administration_records")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="medication_administration_records")
    medical_record = models.ForeignKey(MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="medication_administration_records")
    pharmacy_task = models.ForeignKey(PharmacyTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="medication_administration_records")
    administered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="administered_medications")
    medication_name = models.CharField(max_length=180)
    dose = models.CharField(max_length=120, blank=True)
    route = models.CharField(max_length=80, blank=True)
    scheduled_for = models.DateTimeField()
    administered_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_for", "-created_at"]
        indexes = [
            models.Index(fields=["patient", "scheduled_for", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient} MAR - {self.medication_name}"


class LabPanel(models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_panels")
    name = models.CharField(max_length=180)
    code = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    tests = models.TextField(help_text="Comma-separated test names in this panel.")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("hospital", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Specimen(models.Model):
    class SampleType(models.TextChoices):
        BLOOD = "blood", "Blood"
        URINE = "urine", "Urine"
        STOOL = "stool", "Stool"
        SWAB = "swab", "Swab"
        TISSUE = "tissue", "Tissue"
        OTHER = "other", "Other"

    class ChainStatus(models.TextChoices):
        COLLECTED = "collected", "Collected"
        TRANSFERRED = "transferred", "Transferred"
        RECEIVED = "received", "Received"
        PROCESSING = "processing", "Processing"
        STORED = "stored", "Stored"
        DISPOSED = "disposed", "Disposed"

    request = models.ForeignKey(LabTestRequest, on_delete=models.CASCADE, related_name="specimens")
    collected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="collected_specimens")
    sample_type = models.CharField(max_length=20, choices=SampleType.choices, default=SampleType.BLOOD)
    identifier = models.CharField(max_length=80, unique=True)
    chain_status = models.CharField(max_length=20, choices=ChainStatus.choices, default=ChainStatus.COLLECTED)
    collected_at = models.DateTimeField()
    received_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-collected_at"]

    def __str__(self) -> str:
        return self.identifier


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


class Room(models.Model):
    class RoomType(models.TextChoices):
        CONSULTATION = "consultation", "Consultation"
        WARD = "ward", "Ward"
        OPERATING_THEATRE = "operating_theatre", "Operating theatre"
        LAB = "lab", "Laboratory"
        IMAGING = "imaging", "Imaging"
        PHARMACY = "pharmacy", "Pharmacy"
        ADMIN = "admin", "Administration"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        OCCUPIED = "occupied", "Occupied"
        CLEANING = "cleaning", "Cleaning"
        MAINTENANCE = "maintenance", "Maintenance"

    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="rooms")
    ward = models.ForeignKey(Ward, on_delete=models.SET_NULL, null=True, blank=True, related_name="rooms")
    room_number = models.CharField(max_length=30)
    name = models.CharField(max_length=120, blank=True)
    room_type = models.CharField(max_length=30, choices=RoomType.choices, default=RoomType.OTHER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    floor = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("hospital", "room_number")
        ordering = ["room_number"]

    def __str__(self) -> str:
        return self.name or f"{self.get_room_type_display()} {self.room_number}"


class Equipment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        IN_USE = "in_use", "In use"
        MAINTENANCE = "maintenance", "Maintenance"
        RETIRED = "retired", "Retired"

    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="equipment_items")
    serial_number = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=120, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    model_number = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    purchased_on = models.DateField(null=True, blank=True)
    maintenance_interval_days = models.PositiveIntegerField(default=180)
    next_maintenance_due_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.serial_number})"


class MaintenanceLog(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="maintenance_logs")
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="equipment_maintenance_logs")
    summary = models.TextField()
    service_date = models.DateField()
    next_due_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-service_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.equipment} maintenance on {self.service_date}"


class AssetAssignment(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="assignments")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="asset_assignments")
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_assignments")
    assigned_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            models.UniqueConstraint(fields=["equipment"], condition=models.Q(is_active=True), name="unique_active_equipment_assignment"),
        ]

    def __str__(self) -> str:
        return f"{self.equipment} -> {self.room}"


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


class AnesthesiaRecord(models.Model):
    surgical_case = models.OneToOneField(SurgicalCase, on_delete=models.CASCADE, related_name="anesthesia_record")
    anesthetist = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="anesthesia_records")
    anesthesia_type = models.CharField(max_length=120)
    dosage_summary = models.TextField(blank=True)
    airway_notes = models.TextField(blank=True)
    complications = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Anesthesia - {self.surgical_case}"


class SurgicalTeamMember(models.Model):
    class Role(models.TextChoices):
        SURGEON = "surgeon", "Surgeon"
        ASSISTANT = "assistant", "Assistant"
        ANESTHETIST = "anesthetist", "Anesthetist"
        SCRUB_NURSE = "scrub_nurse", "Scrub nurse"
        CIRCULATING_NURSE = "circulating_nurse", "Circulating nurse"
        OTHER = "other", "Other"

    surgical_case = models.ForeignKey(SurgicalCase, on_delete=models.CASCADE, related_name="team_members")
    member = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="surgical_team_roles")
    display_name = models.CharField(max_length=160, blank=True)
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.OTHER)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["role", "id"]

    def __str__(self) -> str:
        return self.display_name or (self.member.get_full_name() if self.member_id else self.get_role_display())


class MaternityRecord(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="maternity_records")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="maternity_records")
    primary_doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="maternity_records")
    gravida = models.PositiveSmallIntegerField(default=1)
    para = models.PositiveSmallIntegerField(default=0)
    last_menstrual_period = models.DateField(null=True, blank=True)
    estimated_delivery_date = models.DateField(null=True, blank=True)
    risk_notes = models.TextField(blank=True)
    antenatal_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.patient} maternity record"


class NeonatalRecord(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="neonatal_records")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="neonatal_records")
    maternity_record = models.ForeignKey(MaternityRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="neonatal_records")
    birth_weight_kg = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_score_1_min = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_score_5_min = models.PositiveSmallIntegerField(null=True, blank=True)
    delivery_notes = models.TextField(blank=True)
    neonatal_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} neonatal record"


class PediatricGrowthChart(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="growth_chart_entries")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="growth_chart_entries")
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="recorded_growth_chart_entries")
    recorded_on = models.DateField()
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    head_circumference_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-recorded_on", "-id"]

    def __str__(self) -> str:
        return f"{self.patient} growth chart on {self.recorded_on}"


class MentalHealthRecord(models.Model):
    class AccessLevel(models.TextChoices):
        CLINICAL_TEAM = "clinical_team", "Clinical team"
        COUNSELOR_ONLY = "counselor_only", "Counselor only"
        HIGHLY_RESTRICTED = "highly_restricted", "Highly restricted"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="mental_health_records")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="mental_health_records")
    counselor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mental_health_records")
    session_date = models.DateField()
    assessment_summary = models.TextField()
    care_plan = models.TextField(blank=True)
    risk_flags = models.TextField(blank=True)
    access_level = models.CharField(max_length=24, choices=AccessLevel.choices, default=AccessLevel.COUNSELOR_ONLY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-session_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} mental health record"


class OutcomeTracking(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="outcomes")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="outcomes")
    admission = models.ForeignKey(Admission, on_delete=models.SET_NULL, null=True, blank=True, related_name="outcomes")
    medical_record = models.ForeignKey(MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="outcomes")
    outcome_summary = models.TextField()
    recovery_status = models.CharField(max_length=120, blank=True)
    readmitted_within_30_days = models.BooleanField(default=False)
    follow_up_required = models.BooleanField(default=False)
    measured_at = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measured_at", "-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} outcome on {self.measured_at}"


class GeneratedReport(models.Model):
    class ReportType(models.TextChoices):
        FINANCIAL = "financial", "Financial"
        CLINICAL = "clinical", "Clinical"
        OPERATIONAL = "operational", "Operational"
        COMPLIANCE = "compliance", "Compliance"

    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="generated_reports")
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="generated_reports")
    report_type = models.CharField(max_length=20, choices=ReportType.choices, default=ReportType.OPERATIONAL)
    title = models.CharField(max_length=180)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    file = models.FileField(upload_to="reports/", blank=True, null=True)
    summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class InteroperabilityMessageLog(models.Model):
    class Standard(models.TextChoices):
        HL7 = "hl7", "HL7"
        FHIR = "fhir", "FHIR"
        OTHER = "other", "Other"

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="interop_message_logs")
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name="interop_message_logs")
    standard = models.CharField(max_length=16, choices=Standard.choices, default=Standard.FHIR)
    direction = models.CharField(max_length=16, choices=Direction.choices, default=Direction.OUTBOUND)
    message_type = models.CharField(max_length=80, blank=True)
    external_system = models.CharField(max_length=160, blank=True)
    reference_id = models.CharField(max_length=120, blank=True)
    payload_excerpt = models.TextField(blank=True)
    delivered_successfully = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_standard_display()} {self.get_direction_display()} message"


class ExternalReferral(models.Model):
    class Direction(models.TextChoices):
        OUTGOING = "outgoing", "Outgoing"
        INCOMING = "incoming", "Incoming"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="external_referrals")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="external_referrals")
    direction = models.CharField(max_length=16, choices=Direction.choices, default=Direction.OUTGOING)
    organization_name = models.CharField(max_length=180)
    contact_person = models.CharField(max_length=160, blank=True)
    contact_details = models.CharField(max_length=180, blank=True)
    specialty = models.CharField(max_length=120, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=40, default="pending")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} external referral"


class InsurancePreAuthorization(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        EXPIRED = "expired", "Expired"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="insurance_preauthorizations")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="insurance_preauthorizations")
    admission = models.ForeignKey(Admission, on_delete=models.SET_NULL, null=True, blank=True, related_name="insurance_preauthorizations")
    surgical_case = models.ForeignKey(SurgicalCase, on_delete=models.SET_NULL, null=True, blank=True, related_name="insurance_preauthorizations")
    insurer_name = models.CharField(max_length=160)
    reference_number = models.CharField(max_length=80, blank=True)
    requested_service = models.CharField(max_length=180)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decision_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.patient} preauth - {self.requested_service}"


class PatientMessage(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        READ = "read", "Read"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="portal_messages")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="portal_messages")
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_patient_messages")
    recipient = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_patient_messages")
    subject = models.CharField(max_length=180, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SENT)
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self) -> str:
        return self.subject or f"Message for {self.patient}"


class AppointmentReminder(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        IN_APP = "in_app", "In-app"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name="reminders")
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.EMAIL)
    scheduled_for = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_for", "-created_at"]

    def __str__(self) -> str:
        return f"Reminder for appointment {self.appointment_id}"


class DataAccessRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_REVIEW = "in_review", "In review"
        FULFILLED = "fulfilled", "Fulfilled"
        REJECTED = "rejected", "Rejected"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="data_access_requests")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="data_access_requests")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="data_access_requests")
    request_scope = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Data access request for {self.patient}"


class BreachLog(models.Model):
    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MODERATE = "moderate", "Moderate"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="breach_logs")
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reported_breach_logs")
    title = models.CharField(max_length=180)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MODERATE)
    description = models.TextField()
    affected_records_estimate = models.PositiveIntegerField(default=0)
    mitigations = models.TextField(blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    reported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reported_at"]

    def __str__(self) -> str:
        return self.title


class SessionToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hospital_session_tokens")
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name="session_tokens")
    token_hash = models.CharField(max_length=128, unique=True)
    ip_address = models.CharField(max_length=64, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["user", "is_active", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Session token for {self.user}"
