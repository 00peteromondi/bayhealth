from __future__ import annotations

import json
import logging
import os
import random
import time as time_module
from dataclasses import dataclass
from typing import Any
from urllib import error, request as urlrequest

from django.conf import settings
from django.db import models
from django.utils import timezone

from ambulance.models import AmbulanceRequest
from hospital.models import Admission, Appointment, Billing, ConditionCatalog, Hospital, HospitalAccess, LabTestRequest, LabTestResult, MedicalRecord, Patient, PatientCondition, QueueTicket, SurgicalCase, VitalSign, WalkInEncounter
from mental_health.models import MoodLog, TherapySession
from telemedicine.models import VideoConsultation

from .models import AssistantAccessGrant, User


logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"


def _google_ai_api_keys() -> list[str]:
    if getattr(settings, "TESTING", False):
        return []
    keys: list[str] = []
    raw_sources = [
        os.environ.get("GOOGLE_AI_API_KEYS", ""),
        os.environ.get("GEMINI_API_KEYS", ""),
        getattr(settings, "GOOGLE_AI_API_KEYS", []),
        getattr(settings, "GEMINI_API_KEYS", []),
    ]
    for raw in raw_sources:
        if isinstance(raw, str):
            candidates = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            candidates = [str(item).strip() for item in (raw or []) if str(item).strip()]
        for key in candidates:
            if key and key not in keys:
                keys.append(key)
    singletons = [
        os.environ.get("GOOGLE_AI_API_KEY"),
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GOOGLE_API_KEY"),
        getattr(settings, "GOOGLE_AI_API_KEY", ""),
        getattr(settings, "GEMINI_API_KEY", ""),
        getattr(settings, "GOOGLE_API_KEY", ""),
    ]
    for key in singletons:
        cleaned = str(key or "").strip()
        if cleaned and cleaned not in keys:
            keys.append(cleaned)
    if keys:
        os.environ["GOOGLE_AI_API_KEY"] = keys[0]
        os.environ["GEMINI_API_KEY"] = keys[0]
        os.environ["GOOGLE_API_KEY"] = keys[0]
    return keys


def _google_ai_config() -> tuple[str, str]:
    api_keys = _google_ai_api_keys()
    model = (
        os.environ.get("GOOGLE_AI_MODEL")
        or os.environ.get("GEMINI_MODEL")
        or getattr(settings, "GOOGLE_AI_MODEL", "")
        or getattr(settings, "GEMINI_MODEL", "")
        or DEFAULT_GEMINI_MODEL
    )
    return model, (api_keys[0] if api_keys else "")


def _get_baycare_gemini_model() -> str:
    configured = (
        os.environ.get("BAYCARE_ASSISTANT_GEMINI_MODEL")
        or getattr(settings, "BAYCARE_ASSISTANT_GEMINI_MODEL", "")
        or os.environ.get("GOOGLE_AI_MODEL")
        or os.environ.get("GEMINI_MODEL")
        or getattr(settings, "GOOGLE_AI_MODEL", "")
        or getattr(settings, "GEMINI_MODEL", "")
        or DEFAULT_GEMINI_MODEL
    )
    return configured


def _get_baycare_gemini_models() -> list[str]:
    models: list[str] = []
    configured_sources = [
        os.environ.get("BAYCARE_ASSISTANT_GEMINI_CANDIDATES", ""),
        os.environ.get("GEMINI_CANDIDATE_MODELS", ""),
        os.environ.get("GOOGLE_AI_MODELS", ""),
        getattr(settings, "BAYCARE_ASSISTANT_GEMINI_CANDIDATES", []),
        getattr(settings, "GEMINI_CANDIDATE_MODELS", []),
        getattr(settings, "GOOGLE_AI_CANDIDATE_MODELS", []),
    ]
    primary = _get_baycare_gemini_model()
    if primary:
        models.append(primary)
    for raw in configured_sources:
        if isinstance(raw, str):
            candidates = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            candidates = [str(item).strip() for item in (raw or []) if str(item).strip()]
        for candidate in candidates:
            if candidate not in models:
                models.append(candidate)
    if not models:
        models.append(DEFAULT_GEMINI_MODEL)
    return models


@dataclass
class AssistantResponse:
    title: str
    summary: str
    suggestions: list[str]
    signals: list[str]
    safety: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "suggestions": self.suggestions,
            "signals": self.signals,
            "safety": self.safety,
        }


@dataclass
class AssistantChatResponse:
    reply: str
    summary: str
    suggestions: list[str]
    signals: list[str]
    safety: str
    access_scope: str
    can_view_patient_details: bool
    patient_label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "summary": self.summary,
            "suggestions": self.suggestions,
            "signals": self.signals,
            "safety": self.safety,
            "access_scope": self.access_scope,
            "can_view_patient_details": self.can_view_patient_details,
            "patient_label": self.patient_label,
        }


@dataclass
class PatientAccessDecision:
    allowed: bool
    scope: str
    reason: str


@dataclass
class SymptomAnalysisResponse:
    disease: str
    confidence: float
    risk_level: str
    guidance: str
    summary: str
    clinical_rationale: str
    care_setting: str
    red_flags: list[str]
    next_steps: list[str]
    differential_diagnoses: list[str]
    recommended_evaluation: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "disease": self.disease,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "guidance": self.guidance,
            "summary": self.summary,
            "clinical_rationale": self.clinical_rationale,
            "care_setting": self.care_setting,
            "red_flags": self.red_flags,
            "next_steps": self.next_steps,
            "differential_diagnoses": self.differential_diagnoses,
            "recommended_evaluation": self.recommended_evaluation,
        }


@dataclass
class MentalHealthSupportResponse:
    summary: str
    risk_level: str
    guidance: str
    coping_steps: list[str]
    signals: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "risk_level": self.risk_level,
            "guidance": self.guidance,
            "coping_steps": self.coping_steps,
            "signals": self.signals,
        }


@dataclass
class WalkInSeverityResponse:
    severity_index: int
    severity_band: str
    summary: str
    rationale: str
    red_flags: list[str]
    next_steps: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity_index": self.severity_index,
            "severity_band": self.severity_band,
            "summary": self.summary,
            "rationale": self.rationale,
            "red_flags": self.red_flags,
            "next_steps": self.next_steps,
        }


def _ensure_condition_catalog_entry(label: str) -> None:
    cleaned = (label or "").strip(" .,-")
    if not cleaned:
        return
    lowered = cleaned.lower()
    generic_markers = [
        "non-specific",
        "presentation",
        "pattern",
        "support",
        "review",
        "assessment",
        "unknown",
        "unclear",
        "possible",
    ]
    if any(marker in lowered for marker in generic_markers):
        return
    ConditionCatalog.objects.get_or_create(
        name=cleaned[:160].title(),
        defaults={"description": "Condition label added from BayAfya Assistant-supported analysis."},
    )


