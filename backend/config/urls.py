from django.http import JsonResponse
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
router.register("perio", views.PerioExamViewSet, basename="perio")
router.register("prescriptions", views.PrescriptionViewSet, basename="prescription")
router.register("consent-templates", views.ConsentTemplateViewSet, basename="consent-template")
router.register("consents", views.ConsentViewSet, basename="consent")
router.register("procedures", views.ProcedureViewSet, basename="procedure")
router.register("supplies", views.SupplyViewSet, basename="supply")
router.register("stock-movements", views.StockMovementViewSet, basename="stock-movement")
router.register("budgets", views.BudgetViewSet, basename="budget")
router.register("commission-rules", views.CommissionRuleViewSet, basename="commission-rule")
router.register("users", views.UserViewSet, basename="user")
router.register("vitals", views.VitalSignsViewSet, basename="vitals")
router.register("attachments", views.AttachmentViewSet, basename="attachment")

urlpatterns = [
    path("api/login/", views.login),
    path("api/login/mfa/", views.login_mfa),
    path("api/password/", views.change_password),
    path("api/health/", views.health),
    path("api/dentists/", views.dentists),
    path("api/reports/", views.reports),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),  # OpenAPI 3
    path("api/", include(router.urls)),
]


# la API responde siempre JSON, también en errores fuera de DRF
def not_found(request, exception=None):
    return JsonResponse({"detail": "No encontrado"}, status=404)


def server_error(request):
    return JsonResponse({"detail": "Error interno del servidor"}, status=500)


handler404 = not_found
handler500 = server_error
