from datetime import timedelta
import json
import logging

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
import secrets

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import NoReverseMatch, reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from ambulance.models import AmbulanceRequest
from hospital.models import (
    Admission,
    Appointment,
    Billing,
    Certification,
    Doctor,
    LabTestRequest,
    LabTestResult,
    MedicalRecord,
    PatientCondition,
    PharmacyTask,
    QueueTicket,
    ShiftAssignment,
    StaffProfile,
    SurgicalCase,
    VitalSign,
    HospitalAccess,
    Hospital,
    HospitalInvitation,
    Patient,
)


logger = logging.getLogger(__name__)
from mental_health.models import MoodLog, TherapySession
from pharmacy.models import Order
from telemedicine.models import Prescription, VideoConsultation
from .assistant import build_assistant_chat_response, build_assistant_response, evaluate_patient_access
from .email_backends import BrevoEmailAuthError

from .forms import (
    AssistantAccessGrantForm,
    DirectConversationForm,
    HospitalAccessRedeemForm,
    JoinConversationForm,
    ProfileUpdateForm,
    StyledEmailVerificationCodeForm,
    StyledEmailVerificationResendForm,
    StyledPasswordChangeForm,
    TeamConversationForm,
    UserRegistrationForm,
)
from .models import AssistantAccessGrant, Notification, StaffConversation, StaffConversationParticipant, StaffMessage, User
from .services import broadcast_hospital_update, broadcast_staff_message, send_email_verification, send_user_notification


def _build_dashboard_experience(user, stats):
    role_map = {
        User.Role.PATIENT: {
            "kicker": "Patient care view",
            "headline": "Everything related to your care journey is organized in one place.",
            "summary": "Monitor appointments, records, pharmacy activity, and emergency requests with a calmer patient-first interface.",
            "accent_icon": "bi-person-heart",
            "chart_title": "Care activity mix",
            "empty_title": "No care activity yet",
            "empty_copy": "Book an appointment or run a symptom check to start building your care timeline.",
        },
        User.Role.DOCTOR: {
            "kicker": "Doctor care view",
            "headline": "Today’s clinical workload, consultations, and authored records in one live workspace.",
            "summary": "Use the dashboard to prioritize appointments, launch virtual care, and keep documentation moving.",
            "accent_icon": "bi-person-badge",
            "chart_title": "Clinical workload split",
            "empty_title": "No clinical items yet",
            "empty_copy": "Once appointments or virtual consultations are assigned, they will appear here.",
        },
        User.Role.NURSE: {
            "kicker": "Nursing station view",
            "headline": "Track patient observations, ward activity, and bedside support from a focused care board.",
            "summary": "Review patient vitals, active admissions, and ward workload in a streamlined nursing workspace.",
            "accent_icon": "bi-clipboard2-pulse",
            "chart_title": "Ward activity",
            "empty_title": "No nursing activity yet",
            "empty_copy": "Vital signs and ward assignments will appear here once nursing entries are recorded.",
        },
        User.Role.RECEPTIONIST: {
            "kicker": "Front desk view",
            "headline": "Coordinate registration, appointment flow, and queue movement from the reception desk.",
            "summary": "Keep appointment scheduling, patient intake, and waiting room flow organized in one screen.",
            "accent_icon": "bi-person-workspace",
            "chart_title": "Front desk flow",
            "empty_title": "No reception activity yet",
            "empty_copy": "Appointment bookings and queue tickets will appear here as the front desk workflow begins.",
        },
        User.Role.LAB_TECHNICIAN: {
            "kicker": "Laboratory view",
            "headline": "Follow pending investigations and result entry from the laboratory desk.",
            "summary": "Review test requests, results in progress, and completed laboratory work without losing context.",
            "accent_icon": "bi-eyedropper",
            "chart_title": "Lab workload",
            "empty_title": "No laboratory activity yet",
            "empty_copy": "Lab test requests will appear here once clinicians request investigations.",
        },
        User.Role.COUNSELOR: {
            "kicker": "Behavioral health view",
            "headline": "Coordinate therapy sessions, mood engagement, and supportive care services from one clinical workspace.",
            "summary": "Follow counseling schedules and patient wellbeing activity through a dedicated behavioral health dashboard.",
            "accent_icon": "bi-flower2",
            "chart_title": "Support activity",
            "empty_title": "No counseling activity yet",
            "empty_copy": "Schedule a therapy session or publish wellness resources to activate this dashboard.",
        },
        User.Role.PHARMACIST: {
            "kicker": "Pharmacy care view",
            "headline": "Track dispensing demand, fulfillment volume, and order completion at a glance.",
            "summary": "Review medicine orders, fulfillment progress, and stock-sensitive pharmacy activity in one place.",
            "accent_icon": "bi-capsule-pill",
            "chart_title": "Order flow",
            "empty_title": "No pharmacy activity yet",
            "empty_copy": "Orders and fulfillment metrics will populate as patients begin using the pharmacy module.",
        },
        User.Role.EMERGENCY_OPERATOR: {
            "kicker": "Emergency response view",
            "headline": "Critical response indicators are surfaced clearly for rapid operational action.",
            "summary": "Monitor emergency requests, active dispatch cases, and ambulance response demand in real time.",
            "accent_icon": "bi-truck-front",
            "chart_title": "Dispatch load",
            "empty_title": "No emergency requests yet",
            "empty_copy": "Ambulance requests will appear here once emergency workflows are active.",
        },
        User.Role.ADMIN: {
            "kicker": "Hospital command view",
            "headline": "Track hospital throughput, staffing, wards, and service demand from a single command dashboard.",
            "summary": "Monitor the overall platform footprint and system-wide operational performance across clinical and administrative work.",
            "accent_icon": "bi-grid-1x2-fill",
            "chart_title": "Platform composition",
            "empty_title": "No platform data yet",
            "empty_copy": "As users and care modules become active, the operational summary will populate.",
        },
    }
    fallback = role_map[User.Role.ADMIN]
    config = role_map.get(user.role, fallback)
    chart_data = [{"label": label.replace("_", " ").title(), "value": value} for label, value in stats.items()]
    return {
        **config,
        "chart_data": chart_data,
        "max_chart": max([item["value"] for item in chart_data], default=1),
    }


def _profile_cards(user):
    return [
        {"label": "Name", "value": user.get_full_name() or user.username, "icon": "bi-person"},
        {"label": "Role", "value": user.get_role_display(), "icon": "bi-badge-ad"},
        {"label": "Email", "value": user.email or "Not provided", "icon": "bi-envelope"},
        {"label": "Phone", "value": user.phone or "Not provided", "icon": "bi-telephone"},
    ]


def _avatar_data(user):
    if getattr(user, "profile_picture", None):
        return {"url": user.profile_picture.url, "alt": user.get_full_name() or user.username}
    return {"url": "", "alt": user.get_full_name() or user.username}


def _user_hospital_count(user):
    hospital_ids = set(
        HospitalAccess.objects.filter(user=user, status=HospitalAccess.Status.ACTIVE).values_list("hospital_id", flat=True)
    )
    if user.role == User.Role.ADMIN:
        hospital_ids.update(Hospital.objects.filter(owner=user).values_list("id", flat=True))
    return len({hospital_id for hospital_id in hospital_ids if hospital_id})