def _latest_patient_context(patient: Patient | None, *, include_sensitive: bool = True) -> dict[str, Any]:
    if not patient:
        return {"summary": "", "conditions": [], "appointments": [], "records": [], "surgeries": [], "admissions": [], "walk_ins": [], "lab_requests": [], "lab_results": []}
    conditions = list(PatientCondition.objects.filter(patient=patient).select_related("condition").order_by("-created_at")[:5])
    appointments = list(
        Appointment.objects.filter(patient=patient)
        .select_related("doctor__user", "hospital")
        .order_by("-appointment_date", "-appointment_time")[:5]
    )
    records = list(
        MedicalRecord.objects.filter(patient=patient)
        .select_related("doctor__user", "hospital")
        .order_by("-created_at")[:5]
    )
    surgeries = list(
        SurgicalCase.objects.filter(patient=patient)
        .select_related("surgeon__user", "hospital")
        .order_by("-scheduled_start")[:5]
    )
    admissions = list(
        Admission.objects.filter(patient=patient)
        .select_related("hospital", "ward", "bed")
        .order_by("-admitted_at", "-id")[:5]
    )
    walk_ins = list(
        WalkInEncounter.objects.filter(patient=patient)
        .select_related("hospital", "attending_doctor__user")
        .order_by("-last_updated_at", "-arrived_at")[:5]
    )
    lab_requests = list(
        LabTestRequest.objects.filter(patient=patient)
        .select_related("hospital", "requested_by__user")
        .order_by("-requested_at")[:5]
    )
    lab_results = list(
        LabTestResult.objects.filter(request__patient=patient)
        .select_related("request__hospital", "request")
        .order_by("-completed_at")[:5]
    )
    active_conditions = [
        item.condition_name or (item.condition.name if item.condition_id else "Condition recorded")
        for item in conditions
        if item.is_active
    ]
    summary_parts = []
    if active_conditions:
        summary_parts.append("Active conditions: " + ", ".join(active_conditions[:3]))
    if appointments:
        summary_parts.append(f"Next appointment: {appointments[0].appointment_date} at {appointments[0].appointment_time}")
    if surgeries:
        summary_parts.append(f"Upcoming surgery: {surgeries[0].procedure_name}")
    if admissions:
        latest_admission = admissions[0]
        ward_name = latest_admission.ward.name if latest_admission.ward_id else "Ward"
        bed_label = f"Bed {latest_admission.bed.bed_number}" if latest_admission.bed_id else "no bed assigned"
        summary_parts.append(f"Admission: {ward_name}, {bed_label}")
    if walk_ins:
        summary_parts.append(f"Walk-in stage: {walk_ins[0].get_status_display()}")
    if lab_results:
        summary_parts.append(f"Latest lab result: {lab_results[0].request.test_name}")

    if not include_sensitive:
        records = []
        lab_results = []
        admissions = []

    return {
        "summary": " | ".join(summary_parts),
        "conditions": conditions,
        "appointments": appointments,
        "records": records,
        "surgeries": surgeries,
        "admissions": admissions,
        "walk_ins": walk_ins,
        "lab_requests": lab_requests,
        "lab_results": lab_results,
    }


def _symptom_guidance(text: str, patient: Patient | None) -> list[str]:
    lowered = text.lower()
    suggestions: list[str] = []
    if any(term in lowered for term in ["chest pain", "shortness of breath", "breathing trouble", "fainting"]):
        suggestions.append("Seek urgent in-person assessment or emergency support now.")
    if any(term in lowered for term in ["fever", "cough", "sore throat"]):
        suggestions.append("Document temperature, onset, and any exposure history before clinical review.")
    if any(term in lowered for term in ["headache", "blurred vision", "severe pain"]):
        suggestions.append("Capture duration, severity, and associated symptoms for clinician follow-up.")
    if patient:
        active_conditions = PatientCondition.objects.filter(patient=patient, is_active=True).select_related("condition")
        condition_names = [
            item.condition_name or (item.condition.name if item.condition_id else "Condition recorded")
            for item in active_conditions[:4]
        ]
        if condition_names:
            suggestions.append(f"Keep these known conditions in view: {', '.join(condition_names[:3])}.")
    if not suggestions:
        suggestions.extend(
            [
                "Review symptom timing, severity, and triggers before booking care.",
                "If symptoms are worsening or persistent, move to a clinician review.",
            ]
        )
    return suggestions[:4]


def _mental_health_guidance(text: str, patient: Patient | None) -> list[str]:
    lowered = text.lower()
    suggestions: list[str] = [
        "Use a short grounding exercise and capture one specific feeling in the mood log.",
        "If distress is ongoing, schedule a therapy session or counselor review.",
    ]
    if any(term in lowered for term in ["panic", "panic attack", "anxious", "anxiety"]):
        suggestions.insert(0, "Slow breathing and grounding may help while you prepare a calmer check-in.")
    if any(term in lowered for term in ["sad", "low", "hopeless", "depressed"]):
        suggestions.insert(0, "Record the intensity and duration so the care team can follow the pattern.")
    if patient:
        recent_sessions = TherapySession.objects.filter(patient=patient.user).order_by("-scheduled_time")[:2]
        if recent_sessions:
            suggestions.append("Refer to the most recent therapy plan before adding a new note.")
    return suggestions[:4]


def _parse_ai_response(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json\n", "", 1)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = cleaned[start : end + 1]
    try:
        payload = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload.setdefault("title", "BayAfya Assistant")
    payload.setdefault("summary", "")
    payload.setdefault("suggestions", [])
    payload.setdefault("signals", [])
    payload.setdefault("safety", "Use assistant guidance together with clinical judgment.")
    payload.setdefault("reply", "")
    return payload


def _looks_generic_ai_payload(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return True
    combined = " ".join(
        str(payload.get(key) or "")
        for key in ("reply", "summary", "title", "safety")
    ).lower()
    generic_patterns = (
        "general care mode is active",
        "i can help with baycare workflows",
        "patient-specific summary",
        "use assistant guidance together with clinical judgment",
        "guidance is generated from the current workspace",
    )
    return not combined or any(pattern in combined for pattern in generic_patterns)


def _gemini_generation_config(thinking_level: str = "low") -> dict[str, Any]:
    return {
        "response_mime_type": "application/json",
    }


def _is_retryable_google_error(exc: Exception) -> bool:
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    message = str(exc).lower()
    retryable_markers = (
        "resource_exhausted",
        "quota",
        "rate limit",
        "429",
        "unavailable",
        "overloaded",
        "timed out",
        "timeout",
        "internal",
        "service unavailable",
        "backend error",
    )
    return any(marker in message for marker in retryable_markers)


def _is_quota_limited_google_error(exc: Exception) -> bool:
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    message = str(exc).lower()
    quota_markers = (
        "resource_exhausted",
        "quota",
        "rate limit",
        "429",
        "too many requests",
    )
    return any(marker in message for marker in quota_markers)


def _sdk_generate_json_response(
    client: Any,
    *,
    model: str,
    prompt: str,
    thinking_level: str,
) -> dict[str, Any] | None:
    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=_gemini_generation_config(thinking_level=thinking_level),
            )
            text_output = getattr(response, "text", None) or ""
            parsed = _parse_ai_response(text_output)
            if parsed and not _looks_generic_ai_payload(parsed):
                return parsed
            if parsed:
                logger.info("BayAfya Assistant Gemini SDK returned a generic payload for model %s.", model)
            return None
        except Exception as exc:
            logger.warning("BayAfya Assistant Gemini SDK error for model %s (attempt %s): %s", model, attempt, exc)
            if _is_retryable_google_error(exc) and attempt < 3:
                time_module.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.4))
                continue
            return None
    return None


def _sdk_generate_json_response_with_status(
    client: Any,
    *,
    model: str,
    prompt: str,
    thinking_level: str,
) -> tuple[dict[str, Any] | None, bool]:
    quota_limited = False
    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=_gemini_generation_config(thinking_level=thinking_level),
            )
            text_output = getattr(response, "text", None) or ""
            parsed = _parse_ai_response(text_output)
            if parsed and not _looks_generic_ai_payload(parsed):
                return parsed, quota_limited
            if parsed:
                logger.info("BayAfya Assistant Gemini SDK returned a generic payload for model %s.", model)
            return None, quota_limited
        except Exception as exc:
            quota_limited = quota_limited or _is_quota_limited_google_error(exc)
            logger.warning("BayAfya Assistant Gemini SDK error for model %s (attempt %s): %s", model, attempt, exc)
            if _is_retryable_google_error(exc) and attempt < 3 and not quota_limited:
                time_module.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.4))
                continue
            return None, quota_limited
    return None, quota_limited


