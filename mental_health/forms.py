from django import forms

from .models import MoodLog, TherapySession


class MoodLogForm(forms.ModelForm):
    class Meta:
        model = MoodLog
        fields = ["mood", "notes"]
        widgets = {
            "mood": forms.TextInput(attrs={
                "class": "form-control",
                "data-assistant-live": "mental_health",
                "data-assistant-target": "#moodAssistant",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "data-assistant-live": "mental_health",
                "data-assistant-target": "#moodAssistant",
            }),
        }


class TherapySessionForm(forms.ModelForm):
    scheduled_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"})
    )

    class Meta:
        model = TherapySession
        fields = ["patient", "scheduled_time", "notes"]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "data-assistant-live": "mental_health",
                "data-assistant-target": "#sessionAssistant",
            }),
        }
