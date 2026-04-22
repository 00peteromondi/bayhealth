from django.contrib import admin

from .models import Prescription, ReportUpload, VideoConsultation


admin.site.register(VideoConsultation)
admin.site.register(Prescription)
admin.site.register(ReportUpload)
