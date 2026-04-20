from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hospital.models import Appointment, Doctor, Hospital, HospitalAccess, HospitalInvitation, Patient, WalkInEncounter

from .models import AssistantAccessGrant, Notification, User


class CoreTests(TestCase):
    def test_registration_creates_role_profile_for_patient(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "patient1",
                "email": "patient@example.com",
                "first_name": "Jane",
                "last_name": "Doe",
                "phone": "+254700000001",
                "address": "Nairobi",
                "role": User.Role.PATIENT,
                "password": "SafePass123!",
                "confirm_password": "SafePass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/email_verification_sent.html")
        user = User.objects.get(username="patient1")
        self.assertTrue(hasattr(user, "patient"))
        self.assertIsNone(user.email_verified_at)

    def test_notifications_view_marks_items_read(self):
        user = User.objects.create_user(username="user1", password="SafePass123!")
        Notification.objects.create(user=user, title="Test", message="Body")
        self.client.login(username="user1", password="SafePass123!")
        self.client.get(reverse("notifications"))
        self.assertTrue(Notification.objects.get(user=user).is_read)

    def test_logout_route_accepts_get_without_405(self):
        user = User.objects.create_user(username="logoutuser", password="SafePass123!")
        self.client.login(username="logoutuser", password="SafePass123!")
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("home"))

    def test_login_blocks_unverified_email_addresses(self):
        User.objects.create_user(
            username="pendinguser",
            password="SafePass123!",
            email="pending@example.com",
        )
        response = self.client.post(
            reverse("login"),
            {
                "username": "pendinguser",
                "password": "SafePass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not verified yet")

    def test_email_verification_code_confirms_account(self):
        user = User.objects.create_user(
            username="verifyme",
            password="SafePass123!",
            email="verify@example.com",
            email_verification_code="1234567",
            email_verification_sent_at=timezone.now(),
        )
        response = self.client.post(
            reverse("email_verification_confirm"),
            {
                "email": "verify@example.com",
                "code": "1234567",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/email_verification_confirm.html")
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(user.email_verification_code, "")

    def test_registration_invitation_is_redeemed_only_after_email_verification(self):
        inviter = User.objects.create_user(
            username="inviter",
            password="SafePass123!",
            role=User.Role.ADMIN,
            email="inviter@example.com",
            email_verified_at=timezone.now(),
        )
        hospital = Hospital.objects.create(name="Invite Hospital", code="invite-hospital", owner=inviter)
        invitation = HospitalInvitation.objects.create(
            hospital=hospital,
            role=HospitalAccess.Role.DOCTOR,
            code="DOC-INVITE-123",
            created_by=inviter,
            invitee_name="Asha Doctor",
            invitee_email="asha@example.com",
        )

        response = self.client.post(
            reverse("register"),
            {
                "username": "ashadoctor",
                "email": "asha@example.com",
                "first_name": "Asha",
                "last_name": "Doctor",
                "phone": "+254700000011",
                "address": "Nairobi",
                "role": User.Role.DOCTOR,
                "invitation_code": invitation.code,
                "password": "SafePass123!",
                "confirm_password": "SafePass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/email_verification_sent.html")

        user = User.objects.get(username="ashadoctor")
        invitation.refresh_from_db()
        self.assertEqual(user.pending_hospital_invitation_id, invitation.id)
        self.assertFalse(HospitalAccess.objects.filter(user=user, hospital=hospital, role=HospitalAccess.Role.DOCTOR).exists())
        self.assertTrue(invitation.is_active)
        self.assertIsNone(invitation.redeemed_by)

        response = self.client.post(
            reverse("email_verification_confirm"),
            {
                "email": "asha@example.com",
                "code": user.email_verification_code,
            },
        )
        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        invitation.refresh_from_db()
        access = HospitalAccess.objects.get(user=user, hospital=hospital, role=HospitalAccess.Role.DOCTOR)
        self.assertEqual(access.status, HospitalAccess.Status.ACTIVE)
        self.assertEqual(invitation.redeemed_by_id, user.id)
        self.assertFalse(invitation.is_active)
        self.assertIsNone(user.pending_hospital_invitation)

    def test_unverified_user_redeem_keeps_invitation_pending_until_verification(self):
        hospital = Hospital.objects.create(name="Redeem Hospital", code="redeem-hospital")
        user = User.objects.create_user(
            username="pendingredeem",
            password="SafePass123!",
            role=User.Role.NURSE,
            email="pendingredeem@example.com",
            first_name="Pending",
            last_name="Redeem",
            email_verification_code="1234567",
            email_verification_sent_at=timezone.now(),
        )
        invitation = HospitalInvitation.objects.create(
            hospital=hospital,
            role=HospitalAccess.Role.NURSE,
            code="NURSE-INVITE-123",
            invitee_name="Pending Redeem",
            invitee_email="pendingredeem@example.com",
        )

        self.client.login(username="pendingredeem", password="SafePass123!")
        response = self.client.post(
            reverse("redeem_hospital_access"),
            {"invitation_code": invitation.code},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        invitation.refresh_from_db()
        self.assertEqual(user.pending_hospital_invitation_id, invitation.id)
        self.assertFalse(HospitalAccess.objects.filter(user=user, hospital=hospital, role=HospitalAccess.Role.NURSE).exists())
        self.assertTrue(invitation.is_active)
        self.assertIsNone(invitation.redeemed_by)

        response = self.client.post(
            reverse("email_verification_confirm"),
            {
                "email": "pendingredeem@example.com",
                "code": user.email_verification_code,
            },
        )
        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        invitation.refresh_from_db()
        self.assertTrue(HospitalAccess.objects.filter(user=user, hospital=hospital, role=HospitalAccess.Role.NURSE).exists())
        self.assertEqual(invitation.redeemed_by_id, user.id)
        self.assertFalse(invitation.is_active)
        self.assertIsNone(user.pending_hospital_invitation)

    def test_email_verification_locks_after_three_wrong_attempts(self):
        user = User.objects.create_user(
            username="verifylock",
            password="SafePass123!",
            email="verifylock@example.com",
            email_verification_code="1234567",
            email_verification_sent_at=timezone.now(),
        )
        for _ in range(3):
            response = self.client.post(
                reverse("email_verification_confirm"),
                {
                    "email": "verifylock@example.com",
                    "code": "7654321",
                },
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 429)
        user.refresh_from_db()
        self.assertEqual(user.email_verification_failed_count, 3)
        self.assertIsNotNone(user.email_verification_locked_until)

    def test_assistant_chat_restricts_patient_details_without_active_encounter(self):
        hospital = Hospital.objects.create(name="Bay General", code="bay-general")
        doctor_user = User.objects.create_user(
            username="doctor1",
            password="SafePass123!",
            role=User.Role.DOCTOR,
            first_name="Asha",
            last_name="Doctor",
        )
        patient_user = User.objects.create_user(
            username="patient2",
            password="SafePass123!",
            role=User.Role.PATIENT,
            first_name="Paul",
            last_name="Patient",
        )
        doctor = Doctor.objects.get(user=doctor_user)
        doctor.hospital = hospital
        doctor.specialization = "General Medicine"
        doctor.department = "Outpatient"
        doctor.license_number = "LIC-001"
        doctor.consultation_fee = "1500.00"
        doctor.available_days = "monday,tuesday,wednesday"
        doctor.start_time = "08:00"
        doctor.end_time = "17:00"
        doctor.save()
        patient = Patient.objects.get(user=patient_user)
        patient.hospital = hospital
        patient.save()
        HospitalAccess.objects.create(user=doctor_user, hospital=hospital, role=HospitalAccess.Role.DOCTOR, is_primary=True)
        Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            hospital=hospital,
            appointment_date="2026-03-26",
            appointment_time="09:00",
        )

        self.client.login(username="doctor1", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session.save()

        response = self.client.post(
            reverse("assistant_chat"),
            data='{"message":"Summarize this patient history."}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["can_view_patient_details"])
        self.assertIn("general care mode is active", payload["reply"].lower())

    def test_assistant_chat_allows_doctor_for_active_encounter(self):
        hospital = Hospital.objects.create(name="City Care", code="city-care")
        doctor_user = User.objects.create_user(
            username="doctor2",
            password="SafePass123!",
            role=User.Role.DOCTOR,
            first_name="Neema",
            last_name="Doctor",
        )
        patient_user = User.objects.create_user(
            username="patient3",
            password="SafePass123!",
            role=User.Role.PATIENT,
            first_name="Ruth",
            last_name="Patient",
        )
        doctor = Doctor.objects.get(user=doctor_user)
        doctor.hospital = hospital
        doctor.specialization = "General Medicine"
        doctor.department = "Outpatient"
        doctor.license_number = "LIC-002"
        doctor.consultation_fee = "1500.00"
        doctor.available_days = "monday,tuesday,wednesday"
        doctor.start_time = "08:00"
        doctor.end_time = "17:00"
        doctor.save()
        patient = Patient.objects.get(user=patient_user)
        patient.hospital = hospital
        patient.save()
        HospitalAccess.objects.create(user=doctor_user, hospital=hospital, role=HospitalAccess.Role.DOCTOR, is_primary=True)
        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            hospital=hospital,
            appointment_date="2026-03-26",
            appointment_time="09:00",
        )

        self.client.login(username="doctor2", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session["clinical_patient_id"] = patient.id
        session["clinical_appointment_id"] = appointment.id
        session.save()

        response = self.client.post(
            reverse("assistant_chat"),
            data='{"message":"Give me the current patient summary."}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["can_view_patient_details"])
        self.assertTrue(any("patient" in item.lower() for item in payload["signals"]))

    def test_assistant_chat_allows_approved_grant_for_nurse(self):
        hospital = Hospital.objects.create(name="Riverside", code="riverside")
        nurse_user = User.objects.create_user(
            username="nurse1",
            password="SafePass123!",
            role=User.Role.NURSE,
            first_name="Mara",
            last_name="Nurse",
        )
        patient_user = User.objects.create_user(
            username="patient4",
            password="SafePass123!",
            role=User.Role.PATIENT,
            first_name="John",
            last_name="Patient",
        )
        patient = Patient.objects.get(user=patient_user)
        patient.hospital = hospital
        patient.save()
        HospitalAccess.objects.create(user=nurse_user, hospital=hospital, role=HospitalAccess.Role.NURSE, is_primary=True)
        AssistantAccessGrant.objects.create(
            requester=nurse_user,
            patient_user=patient_user,
            hospital_id=hospital.id,
            approved_by=patient_user,
            reason="Ward nursing support",
        )

        self.client.login(username="nurse1", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session["clinical_patient_id"] = patient.id
        session.save()

        response = self.client.post(
            reverse("assistant_chat"),
            data='{"message":"What is the patient context?"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["can_view_patient_details"])

    def test_assistant_chat_allows_doctor_for_active_walk_in(self):
        hospital = Hospital.objects.create(name="Hooks Specialists", code="hooks-specialists")
        doctor_user = User.objects.create_user(
            username="doctorwalkin",
            password="SafePass123!",
            role=User.Role.DOCTOR,
            first_name="Dana",
            last_name="Doctor",
        )
        patient_user = User.objects.create_user(
            username="patientwalkin",
            password="SafePass123!",
            role=User.Role.PATIENT,
            first_name="Peter",
            last_name="Patient",
        )
        doctor = Doctor.objects.get(user=doctor_user)
        doctor.hospital = hospital
        doctor.specialization = "General Medicine"
        doctor.department = "Outpatient"
        doctor.license_number = "LIC-003"
        doctor.consultation_fee = "1500.00"
        doctor.available_days = "monday,tuesday,wednesday"
        doctor.start_time = "08:00"
        doctor.end_time = "17:00"
        doctor.save()
        patient = Patient.objects.get(user=patient_user)
        patient.hospital = hospital
        patient.save()
        HospitalAccess.objects.create(user=doctor_user, hospital=hospital, role=HospitalAccess.Role.DOCTOR, is_primary=True)
        encounter = WalkInEncounter.objects.create(
            patient=patient,
            hospital=hospital,
            attending_doctor=doctor,
            symptoms="Fever and vomiting",
            current_state="Weak",
            status=WalkInEncounter.Status.IN_CONSULTATION,
        )

        self.client.login(username="doctorwalkin", password="SafePass123!")
        session = self.client.session
        session["current_hospital_id"] = hospital.id
        session["clinical_patient_id"] = patient.id
        session["clinical_walk_in_id"] = encounter.id
        session.save()

        response = self.client.post(
            reverse("assistant_chat"),
            data='{"message":"Summarize the current patient context."}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["can_view_patient_details"])