def _safe_reverse(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""


def _authenticated_entry_redirect():
    return _safe_reverse("hospital:dashboard") or _safe_reverse("profile") or _safe_reverse("home") or "/"


def _redirect_authenticated_user(request):
    if request.user.is_authenticated:
        return redirect(_authenticated_entry_redirect())
    return None


class GuestOnlyAccessMixin:
    def dispatch(self, request, *args, **kwargs):
        redirect_response = _redirect_authenticated_user(request)
        if redirect_response is not None:
            return redirect_response
        return super().dispatch(request, *args, **kwargs)


class BayAfyaLoginView(GuestOnlyAccessMixin, auth_views.LoginView):
    redirect_authenticated_user = True


class BayAfyaPasswordResetView(GuestOnlyAccessMixin, auth_views.PasswordResetView):
    pass


class BayAfyaPasswordResetDoneView(GuestOnlyAccessMixin, auth_views.PasswordResetDoneView):
    pass


class BayAfyaPasswordResetConfirmView(GuestOnlyAccessMixin, auth_views.PasswordResetConfirmView):
    pass


class BayAfyaPasswordResetCompleteView(GuestOnlyAccessMixin, auth_views.PasswordResetCompleteView):
    pass


def _send_email_verification(request, user, *, recipient_email=None):
    today = timezone.localdate()
    now = timezone.now()
    if user.email_verification_send_date != today:
        user.email_verification_send_date = today
        user.email_verification_send_count = 0
    if user.email_verification_failed_date != today:
        user.email_verification_failed_date = today
        user.email_verification_failed_count = 0
    if user.email_verification_locked_until and user.email_verification_locked_until > now:
        local_unlock = timezone.localtime(user.email_verification_locked_until)
        raise ValidationError(
            f"Verification is locked until {local_unlock:%Y-%m-%d %H:%M}. Please try again tomorrow."
        )
    if user.email_verification_send_count >= 3:
        raise ValidationError("BayAfya can send only three verification codes per day. Please try again tomorrow.")
    code = "".join(secrets.choice("0123456789") for _ in range(7))
    try:
        delivered = send_email_verification(request, user, code, recipient_email=recipient_email)
    except BrevoEmailAuthError as exc:
        logger.exception("Brevo rejected the configured API key while sending verification for user %s.", getattr(user, "id", "unknown"))
        raise ValidationError(
            "BayAfya email is not configured correctly right now. Brevo rejected the configured API key."
        ) from exc
    except Exception as exc:
        logger.exception("Email verification send failed for user %s.", getattr(user, "id", "unknown"))
        raise ValidationError(
            "BayAfya could not send the verification code right now. Please try again shortly."
        ) from exc
    if not delivered:
        raise ValidationError(
            "BayAfya could not send the verification code right now. Please try again shortly."
        )
    user.email_verification_code = code
    user.email_verification_sent_at = now
    user.email_verification_send_count += 1
    user.save(
        update_fields=[
            "email_verification_code",
            "email_verification_sent_at",
            "email_verification_send_count",
            "email_verification_send_date",
            "email_verification_failed_count",
            "email_verification_failed_date",
        ]
    )
    return code


def _verification_lock_until():
    tomorrow = timezone.localdate() + timedelta(days=1)
    naive_midnight = timezone.datetime.combine(tomorrow, timezone.datetime.min.time())
    return timezone.make_aware(naive_midnight, timezone.get_current_timezone())


def _verification_json_response(*, ok, message, status=200, errors=None, verified=False, locked_until=None):
    payload = {
        "ok": ok,
        "message": message,
        "verified": verified,
    }
    if errors:
        payload["errors"] = errors
    if locked_until:
        payload["locked_until"] = timezone.localtime(locked_until).strftime("%Y-%m-%d %H:%M")
    return JsonResponse(payload, status=status)


def _metric_links(user):
    default_hospital = _safe_reverse("hospital:dashboard")
    return {
        "appointments": _safe_reverse("hospital:book_appointment") if user.role == User.Role.PATIENT else default_hospital,
        "scheduled_appointments": default_hospital,
        "appointments_today": default_hospital,
        "records": default_hospital,
        "records_authored": default_hospital,
        "orders": _safe_reverse("pharmacy:home"),
        "delivered_orders": _safe_reverse("pharmacy:home"),
        "ambulance_requests": _safe_reverse("ambulance:request"),
        "active_cases": _safe_reverse("ambulance:request"),
        "consultations": _safe_reverse("telemedicine:dashboard"),
        "therapy_sessions": _safe_reverse("mental_health:dashboard"),
        "recent_mood_logs": _safe_reverse("mental_health:dashboard"),
        "patients_under_observation": _safe_reverse("hospital:walk_in_hub"),
        "active_admissions": _safe_reverse("hospital:admission_dashboard"),
        "pending_labs": _safe_reverse("hospital:walk_in_hub"),
        "completed_labs": _safe_reverse("hospital:walk_in_hub"),
        "recent_results": _safe_reverse("hospital:clinical_insights"),
        "queued_patients": _safe_reverse("hospital:walk_in_hub"),
        "users": default_hospital,
        "billings": default_hospital,
        "hospitals": default_hospital,
    }


def _metric_icon(label):
    icon_map = {
        "users": "bi-people",
        "appointments": "bi-calendar2-week",
        "billings": "bi-receipt-cutoff",
        "hospitals": "bi-building",
        "scheduled_appointments": "bi-calendar-check",
        "appointments_today": "bi-calendar-date",
        "records": "bi-journal-medical",
        "records_authored": "bi-clipboard2-pulse",
        "orders": "bi-capsule-pill",
        "delivered_orders": "bi-bag-check",
        "ambulance_requests": "bi-truck-front",
        "active_cases": "bi-broadcast-pin",
        "consultations": "bi-camera-video",
        "therapy_sessions": "bi-chat-heart",
        "recent_mood_logs": "bi-emoji-smile",
        "patients_under_observation": "bi-heart-pulse",
        "active_admissions": "bi-hospital",
        "pending_labs": "bi-beaker",
        "completed_labs": "bi-clipboard2-check",
        "recent_results": "bi-activity",
        "queued_patients": "bi-hourglass-split",
    }
    return icon_map.get(label, "bi-bar-chart-line-fill")


def _staff_messaging_roles():
    return {
        User.Role.ADMIN,
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.LAB_TECHNICIAN,
        User.Role.PHARMACIST,
        User.Role.COUNSELOR,
        User.Role.EMERGENCY_OPERATOR,
    }


def _staff_hospital_accesses(user):
    return list(
        HospitalAccess.objects.select_related("hospital")
        .filter(user=user, hospital__is_active=True, status=HospitalAccess.Status.ACTIVE)
        .exclude(role=HospitalAccess.Role.PATIENT)
    )


def _staff_messaging_required(user):
    if user.role not in _staff_messaging_roles() or not _staff_hospital_accesses(user):
        raise PermissionDenied("Messaging is available for BayAfya staff workspaces.")


def _messaging_access_required(user):
    if user.role == User.Role.PATIENT:
        if not hasattr(user, "patient"):
            raise PermissionDenied("Patient messaging requires an active patient profile.")
        return
    _staff_messaging_required(user)


def _conversation_title(conversation, viewer):
    if conversation.kind == StaffConversation.Kind.TEAM:
        return conversation.title or conversation.get_purpose_display()
    others = [
        participant.user.get_full_name() or participant.user.username
        for participant in conversation.participants.select_related("user")
        if participant.user_id != viewer.id
    ]
    return others[0] if others else (conversation.title or "Direct conversation")


def _conversation_subtitle(conversation):
    bits = []
    if conversation.kind == StaffConversation.Kind.TEAM:
        bits.append(conversation.get_purpose_display())
    else:
        bits.append("Direct message")
    if conversation.hospital_id:
        bits.append(conversation.hospital.name)
    if conversation.linked_patient_id:
        bits.append(f"Patient: {conversation.linked_patient}")
    return " · ".join(bits)


def _serialize_staff_message(message):
    return {
        "id": message.pk,
        "body": message.body,
        "kind": message.kind,
        "sender_id": message.sender_id,
        "sender": message.sender_label
        or (message.sender.get_full_name() or message.sender.username if message.sender_id else "BayAfya Assistant"),
        "created_at": message.created_at.isoformat(),
    }


def _staff_messaging_hospital_ids(user):
    if user.role == User.Role.PATIENT and hasattr(user, "patient"):
        hospital_id = user.patient.hospital_id
        return {hospital_id} if hospital_id else set()
    return {access.hospital_id for access in _staff_hospital_accesses(user)}


def _messaging_hospital_ids(user):
    if user.role == User.Role.PATIENT and hasattr(user, "patient"):
        hospital_id = user.patient.hospital_id
        return {hospital_id} if hospital_id else set()
    return _staff_messaging_hospital_ids(user)


def _messaging_conversation_queryset(user):
    queryset = StaffConversation.objects.filter(is_active=True).select_related("hospital", "linked_patient", "created_by").prefetch_related("participants__user", "messages")
    if user.role == User.Role.PATIENT and hasattr(user, "patient"):
        queryset = queryset.filter(
            Q(participants__user=user) | Q(linked_patient__user=user)
        )
    else:
        queryset = queryset.filter(participants__user=user)
    return queryset.distinct().order_by("-last_message_at", "-updated_at")


def _staff_conversation_queryset(user):
    return (
        StaffConversation.objects.filter(participants__user=user, is_active=True)
        .select_related("hospital", "linked_patient", "created_by")
        .prefetch_related("participants__user", "messages")
        .distinct()
        .order_by("-last_message_at", "-updated_at")
    )


def _conversation_can_administer(conversation, user):
    participant = next((item for item in conversation.participants.all() if item.user_id == user.id), None)
    if participant and participant.role == StaffConversationParticipant.Role.ADMIN:
        return True
    return conversation.created_by_id == user.id


def _conversation_summary(conversation, viewer):
    participant = next((item for item in conversation.participants.all() if item.user_id == viewer.id), None)
    last_message = next(iter(reversed(list(conversation.messages.all()))), None) if conversation.messages.exists() else None
    unread_count = 0
    if participant:
        unread_messages = conversation.messages.exclude(sender_id=viewer.id)
        if participant.last_read_at:
            unread_messages = unread_messages.filter(created_at__gt=participant.last_read_at)
        unread_count = unread_messages.count()
    return {
        "id": conversation.id,
        "title": _conversation_title(conversation, viewer),
        "subtitle": _conversation_subtitle(conversation),
        "kind": conversation.kind,
        "purpose": conversation.get_purpose_display(),
        "join_code": conversation.join_code if conversation.kind == StaffConversation.Kind.TEAM else "",
        "assistant_enabled": conversation.assistant_enabled,
        "linked_patient": str(conversation.linked_patient) if conversation.linked_patient_id else "",
        "participant_count": conversation.participants.count(),
        "last_message_preview": (last_message.body[:110] if last_message else "No messages yet."),
        "last_message_at": last_message.created_at if last_message else conversation.created_at,
        "unread_count": unread_count,
        "can_administer": _conversation_can_administer(conversation, viewer),
    }


def _communications_json_response(ok=True, message="", status_code=None, **extra):
    payload = {"ok": ok, "message": message}
    payload.update(extra)
    return JsonResponse(payload, status=status_code or (200 if ok else 400))


def _staff_conversations_context(request, *, conversation_id=None):
    _messaging_access_required(request.user)
    current_access = _current_hospital_access(request)
    current_hospital = current_access.hospital if current_access else None
    if request.user.role == User.Role.PATIENT and hasattr(request.user, "patient"):
        current_hospital = current_hospital or request.user.patient.hospital
    allowed_hospital_ids = _messaging_hospital_ids(request.user)
    conversations = list(_messaging_conversation_queryset(request.user))
    if current_hospital:
        prioritized = [item for item in conversations if item.hospital_id in {None, current_hospital.id}]
        others = [item for item in conversations if item.hospital_id not in {None, current_hospital.id}]
        conversations = prioritized + others
    try:
        conversation_id = int(conversation_id) if conversation_id else None
    except (TypeError, ValueError):
        conversation_id = None
    active_conversation = None
    if conversation_id:
        active_conversation = next((item for item in conversations if item.id == conversation_id), None)
    if active_conversation is None and conversations:
        active_conversation = conversations[0]

    direct_form = DirectConversationForm(hospital=current_hospital, user=request.user, viewer=request.user)
    team_form = TeamConversationForm(hospital=current_hospital, creator=request.user) if request.user.role != User.Role.PATIENT else None
    join_form = JoinConversationForm() if request.user.role != User.Role.PATIENT else None

    return {
        "current_hospital": current_hospital,
        "staff_conversations": [_conversation_summary(item, request.user) for item in conversations],
        "active_conversation": active_conversation,
        "active_conversation_messages": [_serialize_staff_message(message) for message in active_conversation.messages.all()] if active_conversation else [],
        "active_conversation_participants": list(active_conversation.participants.select_related("user")) if active_conversation else [],
        "can_manage_active_conversation": _conversation_can_administer(active_conversation, request.user) if active_conversation else False,
        "direct_conversation_form": direct_form,
        "team_conversation_form": team_form,
        "join_conversation_form": join_form,
        "team_purpose_choices": StaffConversation.Purpose.choices,
        "allowed_messaging_hospital_ids": allowed_hospital_ids,
        "can_create_team": request.user.role != User.Role.PATIENT,
        "can_join_team": request.user.role != User.Role.PATIENT,
    }


def _active_conversation_for_user(user, conversation_id):
    return get_object_or_404(
        _messaging_conversation_queryset(user),
        pk=conversation_id,
    )


def _create_staff_message(conversation, sender, body):
    message = StaffMessage.objects.create(
        conversation=conversation,
        sender=sender,
        sender_label=sender.get_full_name() or sender.username,
        body=body,
        kind=StaffMessage.Kind.USER,
    )
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=["last_message_at", "updated_at"])
    for participant in conversation.participants.select_related("user"):
        if participant.user_id == sender.id:
            continue
        send_user_notification(
            participant.user,
            f"New message in {conversation.title or conversation.get_purpose_display()}",
            f"{sender.get_full_name() or sender.username}: {body[:120]}",
        )
    return message


