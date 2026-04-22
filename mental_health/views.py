from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from core.assistant import analyze_mental_health_support
from core.permissions import counselor_required

from .forms import MoodLogForm, TherapySessionForm
from .models import Counselor, MoodLog, TherapySession, WellnessResource


@login_required
def dashboard(request):
    sessions = TherapySession.objects.none()
    if request.user.role == "counselor":
        counselor = get_object_or_404(Counselor, user=request.user)
        sessions = TherapySession.objects.filter(counselor=counselor)
    elif request.user.role == "patient":
        sessions = TherapySession.objects.filter(patient=request.user)
    mood_support = request.session.pop("mental_health_support", None)
    return render(
        request,
        "mental_health/dashboard.html",
        {
            "mood_logs": MoodLog.objects.filter(user=request.user)[:5],
            "resources": WellnessResource.objects.all(),
            "sessions": sessions,
            "mood_form": MoodLogForm(),
            "session_form": TherapySessionForm() if request.user.role == "counselor" else None,
            "mood_support": mood_support,
        },
    )


@login_required
def log_mood(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    form = MoodLogForm(request.POST)
    if form.is_valid():
        mood_log = form.save(commit=False)
        mood_log.user = request.user
        mood_log.save()
        support = analyze_mental_health_support(
            user=request.user,
            patient=getattr(request.user, "patient", None),
            text=" ".join(filter(None, [mood_log.mood, mood_log.notes])),
        )
        request.session["mental_health_support"] = support.as_dict()
        messages.success(request, "Mood entry recorded.")
    return redirect("mental_health:dashboard")


@login_required
@counselor_required
def schedule_session(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    counselor = get_object_or_404(Counselor, user=request.user)
    form = TherapySessionForm(request.POST)
    if form.is_valid():
        session = form.save(commit=False)
        session.counselor = counselor
        session.save()
        messages.success(request, "Therapy session scheduled.")
    return redirect("mental_health:dashboard")
