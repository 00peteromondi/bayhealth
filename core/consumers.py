import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db.models import Q
from django.utils import timezone

from .assistant import build_assistant_chat_response
from .models import StaffConversation, StaffConversationParticipant, StaffMessage
from .services import broadcast_staff_message, send_user_notification


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close()
            return
        self.group_name = f"user_{user.pk}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_message(self, event):
        await self.send(text_data=json.dumps(event["payload"]))


class CommunicationsInboxConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close()
            return
        self.group_name = f"communications_user_{user.pk}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def communications_inbox(self, event):
        await self.send(text_data=json.dumps(event["payload"]))


class StaffConversationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close()
            return
        self.conversation_id = int(self.scope["url_route"]["kwargs"]["conversation_id"])
        self.group_name = f"staff_conversation_{self.conversation_id}"
        self.allowed = await self._user_can_access()
        if not self.allowed:
            await self.close()
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self._mark_read()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        payload = json.loads(text_data or "{}")
        event_type = payload.get("type")
        if event_type == "typing":
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "typing_indicator",
                    "payload": {
                        "conversation_id": self.conversation_id,
                        "user_id": self.scope["user"].pk,
                        "name": self.scope["user"].get_full_name() or self.scope["user"].username,
                        "is_typing": bool(payload.get("is_typing")),
                    },
                },
            )
            return
        body = (payload.get("message") or "").strip()
        if not body:
            return
        message_payload = await self._create_user_message(body)
        if not message_payload:
            return
        if "@bayafya" in body.lower() or "/bayafya" in body.lower():
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "typing_indicator",
                    "payload": {
                        "conversation_id": self.conversation_id,
                        "user_id": "assistant",
                        "name": "BayAfya Assistant",
                        "is_typing": True,
                    },
                },
            )
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "conversation_message",
                    "payload": {
                        "conversation_id": self.conversation_id,
                        "message": {
                            "id": f"loading-{self.scope['user'].pk}",
                            "body": "",
                            "kind": "assistant_loading",
                            "sender_id": None,
                            "sender": "BayAfya Assistant",
                            "created_at": "",
                        },
                    },
                },
            )
            assistant_payload = await self._create_assistant_reply(body)
            if assistant_payload:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "conversation_message",
                        "payload": {
                            "conversation_id": self.conversation_id,
                            "message": assistant_payload,
                        },
                    },
                )
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "typing_indicator",
                    "payload": {
                        "conversation_id": self.conversation_id,
                        "user_id": "assistant",
                        "name": "BayAfya Assistant",
                        "is_typing": False,
                    },
                },
            )

    async def conversation_message(self, event):
        payload = event["payload"]
        message = payload.get("message") or {}
        sender_id = message.get("sender_id")
        if message.get("kind") != "assistant_loading" and str(sender_id or "") != str(self.scope["user"].pk):
            await self._mark_read()
        await self.send(text_data=json.dumps(payload))

    async def typing_indicator(self, event):
        payload = event["payload"]
        if str(payload.get("user_id")) == str(self.scope["user"].pk):
            return
        await self.send(text_data=json.dumps({"typing": payload}))

    @database_sync_to_async
    def _user_can_access(self):
        user = self.scope["user"]
        if getattr(user, "role", None) == "patient":
            return StaffConversation.objects.filter(
                pk=self.conversation_id,
                is_active=True,
            ).filter(
                Q(participants__user=user) | Q(linked_patient__user=user)
            ).exists()
        return StaffConversationParticipant.objects.filter(
            conversation_id=self.conversation_id,
            user=user,
            conversation__is_active=True,
        ).exists()

    @database_sync_to_async
    def _mark_read(self):
        StaffConversationParticipant.objects.filter(
            conversation_id=self.conversation_id,
            user=self.scope["user"],
        ).update(last_read_at=timezone.now())

    @database_sync_to_async
    def _create_user_message(self, body):
        conversation = (
            StaffConversation.objects.select_related("hospital", "linked_patient")
            .prefetch_related("participants__user")
            .filter(pk=self.conversation_id, is_active=True)
            .filter(Q(participants__user=self.scope["user"]) | Q(linked_patient__user=self.scope["user"]))
            .first()
        )
        if conversation is None:
            return None
        sender = self.scope["user"]
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
        broadcast_staff_message(conversation, message)
        return {
            "id": message.pk,
            "body": message.body,
            "kind": message.kind,
            "sender_id": sender.pk,
            "sender": message.sender_label,
            "created_at": message.created_at.isoformat(),
        }

    @database_sync_to_async
    def _create_assistant_reply(self, trigger_text):
        conversation = (
            StaffConversation.objects.select_related("hospital", "linked_patient")
            .prefetch_related("messages")
            .filter(pk=self.conversation_id, is_active=True, assistant_enabled=True)
            .first()
        )
        if conversation is None:
            return None
        history = []
        for item in conversation.messages.order_by("-created_at")[:12]:
            if item.kind == StaffMessage.Kind.SYSTEM:
                continue
            role = "assistant" if item.kind == StaffMessage.Kind.ASSISTANT else "user"
            history.append({"role": role, "content": item.body})
        history.reverse()
        prompt = trigger_text.replace("@bayafya", "").replace("@BayAfya", "").replace("/bayafya", "").strip() or trigger_text
        history.append({"role": "user", "content": prompt})
        response = build_assistant_chat_response(
            user=self.scope["user"],
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
        return {
            "id": message.pk,
            "body": message.body,
            "kind": message.kind,
            "sender_id": None,
            "sender": message.sender_label,
            "created_at": message.created_at.isoformat(),
        }