def _create_staff_assistant_reply(conversation, user, trigger_text):
    if not conversation.assistant_enabled:
        return None
    history = []
    for item in conversation.messages.order_by("-created_at")[:12]:
        if item.kind == StaffMessage.Kind.SYSTEM:
            continue
        role = "assistant" if item.kind == StaffMessage.Kind.ASSISTANT else "user"
        history.append({"role": role, "content": item.body})
    history.reverse()
    prompt = (
        trigger_text.replace("@bayafya", "")
        .replace("@BayAfya", "")
        .replace("/bayafya", "")
        .strip()
        or trigger_text
    )
    history.append({"role": "user", "content": prompt})
    response = build_assistant_chat_response(
        user=user,
        hospital=conversation.hospital,
        patient=conversation.linked_patient,
        conversation=history,
        context="patient_chart" if conversation.linked_patient_id else "hospital_operations",
        session=None,
    )
    if not response.reply:
        return None
    message = StaffMessage.objects.create(
        conversation=conversation,
        sender=None,
        sender_label="BayAfya Assistant",
        body=response.reply,
        kind=StaffMessage.Kind.ASSISTANT,
    )
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=["last_message_at", "updated_at"])
    return message


@login_required
def communications(request):
    context = _staff_conversations_context(request, conversation_id=request.GET.get("conversation"))
    return render(request, "core/communications.html", context)


@login_required
def notifications_feed(request):
    try:
        from hospital.views import _sweep_overdue_appointments_and_surgeries

        active_access = _current_hospital_access(request)
        if active_access and active_access.hospital_id:
            _sweep_overdue_appointments_and_surgeries(active_access.hospital)
    except Exception:
        pass
    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")[:12]
    try:
        since_id = int(request.GET.get("since_id", "0") or 0)
    except (TypeError, ValueError):
        since_id = 0
    items = [
        {
            "id": item.id,
            "title": item.title,
            "message": item.message,
            "created_at": item.created_at.isoformat(),
            "is_read": item.is_read,
        }
        for item in notifications
        if item.id > since_id
    ]
    return JsonResponse(
        {
            "items": list(reversed(items)),
            "latest_id": notifications[0].id if notifications else since_id,
        }
    )


@login_required
@require_http_methods(["POST"])
def create_direct_conversation(request):
    _messaging_access_required(request.user)
    current_access = _current_hospital_access(request)
    current_hospital = current_access.hospital if current_access else None
    if request.user.role == User.Role.PATIENT and hasattr(request.user, "patient"):
        current_hospital = current_hospital or request.user.patient.hospital
    form = DirectConversationForm(request.POST, hospital=current_hospital, user=request.user, viewer=request.user)
    if not form.is_valid():
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return _communications_json_response(
                False,
                "The selected contact could not be reached from this workspace.",
                errors=form.errors,
            )
        messages.error(request, "The selected contact could not be reached from this workspace.")
        return redirect("communications")

    recipient = form.cleaned_data["recipient"]
    conversation = (
        StaffConversation.objects.filter(kind=StaffConversation.Kind.DIRECT, is_active=True, participants__user=request.user)
        .filter(participants__user=recipient)
        .annotate(member_count=Count("participants", distinct=True))
        .filter(member_count=2)
        .select_related("hospital")
        .first()
    )
    if conversation is None:
        conversation = StaffConversation.objects.create(
            hospital=current_hospital,
            kind=StaffConversation.Kind.DIRECT,
            purpose=StaffConversation.Purpose.CARE_COORDINATION,
            created_by=request.user,
            title="",
        )
        StaffConversationParticipant.objects.create(
            conversation=conversation,
            user=request.user,
            role=StaffConversationParticipant.Role.ADMIN,
            last_read_at=timezone.now(),
        )
        StaffConversationParticipant.objects.create(
            conversation=conversation,
            user=recipient,
            role=StaffConversationParticipant.Role.MEMBER,
        )
        StaffMessage.objects.create(
            conversation=conversation,
            sender=None,
            sender_label="BayAfya System",
            body=f"Direct conversation started between {request.user.get_full_name() or request.user.username} and {recipient.get_full_name() or recipient.username}.",
            kind=StaffMessage.Kind.SYSTEM,
        )
        conversation.last_message_at = timezone.now()
        conversation.save(update_fields=["last_message_at", "updated_at"])
        send_user_notification(
            recipient,
            "New BayAfya conversation",
            f"{request.user.get_full_name() or request.user.username} started a direct conversation with you.",
        )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return _communications_json_response(
            True,
            "Direct conversation opened.",
            conversation_id=conversation.id,
            redirect=f"{reverse('communications')}?conversation={conversation.id}",
        )
    return redirect(f"{reverse('communications')}?conversation={conversation.id}")


@login_required
def communication_messages(request, conversation_id):
    _messaging_access_required(request.user)
    conversation = _active_conversation_for_user(request.user, conversation_id)
    StaffConversationParticipant.objects.filter(
        conversation=conversation,
        user=request.user,
    ).update(last_read_at=timezone.now())
    try:
        since_id = int(request.GET.get("since_id", "0") or 0)
    except (TypeError, ValueError):
        since_id = 0
    messages_qs = conversation.messages.all()
    if since_id:
        messages_qs = messages_qs.filter(pk__gt=since_id)
    items = [_serialize_staff_message(message) for message in messages_qs.order_by("created_at")]
    latest = conversation.messages.order_by("-pk").first()
    return JsonResponse(
        {
            "messages": items,
            "latest_id": latest.pk if latest else since_id,
        }
    )


@login_required
@require_http_methods(["POST"])
def send_communication_message(request, conversation_id):
    _messaging_access_required(request.user)
    conversation = _active_conversation_for_user(request.user, conversation_id)
    body = (request.POST.get("message") or "").strip()
    if not body:
        return JsonResponse({"ok": False, "message": "Enter a message before sending."}, status=400)
    message = _create_staff_message(conversation, request.user, body)
    broadcast_staff_message(conversation, message)
    payload = {
        "ok": True,
        "message": _serialize_staff_message(message),
    }
    if "@bayafya" in body.lower() or "/bayafya" in body.lower():
        assistant_message = _create_staff_assistant_reply(conversation, request.user, body)
        if assistant_message:
            broadcast_staff_message(conversation, assistant_message)
            payload["assistant_message"] = _serialize_staff_message(assistant_message)
    return JsonResponse(payload)


@login_required
@require_http_methods(["POST"])
def change_password(request):
    form = StyledPasswordChangeForm(user=request.user, data=request.POST)
    if not form.is_valid():
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "errors": {field: list(messages) for field, messages in form.errors.items()}}, status=400)
        messages.error(request, "Please correct the password fields and try again.")
        return redirect("profile")

    user = form.save()
    logout(request)
    redirect_url = f"{reverse('login')}?password_changed=1"
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "message": "Your password has been updated. Please sign in again.",
                "redirect": redirect_url,
                "username": user.username,
            }
        )
    return redirect(redirect_url)


