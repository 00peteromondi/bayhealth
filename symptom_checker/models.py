from django.db import models

from core.models import User


class SymptomCheck(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MODERATE = "moderate", "Moderate"
        HIGH = "high", "High"

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    symptoms = models.TextField()
    onset_summary = models.CharField(max_length=160, blank=True)
    progression = models.CharField(max_length=30, blank=True)
    intensity = models.PositiveSmallIntegerField(null=True, blank=True)
    structured_context = models.JSONField(default=dict, blank=True)
    predicted_disease = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.LOW)
    guidance = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at"]
