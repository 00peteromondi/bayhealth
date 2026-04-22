from django.urls import re_path

from .consumers import VideoChatConsumer


websocket_urlpatterns = [
    re_path(r"ws/video/(?P<room_id>[\w-]+)/$", VideoChatConsumer.as_asgi()),
]
