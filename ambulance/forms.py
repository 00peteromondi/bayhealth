from django import forms

from .models import AmbulanceRequest


class AmbulanceRequestForm(forms.ModelForm):
    class Meta:
        model = AmbulanceRequest
        fields = ["latitude", "longitude", "address", "medical_notes"]
        widgets = {
            "latitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "data-location-picker": "address",
                    "data-location-label": "Emergency location",
                }
            ),
            "medical_notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
