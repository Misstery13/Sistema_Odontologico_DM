from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.routers import DefaultRouter

from clinica import views

router = DefaultRouter()
router.register("patients", views.PatientViewSet, basename="patient")
router.register("appointments", views.AppointmentViewSet, basename="appointment")
router.register("treatments", views.TreatmentViewSet, basename="treatment")
router.register("notes", views.ClinicalNoteViewSet, basename="note")
router.register("chairs", views.ChairViewSet, basename="chair")
router.register("audit", views.AuditLogViewSet, basename="audit")

urlpatterns = [
    path("api/login/", views.login),
    path("api/dentists/", views.dentists),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),  # OpenAPI 3
    path("api/", include(router.urls)),
]
