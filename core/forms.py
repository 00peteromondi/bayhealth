from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from datetime import date

from hospital.models import Hospital, HospitalInvitation, HospitalAccess, Patient

from .models import AssistantAccessGrant, StaffConversation, User


class UserRegistrationForm(forms.ModelForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "name@example.com",
            }
        ),
    )
    invitation_code = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    hospital_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "data-auto-slug-target": "#id_hospital_code",
                "autocomplete": "organization",
            }
        ),
    )
    hospital_code = forms.SlugField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "readonly": "readonly",
                "data-generated-code": "hospital",
            }
        ),
    )
    hospital_address = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "data-location-picker": "hospital",
                "data-location-default": "Nairobi, Kenya",
            }
        ),
    )
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"})
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "address",
            "date_of_birth",
            "role",
            "invitation_code",
            "hospital_name",
            "hospital_code",
            "hospital_address",
        ]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "data-location-picker": "address",
                    "data-location-label": "Home or contact address",
                    "data-location-default": "Nairobi, Kenya",
                    "data-location-hide-map": "1",
                }
            ),
            "role": forms.Select(attrs={"class": "form-select"}),
        }

    def _unique_hospital_code(self, name):
        base = slugify(name)[:48] or "hospital"
        code = base
        suffix = 1
        while Hospital.objects.filter(code=code).exists():
            suffix += 1
            code = f"{base[:42]}-{suffix}"
        return code

    def _validate_dob(self, dob, role):
        if dob is None:
            return
        today = date.today()
        if dob > today:
            raise ValidationError("Date of birth cannot be in the future.")
        if role not in {User.Role.PATIENT, User.Role.ADMIN}:
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if age < 18:
                raise ValidationError("Staff must be at least 18 years old.")

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match.")
        if password:
            validate_password(password)
        role = cleaned_data.get("role")
        hospital_name = (cleaned_data.get("hospital_name") or "").strip()
        invitation_code = (cleaned_data.get("invitation_code") or "").strip()
        invitation = None
        if invitation_code:
            invitation = HospitalInvitation.objects.select_related("hospital").filter(
                code__iexact=invitation_code, is_active=True
            ).first()
            if not invitation:
                raise forms.ValidationError("The authorization code is invalid or inactive.")
            if invitation.expires_at and invitation.expires_at < timezone.now():
                raise forms.ValidationError("The authorization code has expired.")
            if invitation.role != role:
                raise forms.ValidationError("The authorization code does not match the selected profile.")
            if invitation.invitee_email and cleaned_data.get("email"):
                existing_user = User.objects.filter(email__iexact=cleaned_data["email"]).first()
                if existing_user and existing_user.role == User.Role.PATIENT:
                    raise forms.ValidationError("A patient profile already exists for this email. Please sign in and redeem the invitation from that account.")
                if invitation.invitee_email.strip().lower() != cleaned_data["email"].strip().lower():
                    raise forms.ValidationError("The authorization code could not be activated because the email does not match the invitation record.")
            if invitation.invitee_name:
                submitted_name = " ".join(
                    part for part in [
                        (cleaned_data.get("first_name") or "").strip(),
                        (cleaned_data.get("last_name") or "").strip(),
                    ]
                    if part
                ).strip()
                if submitted_name:
                    invitee_name = " ".join(invitation.invitee_name.split()).casefold()
                    if submitted_name.casefold() != invitee_name:
                        raise forms.ValidationError("The authorization code could not be activated because the name does not match the invitation record.")
        elif role not in {User.Role.PATIENT, User.Role.ADMIN}:
            raise forms.ValidationError("An authorization code is required for this profile.")
        elif role == User.Role.ADMIN and not hospital_name:
            raise forms.ValidationError("Hospital admins must provide a hospital name.")
        elif role == User.Role.ADMIN:
            cleaned_data["hospital_code"] = self._unique_hospital_code(hospital_name)
        self._validate_dob(cleaned_data.get("date_of_birth"), role)
        self.invitation = invitation
        return cleaned_data

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()


