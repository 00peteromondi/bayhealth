import uuid

from django.db import models

from hospital.models import Appointment, Doctor, Patient


class VideoConsultation(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        ONGOING = "ongoing", "Ongoing"
        COMPLETED = "completed", "Completed"

    appointment = models.OneToOneField(
        Appointment, on_delete=models.CASCADE, related_name="video_consultation"
    )
    room_id = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)


class Prescription(models.Model):
    consultation = models.ForeignKey(
        VideoConsultation, on_delete=models.CASCADE, related_name="prescriptions"
    )
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    medications = models.TextField()
    instructions = models.TextField(blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]


class ReportUpload(models.Model):
    consultation = models.ForeignKey(
        VideoConsultation, on_delete=models.CASCADE, related_name="reports"
    )
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    file = models.FileField(upload_to="reports/")
    description = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