def _google_ai_sdk_response(prompt: str, *, thinking_level: str = "low") -> dict[str, Any] | None:
    api_keys = _google_ai_api_keys()
    if not api_keys:
        return None
    try:
        from google import genai
    except Exception as exc:
        logger.info("BayAfya Assistant Gemini SDK unavailable, using REST fallback: %s", exc)
        return None

    models = _get_baycare_gemini_models()
    for index, api_key in enumerate(api_keys, start=1):
        try:
            client = genai.Client(api_key=api_key)
        except Exception as exc:
            logger.warning("BayAfya Assistant Gemini SDK client init failed for configured key %s: %s", index, exc)
            continue
        key_quota_limited = False
        for model in models:
            payload, quota_limited = _sdk_generate_json_response_with_status(
                client,
                model=model,
                prompt=prompt,
                thinking_level=thinking_level,
            )
            key_quota_limited = key_quota_limited or quota_limited
            if payload:
                return payload
            if quota_limited:
                logger.info(
                    "BayAfya Assistant rotating to the next Gemini API key after quota pressure on key %s for model %s.",
                    index,
                    model,
                )
                break
            logger.info(
                "BayAfya Assistant Gemini SDK model %s did not yield a usable payload on key %s.",
                model,
                index,
            )
        if key_quota_limited:
            continue
    return None


def _google_ai_response(prompt: str, *, thinking_level: str = "low") -> dict[str, Any] | None:
    api_keys = _google_ai_api_keys()
    if not api_keys:
        logger.info("BayAfya Assistant is using fallback mode because no Google AI API key is configured.")
        return None
    sdk_payload = _google_ai_sdk_response(prompt, thinking_level=thinking_level)
    if sdk_payload:
        return sdk_payload
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
        },
    }
    models = _get_baycare_gemini_models()
    for index, api_key in enumerate(api_keys, start=1):
        quota_limited = False
        for model in models:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for attempt in range(1, 3):
                try:
                    req = urlrequest.Request(
                        endpoint,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": api_key,
                        },
                        method="POST",
                    )
                    with urlrequest.urlopen(req, timeout=20) as response:
                        raw = response.read().decode("utf-8")
                    data = json.loads(raw)
                    text_output = "".join(
                        part.get("text", "")
                        for candidate in data.get("candidates", [])
                        for part in candidate.get("content", {}).get("parts", [])
                    )
                    parsed = _parse_ai_response(text_output)
                    if parsed and not _looks_generic_ai_payload(parsed):
                        return parsed
                    if parsed:
                        logger.info("BayAfya Assistant received a generic AI payload from model %s.", model)
                    break
                except error.HTTPError as exc:
                    try:
                        error_body = exc.read().decode("utf-8", errors="ignore")
                    except Exception:
                        error_body = ""
                    logger.warning(
                        "BayAfya Assistant Google AI HTTP error %s for model %s using key %s. Body: %s",
                        exc.code,
                        model,
                        index,
                        error_body,
                    )
                    if _is_quota_limited_google_error(exc):
                        quota_limited = True
                        break
                    if exc.code == 404:
                        logger.info("BayAfya Assistant skipping unavailable Gemini model %s.", model)
                        break
                    if _is_retryable_google_error(exc) and attempt < 2:
                        time_module.sleep((2 ** attempt) + random.uniform(0, 0.5))
                        continue
                    break
                except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
                    logger.warning("BayAfya Assistant Google AI error for model %s using key %s: %s", model, index, exc)
                    if attempt < 2:
                        time_module.sleep((2 ** attempt) + random.uniform(0, 0.5))
                        continue
                    break
            if quota_limited:
                logger.info("BayAfya Assistant rotating to the next Gemini API key after REST quota pressure on key %s.", index)
                break
    return None


def _ai_json_response(prompt: str, *, defaults: dict[str, Any], thinking_level: str = "low") -> dict[str, Any] | None:
    payload = _google_ai_response(prompt, thinking_level=thinking_level)
    if not payload:
        return None
    for key, value in defaults.items():
        payload.setdefault(key, value)
    return payload


def _ai_json_response_with_correction(
    prompt: str,
    *,
    defaults: dict[str, Any],
    correction: str,
    thinking_level: str = "low",
) -> dict[str, Any] | None:
    payload = _ai_json_response(prompt, defaults=defaults, thinking_level=thinking_level)
    if payload and not _looks_generic_ai_payload(payload):
        return payload
    corrected = _ai_json_response(
        f"{prompt}\n\nCorrection pass:\n{correction}\n",
        defaults=defaults,
        thinking_level=thinking_level,
    )
    if corrected:
        return corrected
    return payload


