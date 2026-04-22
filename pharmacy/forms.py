from django import forms


class OrderForm(forms.Form):
    prescription_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
    )
