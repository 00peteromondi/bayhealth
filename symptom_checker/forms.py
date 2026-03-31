from django import forms


class SymptomForm(forms.Form):
    PROGRESSION_CHOICES = [
        ("stable", "Stable"),
        ("worsening", "Worsening"),
        ("improving", "Improving"),
        ("fluctuating", "Fluctuating"),
    ]

    symptoms = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "data-assistant-live": "symptom",
            "data-assistant-target": "#symptomAssistant",
        }),
        help_text="Describe the symptoms in plain language, including anything that is becoming more severe.",
    )
    onset_summary = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "For example: Started three days ago"}),
        help_text="Capture when the symptoms began or how long they have been present.",
    )
    progression = forms.ChoiceField(
        required=False,
        choices=PROGRESSION_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Describe whether the symptoms are stable, worsening, improving, or fluctuating.",
    )
    intensity = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=10,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10, "placeholder": "1 to 10"}),
        help_text="Rate overall symptom intensity from 1 to 10.",
    )