@login_required
@require_http_methods(["POST"])
def update_hospital_access_status(request):
    access_id = request.POST.get("access_id")
    action = (request.POST.get("action") or "").strip().lower()
    reason = (request.POST.get("reason") or "").strip()
    access = get_object_or_404(HospitalAccess.objects.select_related("hospital", "user"), pk=access_id)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if action == "leave":
        if access.user_id != request.user.id:
            raise PermissionDenied("You can only leave hospitals you personally access.")
        if access.status != HospitalAccess.Status.ACTIVE:
            messages.info(request, "That hospital access is already inactive.")
        else:
            access.status = HospitalAccess.Status.LEFT
            access.left_at = timezone.now()
            access.left_reason = reason or "Left voluntarily"
            access.save(update_fields=["status", "left_at", "left_reason"])
            messages.success(request, f"You left {access.hospital.name}.")
        _reset_current_hospital_session(request)
        if is_ajax:
            return JsonResponse({"ok": True, "message": f"You left {access.hospital.name}.", "hospital_id": access.hospital_id})
        return redirect(request.META.get("HTTP_REFERER", "profile"))

    current_access = _current_hospital_access(request)
    if not current_access or current_access.hospital_id != access.hospital_id or current_access.role not in OWNER_ROLES:
        raise PermissionDenied("You do not have permission to manage that hospital access.")

    if action == "revoke":
        patient_profile = getattr(access.user, "patient", None) if access.role == HospitalAccess.Role.PATIENT else None
        if access.role == HospitalAccess.Role.PATIENT and (not patient_profile or not patient_profile.is_deceased):
            message = "Patient access can only be revoked after the patient has been formally recorded as deceased."
            if is_ajax:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return redirect(request.META.get("HTTP_REFERER", "home"))
        if access.status == HospitalAccess.Status.ACTIVE:
            access.status = HospitalAccess.Status.REVOKED
            access.revoked_at = timezone.now()
            access.revoked_by = request.user
            access.revoked_reason = reason
            access.save(update_fields=["status", "revoked_at", "revoked_by", "revoked_reason"])
            send_user_notification(
                access.user,
                f"Access revoked: {access.hospital.name}",
                f"Your access to {access.hospital.name} was revoked by {request.user.get_full_name() or request.user.username}.",
            )
            messages.success(request, f"{access.user.get_full_name() or access.user.username} access revoked.")
        else:
            messages.info(request, "That access is already inactive.")
    elif action == "restore":
        patient_profile = getattr(access.user, "patient", None) if access.role == HospitalAccess.Role.PATIENT else None
        if access.role == HospitalAccess.Role.PATIENT and patient_profile and patient_profile.is_deceased:
            message = "A deceased patient record cannot be restored to active access."
            if is_ajax:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return redirect(request.META.get("HTTP_REFERER", "home"))
        access.status = HospitalAccess.Status.ACTIVE
        access.revoked_at = None
        access.revoked_by = None
        access.revoked_reason = ""
        access.left_at = None
        access.left_reason = ""
        access.save(update_fields=["status", "revoked_at", "revoked_by", "revoked_reason", "left_at", "left_reason"])
        send_user_notification(
            access.user,
            f"Access restored: {access.hospital.name}",
            f"Your access to {access.hospital.name} has been restored by {request.user.get_full_name() or request.user.username}.",
        )
        messages.success(request, f"{access.user.get_full_name() or access.user.username} access restored.")
    else:
        raise PermissionDenied("Unsupported access action.")

    if request.session.get("current_hospital_id") == access.hospital_id and access.status != HospitalAccess.Status.ACTIVE:
        _reset_current_hospital_session(request)
    if is_ajax:
        return JsonResponse({"ok": True, "message": "Hospital access updated.", "access_id": access.id, "status": access.status})
    return redirect(request.META.get("HTTP_REFERER", "home"))


@login_required
@require_http_methods(["POST"])
def grant_assistant_record_access(request):
    current_access = _current_hospital_access(request)
    hospital = current_access.hospital if current_access else None
    if not current_access or current_access.role not in OWNER_ROLES:
        raise PermissionDenied("Only hospital admins and owners can grant assistant record access.")

    form = AssistantAccessGrantForm(request.POST, hospital=hospital)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if not form.is_valid():
        if is_ajax:
            return JsonResponse({"ok": False, "errors": {field: list(messages) for field, messages in form.errors.items()}}, status=400)
        messages.error(request, "Please correct the assistant access form.")
        return redirect(request.META.get("HTTP_REFERER", "home"))

    requester = form.cleaned_data["requester"]
    patient = form.cleaned_data["patient"]
    grant = AssistantAccessGrant.objects.create(
        requester=requester,
        patient_user=patient.user,
        hospital_id=hospital.id if hospital else None,
        approved_by=request.user,
        status=AssistantAccessGrant.Status.APPROVED,
        expires_at=form.cleaned_data.get("expires_at"),
        reason=(form.cleaned_data.get("reason") or "").strip(),
    )
    send_user_notification(
        requester,
        "BayAfya Assistant record access approved",
        f"Access to {patient} has been approved for {hospital.name if hospital else 'the current hospital'}.",
    )
    messages.success(request, f"Assistant record access granted for {requester.get_full_name() or requester.username}.")
    if is_ajax:
        return JsonResponse(
            {
                "ok": True,
                "message": "Assistant record access granted.",
                "grant": {
                    "id": grant.id,
                    "requester": requester.get_full_name() or requester.username,
                    "patient": str(patient),
                },
            }
        )
    return redirect(request.META.get("HTTP_REFERER", "home"))


@login_required
@require_http_methods(["POST"])
def create_team_conversation(request):
    _staff_messaging_required(request.user)
    current_access = _current_hospital_access(request)
    current_hospital = current_access.hospital if current_access else None
    form = TeamConversationForm(request.POST, hospital=current_hospital, creator=request.user)
    if not form.is_valid():
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return _communications_json_response(
                False,
                "The team could not be created. Please review the details and try again.",
                errors=form.errors,
            )
        messages.error(request, "The team could not be created. Please review the details and try again.")
        return redirect("communications")

    conversation = form.save()
    StaffConversationParticipant.objects.create(
        conversation=conversation,
        user=request.user,
        role=StaffConversationParticipant.Role.ADMIN,
        last_read_at=timezone.now(),
    )
    if conversation.linked_patient_id:
        StaffConversationParticipant.objects.get_or_create(
            conversation=conversation,
            user=conversation.linked_patient.user,
            defaults={"role": StaffConversationParticipant.Role.MEMBER},
        )
    StaffMessage.objects.create(
        conversation=conversation,
        sender=None,
        sender_label="BayAfya System",
        body=f"Team created for {conversation.get_purpose_display().lower()}. Share the join code {conversation.join_code} with the relevant staff.",
        kind=StaffMessage.Kind.SYSTEM,
    )
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at", "updated_at"])
    if conversation.linked_patient_id:
        send_user_notification(
            conversation.linked_patient.user,
            f"Care team created for {conversation.linked_patient}",
            f"Your care team has a new coordination thread in {conversation.hospital.name if conversation.hospital else 'BayAfya'}.",
        )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return _communications_json_response(
            True,
            f"Team created. Share join code {conversation.join_code} with teammates.",
            conversation_id=conversation.id,
            join_code=conversation.join_code,
            redirect=f"{reverse('communications')}?conversation={conversation.id}",
        )
    messages.success(request, f"Team created. Share join code {conversation.join_code} with teammates.")
    return redirect(f"{reverse('communications')}?conversation={conversation.id}")


@login_required
@require_http_methods(["POST"])
def join_team_conversation(request):
    _staff_messaging_required(request.user)
    form = JoinConversationForm(request.POST)
    if not form.is_valid():
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return _communications_json_response(False, "Enter a valid team access code.", errors=form.errors)
        messages.error(request, "Enter a valid team access code.")
        return redirect("communications")

    join_code = form.cleaned_data["join_code"]
    conversation = StaffConversation.objects.filter(
        join_code=join_code,
        kind=StaffConversation.Kind.TEAM,
        is_active=True,
    ).select_related("hospital").prefetch_related("participants__user").first()
    if conversation is None:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return _communications_json_response(False, "That team access code is invalid or inactive.")
        messages.error(request, "That team access code is invalid or inactive.")
        return redirect("communications")

    allowed_hospital_ids = _staff_messaging_hospital_ids(request.user)
    if conversation.hospital_id and conversation.hospital_id not in allowed_hospital_ids:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return _communications_json_response(False, "You do not have access to the hospital workspace for this team.")
        messages.error(request, "You do not have access to the hospital workspace for this team.")
        return redirect("communications")

    participant, created = StaffConversationParticipant.objects.get_or_create(
        conversation=conversation,
        user=request.user,
        defaults={"role": StaffConversationParticipant.Role.MEMBER, "last_read_at": timezone.now()},
    )
    if not created:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return _communications_json_response(
                True,
                "You are already a member of that team.",
                conversation_id=conversation.id,
                redirect=f"{reverse('communications')}?conversation={conversation.id}",
            )
        messages.info(request, "You are already a member of that team.")
        return redirect(f"{reverse('communications')}?conversation={conversation.id}")

    StaffMessage.objects.create(
        conversation=conversation,
        sender=None,
        sender_label="BayAfya System",
        body=f"{request.user.get_full_name() or request.user.username} joined the team.",
        kind=StaffMessage.Kind.SYSTEM,
    )
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at", "updated_at"])
    for admin in conversation.participants.select_related("user").filter(role=StaffConversationParticipant.Role.ADMIN):
        if admin.user_id == request.user.id:
            continue
        send_user_notification(
            admin.user,
            "Team member joined",
            f"{request.user.get_full_name() or request.user.username} joined {conversation.title or conversation.get_purpose_display()}.",
        )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return _communications_json_response(
            True,
            "You have joined the team successfully.",
            conversation_id=conversation.id,
            redirect=f"{reverse('communications')}?conversation={conversation.id}",
        )
    messages.success(request, "You have joined the team successfully.")
    return redirect(f"{reverse('communications')}?conversation={conversation.id}")


