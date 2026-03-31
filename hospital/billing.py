from __future__ import annotations

from decimal import Decimal

from hospital.models import Billing, Doctor, LabTestRequest, PharmacyTask


STANDARD_RATES = {
    "walk_in_registration": Decimal("15.00"),
    "walk_in_triage": Decimal("12.00"),
    "admission": Decimal("150.00"),
    "bed_transfer": Decimal("35.00"),
    "discharge": Decimal("25.00"),
    "telemedicine_multiplier": Decimal("0.85"),
    "pharmacy_base": Decimal("20.00"),
}

LAB_RATE_HINTS = [
    ("cbc", Decimal("22.00")),
    ("full blood count", Decimal("22.00")),
    ("malaria", Decimal("18.00")),
    ("urinalysis", Decimal("14.00")),
    ("x-ray", Decimal("40.00")),
    ("ultrasound", Decimal("55.00")),
    ("crp", Decimal("20.00")),
    ("lft", Decimal("26.00")),
    ("kidney", Decimal("28.00")),
    ("renal", Decimal("28.00")),
    ("thyroid", Decimal("35.00")),
]

MEDICATION_RATE_HINTS = [
    ("amoxicillin", Decimal("12.50")),
    ("paracetamol", Decimal("4.00")),
    ("metformin", Decimal("9.80")),
    ("losartan", Decimal("11.60")),
    ("salbutamol", Decimal("22.00")),
    ("omeprazole", Decimal("8.70")),
]


def _lab_rate(test_name: str) -> Decimal:
    lowered = (test_name or "").lower()
    for token, amount in LAB_RATE_HINTS:
        if token in lowered:
            return amount
    return Decimal("25.00")


def _pharmacy_rate(instructions: str) -> Decimal:
    lowered = (instructions or "").lower()
    matched = [amount for token, amount in MEDICATION_RATE_HINTS if token in lowered]
    if matched:
        return sum(matched, Decimal("0.00")) + STANDARD_RATES["pharmacy_base"]
    return STANDARD_RATES["pharmacy_base"]


def _upsert_bill(*, patient, hospital, billing_type: str, amount: Decimal, description: str, **links) -> Billing:
    lookup = {"patient": patient, "hospital": hospital, "billing_type": billing_type}
    lookup.update({key: value for key, value in links.items() if value is not None})
    bill, _ = Billing.objects.get_or_create(
        **lookup,
        defaults={"amount": amount, "description": description, "paid": False},
    )
    bill.amount = amount
    bill.description = description
    if not bill.pk:
        bill.paid = False
    bill.save()
    return bill


def ensure_walk_in_registration_bill(*, encounter) -> Billing:
    return _upsert_bill(
        patient=encounter.patient,
        hospital=encounter.hospital,
        billing_type=Billing.BillingType.WALK_IN_REGISTRATION,
        amount=STANDARD_RATES["walk_in_registration"],
        description="Walk-in reception and records charge.",
        walk_in_encounter=encounter,
    )


def ensure_walk_in_triage_bill(*, encounter) -> Billing:
    return _upsert_bill(
        patient=encounter.patient,
        hospital=encounter.hospital,
        billing_type=Billing.BillingType.WALK_IN_TRIAGE,
        amount=STANDARD_RATES["walk_in_triage"],
        description="Nurse triage and vital-sign review charge.",
        walk_in_encounter=encounter,
    )


def ensure_consultation_bill(*, patient, hospital, doctor: Doctor, appointment=None, walk_in_encounter=None, medical_record=None) -> Billing:
    label = "Doctor consultation charge."
    return _upsert_bill(
        patient=patient,
        hospital=hospital,
        billing_type=Billing.BillingType.CONSULTATION,
        amount=doctor.consultation_fee or Decimal("0.00"),
        description=label,
        appointment=appointment,
        walk_in_encounter=walk_in_encounter,
        medical_record=medical_record,
    )


def ensure_lab_bill(*, request: LabTestRequest) -> Billing:
    return _upsert_bill(
        patient=request.patient,
        hospital=request.hospital,
        billing_type=Billing.BillingType.LAB,
        amount=_lab_rate(request.test_name),
        description=f"Laboratory charge for {request.test_name}.",
        walk_in_encounter=request.walk_in_encounter,
        lab_request=request,
    )


def ensure_pharmacy_bill(*, task: PharmacyTask) -> Billing:
    return _upsert_bill(
        patient=task.patient,
        hospital=task.hospital,
        billing_type=Billing.BillingType.PHARMACY,
        amount=_pharmacy_rate(task.instructions),
        description="Pharmacy dispensing and medication charge.",
        walk_in_encounter=task.walk_in_encounter,
        pharmacy_task=task,
        medical_record=task.medical_record,
    )


def ensure_admission_bill(*, admission) -> Billing:
    return _upsert_bill(
        patient=admission.patient,
        hospital=admission.hospital,
        billing_type=Billing.BillingType.ADMISSION,
        amount=STANDARD_RATES["admission"],
        description="Admission intake and initial bed allocation charge.",
        admission=admission,
    )


def ensure_bed_transfer_bill(*, admission) -> Billing:
    return _upsert_bill(
        patient=admission.patient,
        hospital=admission.hospital,
        billing_type=Billing.BillingType.BED_TRANSFER,
        amount=STANDARD_RATES["bed_transfer"],
        description="Bed transfer and ward movement charge.",
        admission=admission,
    )


def ensure_discharge_bill(*, admission) -> Billing:
    return _upsert_bill(
        patient=admission.patient,
        hospital=admission.hospital,
        billing_type=Billing.BillingType.DISCHARGE,
        amount=STANDARD_RATES["discharge"],
        description="Discharge summary and release processing charge.",
        admission=admission,
    )


def ensure_telemedicine_bill(*, consultation) -> Billing:
    doctor_fee = consultation.appointment.doctor.consultation_fee or Decimal("0.00")
    amount = (doctor_fee * STANDARD_RATES["telemedicine_multiplier"]).quantize(Decimal("0.01"))
    return _upsert_bill(
        patient=consultation.appointment.patient,
        hospital=consultation.appointment.hospital,
        billing_type=Billing.BillingType.TELEMEDICINE,
        amount=amount,
        description="Telemedicine consultation charge.",
        appointment=consultation.appointment,
        video_consultation=consultation,
    )
