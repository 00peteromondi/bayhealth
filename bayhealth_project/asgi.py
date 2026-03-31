import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from ambulance.routing import websocket_urlpatterns as ambulance_ws
from core.routing import websocket_urlpatterns as core_ws
from hospital.routing import websocket_urlpatterns as hospital_ws
from telemedicine.routing import websocket_urlpatterns as telemedicine_ws


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bayhealth_project.settings")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(core_ws + hospital_ws + telemedicine_ws + ambulance_ws)
        ),
    }
)
