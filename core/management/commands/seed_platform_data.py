from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from ambulance.models import Ambulance, AmbulanceRequest
from core.models import User
from hospital.billing import (
    ensure_admission_bill,
    ensure_bed_transfer_bill,
    ensure_consultation_bill,
    ensure_discharge_bill,
    ensure_lab_bill,
    ensure_pharmacy_bill,
    ensure_walk_in_registration_bill,
    ensure_walk_in_triage_bill,
)
from hospital.models import (
    Admission,
    AdvanceDirective,
    Appointment,
    Bed,
    BedTransfer,
    CarePlan,
    CaregiverAccess,
    ConditionCatalog,
    Doctor,
    DoctorTask,
    DischargeSummary,
    Hospital,
    HospitalAccess,
    InternalReferral,
    LabTestRequest,
    LabTestResult,
    MedicalRecord,
    OperatingRoom,
    Patient,
    PatientCondition,
    PatientFeedback,
    PharmacyTask,
    QueueTicket,
    ShiftHandover,
    ShiftAssignment,
    SupplyRequest,
    SurgicalCase,
    VitalSign,
    WalkInEncounter,
    WalkInEvent,
    Ward,
    LabQualityControlLog,
    EmergencyIncident,
)
from mental_health.models import MoodLog, TherapySession, WellnessResource
from pharmacy.models import Medicine, Order, OrderItem
from telemedicine.models import Prescription, VideoConsultation


PASSWORD = "ChangeMeNow123!"


