from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from core.services import send_user_notification

from .forms import AmbulanceRequestForm
from .models import Ambulance, AmbulanceRequest


def _assign_available_ambulance(ambulance_request: AmbulanceRequest):
    ambulance = Ambulance.objects.filter(is_available=True).first()
    if ambulance:
        ambulance_request.assigned_ambulance = ambulance
        ambulance_request.status = AmbulanceRequest.Status.ASSIGNED
        ambulance_request.save(update_fields=["assigned_ambulance", "status"])
        ambulance.is_available = False
        ambulance.save(update_fields=["is_available"])
    return ambulance


@login_required
def request_ambulance(request):
    if request.method == "POST":
        form = AmbulanceRequestForm(request.POST)
        if form.is_valid():
            ambulance_request = form.save(commit=False)
            ambulance_request.user = request.user
            ambulance_request.save()
            assigned = _assign_available_ambulance(ambulance_request)
            if assigned:
                send_user_notification(
                    request.user,
                    "Ambulance assigned",
                    f"Ambulance {assigned.vehicle_number} has been assigned to your emergency request.",
                )
            messages.success(request, "Emergency request submitted.")
            return redirect("ambulance:track", request_id=ambulance_request.pk)
    else:
        form = AmbulanceRequestForm()
    return render(request, "ambulance/request.html", {"form": form})


@login_required
def track_ambulance(request, request_id):
    ambulance_request = get_object_or_404(AmbulanceRequest, pk=request_id, user=request.user)
    return render(request, "ambulance/track.html", {"request_obj": ambulance_request})