@login_required
@require_http_methods(["POST"])
def delete_team_conversation(request, conversation_id):
    _staff_messaging_required(request.user)
    conversation = get_object_or_404(
        _staff_conversation_queryset(request.user).filter(kind=StaffConversation.Kind.TEAM),
        pk=conversation_id,
    )
    if not _conversation_can_administer(conversation, request.user):
        raise PermissionDenied("Only team admins can delete this team.")

    conversation.is_active = False
    conversation.deleted_at = timezone.now()
    conversation.save(update_fields=["is_active", "deleted_at", "updated_at"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        next_conversation = _staff_conversation_queryset(request.user).filter(kind=StaffConversation.Kind.TEAM).first()
        return _communications_json_response(
            True,
            "The team has been archived.",
            conversation_id=next_conversation.id if next_conversation else None,
            redirect=f"{reverse('communications')}?conversation={next_conversation.id}" if next_conversation else reverse("communications"),
        )
    messages.success(request, "The team has been archived.")
    return redirect("communications")


def terms(request):
    return render(request, "core/terms.html")


def privacy(request):
    return render(request, "core/privacy.html")


def support(request):
    return render(request, "core/support.html")


def _notify_hospital_admins(hospital, title, message, exclude_user=None):
    if not hospital:
        return
    admins = HospitalAccess.objects.select_related("user").filter(
        hospital=hospital,
        role__in=[HospitalAccess.Role.OWNER, HospitalAccess.Role.ADMIN],
    )
    for access in admins:
        if exclude_user and access.user_id == exclude_user.id:
            continue
        Notification.objects.create(user=access.user, title=title, message=message)


def _invite_welcome_modal(invitation, user):
    return {
        "hospital": invitation.hospital.name,
        "role": invitation.get_role_display(),
        "note": invitation.note or "Your hospital access has been activated.",
        "message": f"Welcome to {invitation.hospital.name}. Your access is ready.",
        "recipient": user.get_full_name() or user.username,
    }


def _complete_invitation_redemption(*, invitation, user, request, make_primary):
    if not invitation:
        return None
    if invitation.expires_at and invitation.expires_at < timezone.now():
        user.pending_hospital_invitation = None
        user.save(update_fields=["pending_hospital_invitation"])
        return None
    if not invitation.is_active:
        user.pending_hospital_invitation = None
        user.save(update_fields=["pending_hospital_invitation"])
        return None
    HospitalAccess.objects.update_or_create(
        user=user,
        hospital=invitation.hospital,
        role=invitation.role,
        defaults={
            "is_primary": make_primary,
            "can_switch": True,
            "status": HospitalAccess.Status.ACTIVE,
        },
    )
    request.session["current_hospital_id"] = invitation.hospital_id
    request.session["invite_welcome_modal"] = _invite_welcome_modal(invitation, user)
    _notify_hospital_admins(
        invitation.hospital,
        "Invitation redeemed",
        f"{user.get_full_name() or user.username} activated access for {invitation.hospital.name}.",
        exclude_user=user,
    )
    if invitation.created_by and invitation.created_by != user:
        Notification.objects.create(
            user=invitation.created_by,
            title="Invitation activated",
            message=f"{user.get_full_name() or user.username} redeemed your invitation for {invitation.hospital.name}.",
        )
    invitation.redeemed_by = user
    invitation.redeemed_at = timezone.now()
    invitation.is_active = False
    invitation.save(update_fields=["redeemed_by", "redeemed_at", "is_active"])
    broadcast_hospital_update(
        invitation.hospital,
        event_type="invitation_redeemed",
        payload={"invitation_id": invitation.id, "user_id": user.id},
    )
    user.pending_hospital_invitation = None
    user.save(update_fields=["pending_hospital_invitation"])
    return invitation


def _current_hospital_access(request):
    accesses = list(
        HospitalAccess.objects.select_related("hospital").filter(
            user=request.user, hospital__is_active=True, status=HospitalAccess.Status.ACTIVE
        )
    )
    hospital_id = request.session.get("current_hospital_id")
    current_access = None
    if hospital_id:
        current_access = next((access for access in accesses if access.hospital_id == hospital_id), None)
    if current_access is None:
        current_access = next((access for access in accesses if access.is_primary), None)
    if current_access is None and accesses:
        current_access = accesses[0]
    return current_access


def _reset_current_hospital_session(request):
    current_access = _current_hospital_access(request)
    if current_access:
        request.session["current_hospital_id"] = current_access.hospital_id
    else:
        request.session.pop("current_hospital_id", None)
    return current_access


def home(request):
    if not request.user.is_authenticated:
        return render(request, "core/home.html")

    user = request.user
    context = {"notifications": Notification.objects.filter(user=user)[:12], "stats": {}}
    owned_hospitals = Hospital.objects.filter(owner=user, is_active=True) if user.role == User.Role.ADMIN else Hospital.objects.none()
    current_access = _current_hospital_access(request)
    current_hospital = current_access.hospital if current_access else None
    if user.role == User.Role.ADMIN and current_hospital is None and owned_hospitals.exists():
        current_hospital = owned_hospitals.first()
    context["current_hospital"] = current_hospital
    context["owned_hospitals"] = owned_hospitals
    hospital_count = _user_hospital_count(user)

    if user.role == User.Role.PATIENT:
        patient = getattr(user, "patient", None)
        if patient:
            context["stats"] = {
                "appointments": Appointment.objects.filter(patient=patient).count(),
                "records": MedicalRecord.objects.filter(patient=patient).count(),
                "orders": Order.objects.filter(patient=patient).count(),
                "ambulance_requests": AmbulanceRequest.objects.filter(user=user).count(),
                "hospitals": hospital_count,
            }
            context["upcoming_appointments"] = Appointment.objects.filter(
                patient=patient
            ).order_by("-created_at")[:12]
    elif user.role == User.Role.DOCTOR:
        doctor = getattr(user, "doctor", None)
        if doctor:
            context["stats"] = {
                "scheduled_appointments": Appointment.objects.filter(doctor=doctor).count(),
                "consultations": VideoConsultation.objects.filter(
                    appointment__doctor=doctor
                ).count(),
                "records_authored": MedicalRecord.objects.filter(doctor=doctor).count(),
                "hospitals": hospital_count,
            }
            context["upcoming_appointments"] = Appointment.objects.filter(
                doctor=doctor
            ).order_by("-created_at")[:12]
    elif user.role == User.Role.COUNSELOR:
        counselor = getattr(user, "counselor", None)
        if counselor:
            context["stats"] = {
                "therapy_sessions": TherapySession.objects.filter(counselor=counselor).count(),
                "recent_mood_logs": MoodLog.objects.count(),
                "hospitals": hospital_count,
            }
    elif user.role == User.Role.NURSE:
        context["stats"] = {
            "patients_under_observation": VitalSign.objects.values("patient").distinct().count(),
            "active_admissions": Admission.objects.filter(status=Admission.Status.ACTIVE).count(),
            "pending_labs": LabTestRequest.objects.filter(status=LabTestRequest.Status.REQUESTED).count(),
            "hospitals": hospital_count,
        }
        context["recent_vitals"] = VitalSign.objects.select_related("patient__user").order_by("-recorded_at")[:12]
    elif user.role == User.Role.RECEPTIONIST:
        today = timezone.localdate()
        context["stats"] = {
            "appointments_today": Appointment.objects.filter(appointment_date=today).count(),
            "queued_patients": QueueTicket.objects.filter(status=QueueTicket.Status.QUEUED).count(),
            "active_admissions": Admission.objects.filter(status=Admission.Status.ACTIVE).count(),
            "hospitals": hospital_count,
        }
        context["upcoming_appointments"] = Appointment.objects.order_by("-created_at")[:12]
    elif user.role == User.Role.LAB_TECHNICIAN:
        context["stats"] = {
            "pending_labs": LabTestRequest.objects.filter(status=LabTestRequest.Status.REQUESTED).count(),
            "completed_labs": LabTestRequest.objects.filter(status=LabTestRequest.Status.COMPLETED).count(),
            "recent_results": LabTestRequest.objects.filter(result__isnull=False).count(),
            "hospitals": hospital_count,
        }
        context["recent_lab_requests"] = LabTestRequest.objects.select_related("patient__user", "requested_by__user").order_by("-requested_at")[:12]
    elif user.role == User.Role.PHARMACIST:
        context["stats"] = {
            "orders": Order.objects.count(),
            "delivered_orders": Order.objects.filter(status=Order.Status.DELIVERED).count(),
            "hospitals": hospital_count,
        }
    elif user.role == User.Role.EMERGENCY_OPERATOR:
        context["stats"] = {
            "ambulance_requests": AmbulanceRequest.objects.count(),
            "active_cases": AmbulanceRequest.objects.exclude(
                status=AmbulanceRequest.Status.COMPLETED
            ).count(),
            "hospitals": hospital_count,
        }
    else:
        if user.role == User.Role.ADMIN:
            hospital_scope = owned_hospitals
            if current_hospital:
                hospital_scope = Hospital.objects.filter(id=current_hospital.id)
            billings_total = Billing.objects.filter(hospital__in=hospital_scope).aggregate(count=Count("id"))["count"] or 0
            context["stats"] = {
                "users": User.objects.filter(
                    Q(hospital_accesses__hospital__in=hospital_scope) | Q(owned_hospitals__in=hospital_scope)
                ).distinct().count(),
                "appointments": Appointment.objects.filter(hospital__in=hospital_scope).count(),
                "billings": billings_total,
                "hospitals": hospital_count,
            }
        else:
            user_count = User.objects.filter(hospital_accesses__isnull=False).distinct().count()
            appointment_count = Appointment.objects.count()
            billing_count = Billing.objects.aggregate(count=Count("id"))["count"] or 0
            if current_hospital:
                user_count = User.objects.filter(hospital_accesses__hospital=current_hospital).distinct().count()
                appointment_count = Appointment.objects.filter(hospital=current_hospital).count()
                billing_count = Billing.objects.filter(hospital=current_hospital).aggregate(count=Count("id"))["count"] or 0
            context["stats"] = {
                "users": user_count,
                "appointments": appointment_count,
                "billings": billing_count,
                "hospitals": hospital_count,
            }

    metric_links = _metric_links(user)
    context["metric_cards"] = [
        {"label": label, "value": value, "url": metric_links.get(label, ""), "icon": _metric_icon(label)}
        for label, value in context["stats"].items()
    ]
    context["dashboard_experience"] = _build_dashboard_experience(user, context["stats"])
    return render(request, "core/dashboard.html", context)


@login_required
def profile(request):
    user = request.user
    avatar_data = _avatar_data(user)
    current_access = _current_hospital_access(request)
    current_hospital = current_access.hospital if current_access else None
    verification_pending = bool(user.email and not getattr(user, "email_verified_at", None))
    context = {
        "profile_cards": _profile_cards(user),
        "care_links": [],
        "recent_items": [],
        "profile_form": ProfileUpdateForm(instance=user, data=request.POST or None, files=request.FILES or None),
        "password_form": StyledPasswordChangeForm(user=user),
        "redeem_form": HospitalAccessRedeemForm(),
        "avatar_data": avatar_data,
        "current_hospital": current_hospital,
        "email_verification_pending": verification_pending,
        "verification_email": user.email,
    }

    if user.role == User.Role.PATIENT and hasattr(user, "patient"):
        patient = user.patient
        context["profile_cards"].extend([
            {"label": "Patient number", "value": patient.patient_number or "Pending", "icon": "bi-upc-scan"},
            {"label": "Insurance", "value": patient.insurance_provider or "Not provided", "icon": "bi-shield-check"},
        ])
        context["care_links"] = [
            {"label": "Book appointment", "icon": "bi-calendar-plus", "url": "hospital:book_appointment"},
            {"label": "My records", "icon": "bi-folder2-open", "url": "hospital:records_hub"},
            {"label": "Pharmacy", "icon": "bi-capsule-pill", "url": "pharmacy:home"},
            {"label": "Emergency", "icon": "bi-truck-front", "url": "ambulance:request"},
        ]
        context["recent_items"] = [
            {"title": appointment.doctor.__str__(), "subtitle": f"{appointment.appointment_date} at {appointment.appointment_time}", "status": appointment.get_status_display()}
            for appointment in Appointment.objects.filter(patient=patient).order_by("-created_at")[:12]
        ]
    elif user.role == User.Role.DOCTOR and hasattr(user, "doctor"):
        doctor = user.doctor
        context["profile_cards"].extend([
            {"label": "Specialization", "value": doctor.specialization, "icon": "bi-journal-medical"},
            {"label": "Department", "value": doctor.department or "General", "icon": "bi-building"},
        ])
        context["care_links"] = [
            {"label": "Clinical dashboard", "icon": "bi-hospital", "url": "hospital:dashboard"},
            {"label": "Patient registry", "icon": "bi-people", "url": "hospital:patient_registry"},
            {"label": "Clinical insights", "icon": "bi-graph-up-arrow", "url": "hospital:clinical_insights"},
            {"label": "Surgery board", "icon": "bi-scissors", "url": "hospital:surgery_dashboard"},
            {"label": "Virtual care", "icon": "bi-camera-video", "url": "telemedicine:dashboard"},
            {"label": "Notifications", "icon": "bi-bell", "url": "notifications"},
        ]
        context["recent_items"] = [
            {"title": appointment.patient.__str__(), "subtitle": f"{appointment.appointment_date} at {appointment.appointment_time}", "status": appointment.get_status_display()}
            for appointment in Appointment.objects.filter(doctor=doctor).order_by("-created_at")[:12]
        ]
    elif hasattr(user, "staff_profile"):
        staff = user.staff_profile
        context["profile_cards"].extend([
            {"label": "Employee ID", "value": staff.employee_id, "icon": "bi-person-vcard"},
            {"label": "Department", "value": staff.department or "Operations", "icon": "bi-building"},
        ])
        context["care_links"] = [
            {"label": "Hospital operations", "icon": "bi-hospital", "url": "hospital:dashboard"},
            {"label": "Patient registry", "icon": "bi-people", "url": "hospital:patient_registry"},
            {"label": "Clinical insights", "icon": "bi-graph-up-arrow", "url": "hospital:clinical_insights"},
            {"label": "Notifications", "icon": "bi-bell", "url": "notifications"},
        ]
        context["recent_items"] = [
            {
                "title": shift.local_start_at.strftime("%Y-%m-%d") if shift.local_start_at else shift.shift_date.strftime("%Y-%m-%d"),
                "subtitle": (
                    f"{shift.local_start_at:%d %b %Y %H:%M} - {shift.local_end_at:%d %b %Y %H:%M}"
                    if shift.local_start_at and shift.local_end_at
                    else f"{shift.start_time} - {shift.end_time}"
                ),
                "status": shift.staff.get_role_display(),
            }
            for shift in ShiftAssignment.objects.filter(staff=staff).order_by("-start_at", "-shift_date")[:12]
        ]
        context["certifications"] = staff.certifications.order_by("expires_on")[:4]
    elif user.role == User.Role.COUNSELOR:
        context["care_links"] = [
            {"label": "Wellbeing dashboard", "icon": "bi-flower2", "url": "mental_health:dashboard"},
            {"label": "Notifications", "icon": "bi-bell", "url": "notifications"},
        ]
    elif user.role == User.Role.PHARMACIST:
        context["care_links"] = [
            {"label": "Pharmacy", "icon": "bi-capsule-pill", "url": "pharmacy:home"},
            {"label": "Notifications", "icon": "bi-bell", "url": "notifications"},
        ]
    elif user.role == User.Role.EMERGENCY_OPERATOR:
        context["care_links"] = [
            {"label": "Emergency requests", "icon": "bi-truck-front", "url": "ambulance:request"},
            {"label": "Notifications", "icon": "bi-bell", "url": "notifications"},
        ]
    else:
        context["care_links"] = [
            {"label": "Hospital dashboard", "icon": "bi-hospital", "url": "hospital:dashboard"},
            {"label": "Patient registry", "icon": "bi-people", "url": "hospital:patient_registry"},
            {"label": "Clinical insights", "icon": "bi-graph-up-arrow", "url": "hospital:clinical_insights"},
            {"label": "Surgery board", "icon": "bi-scissors", "url": "hospital:surgery_dashboard"},
            {"label": "Notifications", "icon": "bi-bell", "url": "notifications"},
        ]

    form = context["profile_form"]
    if request.method == "POST" and form.is_valid():
        original_email = (user.email or "").strip().lower()
        updated_email = (form.cleaned_data.get("email") or "").strip().lower()
        form.instance.email_verified_at = None if updated_email and updated_email != original_email else user.email_verified_at
        updated_user = form.save()
        if updated_email and updated_email != original_email:
            try:
                _send_email_verification(request, updated_user)
            except ValidationError as exc:
                messages.warning(request, exc.message)
                return redirect("profile")
            messages.success(
                request,
                "Your profile has been updated. We sent a fresh verification email to the new address.",
            )
        else:
            messages.success(request, "Your profile has been updated.")
        return redirect("profile")

    return render(request, "core/profile.html", context)


def register(request):
    redirect_response = _redirect_authenticated_user(request)
    if redirect_response is not None:
        return redirect_response
    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.email_verified_at = None
            user.save()
            invitation = getattr(form, "invitation", None)
            if user.role == User.Role.ADMIN and not invitation:
                hospital = Hospital.objects.create(
                    name=form.cleaned_data["hospital_name"].strip(),
                    code=form.cleaned_data["hospital_code"].strip(),
                    address=form.cleaned_data.get("hospital_address", "").strip(),
                    owner=user,
                )
                HospitalAccess.objects.create(
                    user=user,
                    hospital=hospital,
                    role=HospitalAccess.Role.OWNER,
                    status=HospitalAccess.Status.ACTIVE,
                    is_primary=True,
                )
                request.session["current_hospital_id"] = hospital.id
            elif invitation:
                user.pending_hospital_invitation = invitation
                user.save(update_fields=["pending_hospital_invitation"])
            try:
                _send_email_verification(request, user)
            except ValidationError as exc:
                form.add_error(None, exc.message)
                user.delete()
                return render(request, "core/register.html", {"form": form})
            messages.success(
                request,
                "Your BayAfya account has been created. Check your inbox to verify your email before signing in.",
            )
            return render(
                request,
                "core/email_verification_sent.html",
                {
                    "verification_email": user.email,
                    "account_role": user.get_role_display(),
                    "verification_form": StyledEmailVerificationCodeForm(initial={"email": user.email}),
                },
            )
    else:
        form = UserRegistrationForm()
    return render(request, "core/register.html", {"form": form})


@require_http_methods(["GET", "POST"])
def resend_email_verification(request):
    if request.user.is_authenticated and request.user.email_verified_at:
        return redirect(_authenticated_entry_redirect())
    initial_email = ""
    if request.user.is_authenticated and getattr(request.user, "email", ""):
        initial_email = request.user.email
    if request.GET.get("email"):
        initial_email = request.GET.get("email", "").strip()
    form = StyledEmailVerificationResendForm(request.POST or None, initial={"email": initial_email})
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        user = (
            User.objects.filter(email__iexact=email)
            .exclude(email_verified_at__isnull=False)
            .order_by("-id")
            .first()
        )
        if user:
            try:
                _send_email_verification(request, user, recipient_email=email)
            except ValidationError as exc:
                messages.warning(request, exc.message)
                return render(request, "core/email_verification_resend.html", {"form": form}, status=429)
        messages.success(
            request,
            "If an account is pending verification, we sent a new 7-digit code to the address provided.",
        )
        return render(
            request,
            "core/email_verification_sent.html",
            {
                "verification_email": email,
                "resend_mode": True,
                "verification_form": StyledEmailVerificationCodeForm(initial={"email": email}),
            },
        )
    return render(request, "core/email_verification_resend.html", {"form": form})


@require_http_methods(["GET", "POST"])
def verify_email(request):
    if request.user.is_authenticated and request.user.email_verified_at:
        return redirect(_authenticated_entry_redirect())
    initial_email = request.GET.get("email", "").strip()
    form = StyledEmailVerificationCodeForm(request.POST or None, initial={"email": initial_email})
    is_async = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        code = form.cleaned_data["code"]
        user = User.objects.filter(email__iexact=email).order_by("-id").first()
        today = timezone.localdate()
        if user and user.email_verification_locked_until and user.email_verification_locked_until > timezone.now():
            message = f"Verification is locked until {timezone.localtime(user.email_verification_locked_until):%Y-%m-%d %H:%M}. Please try again tomorrow."
            if is_async:
                return _verification_json_response(
                    ok=False,
                    message=message,
                    status=429,
                    locked_until=user.email_verification_locked_until,
                    errors={"code": [message]},
                )
            messages.error(request, message)
            return render(
                request,
                "core/email_verification_confirm.html",
                {
                    "verified": False,
                    "resend_url": reverse("resend_email_verification"),
                    "form": form,
                    "locked_until": user.email_verification_locked_until,
                },
                status=429,
            )
        if user and user.email_verification_failed_date != today:
            user.email_verification_failed_date = today
            user.email_verification_failed_count = 0
            user.save(update_fields=["email_verification_failed_date", "email_verification_failed_count"])
        if (
            user
            and not user.email_verified_at
            and user.email_verification_code == code
            and user.email_verification_sent_at
            and user.email_verification_sent_at >= timezone.now() - timedelta(minutes=15)
        ):
            user.email_verified_at = timezone.now()
            user.email_verification_code = ""
            user.email_verification_sent_at = None
            user.email_verification_locked_until = None
            user.email_verification_failed_count = 0
            user.email_verification_failed_date = today
            user.save(
                update_fields=[
                    "email_verified_at",
                    "email_verification_code",
                    "email_verification_sent_at",
                    "email_verification_locked_until",
                    "email_verification_failed_count",
                    "email_verification_failed_date",
                ]
            )
            invitation = getattr(user, "pending_hospital_invitation", None)
            if invitation and invitation.is_active:
                invitation = _complete_invitation_redemption(
                    invitation=invitation,
                    user=user,
                    request=request,
                    make_primary=True,
                )
            elif invitation:
                user.pending_hospital_invitation = None
                user.save(update_fields=["pending_hospital_invitation"])
                invitation = None
            if invitation is None:
                invitation = HospitalInvitation.objects.filter(redeemed_by=user).order_by("-redeemed_at").first()
            if invitation:
                request.session["invite_welcome_modal"] = _invite_welcome_modal(invitation, user)
            messages.success(request, "Your email address has been verified. You can now sign in.")
            if is_async:
                return _verification_json_response(
                    ok=True,
                    message="Your email address has been verified. You can now sign in.",
                    verified=True,
                )
            return render(
                request,
                "core/email_verification_confirm.html",
                {"verified": True, "user": user},
            )
        locked_until = None
        message = "That verification code is invalid or expired."
        if user and not user.email_verified_at and user.email_verification_code and user.email_verification_code != code:
            user.email_verification_failed_date = today
            user.email_verification_failed_count += 1
            update_fields = ["email_verification_failed_date", "email_verification_failed_count"]
            remaining = max(0, 3 - user.email_verification_failed_count)
            if user.email_verification_failed_count >= 3:
                locked_until = _verification_lock_until()
                user.email_verification_locked_until = locked_until
                update_fields.append("email_verification_locked_until")
                message = f"That verification code is incorrect. BayAfya has now locked verification until {timezone.localtime(locked_until):%Y-%m-%d %H:%M} after 3 failed attempts."
            else:
                message = f"That verification code is incorrect. You have {remaining} attempt{'s' if remaining != 1 else ''} left today before verification is locked until tomorrow."
            user.save(update_fields=update_fields)
        elif user and user.email_verification_sent_at and user.email_verification_sent_at < timezone.now() - timedelta(minutes=15):
            message = "That verification code has expired. Request another code if you still have resend attempts today."
        if is_async:
            return _verification_json_response(
                ok=False,
                message=message,
                status=429 if locked_until else 400,
                errors={"code": [message]},
                locked_until=locked_until,
            )
        messages.error(request, message)
        return render(
            request,
            "core/email_verification_confirm.html",
            {
                "verified": False,
                "resend_url": reverse("resend_email_verification"),
                "form": form,
                "locked_until": locked_until,
            },
            status=429 if locked_until else 400,
        )
    if request.method == "POST" and is_async:
        return _verification_json_response(
            ok=False,
            message="Please review the verification details and try again.",
            status=400,
            errors={field: [str(error) for error in errors] for field, errors in form.errors.items()},
        )
    return render(
        request,
        "core/email_verification_confirm.html",
        {
            "verified": None,
            "form": form,
            "resend_url": reverse("resend_email_verification"),
        },
    )


@login_required
@require_http_methods(["POST"])
def redeem_hospital_access(request):
    form = HospitalAccessRedeemForm(request.POST)
    if form.is_valid():
        invitation = form.invitation
        allowed_roles = {request.user.role}
        if request.user.role == User.Role.ADMIN:
            allowed_roles.update({HospitalAccess.Role.ADMIN, HospitalAccess.Role.OWNER})
        if request.user.role == User.Role.PATIENT:
            allowed_roles.add(HospitalAccess.Role.PATIENT)
        if invitation.role not in allowed_roles:
            messages.error(request, "This authorization code does not match your profile.")
            return redirect("profile")
        expected_email = (invitation.invitee_email or "").strip().lower()
        actual_email = (request.user.email or "").strip().lower()
        if expected_email and expected_email != actual_email:
            messages.error(
                request,
                "This authorization code could not be activated because the email does not match the invitation record.",
            )
            return redirect("profile")
        expected_name = " ".join((invitation.invitee_name or "").split()).casefold()
        actual_name = " ".join((request.user.get_full_name() or request.user.username or "").split()).casefold()
        if expected_name and expected_name != actual_name:
            messages.error(
                request,
                "This authorization code could not be activated because the name does not match the invitation record.",
            )
            return redirect("profile")
        if request.user.email_verified_at:
            invitation = _complete_invitation_redemption(
                invitation=invitation,
                user=request.user,
                request=request,
                make_primary=False,
            )
            if not invitation:
                messages.error(request, "This authorization code is no longer available.")
                return redirect("profile")
            messages.success(request, f"Access granted for {invitation.hospital.name}.")
            return redirect("profile")
        request.user.pending_hospital_invitation = invitation
        request.user.save(update_fields=["pending_hospital_invitation"])
        try:
            _send_email_verification(request, request.user)
        except ValidationError as exc:
            messages.warning(request, exc.message)
            return redirect("profile")
        messages.info(
            request,
            "Your authorization code is valid. Please verify your email to finish activating hospital access.",
        )
        return redirect("profile")
    messages.error(request, "Enter a valid authorization code.")
    return redirect("profile")


@require_http_methods(["GET", "POST"])
def logout_user(request):
    logout(request)
    messages.success(request, "You have been signed out securely.")
    return redirect("home")


@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user)
    items.update(is_read=True)
    return render(request, "core/notifications.html", {"notifications": items})


@login_required
def assistant_suggest(request):
    payload = request.POST
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            payload = {}

    context = (payload.get("context") or request.GET.get("context") or "general").strip()
    text = (payload.get("text") or request.GET.get("text") or "").strip()
    patient = None
    patient_id = payload.get("patient_id") or request.GET.get("patient_id")
    current_access = _current_hospital_access(request)
    hospital = current_access.hospital if current_access else None

    if patient_id:
        lookup = Patient.objects.select_related("user", "hospital").filter(pk=patient_id)
        if hospital:
            lookup = lookup.filter(Q(hospital=hospital) | Q(appointments__hospital=hospital) | Q(medical_records__hospital=hospital) | Q(condition_records__hospital=hospital)).distinct()
        if request.user.role == User.Role.PATIENT:
            lookup = lookup.filter(user=request.user)
        patient = lookup.first()
    elif request.session.get("clinical_patient_id"):
        lookup = Patient.objects.select_related("user", "hospital").filter(pk=request.session["clinical_patient_id"])
        if request.user.role == User.Role.PATIENT:
            lookup = lookup.filter(user=request.user)
        elif hospital:
            lookup = lookup.filter(Q(hospital=hospital) | Q(appointments__hospital=hospital) | Q(medical_records__hospital=hospital) | Q(condition_records__hospital=hospital)).distinct()
        patient = lookup.first()
    elif request.user.role == User.Role.PATIENT and hasattr(request.user, "patient"):
        patient = request.user.patient

    access_decision = evaluate_patient_access(
        user=request.user,
        hospital=hospital,
        patient=patient,
        session=request.session,
    )
    if patient and not access_decision.allowed:
        patient = None

    response = build_assistant_response(
        user=request.user,
        hospital=hospital,
        patient=patient,
        context=context,
        text=text,
    )
    return JsonResponse(response.as_dict())


@login_required
@require_http_methods(["POST"])
def assistant_chat(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}

    message = (payload.get("message") or "").strip()
    context = (payload.get("context") or "general").strip() or "general"
    current_access = _current_hospital_access(request)
    hospital = current_access.hospital if current_access else None
    patient = None
    patient_id = payload.get("patient_id")

    if patient_id:
        lookup = Patient.objects.select_related("user", "hospital").filter(pk=patient_id)
        if hospital:
            lookup = lookup.filter(
                Q(hospital=hospital)
                | Q(appointments__hospital=hospital)
                | Q(medical_records__hospital=hospital)
                | Q(condition_records__hospital=hospital)
            ).distinct()
        if request.user.role == User.Role.PATIENT:
            lookup = lookup.filter(user=request.user)
        patient = lookup.first()
    elif request.session.get("clinical_patient_id"):
        lookup = Patient.objects.select_related("user", "hospital").filter(pk=request.session["clinical_patient_id"])
        if request.user.role == User.Role.PATIENT:
            lookup = lookup.filter(user=request.user)
        elif hospital:
            lookup = lookup.filter(
                Q(hospital=hospital)
                | Q(appointments__hospital=hospital)
                | Q(medical_records__hospital=hospital)
                | Q(condition_records__hospital=hospital)
            ).distinct()
        patient = lookup.first()
    elif request.user.role == User.Role.PATIENT and hasattr(request.user, "patient"):
        patient = request.user.patient

    histories = request.session.get("assistant_chat_histories", {})
    if not isinstance(histories, dict):
        histories = {}
    legacy_history = request.session.get("assistant_chat_history", [])
    if not histories and isinstance(legacy_history, list) and legacy_history:
        histories["general"] = legacy_history
    conversation = histories.get(context, [])
    if not isinstance(conversation, list):
        conversation = []
    resolved_context = context
    if not message and not conversation:
        preferred_context = request.session.get("assistant_chat_mode")
        if preferred_context and isinstance(histories.get(preferred_context), list) and histories.get(preferred_context):
            resolved_context = preferred_context
            conversation = histories[preferred_context]
        else:
            for history_key, history_value in histories.items():
                if isinstance(history_value, list) and history_value:
                    resolved_context = history_key
                    conversation = history_value
                    break
    if message:
        conversation.append({"role": "user", "content": message})

    response = build_assistant_chat_response(
        user=request.user,
        hospital=hospital,
        patient=patient,
        conversation=conversation,
        context=resolved_context,
        session=request.session,
    )
    if message and response.reply:
        conversation.append({"role": "assistant", "content": response.reply})
    histories[resolved_context] = conversation[-14:]
    request.session["assistant_chat_histories"] = histories
    request.session["assistant_chat_history"] = histories[resolved_context]
    request.session["assistant_chat_mode"] = resolved_context
    request.session.modified = True

    data = response.as_dict()
    data["history"] = histories[resolved_context]
    if not message:
        data["reply"] = ""
    data["context"] = resolved_context
    return JsonResponse(data)


@login_required
@require_http_methods(["POST"])
def assistant_chat_clear(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}
    context = (payload.get("context") or "general").strip() or "general"
    histories = request.session.get("assistant_chat_histories", {})
    if not isinstance(histories, dict):
        histories = {}
    histories[context] = []
    request.session["assistant_chat_histories"] = histories
    request.session["assistant_chat_history"] = []
    request.session["assistant_chat_mode"] = context
    request.session.modified = True
    return JsonResponse({"ok": True, "context": context})


@login_required
def entity_suggestions(request: HttpRequest):
    query = (request.GET.get("q") or "").strip()
    entity_type = (request.GET.get("type") or "patient").strip().lower()
    if len(query) < 2:
        return JsonResponse({"results": []})

    current_access = _current_hospital_access(request)
    hospital = current_access.hospital if current_access else None
    results = []

    if entity_type in {"patient", "any"}:
        patients = Patient.objects.select_related("user", "hospital")
        if hospital:
            patients = patients.filter(Q(hospital=hospital) | Q(appointments__hospital=hospital)).distinct()
        if request.user.role == User.Role.PATIENT:
            patients = patients.filter(user=request.user)
        for patient in patients.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(patient_number__icontains=query)
        ).distinct()[:12]:
            results.append(
                {
                    "label": str(patient),
                    "subtitle": patient.patient_number or patient.age_group,
                    "kind": "Patient",
                    "value": str(patient),
                }
            )

    if entity_type in {"doctor", "any"}:
        doctor_queryset = Doctor.objects.select_related("user", "hospital")
        if hospital:
            doctor_queryset = doctor_queryset.filter(hospital=hospital)
        for doctor in doctor_queryset.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(specialization__icontains=query)
        )[:12]:
            results.append(
                {
                    "label": str(doctor),
                    "subtitle": f"{doctor.specialization or 'Doctor'} • {doctor.hospital.name if doctor.hospital else 'BayAfya'}",
                    "kind": "Doctor",
                    "value": str(doctor),
                }
            )

    if entity_type in {"staff", "any"}:
        staff_queryset = User.objects.filter(
            role__in=[
                User.Role.DOCTOR,
                User.Role.NURSE,
                User.Role.RECEPTIONIST,
                User.Role.LAB_TECHNICIAN,
                User.Role.PHARMACIST,
                User.Role.COUNSELOR,
                User.Role.ADMIN,
                User.Role.EMERGENCY_OPERATOR,
            ],
            hospital_accesses__status=HospitalAccess.Status.ACTIVE,
        )
        if hospital:
            staff_queryset = staff_queryset.filter(hospital_accesses__hospital=hospital).distinct()
        for staff in staff_queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(hospital_accesses__role__icontains=query)
        )[:12]:
            staff_hospital = (
                staff.hospital_accesses.filter(hospital=hospital).values_list("hospital__name", flat=True).first()
                if hospital
                else staff.hospital_accesses.values_list("hospital__name", flat=True).first()
            )
            results.append(
                {
                    "label": staff.get_full_name() or staff.username,
                    "subtitle": f"{staff.get_role_display()}{f' • {staff_hospital}' if staff_hospital else ''}",
                    "kind": "Staff",
                    "value": staff.get_full_name() or staff.username,
                }
            )

    if entity_type in {"service", "any"}:
        service_catalog = [
            ("Patient registry", "Hospital service"),
            ("Walk-in flow", "Hospital service"),
            ("Admission board", "Hospital service"),
            ("Telemedicine", "Virtual care"),
            ("Clinical insights", "Hospital service"),
            ("Surgery board", "Hospital service"),
            ("Laboratory", "Diagnostic service"),
            ("Pharmacy", "Medication service"),
            ("Mental health", "Wellness service"),
            ("Emergency response", "Urgent care service"),
            ("Billing", "Financial service"),
            ("Patient feedback", "Patient service"),
        ]
        lowered = query.lower()
        for label, subtitle in service_catalog:
            if lowered in label.lower() or lowered in subtitle.lower():
                results.append(
                    {
                        "label": label,
                        "subtitle": subtitle,
                        "kind": "Service",
                        "value": label,
                    }
                )

    if entity_type in {"medication", "any"}:
        medication_seen = set()
        medication_querysets = []
        prescription_qs = Prescription.objects.select_related("patient__user", "doctor__user")
        if hospital:
            prescription_qs = prescription_qs.filter(consultation__appointment__hospital=hospital)
        medication_querysets.append(
            prescription_qs.filter(medications__icontains=query).values_list("medications", flat=True)[:12]
        )
        pharmacy_qs = PharmacyTask.objects.select_related("patient__user", "hospital")
        if hospital:
            pharmacy_qs = pharmacy_qs.filter(hospital=hospital)
        medication_querysets.append(
            pharmacy_qs.filter(instructions__icontains=query).values_list("instructions", flat=True)[:12]
        )
        for queryset in medication_querysets:
            for raw_value in queryset:
                for item in [part.strip() for part in str(raw_value or "").split(",") if part.strip()]:
                    if query.lower() not in item.lower():
                        continue
                    key = item.lower()
                    if key in medication_seen:
                        continue
                    medication_seen.add(key)
                    results.append(
                        {
                            "label": item,
                            "subtitle": "Medication",
                            "kind": "Medication",
                            "value": item,
                        }
                    )
                    if len(results) >= 12:
                        break
                if len(results) >= 12:
                    break
            if len(results) >= 12:
                break

    if entity_type in {"record", "any"}:
        record_results = []
        medical_records = MedicalRecord.objects.select_related("patient__user", "hospital")
        if hospital:
            medical_records = medical_records.filter(hospital=hospital)
        for item in medical_records.filter(
            Q(diagnosis__icontains=query) | Q(notes__icontains=query) | Q(patient__user__first_name__icontains=query) | Q(patient__user__last_name__icontains=query)
        )[:4]:
            record_results.append(
                {
                    "label": item.patient.__str__(),
                    "subtitle": f"Medical record • {item.created_at:%Y-%m-%d}",
                    "kind": "Record",
                    "value": item.patient.__str__(),
                }
            )
        lab_requests = LabTestRequest.objects.select_related("patient__user", "hospital")
        if hospital:
            lab_requests = lab_requests.filter(hospital=hospital)
        for item in lab_requests.filter(
            Q(test_name__icontains=query) | Q(patient__user__first_name__icontains=query) | Q(patient__user__last_name__icontains=query)
        )[:4]:
            record_results.append(
                {
                    "label": item.test_name,
                    "subtitle": f"Lab request • {item.patient}",
                    "kind": "Record",
                    "value": item.test_name,
                }
            )
        admissions = Admission.objects.select_related("patient__user", "ward", "bed", "hospital")
        if hospital:
            admissions = admissions.filter(hospital=hospital)
        for item in admissions.filter(
            Q(patient__user__first_name__icontains=query)
            | Q(patient__user__last_name__icontains=query)
            | Q(admission_reason__icontains=query)
            | Q(ward__name__icontains=query)
        )[:4]:
            record_results.append(
                {
                    "label": str(item.patient),
                    "subtitle": f"Admission • {item.ward.name if item.ward else 'Ward pending'}",
                    "kind": "Record",
                    "value": str(item.patient),
                }
            )
        for item in record_results[:12]:
            results.append(item)

    return JsonResponse({"results": results[:12]})


