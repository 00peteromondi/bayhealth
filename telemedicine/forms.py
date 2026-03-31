from django import forms

from .models import Prescription, ReportUpload


class PrescriptionForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ["medications", "instructions"]
        widgets = {
            "medications": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "instructions": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class ReportUploadForm(forms.ModelForm):
    class Meta:
        model = ReportUpload
        fields = ["file", "description"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
        }


class TelemedicineLabRequestForm(forms.Form):
    test_name = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    priority = forms.ChoiceField(
        choices=[("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
