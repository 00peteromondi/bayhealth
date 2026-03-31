from django.urls import re_path

from .consumers import CommunicationsInboxConsumer, NotificationConsumer, StaffConversationConsumer


websocket_urlpatterns = [
    re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
    re_path(r"ws/communications/inbox/$", CommunicationsInboxConsumer.as_asgi()),
    re_path(r"ws/communications/(?P<conversation_id>\d+)/$", StaffConversationConsumer.as_asgi()),
]
