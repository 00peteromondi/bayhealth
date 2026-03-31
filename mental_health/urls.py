from django.urls import path

from . import views


app_name = "mental_health"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("mood/log/", views.log_mood, name="log_mood"),
    path("sessions/schedule/", views.schedule_session, name="schedule_session"),
]