class Command(BaseCommand):
    help = "Seed rich BayAfya demo data with deep Hooks Specialists coverage."

    def handle(self, *args, **options):
        now = timezone.now()
        admin = self._user("admin", "Platform", "Admin", User.Role.ADMIN, "admin@bayafya.local", dob=date(1987, 5, 9), is_staff=True, is_superuser=True)

        bay_central = self._hospital("bay-central", "Bay Central Hospital", "Main clinical campus", admin)
        bay_east = self._hospital("bay-east", "Bay East Hospital", "Satellite care campus", admin)
        hooks = self._hospital("hooks-specialists", "Hooks Specialists", "Specialist and referral campus", admin)
        self._access(admin, bay_central, HospitalAccess.Role.OWNER, primary=True)
        self._access(admin, bay_east, HospitalAccess.Role.ADMIN)
        self._access(admin, hooks, HospitalAccess.Role.ADMIN)

        staff = self._seed_staff(hooks)
        wards, rooms = self._seed_capacity(hooks)
        self._seed_reference_data()
        patients = self._seed_patients(hooks)
        self._seed_activity(hooks, staff, wards, rooms, patients, now)
        self._seed_cross_hospital_baseline(bay_central, bay_east, staff["doctor"][0], now)

        self.stdout.write(self.style.SUCCESS("Hooks Specialists and baseline BayAfya seed data created."))
        self.stdout.write("Password for all seeded users: ChangeMeNow123!")
        for username in [
            "owner_demo", "owner1_demo", "admin_demo", "admin1_demo",
            "doctor_demo", "doctor1_demo", "nurse_demo", "nurse1_demo",
            "receptionist_demo", "receptionist1_demo", "lab_technician_demo", "lab_technician1_demo",
            "pharmacist_demo", "pharmacist1_demo", "counselor_demo", "counselor1_demo",
            "emergency_operator_demo", "emergency_operator1_demo",
        ]:
            self.stdout.write(f" - {username}")

    def _user(self, username, first_name, last_name, role, email, *, dob=None, is_staff=False, is_superuser=False):
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={"first_name": first_name, "last_name": last_name, "role": role, "email": email, "date_of_birth": dob},
        )
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.email = email
        user.date_of_birth = dob
        user.is_staff = is_staff or role == User.Role.ADMIN
        user.is_superuser = is_superuser
        user.phone = user.phone or f"+2547{700000000 + user.pk if user.pk else 700000000}"
        user.set_password(PASSWORD)
        user.save()
        return user

    def _hospital(self, code, name, address, owner):
        hospital, _ = Hospital.objects.get_or_create(code=code, defaults={"name": name, "address": address, "owner": owner})
        hospital.name = name
        hospital.address = address
        hospital.owner = owner
        hospital.is_active = True
        hospital.save()
        return hospital

    def _access(self, user, hospital, role, primary=False):
        access, _ = HospitalAccess.objects.update_or_create(
            user=user,
            hospital=hospital,
            role=role,
            defaults={"is_primary": primary, "status": HospitalAccess.Status.ACTIVE},
        )
        access.is_primary = primary
        access.save()
        return access

    def _seed_staff(self, hooks):
        specs = {
            "owner": [("owner_demo", "Captain", "Hook", User.Role.ADMIN), ("owner1_demo", "Martha", "Hook", User.Role.ADMIN)],
            "admin": [("admin_demo", "Harriet", "Limo", User.Role.ADMIN), ("admin1_demo", "James", "Maina", User.Role.ADMIN)],
            "doctor": [("doctor_demo", "Amina", "Otieno", User.Role.DOCTOR), ("doctor1_demo", "Samson", "Kariuki", User.Role.DOCTOR)],
            "nurse": [("nurse_demo", "Lydia", "Naliaka", User.Role.NURSE), ("nurse1_demo", "Brenda", "Muthoni", User.Role.NURSE)],
            "receptionist": [("receptionist_demo", "Mercy", "Achieng", User.Role.RECEPTIONIST), ("receptionist1_demo", "Kevin", "Barasa", User.Role.RECEPTIONIST)],
            "lab_technician": [("lab_technician_demo", "Nixon", "Mwenda", User.Role.LAB_TECHNICIAN), ("lab_technician1_demo", "Caren", "Kendi", User.Role.LAB_TECHNICIAN)],
            "pharmacist": [("pharmacist_demo", "Diana", "Chebet", User.Role.PHARMACIST), ("pharmacist1_demo", "Tom", "Mutua", User.Role.PHARMACIST)],
            "counselor": [("counselor_demo", "Faith", "Wambui", User.Role.COUNSELOR), ("counselor1_demo", "Ian", "Okello", User.Role.COUNSELOR)],
            "emergency_operator": [("emergency_operator_demo", "Victor", "Koech", User.Role.EMERGENCY_OPERATOR), ("emergency_operator1_demo", "Sharon", "Mumo", User.Role.EMERGENCY_OPERATOR)],
        }
        access_map = {
            "owner": HospitalAccess.Role.OWNER,
            "admin": HospitalAccess.Role.ADMIN,
            "doctor": HospitalAccess.Role.DOCTOR,
            "nurse": HospitalAccess.Role.NURSE,
            "receptionist": HospitalAccess.Role.RECEPTIONIST,
            "lab_technician": HospitalAccess.Role.LAB_TECHNICIAN,
            "pharmacist": HospitalAccess.Role.PHARMACIST,
            "counselor": HospitalAccess.Role.COUNSELOR,
            "emergency_operator": HospitalAccess.Role.EMERGENCY_OPERATOR,
        }
        seeded = {}
        for bucket, rows in specs.items():
            seeded[bucket] = []
            for index, (username, first_name, last_name, role) in enumerate(rows):
                user = self._user(username, first_name, last_name, role, f"{username}@bayafya.local", dob=date(1983 + index, 2 + index, 4 + index))
                self._access(user, hooks, access_map[bucket], primary=True)
                if role == User.Role.DOCTOR:
                    doctor = user.doctor
                    doctor.hospital = hooks
                    doctor.specialization = "Internal Medicine" if index == 0 else "General Surgery"
                    doctor.department = "Specialist Clinic" if index == 0 else "Theatre"
                    doctor.consultation_fee = Decimal("95.00") if index == 0 else Decimal("130.00")
                    doctor.available_days = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday"
                    doctor.start_time = time(8, 0)
                    doctor.end_time = time(17, 0)
                    doctor.save()
                    seeded[bucket].append(doctor)
                elif role in {User.Role.NURSE, User.Role.RECEPTIONIST, User.Role.LAB_TECHNICIAN}:
                    profile = user.staff_profile
                    profile.hospital = hooks
                    profile.department = bucket.replace("_", " ").title()
                    profile.shift_start = time(7, 0)
                    profile.shift_end = time(16, 0)
                    profile.hourly_rate = Decimal("18.00") if role == User.Role.NURSE else Decimal("12.00")
                    profile.save()
                    seeded[bucket].append(profile)
                elif role == User.Role.COUNSELOR:
                    counselor = user.counselor
                    counselor.specialization = "Trauma support" if index == 0 else "Family counseling"
                    counselor.save()
                    seeded[bucket].append(counselor)
                else:
                    seeded[bucket].append(user)
        return seeded

    def _seed_capacity(self, hooks):
        wards = {}
        for name, ward_type, capacity in [
            ("Hooks Emergency Ward", Ward.WardType.EMERGENCY, 10),
            ("Hooks ICU", Ward.WardType.ICU, 6),
            ("Hooks Medical Ward", Ward.WardType.GENERAL, 18),
            ("Hooks Pediatric Ward", Ward.WardType.PEDIATRIC, 8),
        ]:
            ward, _ = Ward.objects.get_or_create(hospital=hooks, name=name, defaults={"ward_type": ward_type, "location": name, "capacity": capacity})
            ward.ward_type = ward_type
            ward.capacity = capacity
            ward.location = name
            ward.save()
            wards[name] = ward
            for bed_no in range(1, 7):
                Bed.objects.get_or_create(hospital=hooks, ward=ward, bed_number=f"{ward_type[:3].upper()}-{bed_no}")
        rooms = {}
        for number, name, ward in [("OR-A", "Main Theatre", wards["Hooks Medical Ward"]), ("OR-B", "Emergency Theatre", wards["Hooks Emergency Ward"])]:
            room, _ = OperatingRoom.objects.get_or_create(hospital=hooks, room_number=number, defaults={"name": name, "ward": ward})
            room.name = name
            room.ward = ward
            room.is_available = True
            room.save()
            rooms[number] = room
        return wards, rooms

    def _seed_reference_data(self):
        for name, code in [("Hypertension", "I10"), ("Asthma", "J45"), ("Migraine", "G43"), ("Gallstones", "K80"), ("Pneumonia", "J18"), ("Diabetes", "E11")]:
            ConditionCatalog.objects.get_or_create(name=name, defaults={"icd10_code": code, "description": f"{name} seed reference."})
        for name, price in [("Paracetamol 500mg", Decimal("4.00")), ("Amoxicillin 500mg", Decimal("12.50")), ("Metformin 500mg", Decimal("9.80")), ("Salbutamol inhaler", Decimal("22.00"))]:
            Medicine.objects.update_or_create(name=name, defaults={"description": f"{name} stock item", "price": price, "stock_quantity": 120, "requires_prescription": True})
        Ambulance.objects.update_or_create(vehicle_number="AMB-001", defaults={"driver_name": "Joseph Kariuki", "driver_phone": "+254700000001", "is_available": True})
        WellnessResource.objects.get_or_create(title="Breathing reset exercise", defaults={"description": "Grounding guide", "resource_type": "exercise"})

    def _seed_patients(self, hooks):
        specs = [
            ("hooks_patient_01", "Miriam", "Njeri", date(1991, 4, 12), "Migraine and dehydration"),
            ("hooks_patient_02", "David", "Mwangi", date(1978, 11, 2), "Type 2 diabetes mellitus"),
            ("hooks_patient_03", "Aisha", "Karemi", date(2004, 7, 28), "Iron deficiency anemia"),
            ("hooks_patient_04", "Peter", "Odhiambo", date(1968, 1, 19), "Hypertension and chronic kidney disease"),
            ("hooks_patient_05", "Lydia", "Atieno", date(2019, 8, 5), "Bronchial asthma"),
            ("hooks_patient_06", "Joseph", "Mutiso", date(1985, 6, 14), "Lumbar disc disease"),
            ("hooks_patient_07", "Hilda", "Wairimu", date(1959, 3, 22), "Osteoarthritis"),
            ("hooks_patient_08", "Brian", "Kiptoo", date(1996, 9, 30), "Peptic ulcer disease"),
            ("hooks_patient_09", "Sarah", "Chebet", date(1988, 12, 9), "Gallstones"),
            ("hooks_patient_10", "Noah", "Kamau", date(2025, 3, 25), "Neonatal jaundice"),
            ("hooks_patient_11", "Janet", "Makena", date(1982, 2, 16), "Pneumonia"),
            ("hooks_patient_12", "Collins", "Muriuki", date(1971, 10, 3), "Heart failure review"),
        ]
        patients = []
        for index, (username, first_name, last_name, dob, history) in enumerate(specs):
            user = self._user(username, first_name, last_name, User.Role.PATIENT, f"{username}@bayafya.local", dob=dob)
            patient = user.patient
            patient.hospital = hooks
            patient.medical_history = history
            patient.insurance_provider = "BayAfya Community Cover"
            patient.insurance_number = f"HKS-{user.pk:06d}"
            patient.emergency_contact_name = f"{first_name} Contact"
            patient.emergency_contact_phone = f"+2547{720000000 + index:09d}"
            patient.save()
            self._access(user, hooks, HospitalAccess.Role.PATIENT, primary=index == 0)
            patients.append(patient)
        return patients

    def _seed_activity(self, hooks, staff, wards, rooms, patients, now):
        doctors = staff["doctor"]
        nurses = staff["nurse"]
        receptionists = staff["receptionist"]
        labs = staff["lab_technician"]
        pharmacists = staff["pharmacist"]
        counselors = staff["counselor"]
        emergency_operators = staff["emergency_operator"]

        for profile in nurses + receptionists + labs:
            for days_back in range(5):
                ShiftAssignment.objects.get_or_create(
                    staff=profile,
                    hospital=hooks,
                    shift_date=(now - timedelta(days=days_back)).date(),
                    start_time=time(7, 0),
                    end_time=time(16, 0),
                )

        for index, nurse in enumerate(nurses):
            ShiftHandover.objects.get_or_create(
                hospital=hooks,
                staff=nurse,
                shift_date=(now - timedelta(days=index)).date(),
                defaults={
                    "summary": f"Seeded handover for {nurse.user.get_full_name()}: monitor admissions, repeat vitals, and close pending bedside tasks.",
                    "risks": "Escalate fever, oxygen desaturation, or unstable pain control promptly.",
                    "pending_tasks": "Repeat vitals, dressing review, medication administration, and discharge preparation.",
                },
            )

        supply_request_users = [
            receptionists[0].user,
            emergency_operators[0],
            labs[0].user,
            pharmacists[0],
        ]
        for index, (department, item_name, quantity, priority) in enumerate([
            ("Reception", "Registration forms and wristbands", 80, SupplyRequest.Priority.ROUTINE),
            ("Emergency", "IV fluids and trauma sets", 24, SupplyRequest.Priority.CRITICAL),
            ("Laboratory", "CBC reagent packs", 12, SupplyRequest.Priority.URGENT),
            ("Pharmacy", "Controlled-drug lock box seals", 40, SupplyRequest.Priority.ROUTINE),
        ]):
            SupplyRequest.objects.get_or_create(
                hospital=hooks,
                department=department,
                item_name=item_name,
                defaults={
                    "requested_by": supply_request_users[index],
                    "quantity": quantity,
                    "priority": priority,
                    "status": [SupplyRequest.Status.OPEN, SupplyRequest.Status.IN_REVIEW, SupplyRequest.Status.OPEN, SupplyRequest.Status.FULFILLED][index],
                    "notes": "Seeded operational supply request for dashboard testing.",
                    "fulfilled_at": now - timedelta(hours=6) if index == 3 else None,
                },
            )

        for index, tech in enumerate(labs):
            LabQualityControlLog.objects.get_or_create(
                hospital=hooks,
                recorded_by=tech,
                analyzer_name=f"Analyzer-{index + 1}",
                reagent_lot=f"HKS-QC-{index + 1:03d}",
                defaults={
                    "qc_status": LabQualityControlLog.Status.REVIEW if index == 0 else LabQualityControlLog.Status.PASS,
                    "notes": "Seeded QC log for analyzer readiness and reagent verification.",
                },
            )

        for index, patient in enumerate(patients):
            doctor = doctors[index % 2]
            record = MedicalRecord.objects.create(
                patient=patient,
                hospital=hooks,
                doctor=doctor,
                diagnosis=patient.medical_history,
                prescription="Continue current treatment plan and return for review.",
                notes="Backdated seeded specialist follow-up.",
            )
            MedicalRecord.objects.filter(pk=record.pk).update(created_at=now - timedelta(days=index + 10))
            PatientCondition.objects.get_or_create(
                patient=patient,
                hospital=hooks,
                medical_record=record,
                recorded_by=doctor,
                condition_name=patient.medical_history.split(";")[0][:180],
                defaults={"diagnosed_at": (now - timedelta(days=index + 10)).date(), "notes": "Seeded condition linkage."},
            )
            appointment, _ = Appointment.objects.update_or_create(
                doctor=doctor,
                appointment_date=(now + timedelta(days=(index % 4) + 1)).date(),
                appointment_time=time(9 + (index % 6), 0),
                defaults={
                    "patient": patient,
                    "hospital": hooks,
                    "status": [Appointment.Status.CONFIRMED, Appointment.Status.PENDING, Appointment.Status.COMPLETED, Appointment.Status.CANCELLED][index % 4],
                    "reason": f"Specialist follow-up for {patient.medical_history.lower()}",
                },
            )
            Appointment.objects.filter(pk=appointment.pk).update(created_at=now - timedelta(days=index + 2))
            if appointment.status in {Appointment.Status.CONFIRMED, Appointment.Status.COMPLETED}:
                QueueTicket.objects.get_or_create(
                    appointment=appointment,
                    defaults={"hospital": hooks, "ticket_number": f"HKS-Q-{index + 1:03d}", "estimated_wait_minutes": 15 + index, "status": QueueTicket.Status.QUEUED},
                )
                ensure_consultation_bill(patient=patient, hospital=hooks, doctor=doctor, appointment=appointment)
            VitalSign.objects.create(
                patient=patient,
                hospital=hooks,
                recorded_by=nurses[index % 2].user,
                temperature_c=Decimal("36.8"),
                pulse_rate=76 + index,
                respiratory_rate=18,
                systolic_bp=120 + index,
                diastolic_bp=78,
                oxygen_saturation=98,
                notes="Seeded observation set.",
            )
            if index < 6:
                therapy = TherapySession.objects.create(
                    patient=patient.user,
                    counselor=counselors[index % 2],
                    scheduled_time=now - timedelta(days=index + 3),
                    status=TherapySession.Status.COMPLETED if index % 2 == 0 else TherapySession.Status.SCHEDULED,
                    notes="Seeded wellbeing follow-up.",
                )
                TherapySession.objects.filter(pk=therapy.pk).update(created_at=now - timedelta(days=index + 4))
                for mood in ["Steady", "Anxious"]:
                    log = MoodLog.objects.create(user=patient.user, mood=mood, notes="Seeded mood log.")
                    MoodLog.objects.filter(pk=log.pk).update(logged_at=now - timedelta(days=index + 1))
            if index < 4 and appointment.status in {Appointment.Status.CONFIRMED, Appointment.Status.COMPLETED}:
                consultation, _ = VideoConsultation.objects.get_or_create(appointment=appointment)
                consultation.status = VideoConsultation.Status.COMPLETED if index % 2 else VideoConsultation.Status.SCHEDULED
                consultation.start_time = now - timedelta(hours=2)
                consultation.end_time = now - timedelta(hours=1) if consultation.status == VideoConsultation.Status.COMPLETED else None
                consultation.save()
                ensure_consultation_bill(patient=patient, hospital=hooks, doctor=doctor, appointment=appointment)
                Prescription.objects.get_or_create(consultation=consultation, doctor=doctor, patient=patient, defaults={"medications": "Paracetamol 500mg", "instructions": "Take one tablet every 8 hours as needed."})
            if index < 6:
                CarePlan.objects.get_or_create(
                    patient=patient,
                    hospital=hooks,
                    doctor=doctor,
                    title=f"Specialist care plan {index + 1}",
                    defaults={
                        "goals": f"Stabilize and monitor {patient.medical_history.lower()} while improving functional recovery.",
                        "milestones": "Review symptoms, repeat vitals, update medication plan, and confirm follow-up completion.",
                        "timeline": "2-6 weeks",
                        "care_team": "Nurse follow-up, lab review, pharmacist counseling",
                        "status": CarePlan.Status.ACTIVE,
                    },
                )
            if index < 4:
                CaregiverAccess.objects.get_or_create(
                    patient=patient,
                    hospital=hooks,
                    caregiver_name=f"{patient.user.first_name} Family Contact",
                    defaults={
                        "caregiver_email": f"caregiver{index + 1}@bayafya.local",
                        "relationship": "Family member",
                        "can_view_updates": True,
                        "can_view_billing": index % 2 == 0,
                        "note": "Seeded caregiver visibility for patient-portal testing.",
                    },
                )
                AdvanceDirective.objects.get_or_create(
                    patient=patient,
                    hospital=hooks,
                    directive_type=AdvanceDirective.DirectiveType.LIVING_WILL if index % 2 == 0 else AdvanceDirective.DirectiveType.OTHER,
                    defaults={
                        "summary": "Seeded continuity-of-care directive for emergency and inpatient review.",
                        "is_active": True,
                    },
                )
                PatientFeedback.objects.get_or_create(
                    patient=patient,
                    hospital=hooks,
                    doctor=doctor,
                    service_area="Outpatient care",
                    defaults={
                        "rating": 4 if index % 2 == 0 else 5,
                        "comments": "Seeded patient feedback entry covering satisfaction, clarity, and wait times.",
                    },
                )
            if index < 8:
                DoctorTask.objects.get_or_create(
                    hospital=hooks,
                    patient=patient,
                    created_by=doctor.user,
                    assigned_to=nurses[index % 2].user,
                    title=f"Follow up vitals for {patient.user.first_name}",
                    defaults={
                        "details": "Repeat vitals, confirm symptom response, and escalate abnormal findings to the doctor.",
                        "priority": DoctorTask.Priority.HIGH if index % 3 == 0 else DoctorTask.Priority.MEDIUM,
                        "status": DoctorTask.Status.OPEN,
                        "due_at": now + timedelta(hours=6 + index),
                    },
                )
            if index < 5:
                order = Order.objects.create(patient=patient, total_amount=Decimal("16.50"), status=Order.Status.CONFIRMED if index % 2 else Order.Status.DELIVERED)
                OrderItem.objects.get_or_create(order=order, medicine=Medicine.objects.get(name="Paracetamol 500mg"), defaults={"quantity": 2, "price": Decimal("4.00")})
                OrderItem.objects.get_or_create(order=order, medicine=Medicine.objects.get(name="Amoxicillin 500mg"), defaults={"quantity": 1, "price": Decimal("12.50")})
            if index < 3:
                request = AmbulanceRequest.objects.create(user=patient.user, latitude=Decimal("-1.286389"), longitude=Decimal("36.817223"), address=f"Hooks zone {index + 1}", medical_notes="Seeded emergency request.", status=[AmbulanceRequest.Status.PENDING, AmbulanceRequest.Status.EN_ROUTE, AmbulanceRequest.Status.COMPLETED][index], assigned_ambulance=Ambulance.objects.first())
                AmbulanceRequest.objects.filter(pk=request.pk).update(created_at=now - timedelta(days=index + 1))
                EmergencyIncident.objects.get_or_create(
                    hospital=hooks,
                    linked_request=request,
                    title=f"Emergency dispatch {index + 1}",
                    defaults={
                        "created_by": emergency_operators[index % 2],
                        "category": "Emergency call triage",
                        "severity": [EmergencyIncident.Severity.CRITICAL, EmergencyIncident.Severity.HIGH, EmergencyIncident.Severity.MODERATE][index],
                        "status": [EmergencyIncident.Status.ACTIVE, EmergencyIncident.Status.DISPATCHED, EmergencyIncident.Status.RESOLVED][index],
                        "location": request.address,
                        "notes": "Seeded emergency incident linked to ambulance dispatch flow.",
                        "resolved_at": now - timedelta(hours=2) if index == 2 else None,
                    },
                )

        # Walk-in scenarios
        walk_in_specs = [
            (patients[0], WalkInEncounter.Status.COMPLETED, 54, False, "Severe headache with vomiting for three days."),
            (patients[1], WalkInEncounter.Status.WAITING_DOCTOR, 76, False, "Uncontrolled blood sugar with dizziness."),
            (patients[2], WalkInEncounter.Status.AWAITING_LAB, 61, False, "Fatigue and exertional shortness of breath."),
            (patients[8], WalkInEncounter.Status.AWAITING_PHARMACY, 58, False, "Biliary colic after meals."),
            (patients[10], WalkInEncounter.Status.ADMISSION_REVIEW, 88, True, "High fever, dehydration, and worsening cough."),
        ]
        for index, (patient, status, severity_index, critical, symptoms) in enumerate(walk_in_specs):
            encounter, _ = WalkInEncounter.objects.update_or_create(
                ticket_number=f"HKS-WI-{index + 1:03d}",
                defaults={
                    "patient": patient,
                    "hospital": hooks,
                    "registered_by": receptionists[index % 2].user,
                    "triaged_by": nurses[index % 2].user,
                    "attending_doctor": doctors[index % 2],
                    "queue_position": index + 1,
                    "symptoms": symptoms,
                    "current_state": "Seeded current-state note.",
                    "triage_notes": "Seeded triage note.",
                    "doctor_notes": "Seeded doctor note.",
                    "severity_index": severity_index,
                    "severity_band": WalkInEncounter.SeverityBand.CRITICAL if critical else WalkInEncounter.SeverityBand.HIGH if severity_index >= 70 else WalkInEncounter.SeverityBand.MODERATE,
                    "is_critical": critical,
                    "status": status,
                },
            )
            WalkInEncounter.objects.filter(pk=encounter.pk).update(arrived_at=now - timedelta(hours=6 + index), triaged_at=now - timedelta(hours=5 + index), consultation_started_at=now - timedelta(hours=4 + index), consultation_completed_at=now - timedelta(hours=3 + index), completed_at=now - timedelta(hours=2 + index) if status == WalkInEncounter.Status.COMPLETED else None)
            WalkInEvent.objects.create(encounter=encounter, actor=encounter.registered_by, stage="intake", note="Walk-in registered at the reception desk.")
            WalkInEvent.objects.create(encounter=encounter, actor=encounter.triaged_by, stage="triage", note="Triage completed and severity recorded.")
            ensure_walk_in_registration_bill(encounter=encounter)
            ensure_walk_in_triage_bill(encounter=encounter)
            record = MedicalRecord.objects.create(patient=patient, hospital=hooks, doctor=encounter.attending_doctor, diagnosis=patient.medical_history, prescription="Seeded walk-in prescription.", notes="Seeded walk-in consultation note.")
            encounter.medical_record = record
            encounter.save(update_fields=["medical_record"])
            ensure_consultation_bill(patient=patient, hospital=hooks, doctor=encounter.attending_doctor, walk_in_encounter=encounter, medical_record=record)
            if status in {WalkInEncounter.Status.AWAITING_LAB, WalkInEncounter.Status.ADMISSION_REVIEW}:
                lab_request = LabTestRequest.objects.create(patient=patient, hospital=hooks, walk_in_encounter=encounter, requested_by=encounter.attending_doctor, test_name="CBC", priority="urgent", notes="Seeded doctor-ordered lab.")
                ensure_lab_bill(request=lab_request)
                if status == WalkInEncounter.Status.ADMISSION_REVIEW:
                    result = LabTestResult.objects.create(request=lab_request, recorded_by=labs[0], reviewed_by=encounter.attending_doctor, result_summary="Seeded abnormal result requiring escalation.")
                    LabTestResult.objects.filter(pk=result.pk).update(completed_at=now - timedelta(hours=1))
            if status in {WalkInEncounter.Status.AWAITING_PHARMACY, WalkInEncounter.Status.COMPLETED}:
                task = PharmacyTask.objects.create(patient=patient, hospital=hooks, walk_in_encounter=encounter, medical_record=record, requested_by=encounter.attending_doctor.user, completed_by=pharmacists[0] if status == WalkInEncounter.Status.COMPLETED else None, instructions="Paracetamol 500mg and Amoxicillin 500mg", status=PharmacyTask.Status.COMPLETED if status == WalkInEncounter.Status.COMPLETED else PharmacyTask.Status.PENDING, completed_at=now - timedelta(minutes=30) if status == WalkInEncounter.Status.COMPLETED else None)
                ensure_pharmacy_bill(task=task)
            if index < 3:
                InternalReferral.objects.get_or_create(
                    patient=patient,
                    source_hospital=hooks,
                    target_hospital=hooks,
                    referring_doctor=encounter.attending_doctor,
                    target_doctor=doctors[(index + 1) % 2],
                    specialty="Second opinion",
                    reason="Review complex walk-in presentation and confirm management plan.",
                    defaults={
                        "priority": InternalReferral.Priority.URGENT if critical else InternalReferral.Priority.ROUTINE,
                        "status": InternalReferral.Status.PENDING,
                        "due_at": now + timedelta(hours=4 + index),
                    },
                )

        # Admissions
        med_bed = wards["Hooks Medical Ward"].beds.order_by("bed_number")[0]
        icu_bed = wards["Hooks ICU"].beds.order_by("bed_number")[0]
        for patient, doctor, bed, reason, status in [
            (patients[3], doctors[0], med_bed, "Renal monitoring and pressure stabilization", Admission.Status.ACTIVE),
            (patients[10], doctors[1], icu_bed, "Respiratory support and close observation", Admission.Status.DISCHARGED),
        ]:
            admission = Admission.objects.create(patient=patient, hospital=hooks, attending_doctor=doctor, ward=bed.ward, bed=bed, admission_reason=reason, status=status, notes="Seeded admission.")
            Admission.objects.filter(pk=admission.pk).update(admitted_at=now - timedelta(days=5), discharged_at=now - timedelta(days=1) if status == Admission.Status.DISCHARGED else None)
            bed.is_occupied = status == Admission.Status.ACTIVE
            bed.current_patient = patient if status == Admission.Status.ACTIVE else None
            bed.save(update_fields=["is_occupied", "current_patient"])
            ensure_admission_bill(admission=admission)
            if status == Admission.Status.DISCHARGED:
                transfer = BedTransfer.objects.create(admission=admission, from_bed=bed, to_bed=wards["Hooks Medical Ward"].beds.order_by("bed_number")[1], reason="Seeded bed change.")
                ensure_bed_transfer_bill(admission=admission)
                DischargeSummary.objects.create(admission=admission, final_diagnosis=patient.medical_history, summary="Seeded discharge summary.", follow_up_plan="Return in one week.", prepared_by=doctor)
                ensure_discharge_bill(admission=admission)

        for idx, surgery_status in enumerate([SurgicalCase.Status.SCHEDULED, SurgicalCase.Status.RECOVERY, SurgicalCase.Status.COMPLETED]):
            SurgicalCase.objects.get_or_create(
                patient=patients[idx + 4],
                hospital=hooks,
                surgeon=doctors[idx % 2],
                operating_room=rooms["OR-A"] if idx < 2 else rooms["OR-B"],
                procedure_name=["Laparoscopic cholecystectomy", "Arthroscopic knee repair", "Emergency appendectomy"][idx],
                defaults={
                    "priority": SurgicalCase.Priority.URGENT if idx == 2 else SurgicalCase.Priority.ELECTIVE,
                    "status": surgery_status,
                    "scheduled_start": now + timedelta(days=idx - 2),
                    "estimated_duration_minutes": 90 + (idx * 20),
                    "anesthesia_type": "General anesthesia",
                    "pre_op_assessment": "Seeded pre-op note.",
                    "post_op_summary": "Seeded recovery note." if surgery_status in {SurgicalCase.Status.RECOVERY, SurgicalCase.Status.COMPLETED} else "",
                    "notes": "Seeded theatre workflow coverage.",
                },
            )

    def _seed_cross_hospital_baseline(self, hospital_one, hospital_two, doctor, now):
        patient_user = self._user("patient_demo", "Grace", "Wanjiku", User.Role.PATIENT, "patient@bayafya.local", dob=date(1988, 5, 16))
        patient = patient_user.patient
        patient.hospital = hospital_one
        patient.medical_history = "Baseline chronic care patient for cross-hospital checks."
        patient.save()
        self._access(patient_user, hospital_one, HospitalAccess.Role.PATIENT, primary=True)
        self._access(patient_user, hospital_two, HospitalAccess.Role.PATIENT)
        appointment, _ = Appointment.objects.update_or_create(
            doctor=doctor,
            appointment_date=(now + timedelta(days=2)).date(),
            appointment_time=time(10, 0),
            defaults={
                "patient": patient,
                "hospital": hospital_one,
                "status": Appointment.Status.CONFIRMED,
                "reason": "Cross-hospital review.",
            },
        )
        ensure_consultation_bill(patient=patient, hospital=hospital_one, doctor=doctor, appointment=appointment)