class HospitalAccessRedeemForm(forms.Form):
    invitation_code = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))

    def clean_invitation_code(self):
        code = self.cleaned_data["invitation_code"].strip()
        invitation = HospitalInvitation.objects.select_related("hospital").filter(
            code__iexact=code, is_active=True
        ).first()
        if not invitation:
            raise forms.ValidationError("The authorization code is invalid or inactive.")
        if invitation.expires_at and invitation.expires_at < timezone.now():
            raise forms.ValidationError("The authorization code has expired.")
        self.invitation = invitation
        return code


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "address",
            "date_of_birth",
            "profile_picture",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "data-location-picker": "address",
                    "data-location-label": "Residential address",
                    "data-location-default": "Nairobi, Kenya",
                }
            ),
            "date_of_birth": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "profile_picture": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob is None:
            return dob
        today = date.today()
        if dob > today:
            raise ValidationError("Date of birth cannot be in the future.")
        role = getattr(self.instance, "role", None)
        if role not in {User.Role.PATIENT, User.Role.ADMIN}:
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if age < 18:
                raise ValidationError("Staff must be at least 18 years old.")
        return dob

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()


class StyledPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "Enter your current password",
                "data-password-current": "1",
            }
        ),
    )
    new_password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Create a new password",
                "data-password-strength-input": "1",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Re-enter the new password",
                "data-password-confirm-input": "1",
            }
        ),
    )


class StyledPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "name@example.com",
            }
        ),
    )


class StyledEmailVerificationResendForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "name@example.com",
            }
        ),
    )


class StyledEmailVerificationCodeForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "name@example.com",
            }
        ),
    )
    code = forms.CharField(
        label="Verification code",
        min_length=7,
        max_length=7,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "pattern": "[0-9]{7}",
                "placeholder": "1234567",
            }
        ),
    )

    def clean_code(self):
        code = "".join(ch for ch in (self.cleaned_data.get("code") or "") if ch.isdigit())
        if len(code) != 7:
            raise forms.ValidationError("Enter the 7-digit verification code from your email.")
        return code


class StyledSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Create a new password",
                "data-password-strength-input": "1",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Re-enter the new password",
                "data-password-confirm-input": "1",
            }
        ),
    )


class AssistantAccessGrantForm(forms.Form):
    requester = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "form-select", "data-autocomplete": "staff"}),
    )
    patient = forms.ModelChoiceField(
        queryset=Patient.objects.none(),
        widget=forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Why does this staff member need BayAfya Assistant access to this patient record?"}),
    )

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._hospital = hospital
        staff_roles = [
            User.Role.DOCTOR,
            User.Role.NURSE,
            User.Role.RECEPTIONIST,
            User.Role.LAB_TECHNICIAN,
            User.Role.PHARMACIST,
            User.Role.COUNSELOR,
            User.Role.EMERGENCY_OPERATOR,
            User.Role.ADMIN,
        ]
        staff_qs = User.objects.filter(role__in=staff_roles)
        if hospital is not None:
            staff_qs = staff_qs.filter(
                hospital_accesses__hospital=hospital,
                hospital_accesses__status=HospitalAccess.Status.ACTIVE,
            ).distinct()
            self.fields["patient"].queryset = Patient.objects.select_related("user").filter(hospital=hospital).order_by("user__last_name", "user__first_name", "user__username")
        else:
            self.fields["patient"].queryset = Patient.objects.select_related("user").order_by("user__last_name", "user__first_name", "user__username")
        self.fields["requester"].queryset = staff_qs.distinct().order_by("first_name", "last_name", "username")

    def clean(self):
        cleaned = super().clean()
        requester = cleaned.get("requester")
        patient = cleaned.get("patient")
        if requester and patient and requester.id == patient.user_id:
            raise forms.ValidationError("The staff member granting access must be different from the patient record owner.")
        if self._hospital is not None:
            if requester and not HospitalAccess.objects.filter(
                user=requester,
                hospital=self._hospital,
                status=HospitalAccess.Status.ACTIVE,
            ).exclude(role=HospitalAccess.Role.PATIENT).exists():
                raise forms.ValidationError("The selected staff member does not currently hold active access in this hospital.")
            if patient and patient.hospital_id not in {None, self._hospital.id}:
                raise forms.ValidationError("The selected patient is not associated with this hospital.")
        return cleaned


class StyledAuthenticationForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if getattr(user, "email", "") and not getattr(user, "email_verified_at", None):
            raise ValidationError(
                "Your email address is not verified yet. Please check your inbox or request a new verification email."
            )


class DirectConversationForm(forms.Form):
    recipient = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "form-select", "data-autocomplete": "staff"}),
    )

    def __init__(self, *args, hospital=None, user=None, viewer=None, **kwargs):
        super().__init__(*args, **kwargs)
        viewer = viewer or user
        queryset = User.objects.filter(
            role__in=[
                User.Role.DOCTOR,
                User.Role.NURSE,
                User.Role.RECEPTIONIST,
                User.Role.LAB_TECHNICIAN,
                User.Role.PHARMACIST,
                User.Role.COUNSELOR,
                User.Role.EMERGENCY_OPERATOR,
                User.Role.ADMIN,
            ]
        )
        if viewer is not None and getattr(viewer, "role", None) == User.Role.PATIENT and hasattr(viewer, "patient"):
            patient_hospital = getattr(viewer.patient, "hospital", None)
            hospital = hospital or patient_hospital
        if viewer is not None and getattr(viewer, "role", None) == User.Role.PATIENT:
            care_hospital_ids = {hospital.id} if hospital else set()
            if not care_hospital_ids and hasattr(viewer, "patient") and viewer.patient.hospital_id:
                care_hospital_ids.add(viewer.patient.hospital_id)
            if care_hospital_ids:
                queryset = queryset.filter(
                    hospital_accesses__hospital_id__in=care_hospital_ids,
                    hospital_accesses__status=HospitalAccess.Status.ACTIVE,
                )
        if hospital is not None:
            queryset = queryset.filter(hospital_accesses__hospital=hospital).distinct()
        if user is not None:
            queryset = queryset.exclude(pk=user.pk)
        self.fields["recipient"].queryset = queryset.order_by("first_name", "last_name", "username")


class TeamConversationForm(forms.ModelForm):
    class Meta:
        model = StaffConversation
        fields = ["title", "purpose", "description", "linked_patient", "assistant_enabled"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rapid recovery pod, theatre prep, discharge coordination..."}),
            "purpose": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Define the scope, patient outcome, or coordination goal for the team."}),
            "linked_patient": forms.Select(attrs={"class": "form-select", "data-autocomplete": "patient"}),
            "assistant_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "purpose": "Choose the main reason this team exists so the conversation stays focused.",
            "assistant_enabled": "Allow BayAfya Assistant to participate when teammates mention @bayafya.",
        }

    def __init__(self, *args, hospital=None, creator=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["linked_patient"].required = False
        patient_qs = Patient.objects.select_related("user")
        if hospital is not None:
            patient_qs = patient_qs.filter(hospital=hospital)
        self.fields["linked_patient"].queryset = patient_qs.order_by("user__last_name", "user__first_name")
        self._hospital = hospital
        self._creator = creator

    def save(self, commit=True):
        conversation = super().save(commit=False)
        conversation.kind = StaffConversation.Kind.TEAM
        conversation.hospital = self._hospital
        conversation.created_by = self._creator
        if commit:
            conversation.save()
        return conversation


class JoinConversationForm(forms.Form):
    join_code = forms.CharField(
        max_length=16,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter a team access code"}),
    )

    def clean_join_code(self):
        return (self.cleaned_data["join_code"] or "").strip().upper()
