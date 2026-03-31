from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.permissions import doctor_required, patient_required
from hospital.billing import ensure_lab_bill, ensure_pharmacy_bill, ensure_telemedicine_bill
from hospital.models import Appointment, LabTestRequest, PharmacyTask

from .forms import PrescriptionForm, ReportUploadForm, TelemedicineLabRequestForm
from .models import VideoConsultation


@login_required
def dashboard(request):
    if request.user.role == "doctor":
        consultations = VideoConsultation.objects.filter(appointment__doctor__user=request.user)
    else:
        consultations = VideoConsultation.objects.filter(appointment__patient__user=request.user)
    return render(request, "telemedicine/dashboard.html", {"consultations": consultations})


@login_required
def create_consultation(request, appointment_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    appointment = get_object_or_404(Appointment, pk=appointment_id, doctor__user=request.user)
    if appointment.status != Appointment.Status.CONFIRMED:
        messages.error(request, "Telemedicine rooms can only be created for confirmed appointments.")
        return redirect("telemedicine:dashboard")
    request.session["clinical_patient_id"] = appointment.patient_id
    request.session["clinical_appointment_id"] = appointment.id
    if appointment.hospital_id:
        request.session["current_hospital_id"] = appointment.hospital_id
    consultation, _ = VideoConsultation.objects.get_or_create(appointment=appointment)
    ensure_telemedicine_bill(consultation=consultation)
    messages.success(request, "Video consultation room is ready.")
    return redirect("telemedicine:dashboard")


@login_required
def join_room(request, room_id):
    consultation = get_object_or_404(VideoConsultation, room_id=room_id)
    if request.user not in {
        consultation.appointment.patient.user,
        consultation.appointment.doctor.user,
    }:
        messages.error(request, "You are not authorized to join this consultation.")
        return redirect("telemedicine:dashboard")
    request.session["clinical_patient_id"] = consultation.appointment.patient_id
    request.session["clinical_appointment_id"] = consultation.appointment.id
    if consultation.appointment.hospital_id:
        request.session["current_hospital_id"] = consultation.appointment.hospital_id
    if consultation.status == VideoConsultation.Status.SCHEDULED:
        consultation.status = VideoConsultation.Status.ONGOING
        consultation.start_time = consultation.start_time or timezone.now()
        consultation.save(update_fields=["status", "start_time"])
    ensure_telemedicine_bill(consultation=consultation)
    return render(
        request,
        "telemedicine/room.html",
        {
            "consultation": consultation,
            "upload_form": ReportUploadForm(),
            "prescription_form": PrescriptionForm(),
            "lab_request_form": TelemedicineLabRequestForm(),
            "prescriptions": consultation.prescriptions.all(),
            "reports": consultation.reports.all(),
        },
    )


@login_required
@patient_required
def upload_report(request, consultation_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    consultation = get_object_or_404(
        VideoConsultation,
        pk=consultation_id,
        appointment__patient__user=request.user,
    )
    form = ReportUploadForm(request.POST, request.FILES)
    if form.is_valid():
        report = form.save(commit=False)
        report.consultation = consultation
        report.patient = consultation.appointment.patient
        report.save()
        messages.success(request, "Clinical report uploaded.")
    return redirect("telemedicine:join_room", room_id=consultation.room_id)


@login_required
@doctor_required
def issue_prescription(request, consultation_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    consultation = get_object_or_404(
        VideoConsultation,
        pk=consultation_id,
        appointment__doctor__user=request.user,
    )
    form = PrescriptionForm(request.POST)
    if form.is_valid():
        prescription = form.save(commit=False)
        prescription.consultation = consultation
        prescription.doctor = consultation.appointment.doctor
        prescription.patient = consultation.appointment.patient
        prescription.save()
        task, _ = PharmacyTask.objects.get_or_create(
            patient=consultation.appointment.patient,
            hospital=consultation.appointment.hospital,
            requested_by=request.user,
            instructions=form.cleaned_data.get("medications", ""),
            defaults={"status": PharmacyTask.Status.PENDING},
        )
        task.instructions = form.cleaned_data.get("medications", "")
        task.status = PharmacyTask.Status.PENDING
        task.save()
        ensure_pharmacy_bill(task=task)
        messages.success(request, "Prescription issued.")
    return redirect("telemedicine:join_room", room_id=consultation.room_id)


@login_required
@doctor_required
def issue_lab_request(request, consultation_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    consultation = get_object_or_404(
        VideoConsultation,
        pk=consultation_id,
        appointment__doctor__user=request.user,
    )
    form = TelemedicineLabRequestForm(request.POST)
    if form.is_valid():
        request_item = LabTestRequest.objects.create(
            patient=consultation.appointment.patient,
            hospital=consultation.appointment.hospital,
            requested_by=consultation.appointment.doctor,
            test_name=form.cleaned_data["test_name"],
            priority=form.cleaned_data["priority"],
            notes=f"Telemedicine request: {form.cleaned_data.get('notes', '').strip()}",
            status=LabTestRequest.Status.REQUESTED,
        )
        ensure_lab_bill(request=request_item)
        messages.success(request, "In-person lab request issued from telemedicine consultation.")
    return redirect("telemedicine:join_room", room_id=consultation.room_id)
