from django.urls import re_path

from .consumers import AmbulanceLocationConsumer


websocket_urlpatterns = [
    re_path(r"ws/ambulance/(?P<request_id>\d+)/$", AmbulanceLocationConsumer.as_asgi()),
]
