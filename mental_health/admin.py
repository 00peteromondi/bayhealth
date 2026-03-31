from django.contrib import admin

from .models import Counselor, MoodLog, TherapySession, WellnessResource


admin.site.register(Counselor)
admin.site.register(TherapySession)
admin.site.register(MoodLog)
admin.site.register(WellnessResource)
