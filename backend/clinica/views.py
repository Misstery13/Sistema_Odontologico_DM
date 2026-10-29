import hmac
import secrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .auth import RolePermission
from .models import (
    Appointment, AuditLog, Chair, ClinicalNote, Consent, ConsentTemplate, Patient, PerioExam, Prescription, Tooth,
    Treatment, User, sign,
)
from .notify import notify, send
from .serializers import (
    AppointmentSerializer,
    AuditLogSerializer,
    ChairSerializer,
    ClinicalNoteSerializer,
    ConsentSerializer,
    ConsentTemplateSerializer,
    PerioExamSerializer,
    PrescriptionSerializer,
    PatientSerializer,
    ToothSerializer,
    TreatmentSerializer,
)


def audit(request, action, model, object_id=""):
    # Caddy reescribe X-Forwarded-For con la IP real del cliente
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
    AuditLog.objects.create(clinic_id=request.tenant, user=request.user, action=action, model=model, object_id=str(object_id), ip=ip)


class TenantViewSet(viewsets.ModelViewSet):
    """Filtra todo por la clínica del usuario (multitenant) y, si `audited`, registra cada acción (RNF-06)."""

    model = None
    resource = None
    audited = False
    permission_classes = [RolePermission]

    def get_queryset(self):
        qs = self.model.objects.filter(clinic_id=self.request.tenant)
        patient = self.request.query_params.get("patient")
        if patient and hasattr(self.model, "patient"):
            qs = qs.filter(patient_id=patient)
        return qs

    def list(self, request, *args, **kwargs):
        if self.audited:
            audit(request, "list", self.model.__name__, request.query_params.get("patient", ""))
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        if self.audited:
            audit(request, "read", self.model.__name__, kwargs["pk"])
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        obj = serializer.save(clinic_id=self.request.tenant)
        if self.audited:
            audit(self.request, "create", self.model.__name__, obj.pk)
        return obj

    def perform_update(self, serializer):
        obj = serializer.save()
        if self.audited:
            audit(self.request, "update", self.model.__name__, obj.pk)


class PatientViewSet(TenantViewSet):
    model = Patient
    resource = "patients"
    action_resources = {"odontogram": "odontogram"}
    audited = True
    serializer_class = PatientSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

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
            v = s.validated_data
            Tooth.objects.update_or_create(
                patient=patient,
                number=v["number"],
                defaults={"state": v.get("state", "sano"), "surfaces": v.get("surfaces", {}), "clinic_id": patient.clinic_id},
            )
        audit(request, "update" if request.method == "POST" else "read", "Tooth", patient.pk)
        return Response(ToothSerializer(patient.teeth.all(), many=True).data)


class ChairViewSet(TenantViewSet):
    model = Chair
    resource = "chairs"
    serializer_class = ChairSerializer


class AppointmentViewSet(TenantViewSet):
    model = Appointment
    resource = "appointments"
    serializer_class = AppointmentSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient", "dentist", "chair")
        p = self.request.query_params
        if p.get("date"):
            qs = qs.filter(start__date=p["date"])
        if p.get("from") and p.get("to"):  # vista semanal: rango inclusivo de fechas
            qs = qs.filter(start__date__gte=p["from"], start__date__lte=p["to"])
        for f in ("chair", "dentist"):
            if p.get(f):
                qs = qs.filter(**{f"{f}_id": p[f]})
        return qs

    def perform_create(self, serializer):
        notify(super().perform_create(serializer), "confirmacion")


class TreatmentViewSet(TenantViewSet):
    model = Treatment
    resource = "treatments"
    audited = True
    serializer_class = TreatmentSerializer
    http_method_names = ["get", "post", "head", "options"]  # RN-01: lo realizado no se edita ni se borra


class ClinicalNoteViewSet(TenantViewSet):
    model = ClinicalNote
    resource = "notes"
    audited = True
    serializer_class = ClinicalNoteSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]  # sin DELETE (RN-01)

    def get_queryset(self):
        return super().get_queryset().select_related("author")

    def perform_create(self, serializer):
        obj = serializer.save(clinic_id=self.request.tenant, author=self.request.user)
        audit(self.request, "create", "ClinicalNote", obj.pk)

    def perform_update(self, serializer):
        note = serializer.instance
        if note.author_id != self.request.user.pk:
            raise PermissionDenied("Solo el autor puede modificar su nota")
        if note.locked:
            raise PermissionDenied("La nota está bloqueada; registra una adenda")
        super().perform_update(serializer)


class AuthoredViewSet(TenantViewSet):
    """Registros clínicos firmados (perio, recetas): se crean con su autor y no se editan ni borran (RN-01)."""

    audited = True
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().select_related("author")

    def perform_create(self, serializer):
        obj = serializer.save(clinic_id=self.request.tenant, author=self.request.user)
        audit(self.request, "create", self.model.__name__, obj.pk)


class PerioExamViewSet(AuthoredViewSet):
    model = PerioExam
    resource = "perio"
    serializer_class = PerioExamSerializer


