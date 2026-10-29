from django.contrib.auth import authenticate
from django.db.models import Q
from rest_framework import permissions, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .models import Appointment, Patient, Tooth, Treatment, User
from .serializers import AppointmentSerializer, PatientSerializer, ToothSerializer, TreatmentSerializer


class HasTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.tenant is not None


class TenantViewSet(viewsets.ModelViewSet):
    """Todas las consultas se filtran por la clínica del usuario (aislamiento multitenant)."""

    model = None
    permission_classes = [permissions.IsAuthenticated, HasTenant]

    def get_queryset(self):
        qs = self.model.objects.filter(clinic_id=self.request.tenant)
        patient = self.request.query_params.get("patient")
        if patient and hasattr(self.model, "patient"):
            qs = qs.filter(patient_id=patient)
        return qs

    def perform_create(self, serializer):
        serializer.save(clinic_id=self.request.tenant)


class PatientViewSet(TenantViewSet):
    model = Patient
    serializer_class = PatientSerializer

    def get_queryset(self):
        q = self.request.query_params.get("q")
        qs = super().get_queryset()
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(cedula__icontains=q))
        return qs

    @action(detail=True, methods=["get", "post"])
    def odontogram(self, request, pk=None):
        patient = self.get_object()
        if request.method == "POST":
            s = ToothSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            Tooth.objects.update_or_create(
                patient=patient,
                number=s.validated_data["number"],
                defaults={"state": s.validated_data["state"], "clinic_id": patient.clinic_id},
            )
        return Response(ToothSerializer(patient.teeth.all(), many=True).data)


class AppointmentViewSet(TenantViewSet):
    model = Appointment
    serializer_class = AppointmentSerializer

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient", "dentist")
        date = self.request.query_params.get("date")
        return qs.filter(start__date=date) if date else qs


class TreatmentViewSet(TenantViewSet):
    model = Treatment
    serializer_class = TreatmentSerializer


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([AnonRateThrottle])
def login(request):
    user = authenticate(username=request.data.get("username"), password=request.data.get("password"))
    if not user or not user.clinic_id:
        return Response({"detail": "Usuario o contraseña incorrectos"}, status=400)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": user.get_full_name() or user.username, "clinic": user.clinic.name})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated, HasTenant])
def dentists(request):
    users = User.objects.filter(clinic_id=request.tenant, is_active=True)
    return Response([{"id": u.id, "name": u.get_full_name() or u.username} for u in users])
