from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import User

from .models import AdvanceDirective, Allergy, Appointment, CaregiverAccess, ChronicCondition, ConditionCatalog, Doctor, FamilyMedicalHistory, Hospital, HospitalAccess, HospitalInvitation, Immunization, LabTestRequest, MedicalRecord, Patient, PatientCondition, PatientFeedback, PharmacyTask, WalkInEncounter


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

    def test_clinical_user_can_add_extended_patient_records(self):
        hospital = Hospital.objects.create(name="Extension Hospital", code="extension-hospital", owner=self.doctor_user)
        self.doctor.hospital = hospital
        self.doctor.save()
        patient = Patient.objects.get(user=self.patient_user)
        patient.hospital = hospital
        patient.save()
        HospitalAccess.objects.create(user=self.patient_user, hospital=hospital, role=HospitalAccess.Role.PATIENT, is_primary=True)
        HospitalAccess.objects.create(user=self.doctor_user, hospital=hospital, role=HospitalAccess.Role.DOCTOR, is_primary=True)

        self.client.login(username="doctor", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()

        response = self.client.post(
            reverse("hospital:create_allergy", args=[patient.id]),
            {
                "allergen": "Penicillin",
                "reaction_type": "Rash",
                "severity": "moderate",
                "notes": "Avoid beta-lactam antibiotics where possible.",
            },
        )
        self.assertRedirects(response, reverse("hospital:patient_detail", args=[patient.id]))
        self.assertEqual(Allergy.objects.filter(patient=patient).count(), 1)

        response = self.client.post(
            reverse("hospital:create_immunization", args=[patient.id]),
            {
                "vaccine_name": "Tetanus booster",
                "dose_number": "Booster",
                "administered_on": timezone.localdate(),
                "notes": "Routine update.",
            },
        )
        self.assertRedirects(response, reverse("hospital:patient_detail", args=[patient.id]))
        self.assertEqual(Immunization.objects.filter(patient=patient).count(), 1)

        response = self.client.post(
            reverse("hospital:create_chronic_condition", args=[patient.id]),
            {
                "name": "Hypertension",
                "primary_doctor": self.doctor.pk,
                "status": "active",
                "management_plan": "Blood pressure checks and medication adherence review.",
            },
        )
        self.assertRedirects(response, reverse("hospital:patient_detail", args=[patient.id]))
        self.assertEqual(ChronicCondition.objects.filter(patient=patient).count(), 1)

        response = self.client.post(
            reverse("hospital:create_family_history", args=[patient.id]),
            {
                "condition_name": "Diabetes mellitus",
                "relative": "Mother",
                "relationship": "First-degree relative",
                "notes": "Diagnosed in mid-life.",
            },
        )
        self.assertRedirects(response, reverse("hospital:patient_detail", args=[patient.id]))
        self.assertEqual(FamilyMedicalHistory.objects.filter(patient=patient).count(), 1)

    def test_duplicate_active_invitation_is_blocked_for_same_email_and_role(self):
        hospital = Hospital.objects.create(name="Invite Guard Hospital", code="invite-guard-hospital", owner=self.doctor_user)
        HospitalAccess.objects.create(user=self.doctor_user, hospital=hospital, role=HospitalAccess.Role.OWNER, is_primary=True)
        HospitalInvitation.objects.create(
            hospital=hospital,
            role=HospitalAccess.Role.DOCTOR,
            code="DOC-LOCK-001",
            created_by=self.doctor_user,
            invitee_name="Asha Doctor",
            invitee_email="asha@example.com",
        )

        self.client.login(username="doctor", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()

        response = self.client.post(
            reverse("hospital:create_invitation"),
            {
                "role": HospitalAccess.Role.DOCTOR,
                "invitee_name": "Asha Doctor",
                "invitee_email": "asha@example.com",
                "note": "Duplicate should be blocked.",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("already exists", payload["message"])
        self.assertEqual(HospitalInvitation.objects.filter(hospital=hospital).count(), 1)

    def test_invitation_can_be_revoked_and_reactivated_without_redeeming(self):
        hospital = Hospital.objects.create(name="Manage Invite Hospital", code="manage-invite-hospital", owner=self.doctor_user)
        HospitalAccess.objects.create(user=self.doctor_user, hospital=hospital, role=HospitalAccess.Role.OWNER, is_primary=True)
        invitation = HospitalInvitation.objects.create(
            hospital=hospital,
            role=HospitalAccess.Role.NURSE,
            code="NURSE-OPEN-01",
            created_by=self.doctor_user,
            invitee_name="Pending Nurse",
            invitee_email="pending.nurse@example.com",
        )

        self.client.login(username="doctor", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()

        revoke_response = self.client.post(
            reverse("hospital:manage_invitation", args=[invitation.id]),
            {"action": "revoke"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(revoke_response.status_code, 200)
        invitation.refresh_from_db()
        self.assertFalse(invitation.is_active)
        self.assertEqual(invitation.revoked_by_id, self.doctor_user.id)
        self.assertIsNotNone(invitation.revoked_at)

        reactivate_response = self.client.post(
            reverse("hospital:manage_invitation", args=[invitation.id]),
            {"action": "reactivate"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(reactivate_response.status_code, 200)
        invitation.refresh_from_db()
        self.assertTrue(invitation.is_active)
        self.assertIsNone(invitation.revoked_by)
        self.assertIsNone(invitation.revoked_at)
