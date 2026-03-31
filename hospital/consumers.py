import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from core.models import User
from hospital.models import Hospital, HospitalAccess, Patient


class HospitalLiveConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close()
            return
        self.hospital_id = await self._resolve_hospital_id()
        if not self.hospital_id:
            await self.close()
            return
        self.group_name = f"hospital_{self.hospital_id}"
        if not await self._can_access_hospital():
            await self.close()
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if getattr(self, "group_name", None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def hospital_message(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    @database_sync_to_async
    def _resolve_hospital_id(self):
        user = self.scope["user"]
        requested_hospital_id = self.scope.get("url_route", {}).get("kwargs", {}).get("hospital_id")
        if requested_hospital_id:
            try:
                requested_hospital_id = int(requested_hospital_id)
            except (TypeError, ValueError):
                requested_hospital_id = None
        if user.role == User.Role.PATIENT and hasattr(user, "patient") and user.patient.hospital_id:
            return user.patient.hospital_id
        session_hospital_id = self.scope["session"].get("current_hospital_id")
        if requested_hospital_id:
            return requested_hospital_id
        if session_hospital_id:
            return session_hospital_id
        access = HospitalAccess.objects.filter(user=user, status=HospitalAccess.Status.ACTIVE).select_related("hospital").order_by("-is_primary", "hospital__name").first()
        if access:
            return access.hospital_id
        if hasattr(user, "patient") and user.patient.hospital_id:
            return user.patient.hospital_id
        return None

    @database_sync_to_async
    def _can_access_hospital(self):
        user = self.scope["user"]
        return (
            HospitalAccess.objects.filter(
                user=user,
                hospital_id=self.hospital_id,
                status=HospitalAccess.Status.ACTIVE,
            ).exists()
            or (user.role == User.Role.PATIENT and hasattr(user, "patient") and user.patient.hospital_id == self.hospital_id)
        )