def analyze_symptoms_with_ai(
    *,
    user: User,
    hospital: Hospital | None = None,
    patient: Patient | None = None,
    symptoms: str,
    onset_summary: str = "",
    progression: str = "",
    intensity: int | None = None,
) -> SymptomAnalysisResponse:
    baseline = _symptom_guidance(symptoms, patient)
    patient_context = _latest_patient_context(patient, include_sensitive=True)
    current_conditions = []
    if patient:
        current_conditions = [
            item.condition_name or (item.condition.name if item.condition_id else "Recorded condition")
            for item in PatientCondition.objects.filter(patient=patient, is_active=True).select_related("condition")[:6]
        ]
    recent_records = [
        {
            "diagnosis": (item.diagnosis or "Diagnosis recorded")[:160],
            "assessment": (item.assessment or item.notes or "")[:220],
            "recorded_at": timezone.localtime(item.created_at).strftime("%Y-%m-%d %H:%M"),
        }
        for item in patient_context.get("records", [])[:3]
    ]
    recent_admissions = [
        {
            "status": item.status,
            "hospital": item.hospital.name if item.hospital_id else "",
            "ward": item.ward.name if item.ward_id else "",
            "bed": item.bed.bed_number if item.bed_id else "",
            "reason": (item.admission_reason or item.notes or "")[:220],
            "admitted_at": timezone.localtime(item.admitted_at).strftime("%Y-%m-%d %H:%M") if item.admitted_at else "",
        }
        for item in patient_context.get("admissions", [])[:2]
    ]
    recent_lab_requests = [
        {
            "test_name": item.test_name,
            "status": item.status,
            "priority": item.priority,
            "requested_at": timezone.localtime(item.requested_at).strftime("%Y-%m-%d %H:%M"),
        }
        for item in patient_context.get("lab_requests", [])[:3]
    ]
    recent_lab_results = [
        {
            "test_name": item.request.test_name if item.request_id else "Lab result",
            "summary": (item.result_summary or "")[:220],
            "completed_at": timezone.localtime(item.completed_at).strftime("%Y-%m-%d %H:%M") if item.completed_at else "",
        }
        for item in patient_context.get("lab_results", [])[:3]
    ]
    prompt = (
        "You are BayAfya Assistant working inside a healthcare platform.\n"
        "Return strictly valid JSON with keys: disease, confidence, risk_level, guidance, summary, clinical_rationale, care_setting, red_flags, next_steps, differential_diagnoses, recommended_evaluation.\n"
        "This is a symptom-triage support output, not a final diagnosis.\n"
        "risk_level must be one of: low, moderate, high.\n"
        "confidence must be a number between 0 and 1.\n"
        "Keep guidance concrete, safe, and clinically cautious.\n"
        "clinical_rationale should explain briefly which presentation details drove the assessment.\n"
        "care_setting must be one of: home_monitoring, outpatient_review, same_day_clinic, urgent_in_person, emergency_care.\n"
        "differential_diagnoses should contain 2 to 4 short plausible considerations.\n"
        "recommended_evaluation should contain 2 to 5 concise questions, examinations, or tests that would clarify the case.\n"
        "If symptoms suggest emergency risk, make that explicit.\n"
        "Use the symptom text, known conditions, and recent patient context below.\n\n"
        f"User role: {user.role}\n"
        f"Hospital: {getattr(hospital, 'name', '') or 'None'}\n"
        f"Known conditions: {json.dumps(current_conditions, default=str)}\n"
        f"Patient context summary: {patient_context.get('summary', '')}\n"
        f"Recent medical records: {json.dumps(recent_records, default=str)}\n"
        f"Recent admissions: {json.dumps(recent_admissions, default=str)}\n"
        f"Recent lab requests: {json.dumps(recent_lab_requests, default=str)}\n"
        f"Recent lab results: {json.dumps(recent_lab_results, default=str)}\n"
        f"Onset summary: {onset_summary}\n"
        f"Progression: {progression}\n"
        f"Intensity (1-10): {intensity if intensity is not None else 'Unknown'}\n"
        f"Symptoms: {symptoms}\n"
        f"Fallback next steps: {json.dumps(baseline, default=str)}\n"
    )
    ai_payload = _ai_json_response(
        prompt,
        defaults={
            "disease": "Non-specific symptom pattern",
            "confidence": 0.55,
            "risk_level": "low",
            "guidance": "Arrange a clinical review if symptoms persist, worsen, or feel concerning.",
            "summary": "Symptoms require structured review and safe follow-up.",
            "clinical_rationale": "The current symptom pattern does not yet strongly identify one urgent diagnosis, so cautious structured follow-up is safer.",
            "care_setting": "outpatient_review",
            "red_flags": [],
            "next_steps": baseline,
            "differential_diagnoses": ["Non-specific viral illness", "Medication or hydration-related symptoms"],
            "recommended_evaluation": [
                "Review duration, triggers, and symptom progression.",
                "Check temperature, hydration, and any recent exposures.",
            ],
        },
        thinking_level="medium",
    )
    if ai_payload:
        care_setting = str(ai_payload.get("care_setting") or "outpatient_review").lower()
        if care_setting not in {"home_monitoring", "outpatient_review", "same_day_clinic", "urgent_in_person", "emergency_care"}:
            care_setting = "outpatient_review"
        response = SymptomAnalysisResponse(
            disease=str(ai_payload.get("disease") or "Non-specific symptom pattern"),
            confidence=max(0.0, min(float(ai_payload.get("confidence") or 0.55), 1.0)),
            risk_level=str(ai_payload.get("risk_level") or "low").lower(),
            guidance=str(ai_payload.get("guidance") or "Arrange a clinical review if symptoms persist, worsen, or feel concerning."),
            summary=str(ai_payload.get("summary") or "Symptoms require structured review and safe follow-up."),
            clinical_rationale=str(
                ai_payload.get("clinical_rationale")
                or "The assessment was guided by the symptom pattern, timeline, severity, and recent chart context."
            ),
            care_setting=care_setting,
            red_flags=[str(item) for item in (ai_payload.get("red_flags") or [])][:4],
            next_steps=[str(item) for item in (ai_payload.get("next_steps") or baseline)][:4],
            differential_diagnoses=[str(item) for item in (ai_payload.get("differential_diagnoses") or []) if str(item).strip()][:4],
            recommended_evaluation=[str(item) for item in (ai_payload.get("recommended_evaluation") or []) if str(item).strip()][:5],
        )
        _ensure_condition_catalog_entry(response.disease)
        return response

    lowered = symptoms.lower()
    disease = "Non-specific symptom pattern"
    risk_level = "low"
    confidence = 0.55
    guidance = "Arrange a professional consultation for a complete assessment."
    clinical_rationale = "The available symptom details suggest a non-specific pattern, so a cautious structured review is safer than overcommitting to one diagnosis."
    care_setting = "outpatient_review"
    red_flags: list[str] = []
    differential_diagnoses = [
        "Non-specific viral illness",
        "Mild dehydration or recovery-related symptoms",
        "Medication, stress, or sleep-related presentation",
    ]
    recommended_evaluation = [
        "Clarify the exact start time and recent progression of symptoms.",
        "Review temperature, hydration, appetite, and medication use.",
        "Escalate to in-person review if symptoms are persistent or worsening.",
    ]
    has_fever = "fever" in lowered
    has_headache = "headache" in lowered or "headaches" in lowered
    has_vomiting = "vomit" in lowered or "vomiting" in lowered
    has_nausea = "nausea" in lowered or "nauseous" in lowered
    has_joint_pain = "joint pain" in lowered or "pain in the joints" in lowered or "body ache" in lowered or "body aches" in lowered
    has_worsening = progression == "worsening" or any(term in lowered for term in ["getting more severe", "worsening", "worse", "persistent", "severe"])
    high_intensity = intensity is not None and intensity >= 8

    if any(term in lowered for term in ["chest pain", "shortness of breath", "breathing trouble", "fainting"]):
        disease = "Possible cardiac or respiratory emergency"
        risk_level = "high"
        confidence = 0.82
        guidance = "Seek immediate emergency or urgent in-person clinical assessment."
        clinical_rationale = "Chest pain, breathing difficulty, or fainting can signal rapidly unsafe cardiac or respiratory compromise."
        care_setting = "emergency_care"
        red_flags = ["Chest pain", "Shortness of breath", "Fainting or collapse"]
        differential_diagnoses = [
            "Acute respiratory compromise",
            "Cardiac ischemia or arrhythmia",
            "Severe asthma or pulmonary infection",
        ]
        recommended_evaluation = [
            "Check airway, breathing, circulation, and oxygen saturation immediately.",
            "Assess chest pain quality, duration, and radiation.",
            "Arrange urgent clinician or emergency evaluation now.",
        ]
    elif has_fever and has_headache and (has_vomiting or has_nausea) and (has_worsening or high_intensity):
        disease = "Possible severe infectious illness requiring urgent clinician review"
        risk_level = "high"
        confidence = 0.86
        guidance = (
            "This symptom pattern needs urgent in-person assessment today, especially because the fever and headache are worsening with vomiting or persistent nausea."
        )
        clinical_rationale = "The combination of worsening fever, headache, and vomiting raises concern for dehydration or a significant systemic or central nervous system infection."
        care_setting = "urgent_in_person"
        red_flags = [
            "Worsening fever",
            "Headache becoming more severe",
            "Vomiting or persistent nausea",
            "Risk of dehydration or serious infection",
        ]
        differential_diagnoses = [
            "Severe systemic infection",
            "Meningeal or central nervous system irritation",
            "Complicated malaria or other febrile illness",
        ]
        recommended_evaluation = [
            "Review temperature trend, neck stiffness, hydration, and mental status.",
            "Check vital signs and assess dehydration urgently.",
            "Arrange same-day clinician assessment and targeted testing.",
        ]
    elif has_fever and has_joint_pain and has_headache:
        disease = "Possible systemic infectious illness"
        risk_level = "moderate"
        confidence = 0.74
        guidance = "Book prompt medical review, maintain fluids, and escalate urgently if vomiting, weakness, confusion, or breathing issues develop."
        clinical_rationale = "Fever with headache and joint pain fits a systemic infectious presentation and deserves prompt clinical review before it progresses."
        care_setting = "same_day_clinic"
        red_flags = ["Persistent fever", "Headache", "Joint pain"]
        differential_diagnoses = [
            "Viral febrile illness",
            "Malaria or other regional febrile infection",
            "Inflammatory or mosquito-borne illness",
        ]
        recommended_evaluation = [
            "Review exposure history, mosquito exposure, and travel context.",
            "Check hydration status and current temperature.",
            "Consider clinician review with malaria or infection-focused testing.",
        ]
    elif high_intensity and has_worsening:
        disease = "Escalating symptom pattern requiring prompt clinician review"
        risk_level = "moderate"
        confidence = 0.7
        guidance = "Because intensity is high and the symptoms are worsening, arrange urgent professional review and escalate immediately if red-flag symptoms appear."
        clinical_rationale = "High-intensity symptoms that are still worsening usually need in-person reassessment to prevent deterioration."
        care_setting = "same_day_clinic"
        red_flags = ["High symptom intensity", "Symptoms worsening over time"]
        differential_diagnoses = [
            "Acute worsening illness",
            "Uncontrolled pain or inflammation",
            "Evolving infection or complication",
        ]
        recommended_evaluation = [
            "Confirm the main symptom driving the high intensity score.",
            "Check whether new red-flag features have appeared today.",
            "Arrange prompt in-person clinician review.",
        ]
    elif "fever" in lowered and "cough" in lowered:
        disease = "Flu-like or respiratory infectious presentation"
        risk_level = "moderate"
        confidence = 0.78
        guidance = "Book a consultation, monitor temperature, and seek urgent review if breathing worsens."
        clinical_rationale = "Fever with cough is consistent with a respiratory infectious pattern and needs monitoring for escalation."
        care_setting = "outpatient_review"
        differential_diagnoses = [
            "Upper respiratory viral infection",
            "Influenza-like illness",
            "Early lower respiratory infection",
        ]
        recommended_evaluation = [
            "Monitor temperature and breathing pattern.",
            "Check for sputum, chest pain, or worsening shortness of breath.",
            "Arrange clinician review if symptoms persist or intensify.",
        ]
    elif "headache" in lowered and "fatigue" in lowered:
        disease = "Possible viral syndrome, dehydration, or stress-related presentation"
        risk_level = "low"
        confidence = 0.64
        guidance = "Hydrate, rest, and arrange outpatient review if symptoms continue."
        clinical_rationale = "Headache with fatigue is common in several lower-acuity presentations, but persistence or worsening still needs follow-up."
        care_setting = "home_monitoring"
        differential_diagnoses = [
            "Viral syndrome",
            "Dehydration",
            "Stress-related or sleep-related symptoms",
        ]
        recommended_evaluation = [
            "Review fluid intake, sleep, stressors, and temperature.",
            "Escalate if fever, vomiting, confusion, or worsening pain develops.",
        ]
    response = SymptomAnalysisResponse(
        disease=disease,
        confidence=confidence,
        risk_level=risk_level,
        guidance=guidance,
        summary="BayAfya generated a structured symptom review using the current symptom description, severity, progression, and recent chart context.",
        clinical_rationale=clinical_rationale,
        care_setting=care_setting,
        red_flags=red_flags,
        next_steps=baseline,
        differential_diagnoses=differential_diagnoses,
        recommended_evaluation=recommended_evaluation,
    )
    _ensure_condition_catalog_entry(response.disease)
    return response


