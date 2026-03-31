from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import User

from .models import AdvanceDirective, Appointment, CaregiverAccess, ConditionCatalog, Doctor, Hospital, HospitalAccess, LabTestRequest, MedicalRecord, Patient, PatientCondition, PatientFeedback, PharmacyTask, WalkInEncounter


class HospitalTests(TestCase):
    def setUp(self):
        self.patient_user = User.objects.create_user(
            username="patient", password="SafePass123!", role=User.Role.PATIENT
        )
        self.doctor_user = User.objects.create_user(
            username="doctor", password="SafePass123!", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.get(user=self.doctor_user)

    def test_patient_can_book_future_appointment(self):
        self.client.login(username="patient", password="SafePass123!")
        response = self.client.post(
            reverse("hospital:book_appointment"),
            {
                "doctor": self.doctor.pk,
                "appointment_date": timezone.localdate() + timedelta(days=1),
                "appointment_time": "10:00",
                "reason": "Routine check",
            },
        )
        self.assertRedirects(response, reverse("hospital:dashboard"))
        self.assertEqual(Appointment.objects.count(), 1)

    def test_cannot_book_past_appointment(self):
        self.client.login(username="patient", password="SafePass123!")
        response = self.client.post(
            reverse("hospital:book_appointment"),
            {
                "doctor": self.doctor.pk,
                "appointment_date": timezone.localdate() - timedelta(days=1),
                "appointment_time": "10:00",
                "reason": "Routine check",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Appointments cannot be booked in the past.")

    def test_medical_record_creates_condition_tracking(self):
        hospital = Hospital.objects.create(name="Test Hospital", code="test-hospital", owner=self.doctor_user)
        HospitalAccess.objects.create(user=self.doctor_user, hospital=hospital, role=HospitalAccess.Role.DOCTOR)
        HospitalAccess.objects.create(user=self.patient_user, hospital=hospital, role=HospitalAccess.Role.PATIENT)
        doctor = Doctor.objects.get(user=self.doctor_user)
        patient = Patient.objects.get(user=self.patient_user)

        MedicalRecord.objects.create(
            patient=patient,
            hospital=hospital,
            doctor=doctor,
            diagnosis="Hypertension; diabetes mellitus",
            notes="Chronic care follow-up.",
        )

        self.assertGreaterEqual(PatientCondition.objects.filter(patient=patient, hospital=hospital).count(), 2)
        self.assertTrue(ConditionCatalog.objects.filter(name__icontains="Hypertension").exists())

    def test_walk_in_flow_creates_triage_lab_and_pharmacy_handoffs(self):
        hospital = Hospital.objects.create(name="Hooks Specialists", code="hooks-specialists", owner=self.doctor_user)
        receptionist_user = User.objects.create_user(
            username="reception1", password="SafePass123!", role=User.Role.RECEPTIONIST
        )
        nurse_user = User.objects.create_user(
            username="nurse1", password="SafePass123!", role=User.Role.NURSE
        )
        HospitalAccess.objects.create(user=self.doctor_user, hospital=hospital, role=HospitalAccess.Role.DOCTOR, is_primary=True)
        HospitalAccess.objects.create(user=receptionist_user, hospital=hospital, role=HospitalAccess.Role.RECEPTIONIST, is_primary=True)
        HospitalAccess.objects.create(user=nurse_user, hospital=hospital, role=HospitalAccess.Role.NURSE, is_primary=True)

        self.client.login(username="reception1", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()
        response = self.client.post(
            reverse("hospital:intake_walk_in"),
            {
                "first_name": "Mina",
                "last_name": "Hook",
                "phone": "+254700111222",
                "date_of_birth": "1997-04-08",
                "gender": "female",
                "symptoms": "Fever, headache, persistent nausea",
                "current_state": "Walk-in patient feeling weak",
            },
        )
        self.assertRedirects(response, reverse("hospital:walk_in_hub"))
        encounter = WalkInEncounter.objects.get()
        self.assertEqual(encounter.status, WalkInEncounter.Status.WAITING_TRIAGE)

        self.client.logout()
        self.client.login(username="nurse1", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()
        response = self.client.post(
            reverse("hospital:triage_walk_in", args=[encounter.id]),
            {
                "symptoms": "Fever, headache, persistent nausea",
                "current_state": "Weak and febrile",
                "triage_notes": "Concern for worsening infection",
                "temperature_c": "39.2",
                "pulse_rate": 124,
                "respiratory_rate": 24,
                "systolic_bp": 102,
                "diastolic_bp": 68,
                "oxygen_saturation": 95,
            },
        )
        self.assertRedirects(response, reverse("hospital:walk_in_hub"))
        encounter.refresh_from_db()
        self.assertEqual(encounter.status, WalkInEncounter.Status.WAITING_DOCTOR)
        self.assertGreater(encounter.severity_index, 0)

        self.client.logout()
        self.client.login(username="doctor", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()
        response = self.client.post(
            reverse("hospital:consult_walk_in", args=[encounter.id]),
            {
                "diagnosis": "Malaria",
                "prescription": "Artemether/lumefantrine",
                "notes": "Needs urgent malaria test review",
                "lab_test_name": "Malaria test",
                "lab_priority": "urgent",
                "lab_notes": "Check smear urgently",
                "pharmacy_instructions": "Dispense antimalarials after result review",
                "refer_for_admission": "",
            },
        )
        self.assertRedirects(response, reverse("hospital:walk_in_hub"))
        encounter.refresh_from_db()
        self.assertEqual(encounter.status, WalkInEncounter.Status.AWAITING_LAB)
        self.assertEqual(LabTestRequest.objects.filter(walk_in_encounter=encounter).count(), 1)
        self.assertEqual(PharmacyTask.objects.filter(walk_in_encounter=encounter).count(), 1)

    def test_patient_can_save_feedback_caregiver_and_advance_directive(self):
        hospital = Hospital.objects.create(name="Patient Portal Hospital", code="patient-portal-hospital", owner=self.doctor_user)
        self.doctor.hospital = hospital
        self.doctor.save()
        HospitalAccess.objects.create(user=self.patient_user, hospital=hospital, role=HospitalAccess.Role.PATIENT, is_primary=True)
        HospitalAccess.objects.create(user=self.doctor_user, hospital=hospital, role=HospitalAccess.Role.DOCTOR, is_primary=True)
        self.client.login(username="patient", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()

        response = self.client.post(
            reverse("hospital:create_caregiver_access"),
            {
                "caregiver_name": "Jane Guardian",
                "caregiver_email": "jane@example.com",
                "relationship": "Sibling",
                "can_view_updates": "on",
                "note": "Helps coordinate home care.",
            },
        )
        self.assertRedirects(response, reverse("hospital:dashboard"))
        self.assertEqual(CaregiverAccess.objects.count(), 1)

        response = self.client.post(
            reverse("hospital:create_advance_directive"),
            {
                "directive_type": "living_will",
                "summary": "Comfort-focused care preferences documented.",
                "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("hospital:dashboard"))
        self.assertEqual(AdvanceDirective.objects.count(), 1)

        response = self.client.post(
            reverse("hospital:submit_patient_feedback"),
            {
                "doctor": self.doctor.pk,
                "rating": 5,
                "service_area": "Portal care",
                "comments": "The workflow was clear and easy to follow.",
            },
        )
        self.assertRedirects(response, reverse("hospital:dashboard"))
        self.assertEqual(PatientFeedback.objects.count(), 1)
