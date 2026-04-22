from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from core.assistant import analyze_symptoms_with_ai
from hospital.models import Hospital

from .forms import SymptomForm
from .models import SymptomCheck


def _active_hospital(request):
    hospital_id = request.session.get("current_hospital_id")
    if hospital_id:
        return Hospital.objects.filter(pk=hospital_id, is_active=True).first()
    if hasattr(request.user, "patient") and request.user.patient.hospital_id:
        return request.user.patient.hospital
    return None


@login_required
def symptom_check(request):
    result = None
    patient = getattr(request.user, "patient", None)
    hospital = _active_hospital(request)
    is_async = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        form = SymptomForm(request.POST)
        if form.is_valid():
            onset_summary = form.cleaned_data.get("onset_summary", "")
            progression = form.cleaned_data.get("progression", "")
            intensity = form.cleaned_data.get("intensity")
            result = analyze_symptoms_with_ai(
                user=request.user,
                hospital=hospital,
                patient=patient,
                symptoms=form.cleaned_data["symptoms"],
                onset_summary=onset_summary,
                progression=progression,
                intensity=intensity,
            ).as_dict()
            SymptomCheck.objects.create(
                user=request.user,
                symptoms=form.cleaned_data["symptoms"],
                onset_summary=onset_summary,
                progression=progression,
                intensity=intensity,
                structured_context={
                    "symptoms": form.cleaned_data["symptoms"],
                    "onset_summary": onset_summary,
                    "progression": progression,
                    "intensity": intensity,
                    "clinical_rationale": result.get("clinical_rationale", ""),
                    "care_setting": result.get("care_setting", ""),
                    "differential_diagnoses": result.get("differential_diagnoses", []),
                    "recommended_evaluation": result.get("recommended_evaluation", []),
                },
                predicted_disease=result["disease"],
                confidence=result["confidence"],
                risk_level=result["risk_level"],
                guidance=result["guidance"],
            )
            if is_async:
                checks = list(
                    SymptomCheck.objects.filter(user=request.user)
                    .values("predicted_disease", "guidance", "risk_level", "confidence", "checked_at")[:5]
                )
                for item in checks:
                    item["checked_at"] = item["checked_at"].strftime("%Y-%m-%d %H:%M")
                return JsonResponse(
                    {
                        "ok": True,
                        "result": result,
                        "structured_context": {
                            "onset_summary": onset_summary,
                            "progression": progression,
                            "intensity": intensity,
                        },
                        "history": checks,
                        "active_hospital": hospital.name if hospital else "",
                    }
                )
        elif is_async:
            errors = {}
            for field, field_errors in form.errors.items():
                errors[field] = [str(error) for error in field_errors]
            return JsonResponse({"ok": False, "errors": errors}, status=400)
    else:
        form = SymptomForm()
    checks = SymptomCheck.objects.filter(user=request.user)[:5]
    return render(
        request,
        "symptom_checker/check.html",
        {"form": form, "result": result, "checks": checks, "active_hospital": hospital},
    )
