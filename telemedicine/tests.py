from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import User
from hospital.models import Appointment, Doctor

from .models import VideoConsultation


class TelemedicineTests(TestCase):
    def setUp(self):
        self.patient_user = User.objects.create_user(
            username="patient_tm", password="SafePass123!", role=User.Role.PATIENT
        )
        self.doctor_user = User.objects.create_user(
            username="doctor_tm", password="SafePass123!", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.get(user=self.doctor_user)
        self.appointment = Appointment.objects.create(
            patient=self.patient_user.patient,
            doctor=self.doctor,
            appointment_date=timezone.localdate() + timedelta(days=1),
            appointment_time="11:00",
            status=Appointment.Status.CONFIRMED,
        )

    def test_doctor_can_create_consultation_for_confirmed_appointment(self):
        self.client.login(username="doctor_tm", password="SafePass123!")
        response = self.client.post(
            reverse("telemedicine:create_consultation", args=[self.appointment.pk])
        )
        self.assertRedirects(response, reverse("telemedicine:dashboard"))
        self.assertTrue(VideoConsultation.objects.filter(appointment=self.appointment).exists())