def analyze_walk_in_severity(
    *,
    user: User,
    hospital: Hospital | None = None,
    patient: Patient | None = None,
    symptoms: str,
    current_state: str = "",
    triage_notes: str = "",
    vitals: dict[str, Any] | None = None,
) -> WalkInSeverityResponse:
    vitals = vitals or {}
    risk_points = 0
    red_flags: list[str] = []
    lowered_text = " ".join([symptoms or "", current_state or "", triage_notes or ""]).lower()

    def _add_flag(label: str, points: int) -> None:
        nonlocal risk_points
        risk_points += points
        if label not in red_flags:
            red_flags.append(label)

    try:
        temperature = float(vitals.get("temperature_c")) if vitals.get("temperature_c") not in (None, "") else None
    except (TypeError, ValueError):
        temperature = None
    try:
        pulse_rate = int(vitals.get("pulse_rate")) if vitals.get("pulse_rate") not in (None, "") else None
    except (TypeError, ValueError):
        pulse_rate = None
    try:
        respiratory_rate = int(vitals.get("respiratory_rate")) if vitals.get("respiratory_rate") not in (None, "") else None
    except (TypeError, ValueError):
        respiratory_rate = None
    try:
        oxygen_saturation = int(vitals.get("oxygen_saturation")) if vitals.get("oxygen_saturation") not in (None, "") else None
    except (TypeError, ValueError):
        oxygen_saturation = None
    try:
        systolic_bp = int(vitals.get("systolic_bp")) if vitals.get("systolic_bp") not in (None, "") else None
    except (TypeError, ValueError):
        systolic_bp = None

    if temperature is not None and temperature >= 39:
        _add_flag("High fever", 12)
    elif temperature is not None and temperature >= 38:
        risk_points += 7

    if pulse_rate is not None and pulse_rate >= 120:
        _add_flag("Very fast pulse", 12)
    elif pulse_rate is not None and pulse_rate >= 100:
        risk_points += 6

    if respiratory_rate is not None and respiratory_rate >= 30:
        _add_flag("Rapid breathing", 12)
    elif respiratory_rate is not None and respiratory_rate >= 22:
        risk_points += 6

    if oxygen_saturation is not None and oxygen_saturation < 90:
        _add_flag("Low oxygen saturation", 25)
    elif oxygen_saturation is not None and oxygen_saturation < 94:
        _add_flag("Borderline oxygen saturation", 12)

    if systolic_bp is not None and systolic_bp < 90:
        _add_flag("Low blood pressure", 18)

    text_flag_weights = {
        "chest pain": ("Chest pain", 18),
        "shortness of breath": ("Shortness of breath", 20),
        "difficulty breathing": ("Difficulty breathing", 20),
        "confusion": ("Confusion", 16),
        "unconscious": ("Loss of consciousness", 28),
        "seizure": ("Seizure", 26),
        "bleeding": ("Bleeding", 18),
        "vomiting": ("Vomiting", 8),
        "persistent nausea": ("Persistent nausea", 6),
        "severe headache": ("Severe headache", 12),
        "headache": ("Headache", 5),
        "fever": ("Fever", 6),
        "weakness": ("Weakness", 6),
    }
    for phrase, (label, points) in text_flag_weights.items():
        if phrase in lowered_text:
            if label in {
                "Chest pain",
                "Shortness of breath",
                "Difficulty breathing",
                "Confusion",
                "Loss of consciousness",
                "Seizure",
                "Bleeding",
            }:
                _add_flag(label, points)
            else:
                risk_points += points

    baseline_steps = _symptom_guidance(f"{symptoms}. {current_state}. {triage_notes}".strip(), patient)
    heuristic_index = max(5, min(risk_points, 100))
    heuristic_band = "low"
    if heuristic_index >= 75:
        heuristic_band = "critical"
    elif heuristic_index >= 50:
        heuristic_band = "high"
    elif heuristic_index >= 25:
        heuristic_band = "moderate"

    prompt = (
        "You are BayAfya Assistant supporting walk-in hospital triage.\n"
        "Return strictly valid JSON with keys: severity_index, severity_band, summary, rationale, red_flags, next_steps.\n"
        "severity_index must be an integer between 0 and 100.\n"
        "severity_band must be one of: low, moderate, high, critical.\n"
        "This supports queue prioritization only. Do not present it as a diagnosis.\n"
        "Be clinically cautious and explicit about urgent warning signs.\n\n"
        f"User role: {user.role}\n"
        f"Hospital: {getattr(hospital, 'name', '') or 'None'}\n"
        f"Patient age group: {getattr(patient, 'age_group', 'Unknown') if patient else 'Unknown'}\n"
        f"Symptoms: {symptoms}\n"
        f"Current state: {current_state}\n"
        f"Triage notes: {triage_notes}\n"
        f"Vitals: {json.dumps(vitals, default=str)}\n"
        f"Baseline severity index: {heuristic_index}\n"
        f"Baseline severity band: {heuristic_band}\n"
        f"Detected red flags: {json.dumps(red_flags, default=str)}\n"
        f"Fallback next steps: {json.dumps(baseline_steps, default=str)}\n"
    )
    ai_payload = _ai_json_response(
        prompt,
        defaults={
            "severity_index": heuristic_index,
            "severity_band": heuristic_band,
            "summary": "Walk-in triage captured and ready for prioritization.",
            "rationale": "Severity was estimated from recorded symptoms, current state, and vitals.",
            "red_flags": red_flags,
            "next_steps": baseline_steps,
        },
        thinking_level="medium",
    )
    if ai_payload:
        try:
            severity_index = max(0, min(int(ai_payload.get("severity_index") or heuristic_index), 100))
        except (TypeError, ValueError):
            severity_index = heuristic_index
        severity_band = str(ai_payload.get("severity_band") or heuristic_band).lower()
        if severity_band not in {"low", "moderate", "high", "critical"}:
            severity_band = heuristic_band
        return WalkInSeverityResponse(
            severity_index=severity_index,
            severity_band=severity_band,
            summary=str(ai_payload.get("summary") or "Walk-in triage captured and ready for prioritization."),
            rationale=str(ai_payload.get("rationale") or "Severity was estimated from recorded symptoms, current state, and vitals."),
            red_flags=[str(item) for item in (ai_payload.get("red_flags") or red_flags)][:6],
            next_steps=[str(item) for item in (ai_payload.get("next_steps") or baseline_steps)][:5],
        )

    return WalkInSeverityResponse(
        severity_index=heuristic_index,
        severity_band=heuristic_band,
        summary="Walk-in triage captured and ready for prioritization.",
        rationale="Severity was estimated from recorded symptoms, current state, and vitals.",
        red_flags=red_flags[:6],
        next_steps=baseline_steps[:5],
    )


