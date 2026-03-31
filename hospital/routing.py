from django.urls import re_path

from .consumers import HospitalLiveConsumer


websocket_urlpatterns = [
    re_path(r"ws/hospital/(?P<hospital_id>\d+)/$", HospitalLiveConsumer.as_asgi()),
]
