import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import AmbulanceRequest


class AmbulanceLocationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.request_id = self.scope["url_route"]["kwargs"]["request_id"]
        self.group_name = f"ambulance_{self.request_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        if "status" in data:
            await self.update_request_status(data["status"])
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "location_update",
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "status": data.get("status"),
            },
        )

    async def location_update(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def update_request_status(self, status: str):
        AmbulanceRequest.objects.filter(pk=self.request_id).update(status=status)
