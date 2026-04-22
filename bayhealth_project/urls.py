from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("hospital/", include("hospital.urls")),
    path("telemedicine/", include("telemedicine.urls")),
    path("symptom-checker/", include("symptom_checker.urls")),
    path("pharmacy/", include("pharmacy.urls")),
    path("mental-health/", include("mental_health.urls")),
    path("ambulance/", include("ambulance.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler400 = "core.views.error_400"
handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
