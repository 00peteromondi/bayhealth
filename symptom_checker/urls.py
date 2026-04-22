from django.urls import path

from .views import symptom_check


app_name = "symptom_checker"

urlpatterns = [
    path("", symptom_check, name="check"),
]
