import json

from channels.generic.websocket import AsyncWebsocketConsumer


class VideoChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"video_{self.room_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        payload = json.loads(text_data)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "room_message",
                "message": payload.get("message", ""),
                "sender": getattr(self.scope.get("user"), "username", "guest"),
            },
        )

    async def room_message(self, event):
        await self.send(text_data=json.dumps({"message": event["message"], "sender": event["sender"]}))
