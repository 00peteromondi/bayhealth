from django.test import TestCase
from django.urls import reverse

from core.models import User

from .models import Ambulance, AmbulanceRequest


class AmbulanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="emergency_patient", password="SafePass123!", role=User.Role.PATIENT
        )
        Ambulance.objects.create(
            vehicle_number="AMB-100",
            driver_name="Driver One",
            driver_phone="+254700000002",
            is_available=True,
        )

    def test_request_assigns_ambulance(self):
        self.client.login(username="emergency_patient", password="SafePass123!")
        response = self.client.post(
            reverse("ambulance:request"),
            {
                "latitude": "-1.286389",
                "longitude": "36.817223",
                "address": "CBD",
                "medical_notes": "Acute distress",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AmbulanceRequest.objects.count(), 1)
        self.assertIsNotNone(AmbulanceRequest.objects.first().assigned_ambulance)
