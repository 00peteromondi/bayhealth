from django.db.models.signals import post_save
from django.dispatch import receiver

from hospital.models import Doctor, Patient, StaffProfile
from mental_health.models import Counselor

from .models import User


@receiver(post_save, sender=User)
def ensure_role_profile(sender, instance: User, created: bool, **kwargs):
    if not created:
        return
    if instance.role == User.Role.PATIENT:
        Patient.objects.get_or_create(user=instance)
    elif instance.role == User.Role.DOCTOR:
        Doctor.objects.get_or_create(
            user=instance,
            defaults={
                "specialization": "General Practice",
                "license_number": f"LIC-{instance.pk:05d}",
                "consultation_fee": 0,
                "available_days": "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday",
                "start_time": "09:00",
                "end_time": "17:00",
            },
        )
    elif instance.role == User.Role.COUNSELOR:
        Counselor.objects.get_or_create(
            user=instance,
            defaults={"specialization": "General Counseling", "bio": ""},
        )
    elif instance.role in {User.Role.NURSE, User.Role.RECEPTIONIST, User.Role.LAB_TECHNICIAN}:
        staff_role = {
            User.Role.NURSE: StaffProfile.Role.NURSE,
            User.Role.RECEPTIONIST: StaffProfile.Role.RECEPTIONIST,
            User.Role.LAB_TECHNICIAN: StaffProfile.Role.LAB_TECHNICIAN,
        }[instance.role]
        StaffProfile.objects.get_or_create(
            user=instance,
            defaults={"role": staff_role, "department": "General", "hourly_rate": 0},
        )