class PrescriptionViewSet(AuthoredViewSet):
    model = Prescription
    resource = "prescriptions"
    serializer_class = PrescriptionSerializer


class ConsentTemplateViewSet(TenantViewSet):
    model = ConsentTemplate
    resource = "consent_templates"
    serializer_class = ConsentTemplateSerializer


def mask(contact):
    return f"{contact[:3]}…{contact[-2:]}"


class ConsentViewSet(TenantViewSet):
    """RF-06: el formato se copia completado al crearlo y se firma una vez (pantalla táctil u OTP)."""

    model = Consent
    resource = "consents"
    audited = True
    serializer_class = ConsentSerializer
    http_method_names = ["get", "post", "head", "options"]
    OTP_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5

    def perform_create(self, serializer):
        tpl, patient, user = serializer.validated_data.pop("template"), serializer.validated_data["patient"], self.request.user
        text = tpl.body.format_map({
            "paciente": f"{patient.first_name} {patient.last_name}",
            "cedula": patient.cedula,
            "procedimiento": tpl.procedure,
            "odontologo": user.get_full_name() or user.username,
            "fecha": timezone.localdate().strftime("%d/%m/%Y"),
        })
        obj = serializer.save(clinic_id=self.request.tenant, created_by=user, procedure=tpl.procedure, text=text)
        audit(self.request, "create", "Consent", obj.pk)

    def unsigned(self):
        consent = self.get_object()
        if consent.signed_at:
            raise ValidationError("Este consentimiento ya fue firmado")
        return consent

    @action(detail=True, methods=["post"], url_path="request-otp")
    def request_otp(self, request, pk=None):
        c = self.unsigned()
        p = c.patient
        channel, recipient = ("whatsapp", p.phone) if p.phone else ("email", p.email)
        if not recipient:
            raise ValidationError("El paciente no tiene teléfono ni email para recibir el código")
        code = f"{secrets.randbelow(10**6):06d}"
        c.otp_hash, c.otp_expires, c.otp_attempts = sign("otp", c.pk, code), timezone.now() + timedelta(minutes=self.OTP_MINUTES), 0
        c.save(update_fields=["otp_hash", "otp_expires", "otp_attempts"])
        send(channel, recipient, f"Tu código para firmar el consentimiento de {c.procedure} es {code}. Vence en {self.OTP_MINUTES} minutos.")
        return Response({"sent_to": mask(recipient), "channel": channel})

    @action(detail=True, methods=["post"], url_path="sign")
    def sign_consent(self, request, pk=None):
        c = self.unsigned()
        method, signer = request.data.get("method"), str(request.data.get("signer_name", "")).strip()
        if not signer:
            raise ValidationError({"signer_name": "Indica quién firma (paciente o tutor legal)"})
        if method == "biometrica":
            img = str(request.data.get("signature_image", ""))
            if not img.startswith("data:image/png;base64,") or not 200 < len(img) < 400_000:
                raise ValidationError({"signature_image": "Falta la firma o es inválida"})
            c.signature_image = img
        elif method == "otp":
            if not c.otp_hash or timezone.now() > c.otp_expires:
                raise ValidationError({"code": "El código venció; solicita uno nuevo"})
            if c.otp_attempts >= self.OTP_MAX_ATTEMPTS:
                raise ValidationError({"code": "Demasiados intentos; solicita un código nuevo"})
            if not hmac.compare_digest(c.otp_hash, sign("otp", c.pk, str(request.data.get("code", "")).strip())):
                c.otp_attempts += 1
                c.save(update_fields=["otp_attempts"])
                raise ValidationError({"code": "Código incorrecto"})
        else:
            raise ValidationError({"method": "Método de firma inválido"})
        c.method, c.signer_name, c.signed_at = method, signer, timezone.now()
        c.signature = sign(c.pk, c.text, signer, method, c.signed_at.isoformat(), c.signature_image or c.otp_hash)
        c.save()
        audit(request, "update", "Consent", c.pk)
        return Response(self.get_serializer(c).data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    resource = "audit"
    permission_classes = [RolePermission]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.filter(clinic_id=self.request.tenant).select_related("user")
        return qs[:300]  # ponytail: últimos 300; paginar cuando el volumen lo pida


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def login(request):
    user = authenticate(username=request.data.get("username"), password=request.data.get("password"))
    if not user or not user.clinic_id:
        return Response({"detail": "Usuario o contraseña incorrectos"}, status=400)
    Token.objects.filter(user=user).delete()  # sesión nueva en cada ingreso
    token = Token.objects.create(user=user)
    User.objects.filter(pk=user.pk).update(last_activity=timezone.now())
    return Response(
        {"token": token.key, "id": user.pk, "user": user.get_full_name() or user.username, "role": user.role, "clinic": user.clinic.name}
    )


@api_view(["GET"])
@permission_classes([RolePermission])
def dentists(request):
    users = User.objects.filter(clinic_id=request.tenant, is_active=True, role="odontologo")
    return Response([{"id": u.id, "name": u.get_full_name() or u.username} for u in users])


dentists.cls.resource = "dentists"
