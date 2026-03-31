from django.contrib import admin

from .models import Ambulance, AmbulanceRequest, EmergencyContact


admin.site.register(Ambulance)
admin.site.register(AmbulanceRequest)
admin.site.register(EmergencyContact)
