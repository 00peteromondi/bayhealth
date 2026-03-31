from django.db import models

from core.models import User


class Counselor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="counselor")
    specialization = models.CharField(max_length=100)
    bio = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.user.get_full_name() or self.user.username


class TherapySession(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="patient_sessions")
    counselor = models.ForeignKey(Counselor, on_delete=models.CASCADE, related_name="sessions")
    scheduled_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_time"]


class MoodLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mood_logs")
    mood = models.CharField(max_length=50)
    notes = models.TextField(blank=True)
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-logged_at"]


class WellnessResource(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    url = models.URLField(blank=True)
    resource_type = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.title