@login_required
@require_http_methods(["POST"])
def switch_hospital(request):
    hospital_id = request.POST.get("hospital_id")
    if not hospital_id:
        messages.warning(request, "Select a hospital to continue.")
        return redirect(request.META.get("HTTP_REFERER", "home"))

    access = HospitalAccess.objects.filter(
        user=request.user,
        hospital_id=hospital_id,
        status=HospitalAccess.Status.ACTIVE,
        hospital__is_active=True,
    ).select_related("hospital").first()
    if not access:
        messages.error(request, "You do not have access to that hospital.")
        return redirect(request.META.get("HTTP_REFERER", "home"))

    request.session["current_hospital_id"] = access.hospital_id
    messages.success(request, f"Workspace switched to {access.hospital.name}.")
    return redirect(request.META.get("HTTP_REFERER", "home"))


def error_400(request: HttpRequest, exception):
    return render(request, "errors/400.html", status=400)


def error_403(request: HttpRequest, exception):
    return render(request, "errors/403.html", status=403)


def error_404(request: HttpRequest, exception):
    return render(request, "errors/404.html", status=404)


def error_500(request: HttpRequest):
    return render(request, "errors/500.html", status=500)


def manifest(request):
    payload = {
        "name": "BayAfya",
        "short_name": "BayAfya",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f8fcfb",
        "theme_color": "#153147",
        "icons": [
            {
                "src": "/static/img/hero-clinical.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }
    return JsonResponse(payload)


def service_worker(request):
    script = """
const CACHE_NAME = "bayafya-v21";
const PRECACHE_URLS = [
  "/",
  "/manifest.webmanifest",
  "/static/css/app.css?v=20260327-01",
  "/static/js/app.js?v=20260327-02",
  "/static/img/hero-clinical.svg",
  "/static/img/banner-health-grid.svg",
  "/static/img/auth-care.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const requestUrl = new URL(event.request.url);
  if (requestUrl.origin !== self.location.origin) return;
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/"))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
        return response;
      });
    })
  );
});
"""
    return HttpResponse(script, content_type="application/javascript")