def analyze_mental_health_support(*, user: User, text: str, patient: Patient | None = None) -> MentalHealthSupportResponse:
    baseline = _mental_health_guidance(text, patient)
    mood_history = []
    if user.role == User.Role.PATIENT:
        mood_history = list(MoodLog.objects.filter(user=user).values_list("mood", flat=True)[:5])
    prompt = (
        "You are BayAfya Assistant providing supportive mental-health guidance inside a care platform.\n"
        "Return strictly valid JSON with keys: summary, risk_level, guidance, coping_steps, signals.\n"
        "risk_level must be one of: low, moderate, high.\n"
        "Be calm, supportive, and direct. Escalate clearly if there are safety concerns.\n\n"
        f"User role: {user.role}\n"
        f"Recent mood history: {json.dumps(mood_history, default=str)}\n"
        f"Current text: {text}\n"
        f"Fallback coping steps: {json.dumps(baseline, default=str)}\n"
    )
    ai_payload = _ai_json_response(
        prompt,
        defaults={
            "summary": "Use the information provided to support a calmer next step and encourage follow-up where needed.",
            "risk_level": "low",
            "guidance": "Continue with grounding, mood tracking, and professional support where appropriate.",
            "coping_steps": baseline,
            "signals": [],
        },
        thinking_level="low",
    )
    if ai_payload:
        return MentalHealthSupportResponse(
            summary=str(ai_payload.get("summary") or ""),
            risk_level=str(ai_payload.get("risk_level") or "low").lower(),
            guidance=str(ai_payload.get("guidance") or ""),
            coping_steps=[str(item) for item in (ai_payload.get("coping_steps") or baseline)][:4],
            signals=[str(item) for item in (ai_payload.get("signals") or [])][:4],
        )
    return MentalHealthSupportResponse(
        summary="Use the current mood entry to guide a calmer next step and follow-up if distress is rising.",
        risk_level="low",
        guidance="Track what you are feeling, use grounding, and escalate to a counselor or trusted human support if things worsen.",
        coping_steps=baseline,
        signals=[],
    )


def evaluate_patient_access(*, user: User, hospital: Hospital | None, patient: Patient | None, session: dict[str, Any] | None = None) -> PatientAccessDecision:
    if not patient:
        return PatientAccessDecision(True, "general", "No patient context is active.")

    if patient.user_id == user.id:
        return PatientAccessDecision(True, "self", "You are viewing your own patient record.")

    if hospital:
        access = HospitalAccess.objects.filter(
            user=user,
            hospital=hospital,
            status=HospitalAccess.Status.ACTIVE,
        ).first()
        if access and access.role in {HospitalAccess.Role.OWNER, HospitalAccess.Role.ADMIN}:
            return PatientAccessDecision(True, "hospital_admin", "Hospital leadership access is active.")

    if session and hospital:
        active_patient_id = session.get("clinical_patient_id")
        appointment_id = session.get("clinical_appointment_id")
        walk_in_id = session.get("clinical_walk_in_id")
        if active_patient_id == patient.id:
            staff_access = HospitalAccess.objects.filter(
                user=user,
                hospital=hospital,
                status=HospitalAccess.Status.ACTIVE,
            ).first()
            if staff_access and staff_access.role != HospitalAccess.Role.PATIENT:
                if user.role == User.Role.DOCTOR and appointment_id:
                    appointment = Appointment.objects.filter(
                        pk=appointment_id,
                        patient=patient,
                        doctor__user=user,
                    ).first()
                    if appointment:
                        return PatientAccessDecision(True, "active_encounter", "Doctor is in an active patient encounter.")
                if user.role == User.Role.DOCTOR and walk_in_id:
                    encounter = WalkInEncounter.objects.filter(
                        pk=walk_in_id,
                        patient=patient,
                        attending_doctor__user=user,
                    ).first()
                    if encounter:
                        return PatientAccessDecision(True, "active_walk_in", "Doctor is handling an active walk-in encounter.")
                return PatientAccessDecision(True, "active_chart", "Open patient chart context is active for this staff workspace.")

    grant_query = AssistantAccessGrant.objects.filter(
        requester=user,
        patient_user=patient.user,
        status=AssistantAccessGrant.Status.APPROVED,
    )
    if hospital:
        grant_query = grant_query.filter(models.Q(hospital_id__isnull=True) | models.Q(hospital_id=hospital.id))
    grant = next((item for item in grant_query.order_by("-created_at") if item.is_active), None)
    if grant:
        return PatientAccessDecision(True, "approved_grant", "Patient or hospital-approved assistant access is active.")

    if user.role in {User.Role.DOCTOR, User.Role.NURSE}:
        return PatientAccessDecision(
            False,
            "restricted",
            "Patient details require an active encounter or explicit approval from the patient or hospital administrator.",
        )

    return PatientAccessDecision(
        False,
        "restricted",
        "Detailed patient data is restricted for this role.",
    )


