from django.test import TestCase
from django.urls import reverse

from core.models import User

from .models import MoodLog


class MentalHealthTests(TestCase):
    def test_patient_can_log_mood(self):
        user = User.objects.create_user(
            username="mh_patient", password="SafePass123!", role=User.Role.PATIENT
        )
        self.client.login(username="mh_patient", password="SafePass123!")
        response = self.client.post(reverse("mental_health:log_mood"), {"mood": "Calm", "notes": "Stable"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MoodLog.objects.filter(user=user).count(), 1)
