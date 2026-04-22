from django.urls import path

from . import views


app_name = "telemedicine"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path(
        "consultations/create/<int:appointment_id>/",
        views.create_consultation,
        name="create_consultation",
    ),
    path("room/<str:room_id>/", views.join_room, name="join_room"),
    path(
        "consultations/<int:consultation_id>/upload-report/",
        views.upload_report,
        name="upload_report",
    ),
    path(
        "consultations/<int:consultation_id>/issue-prescription/",
        views.issue_prescription,
        name="issue_prescription",
    ),
    path(
        "consultations/<int:consultation_id>/issue-lab-request/",
        views.issue_lab_request,
        name="issue_lab_request",
    ),
]