def _platform_context_summary(*, user: User, hospital: Hospital | None) -> list[str]:
    signals: list[str] = []
    platform_hospitals = list(Hospital.objects.filter(is_active=True).order_by("name").values_list("name", flat=True))
    if platform_hospitals:
        signals.append("Hospitals on platform: " + ", ".join(platform_hospitals[:6]))
    if hospital:
        signals.append(f"Hospital workspace: {hospital.name}")
        signals.append(f"Appointments today: {Appointment.objects.filter(hospital=hospital).count()}")
        signals.append(f"Queued patients: {QueueTicket.objects.filter(hospital=hospital, status=QueueTicket.Status.QUEUED).count()}")
        signals.append(f"Active admissions: {Admission.objects.filter(hospital=hospital, status=Admission.Status.ACTIVE).count()}")
        signals.append(f"Open lab requests: {LabTestRequest.objects.filter(hospital=hospital, status=LabTestRequest.Status.REQUESTED).count()}")
        signals.append(f"Recent chart entries: {MedicalRecord.objects.filter(hospital=hospital).count()}")
        signals.append(f"Billing entries: {Billing.objects.filter(hospital=hospital).count()}")
        recent_walk_ins = list(
            WalkInEncounter.objects.select_related("patient__user")
            .filter(hospital=hospital)
            .order_by("-last_updated_at", "-triaged_at", "-arrived_at")[:3]
        )
        if recent_walk_ins:
            signals.append(
                "Recent walk-ins: "
                + ", ".join(
                    f"{item.patient} ({item.get_status_display()})"
                    for item in recent_walk_ins
                )
            )
    if user.role == User.Role.PATIENT and hasattr(user, "patient"):
        signals.append("Patient self-service access is active.")
        signals.append(f"Recent patient observations: {VitalSign.objects.filter(patient=user.patient).count()}")
    elif user.role == User.Role.DOCTOR:
        open_consults = VideoConsultation.objects.filter(
            appointment__doctor__user=user,
            status=VideoConsultation.Status.ONGOING,
        ).count()
        signals.append(f"Ongoing telemedicine sessions: {open_consults}")
        signals.append(f"Recent doctor notes: {MedicalRecord.objects.filter(doctor__user=user).count()}")
    elif user.role == User.Role.COUNSELOR:
        recent_moods = MoodLog.objects.filter(user=user).count()
        signals.append(f"Mood logs available: {recent_moods}")
    elif user.role == User.Role.EMERGENCY_OPERATOR:
        requests_count = AmbulanceRequest.objects.filter(status__in=["pending", "assigned", "en_route"]).count()
        signals.append(f"Open ambulance requests: {requests_count}")
    return signals


def _format_chat_prompt(
    *,
    user: User,
    hospital: Hospital | None,
    patient: Patient | None,
    access: PatientAccessDecision,
    conversation: list[dict[str, str]],
    summary: str,
    suggestions: list[str],
    signals: list[str],
) -> str:
    patient_block: dict[str, Any] | str = "No patient context"
    if patient and access.allowed:
        patient_context = _latest_patient_context(patient, include_sensitive=True)
        patient_block = {
            "name": str(patient),
            "age_group": getattr(patient, "age_group", "Unknown"),
            "conditions": [
                item.condition_name or (item.condition.name if item.condition_id else "Recorded condition")
                for item in patient_context["conditions"][:6]
            ],
            "appointments": [
                f"{item.appointment_date} {item.appointment_time} ({item.get_status_display()})"
                for item in patient_context["appointments"][:5]
            ],
            "records": [
                f"{item.created_at:%Y-%m-%d}: {item.diagnosis[:160]}"
                for item in patient_context["records"][:5]
            ],
            "surgeries": [
                f"{item.scheduled_start:%Y-%m-%d %H:%M}: {item.procedure_name} ({item.get_status_display()})"
                for item in patient_context["surgeries"][:4]
            ],
            "admissions": [
                f"{item.created_at:%Y-%m-%d}: {item.get_status_display()} - {item.ward.name if item.ward_id else 'Ward'}"
                for item in patient_context["admissions"][:4]
            ],
            "walk_ins": [
                f"{item.arrived_at:%Y-%m-%d %H:%M}: {item.get_status_display()} - {item.severity_index}/100"
                for item in patient_context["walk_ins"][:4]
            ],
            "lab_results": [
                f"{item.completed_at:%Y-%m-%d}: {item.request.test_name} - {item.result_summary[:160]}"
                for item in patient_context["lab_results"][:4]
            ],
        }

    return (
        "You are BayAfya Assistant, a healthcare and platform operations assistant.\n"
        "Return strictly valid JSON with keys: reply, summary, suggestions, signals, safety.\n"
        "Reply in a calm, privacy-aware tone. Be concise, useful, and clinically careful.\n"
        "When a conversation thread is provided, act like a live participant in that thread: answer the latest message directly, keep continuity with the recent turn-taking, and avoid generic boilerplate.\n"
        "Never claim access to hidden records when access is restricted.\n"
        "If patient access is restricted, explain that clearly and offer safe next steps.\n"
        "You can answer general health questions, explain BayAfya features, and summarize chart context only when permitted.\n"
        "For any question about BayAfya platform data such as hospitals, patients, conditions, services, or reports, answer strictly from the platform context provided here.\n"
        "Do not answer with public-web information about unrelated real-world organizations named BayAfya unless the user explicitly asks for that.\n\n"
        f"User role: {user.role}\n"
        f"Hospital: {getattr(hospital, 'name', '') or 'None'}\n"
        f"Patient access scope: {access.scope}\n"
        f"Patient access note: {access.reason}\n"
        f"Patient context: {json.dumps(patient_block, default=str)}\n"
        f"Workspace summary: {summary}\n"
        f"Current suggestions: {json.dumps(suggestions, default=str)}\n"
        f"Signals: {json.dumps(signals, default=str)}\n"
        f"Conversation: {json.dumps(conversation[-8:], default=str)}\n"
    )


def build_assistant_response(*, user, hospital=None, patient=None, context="general", text="") -> AssistantResponse:
    current_patient = patient
    if current_patient is None and getattr(user, "role", None) == "patient" and hasattr(user, "patient"):
        current_patient = user.patient

    patient_context = _latest_patient_context(current_patient)
    signals = _platform_context_summary(user=user, hospital=hospital)
    title = "BayAfya Assistant"
    summary = "Guidance is based on the current workspace and the information available in the chart."
    suggestions: list[str] = []
    safety = "Use the assistant as a support layer. Clinical decisions remain with the care team."

    if hospital:
        signals.append(f"Hospital: {hospital.name}")
    if current_patient:
        signals.append(f"Patient: {current_patient}")
        if patient_context["summary"]:
            summary = patient_context["summary"]

    if context == "symptom":
        title = "Symptom support"
        suggestions = _symptom_guidance(text, current_patient)
        safety = "Escalate urgent or rapidly worsening symptoms without delay."
    elif context == "mental_health":
        title = "Wellbeing support"
        suggestions = _mental_health_guidance(text, current_patient)
        safety = "If there is any safety concern, move to immediate human support."
    elif context == "clinical":
        title = "Clinical workspace support"
        conditions = patient_context["conditions"]
        if conditions:
            suggestions.append("Review the active problem list before writing new notes.")
            suggestions.append("Confirm whether any condition should be marked as resolved or followed up.")
        if patient_context["appointments"]:
            suggestions.append("Open the current appointment before creating a new medical record.")
        if patient_context["surgeries"]:
            suggestions.append("Check surgical timing, anesthesia type, and theatre readiness.")
        if not suggestions:
            suggestions.append("Select a patient to surface chart-linked guidance.")
    else:
        title = "Care assistant"
        suggestions = [
            "Open the current hospital workspace to continue with patient care.",
            "Review active conditions, appointments, and any linked emergency activity.",
        ]
        if current_patient:
            suggestions.append("Use the patient record to review the latest chart history.")

    if current_patient and getattr(current_patient, "age_group", None):
        signals.append(f"Age group: {current_patient.age_group}")

    prompt = _format_chat_prompt(
        user=user,
        hospital=hospital,
        patient=current_patient,
        access=PatientAccessDecision(True, "suggestion", "Suggestion mode"),
        conversation=[{"role": "user", "content": text}],
        summary=summary,
        suggestions=suggestions,
        signals=signals,
    )
    ai_payload = _ai_json_response_with_correction(
        prompt,
        defaults={
            "title": title,
            "summary": summary,
            "suggestions": suggestions[:4],
            "signals": signals[:4],
            "safety": safety,
        },
        correction=(
            "Avoid generic platform boilerplate. Answer directly from BayAfya context, "
            "keep suggestions specific, and do not repeat default fallback wording."
        ),
        thinking_level="low",
    )
    if ai_payload:
        return AssistantResponse(
            title=ai_payload.get("title") or title,
            summary=ai_payload.get("summary") or summary,
            suggestions=list(ai_payload.get("suggestions") or suggestions)[:4],
            signals=list(ai_payload.get("signals") or signals)[:4],
            safety=ai_payload.get("safety") or safety,
        )

    return AssistantResponse(title=title, summary=summary, suggestions=suggestions[:4], signals=signals[:4], safety=safety)


