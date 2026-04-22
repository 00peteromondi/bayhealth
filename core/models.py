import secrets
import string

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        PATIENT = "patient", "Patient"
        DOCTOR = "doctor", "Doctor"
        NURSE = "nurse", "Nurse"
        RECEPTIONIST = "receptionist", "Receptionist"
        LAB_TECHNICIAN = "lab_technician", "Lab Technician"
        ADMIN = "admin", "Admin"
        PHARMACIST = "pharmacist", "Pharmacist"
        COUNSELOR = "counselor", "Counselor"
        EMERGENCY_OPERATOR = "emergency_operator", "Emergency Operator"

    role = models.CharField(max_length=32, choices=Role.choices, default=Role.PATIENT)
    profile_picture = models.ImageField(upload_to="profiles/", blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_verification_code = models.CharField(max_length=7, blank=True)
    email_verification_sent_at = models.DateTimeField(null=True, blank=True)
    email_verification_send_count = models.PositiveSmallIntegerField(default=0)
    email_verification_send_date = models.DateField(null=True, blank=True)
    email_verification_locked_until = models.DateTimeField(null=True, blank=True)
    email_verification_failed_count = models.PositiveSmallIntegerField(default=0)
    email_verification_failed_date = models.DateField(null=True, blank=True)
    pending_hospital_invitation = models.ForeignKey(
        "hospital.HospitalInvitation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_users",
    )

    def __str__(self) -> str:
        return self.get_full_name() or self.username


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=150)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user}: {self.title}"


class AssistantAccessGrant(models.Model):
    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        REVOKED = "revoked", "Revoked"

    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assistant_access_requests")
    patient_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assistant_access_grants")
    hospital_id = models.PositiveIntegerField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_assistant_access_grants",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.APPROVED)
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["requester", "patient_user", "hospital_id", "status"]),
        ]

    @property
    def is_active(self) -> bool:
        if self.status != self.Status.APPROVED:
            return False
        return not self.expires_at or self.expires_at >= timezone.now()

    def __str__(self) -> str:
        return f"{self.requester} -> {self.patient_user} ({self.status})"


def _team_join_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


class StaffConversation(models.Model):
    class Kind(models.TextChoices):
        DIRECT = "direct", "Direct"
        TEAM = "team", "Team"

    class Purpose(models.TextChoices):
        GENERAL_COLLABORATION = "general_collaboration", "General collaboration"
        CARE_COORDINATION = "care_coordination", "Care coordination"
        RAPID_RECOVERY = "rapid_recovery", "Rapid recovery"
        SHIFT_HANDOVER = "shift_handover", "Shift handover"
        LAB_REVIEW = "lab_review", "Lab review"
        PHARMACY_SYNC = "pharmacy_sync", "Pharmacy synchronization"
        SURGERY_PREP = "surgery_prep", "Surgery preparation"
        EMERGENCY_RESPONSE = "emergency_response", "Emergency response"
        DISCHARGE_PLANNING = "discharge_planning", "Discharge planning"

    hospital = models.ForeignKey(
        "hospital.Hospital",
        on_delete=models.CASCADE,
        related_name="staff_conversations",
        null=True,
        blank=True,
    )
    linked_patient = models.ForeignKey(
        "hospital.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_conversations",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.DIRECT)
    purpose = models.CharField(max_length=32, choices=Purpose.choices, default=Purpose.GENERAL_COLLABORATION)
    title = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    join_code = models.CharField(max_length=16, unique=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_staff_conversations",
    )
    assistant_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-updated_at"]
        indexes = [
            models.Index(fields=["hospital", "kind", "is_active"]),
            models.Index(fields=["last_message_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self.join_code:
            code = _team_join_code()
            while StaffConversation.objects.filter(join_code=code).exists():
                code = _team_join_code()
            self.join_code = code
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title or self.get_purpose_display()


class StaffConversationParticipant(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    conversation = models.ForeignKey(
        StaffConversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversation_participants",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("conversation", "user")
        ordering = ["joined_at"]

    def __str__(self) -> str:
        return f"{self.user} in {self.conversation}"


class StaffMessage(models.Model):
    class Kind(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(
        StaffConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_messages",
    )
    sender_label = models.CharField(max_length=160, blank=True)
    body = models.TextField()
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.USER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self) -> str:
        label = self.sender_label or (self.sender.get_full_name() if self.sender_id else self.get_kind_display())
        return f"{self.get_kind_display()} message from {label} in conversation {self.conversation_id}"
