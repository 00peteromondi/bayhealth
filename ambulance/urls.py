from django.urls import path

from . import views


app_name = "ambulance"

urlpatterns = [
    path("request/", views.request_ambulance, name="request"),
    path("track/<int:request_id>/", views.track_ambulance, name="track"),
]