def build_assistant_chat_response(
    *,
    user: User,
    hospital: Hospital | None = None,
    patient: Patient | None = None,
    conversation: list[dict[str, str]] | None = None,
    context: str = "general",
    session: dict[str, Any] | None = None,
) -> AssistantChatResponse:
    conversation = conversation or []
    access = evaluate_patient_access(user=user, hospital=hospital, patient=patient, session=session)
    patient_context = _latest_patient_context(patient, include_sensitive=access.allowed)
    signals = _platform_context_summary(user=user, hospital=hospital)
    mode_labels = {
        "patient_chart": "Patient chart",
        "triage": "Triage",
        "mental_health": "Mental health",
        "hospital_operations": "Hospital operations",
        "general": "General care",
    }
    mode_label = mode_labels.get(context, "General care")
    if patient:
        signals.append(f"Patient context: {patient}")
        if getattr(patient, "age_group", None):
            signals.append(f"Age group: {patient.age_group}")
    if access.allowed:
        summary = patient_context["summary"] or "Patient context is active for this conversation."
    elif patient:
        summary = access.reason
    else:
        summary = "Ask about care guidance, BayAfya workflows, appointments, records, pharmacy, or hospital services."
        if hospital:
            summary = f"{hospital.name} workspace is active. " + " ".join(signals[:4])
    summary = f"{mode_label} mode. {summary}"

    latest_user_text = next((entry.get("content", "") for entry in reversed(conversation) if entry.get("role") == "user"), "")
    suggestions = []
    lowered = latest_user_text.lower()
    platform_hospital_names = list(Hospital.objects.filter(is_active=True).order_by("name").values_list("name", flat=True))
    if context == "triage":
        suggestions.extend(_symptom_guidance(latest_user_text, patient if access.allowed else None))
        if not latest_user_text:
            suggestions.extend(
                [
                    "Summarize symptoms, duration, severity, and any urgent warning signs.",
                    "Ask for next-step triage guidance when symptoms are worsening or acute.",
                ]
            )
    elif context == "mental_health":
        suggestions.extend(_mental_health_guidance(latest_user_text, patient if access.allowed else None))
        if not latest_user_text:
            suggestions.extend(
                [
                    "Ask for mood support, coping guidance, or follow-up planning.",
                    "Use this mode for anxiety, distress, therapy support, or wellbeing questions.",
                ]
            )
    elif context == "patient_chart":
        if access.allowed and patient:
            suggestions.extend(
                [
                    "Summarize the active condition list, latest records, surgery items, and lab results.",
                    "Outline the follow-up actions that remain open in this chart.",
                ]
            )
        else:
            suggestions.append("Activate an approved patient context to review patient-chart details.")
    elif context == "hospital_operations":
        suggestions.extend(
            [
                "Ask for disease trends, admissions, theatre scheduling, or operational reporting guidance.",
                "Use this mode for hospital-wide workflows, service demand, and reporting questions.",
            ]
        )
    elif any(term in lowered for term in ["symptom", "pain", "fever", "cough", "breath", "mood", "anxious"]):
        suggestions.extend(_symptom_guidance(latest_user_text, patient if access.allowed else None))
    elif "mental" in lowered or "stress" in lowered or "sad" in lowered:
        suggestions.extend(_mental_health_guidance(latest_user_text, patient if access.allowed else None))
    if not suggestions:
        if access.allowed and patient:
            suggestions = [
                "I can summarize the current chart, recent appointments, active conditions, and planned surgery items for this patient.",
                "I can also explain BayAfya workflows such as telemedicine, pharmacy, admissions, and documentation steps.",
            ]
        else:
            suggestions = [
                "I can answer general health questions and explain how BayAfya workflows operate.",
                "Detailed patient data stays restricted unless you are the patient, a hospital owner/admin, or the treating doctor in an active encounter.",
            ]

    safety = "Assistant guidance supports care decisions but does not replace clinician judgment, emergency escalation, or hospital policy."

    prompt = _format_chat_prompt(
        user=user,
        hospital=hospital,
        patient=patient if access.allowed else None,
        access=access,
        conversation=conversation,
        summary=summary,
        suggestions=[f"Mode: {mode_label}"] + suggestions,
        signals=signals,
    )
    ai_payload = _ai_json_response_with_correction(
        prompt,
        defaults={
            "reply": "",
            "summary": summary,
            "suggestions": suggestions[:4],
            "signals": signals[:4],
            "safety": safety,
        },
        correction=(
            "Do not reply with generic 'mode is active' boilerplate unless there is truly no better platform-grounded answer. "
            "If the user asks about BayAfya data, answer from BayAfya data directly. "
            "If access is restricted, say exactly what is restricted and what can be done next."
        ),
        thinking_level="low",
    )

    if ai_payload and ai_payload.get("reply"):
        reply = ai_payload["reply"]
        summary = ai_payload.get("summary") or summary
        suggestions = list(ai_payload.get("suggestions") or suggestions)[:4]
        signals = list(ai_payload.get("signals") or signals)[:4]
        safety = ai_payload.get("safety") or safety
    else:
        if access.allowed and patient:
            reply = (
                f"{mode_label} mode is active. I can work with {patient}'s current chart context here. "
                f"{patient_context['summary'] or 'The active encounter is ready for review.'} "
                "Ask for a summary of appointments, condition history, surgery planning, or BayAfya workflow steps."
            )
        elif patient:
            reply = f"{mode_label} mode is active. {access.reason}"
        elif "hospital" in lowered and any(term in lowered for term in ["added", "platform", "available", "list", "which"]):
            if platform_hospital_names:
                reply = "The hospitals currently added to the BayAfya platform are: " + ", ".join(platform_hospital_names) + "."
            else:
                reply = "There are no hospitals added to the BayAfya platform yet."
        else:
            if hospital:
                reply = (
                    f"{mode_label} mode is active for {hospital.name}. "
                    "I can answer questions about current hospital activity, queues, admissions, lab work, pharmacy, appointments, and role-specific user records available in this workspace."
                )
            else:
                reply = (
                    f"{mode_label} mode is active. I can help with BayAfya workflows, appointments, pharmacy activity, telemedicine, ambulance requests, and general health guidance. "
                    "If you need a patient-specific summary, open an active encounter or use an approved access path."
                )

    return AssistantChatResponse(
        reply=reply,
        summary=summary,
        suggestions=suggestions[:4],
        signals=signals[:4],
        safety=safety,
        access_scope=access.scope,
        can_view_patient_details=bool(patient and access.allowed),
        patient_label=str(patient) if patient else "",
    )
