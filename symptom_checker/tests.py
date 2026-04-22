from django.test import TestCase
from django.urls import reverse

from core.models import User

from .models import SymptomCheck


class SymptomCheckerTests(TestCase):
    def test_symptom_check_persists_assessment(self):
        user = User.objects.create_user(
            username="checker", password="SafePass123!", role=User.Role.PATIENT
        )
        self.client.login(username="checker", password="SafePass123!")
        response = self.client.post(reverse("symptom_checker:check"), {"symptoms": "fever, cough"})
        self.assertEqual(response.status_code, 200)
        check = SymptomCheck.objects.get(user=user)
        self.assertEqual(check.risk_level, SymptomCheck.RiskLevel.MODERATE)

    def test_symptom_check_flags_worsening_fever_headache_vomiting_as_high_risk(self):
        user = User.objects.create_user(
            username="checker2", password="SafePass123!", role=User.Role.PATIENT
        )
        self.client.login(username="checker2", password="SafePass123!")
        response = self.client.post(
            reverse("symptom_checker:check"),
            {
                "symptoms": "Fever, headaches, pain in the joints, lack of appetite. Started about three days ago. Headaches and fever getting more severe with vomiting and persistent nausea.",
                "onset_summary": "Started about three days ago",
                "progression": "worsening",
                "intensity": 9,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["risk_level"], SymptomCheck.RiskLevel.HIGH)
        self.assertTrue(payload["result"]["red_flags"])
        check = SymptomCheck.objects.get(user=user)
        self.assertEqual(check.progression, "worsening")

    def test_symptom_check_persists_structured_context(self):
        user = User.objects.create_user(
            username="checker3", password="SafePass123!", role=User.Role.PATIENT
        )
        self.client.login(username="checker3", password="SafePass123!")
        response = self.client.post(
            reverse("symptom_checker:check"),
            {
                "symptoms": "Fever and headache",
                "onset_summary": "Started two days ago",
                "progression": "worsening",
                "intensity": 8,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        check = SymptomCheck.objects.get(user=user)
        self.assertEqual(check.onset_summary, "Started two days ago")
        self.assertEqual(check.progression, "worsening")
        self.assertEqual(check.intensity, 8)
        self.assertEqual(check.structured_context["progression"], "worsening")

    def test_async_symptom_response_includes_thorough_assessment_fields(self):
        user = User.objects.create_user(
            username="checker4", password="SafePass123!", role=User.Role.PATIENT
        )
        self.client.login(username="checker4", password="SafePass123!")
        response = self.client.post(
            reverse("symptom_checker:check"),
            {
                "symptoms": "Fever, cough, chest discomfort, and fatigue for two days",
                "onset_summary": "Started two days ago",
                "progression": "worsening",
                "intensity": 7,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("clinical_rationale", payload["result"])
        self.assertIn("care_setting", payload["result"])
        self.assertIn("differential_diagnoses", payload["result"])
        self.assertIn("recommended_evaluation", payload["result"])
