from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from .models import Notification, StaffConversation, StaffConversationParticipant, StaffMessage, User


def send_user_notification(user: User, title: str, message: str) -> Notification:
    notification = Notification.objects.create(user=user, title=title, message=message)
    if getattr(user, "email", ""):
        send_mail(
            subject=title,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[user.email],
            fail_silently=getattr(settings, "EMAIL_FAIL_SILENTLY", True),
        )
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user.pk}",
        {
            "type": "notification_message",
            "payload": {
                "id": notification.pk,
                "title": notification.title,
                "message": notification.message,
                "created_at": notification.created_at.isoformat(),
            },
        },
    )
    return notification


def send_email_verification(request, user: User, code: str, *, recipient_email: str | None = None) -> None:
    email = (recipient_email or getattr(user, "email", "") or "").strip()
    if not email:
        return
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    context = {
        "user": user,
        "verification_code": code,
        "recipient_email": email,
        "platform_name": getattr(settings, "PLATFORM_NAME", "BayAfya"),
        "verification_url": request.build_absolute_uri(reverse("email_verification_confirm")),
    }
    subject = render_to_string("core/email_verification_subject.txt", context).strip()
    text_body = render_to_string("core/email_verification_email.txt", context)
    html_body = render_to_string("core/email_verification_email.html", context)
    email_message = EmailMultiAlternatives(subject, text_body, from_email, [email])
    email_message.attach_alternative(html_body, "text/html")
    email_message.send(fail_silently=getattr(settings, "EMAIL_FAIL_SILENTLY", True))


def broadcast_staff_message(conversation: StaffConversation, message: StaffMessage) -> None:
    channel_layer = get_channel_layer()
    payload = {
        "conversation_id": conversation.pk,
        "message": {
            "id": message.pk,
            "body": message.body,
            "kind": message.kind,
            "sender_id": message.sender_id,
            "sender": message.sender_label
            or (message.sender.get_full_name() or message.sender.username if message.sender_id else "BayAfya Assistant"),
            "created_at": message.created_at.isoformat(),
        },
    }
    prefetched_conversation = (
        StaffConversation.objects.select_related("hospital", "linked_patient")
        .prefetch_related("participants__user", "messages")
        .filter(pk=conversation.pk)
        .first()
    ) or conversation

    def conversation_title_for(user: User) -> str:
        if prefetched_conversation.kind == StaffConversation.Kind.TEAM:
            return prefetched_conversation.title or prefetched_conversation.get_purpose_display()
        others = [
            participant.user.get_full_name() or participant.user.username
            for participant in prefetched_conversation.participants.all()
            if participant.user_id != user.id
        ]
        return others[0] if others else (prefetched_conversation.title or "Direct conversation")

    subtitle_parts = []
    if prefetched_conversation.kind == StaffConversation.Kind.TEAM:
        subtitle_parts.append(prefetched_conversation.get_purpose_display())
    else:
        subtitle_parts.append("Direct message")
    if prefetched_conversation.hospital_id:
        subtitle_parts.append(prefetched_conversation.hospital.name)
    if prefetched_conversation.linked_patient_id:
        subtitle_parts.append(f"Patient: {prefetched_conversation.linked_patient}")
    subtitle = " · ".join(subtitle_parts)
    preview = (message.body or "")[:110] or "No messages yet."

    for participant in StaffConversationParticipant.objects.select_related("user").filter(conversation=prefetched_conversation):
        if message.sender_id and participant.user_id == message.sender_id:
            unread_count = 0
        else:
            unread_messages = prefetched_conversation.messages.exclude(sender_id=participant.user_id)
            if participant.last_read_at:
                unread_messages = unread_messages.filter(created_at__gt=participant.last_read_at)
            unread_count = unread_messages.count()
        async_to_sync(channel_layer.group_send)(
            f"communications_user_{participant.user_id}",
            {
                "type": "communications_inbox",
                "payload": {
                    "conversation_id": prefetched_conversation.pk,
                    "title": conversation_title_for(participant.user),
                    "subtitle": subtitle,
                    "preview": preview,
                    "kind": prefetched_conversation.kind,
                    "purpose": prefetched_conversation.get_purpose_display(),
                    "assistant_enabled": prefetched_conversation.assistant_enabled,
                    "unread_count": unread_count,
                    "last_message_at": message.created_at.isoformat(),
                    "is_active": prefetched_conversation.is_active,
                },
            },
        )
    async_to_sync(channel_layer.group_send)(
        f"staff_conversation_{conversation.pk}",
        {
            "type": "conversation_message",
            "payload": payload,
        },
    )


def broadcast_hospital_update(hospital, *, event_type: str, payload: dict | None = None) -> None:
    if not hospital:
        return
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"hospital_{hospital.pk}",
        {
            "type": "hospital_message",
            "payload": {
                "hospital_id": hospital.pk,
                "event_type": event_type,
                **(payload or {}),
            },
        },
    )
