from django.urls import include, path
from rest_framework.routers import DefaultRouter

from clinica import views

router = DefaultRouter()
router.register("patients", views.PatientViewSet, basename="patient")
router.register("appointments", views.AppointmentViewSet, basename="appointment")
router.register("treatments", views.TreatmentViewSet, basename="treatment")

urlpatterns = [
    path("api/login/", views.login),
    path("api/dentists/", views.dentists),
    path("api/", include(router.urls)),
]
