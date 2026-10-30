import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import FileResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from . import mfa

from .auth import RolePermission
from .models import (
    Appointment, AuditLog, Chair, ClinicalNote, Consent, ConsentTemplate, Patient, PerioExam, Prescription, Tooth,
    Treatment, User, sign, Budget, BudgetItem, CommissionRule, Procedure, StockMovement, Supply, Attachment, VitalSigns,
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
    UserSerializer,
    AttachmentSerializer,
    TransferSerializer,
    VitalSignsSerializer,
    location_stock,
    BudgetItemSerializer,
    BudgetSerializer,
    CommissionRuleSerializer,
    ProcedureSerializer,
    StockMovementSerializer,
    SupplySerializer,
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
    http_method_names = ["get", "post", "patch", "head", "options"]  # se desactivan: las citas y el kardex los referencian


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


def consume_supplies(treatment, user):
    """RF-14: descarga los insumos de la receta estándar del procedimiento; devuelve el costo de materiales.
    ponytail: el stock puede quedar negativo; el registro clínico no se bloquea por inventario, la alerta de stock bajo lo señala."""
    cost = 0
    for line in treatment.catalog.recipe.select_related("supply") if treatment.catalog else []:
        Supply.objects.filter(pk=line.supply_id).update(stock=F("stock") - line.quantity)
        StockMovement.objects.create(clinic_id=treatment.clinic_id, supply=line.supply, chair=treatment.chair, quantity=-line.quantity,
                                     reason="consumo", treatment=treatment, user=user)
        cost += line.quantity * line.supply.unit_cost
    return round(cost, 2)


class TreatmentViewSet(TenantViewSet):
    model = Treatment
    resource = "treatments"
    audited = True
    serializer_class = TreatmentSerializer
    http_method_names = ["get", "post", "head", "options"]  # RN-01: lo realizado no se edita ni se borra

    def get_queryset(self):
        return super().get_queryset().select_related("dentist")

    @transaction.atomic
    def perform_create(self, serializer):
        t = serializer.save(clinic_id=self.request.tenant, dentist=self.request.user)
        t.material_cost = consume_supplies(t, self.request.user)
        t.save(update_fields=["material_cost"])
        audit(self.request, "create", "Treatment", t.pk)


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


class ExportMixin:
    """RNF-06: imprimir o descargar un registro clínico queda en la auditoría como exportación."""

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        obj = self.get_object()
        audit(request, "export", self.model.__name__, obj.pk)
        return Response(self.get_serializer(obj).data)


class PerioExamViewSet(AuthoredViewSet):
    model = PerioExam
    resource = "perio"
    serializer_class = PerioExamSerializer


class PrescriptionViewSet(ExportMixin, AuthoredViewSet):
    model = Prescription
    resource = "prescriptions"
    serializer_class = PrescriptionSerializer


class ConsentTemplateViewSet(TenantViewSet):
    model = ConsentTemplate
    resource = "consent_templates"
    serializer_class = ConsentTemplateSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]  # lo firmado guarda su copia; editar no lo altera


def mask(contact):
    return f"{contact[:3]}…{contact[-2:]}"


class ConsentViewSet(ExportMixin, TenantViewSet):
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


class ProcedureViewSet(TenantViewSet):
    model = Procedure
    resource = "catalog"
    serializer_class = ProcedureSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().prefetch_related("recipe__supply")


class SupplyViewSet(TenantViewSet):
    model = Supply
    resource = "supplies"
    serializer_class = SupplySerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=False, url_path="by-location")
    def by_location(self, request):
        """Existencias por ubicación: bodega central y cada consultorio (objetivo 2.2)."""
        rows = (StockMovement.objects.filter(clinic_id=request.tenant).values("supply_id", "chair_id").annotate(q=Sum("quantity")))
        stock = {}
        for r in rows:
            stock.setdefault(r["supply_id"], {})[str(r["chair_id"] or "bodega")] = r["q"]
        chairs = Chair.objects.filter(clinic_id=request.tenant, active=True)
        return Response({
            "locations": [{"id": "bodega", "name": "Bodega central"}] + [{"id": str(c.pk), "name": c.name} for c in chairs],
            "supplies": [
                {"id": s.pk, "name": s.name, "unit": s.unit, "min_stock": s.min_stock, "total": s.stock, "low": s.stock <= s.min_stock,
                 "by_location": stock.get(s.pk, {})}
                for s in Supply.objects.filter(clinic_id=request.tenant)
            ],
        })


class StockMovementViewSet(TenantViewSet):
    model = StockMovement
    resource = "supplies"
    serializer_class = StockMovementSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("supply", "user", "chair")
        supply = self.request.query_params.get("supply")
        return (qs.filter(supply_id=supply) if supply else qs)[:200]

    @transaction.atomic
    def perform_create(self, serializer):
        supply = Supply.objects.select_for_update().get(pk=serializer.validated_data["supply"].pk)
        chair, qty = serializer.validated_data.get("chair"), serializer.validated_data["quantity"]
        if qty < 0 and location_stock(supply, chair) + qty < 0:
            raise ValidationError({"quantity": "No hay suficiente existencia en esa ubicación"})
        m = serializer.save(clinic_id=self.request.tenant, user=self.request.user)
        Supply.objects.filter(pk=m.supply_id).update(stock=F("stock") + m.quantity)

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def transfer(self, request):
        s = TransferSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        d = s.validated_data
        supply = Supply.objects.select_for_update().get(pk=d["supply"].pk)  # serializa traslados del mismo insumo
        if location_stock(supply, d["from_chair"]) < d["quantity"]:
            raise ValidationError({"quantity": "No hay suficiente existencia en el origen"})
        name = lambda c: c.name if c else "Bodega central"
        note = f"{name(d['from_chair'])} → {name(d['to_chair'])}"
        for chair, qty in ((d["from_chair"], -d["quantity"]), (d["to_chair"], d["quantity"])):
            StockMovement.objects.create(clinic_id=request.tenant, supply=supply, chair=chair, quantity=qty,
                                         reason="traslado", user=request.user, note=note)
        return Response({"detail": f"Trasladado: {note}"}, status=201)


class BudgetViewSet(TenantViewSet):
    model = Budget
    resource = "budgets"
    action_resources = {"decide": "budget_decision"}
    audited = True
    serializer_class = BudgetSerializer
    http_method_names = ["get", "post", "head", "options"]  # un presupuesto emitido no se edita: se emite otro

    def get_queryset(self):
        return super().get_queryset().select_related("author").prefetch_related("items__procedure", "items__appointments")

    def perform_create(self, serializer):
        obj = serializer.save(clinic_id=self.request.tenant, author=self.request.user)
        audit(self.request, "create", "Budget", obj.pk)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        """RF-08: el paciente aprueba todo o parte; lo aprobado queda listo para agendar."""
        budget = self.get_object()
        if budget.status != "pendiente":
            raise ValidationError("El presupuesto ya fue decidido")
        approved = {int(i) for i in request.data.get("approved_items", [])}
        items = list(budget.items.all())
        if not approved <= {i.pk for i in items}:
            raise ValidationError({"approved_items": "Ítem inválido"})
        for i in items:
            i.approved = i.pk in approved
        BudgetItem.objects.bulk_update(items, ["approved"])
        budget.status = "rechazado" if not approved else "aprobado" if len(approved) == len(items) else "parcial"
        budget.decided_at = timezone.now()
        budget.save(update_fields=["status", "decided_at"])
        audit(request, "update", "Budget", budget.pk)
        return Response(self.get_serializer(budget).data)

    @action(detail=False)
    def pending(self, request):
        """Ítems aprobados y aún no realizados del paciente: tareas para agendar o registrar."""
        items = BudgetItem.objects.filter(
            budget__clinic_id=request.tenant, budget__patient_id=request.query_params.get("patient"), approved=True, treatment__isnull=True
        ).select_related("procedure", "budget").prefetch_related("appointments")
        return Response(BudgetItemSerializer(items, many=True).data)


class CommissionRuleViewSet(TenantViewSet):
    model = CommissionRule
    resource = "commissions"
    serializer_class = CommissionRuleSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().select_related("dentist")


@api_view(["GET"])
@permission_classes([RolePermission])
def reports(request):
    """Reportes de gestión del período: producción, honorarios a liquidar (RF-13), agenda e inventario."""
    start, end = request.query_params.get("from"), request.query_params.get("to")
    if not start or not end:
        raise ValidationError("Indica el rango ?from=AAAA-MM-DD&to=AAAA-MM-DD")
    tenant = request.tenant
    treatments = Treatment.objects.filter(clinic_id=tenant, date__gte=start, date__lte=end).select_related("dentist")
    rules = {r.dentist_id: r for r in CommissionRule.objects.filter(clinic_id=tenant)}
    by_dentist = {}
    for t in treatments:
        if not t.dentist_id:
            continue
        row = by_dentist.setdefault(t.dentist_id, {
            "dentist": t.dentist.get_full_name() or t.dentist.username, "treatments": 0, "production": 0, "lab": 0, "materials": 0,
            "rule": rules[t.dentist_id].get_kind_display() + f" ({rules[t.dentist_id].value})" if t.dentist_id in rules else "Sin regla",
            "commission": 0,
        })
        row["treatments"] += 1
        row["production"] += t.cost
        row["lab"] += t.lab_cost
        row["materials"] += t.material_cost
        if t.dentist_id in rules:
            row["commission"] += rules[t.dentist_id].amount(t)
    appts = Appointment.objects.filter(clinic_id=tenant, start__date__gte=start, start__date__lte=end)
    by_status = dict(appts.values_list("status").annotate(n=Count("id")))
    attended = by_status.get("atendido", 0) + by_status.get("no_asistio", 0)
    used = StockMovement.objects.filter(clinic_id=tenant, reason="consumo", created_at__date__gte=start, created_at__date__lte=end)
    cost = Sum(ExpressionWrapper(-F("quantity") * F("supply__unit_cost"), output_field=DecimalField(max_digits=14, decimal_places=4)))
    consumption = used.values("supply__name", "supply__unit").annotate(quantity=-Sum("quantity")).order_by("-quantity")
    by_chair = [{"location": r["chair__name"] or "Bodega central", "cost": round(r["cost"] or 0, 2), "movements": r["n"]}
                for r in used.values("chair__name").annotate(cost=cost, n=Count("id")).order_by("-cost")]
    used_by_dentist = [{"dentist": " ".join(filter(None, [r["treatment__dentist__first_name"], r["treatment__dentist__last_name"]])) or "—",
                   "cost": round(r["cost"] or 0, 2), "movements": r["n"]}
                  for r in used.values("treatment__dentist__first_name", "treatment__dentist__last_name").annotate(cost=cost, n=Count("id")).order_by("-cost")]
    return Response({
        "production": treatments.aggregate(total=Sum("cost"))["total"] or 0,
        "commissions": list(by_dentist.values()),
        "top_procedures": list(treatments.values("procedure").annotate(count=Count("id"), production=Sum("cost")).order_by("-count")[:8]),
        "appointments": by_status,
        "no_show_rate": round(100 * by_status.get("no_asistio", 0) / attended, 1) if attended else None,
        "new_patients": Patient.objects.filter(clinic_id=tenant, created_at__date__gte=start, created_at__date__lte=end).count(),
        "consumption": list(consumption),
        "consumption_by_location": by_chair,
        "consumption_by_dentist": used_by_dentist,
        "low_stock": list(Supply.objects.filter(clinic_id=tenant, stock__lte=F("min_stock")).values("name", "unit", "stock", "min_stock")),
    })


reports.cls.resource = "reports"


class UserViewSet(TenantViewSet):
    """Administrador TI: alta, rol, activación, contraseña temporal y reinicio de MFA de los usuarios de su clínica."""

    model = User
    resource = "users"
    serializer_class = UserSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]  # sin borrar: los registros clínicos referencian al autor

    def get_queryset(self):
        return super().get_queryset().order_by("-is_active", "role", "last_name", "username")

    def perform_create(self, serializer):
        user = serializer.save()
        audit(self.request, "create", "User", user.pk)

    def perform_update(self, serializer):
        user = serializer.save()
        if not user.is_active:
            Token.objects.filter(user=user).delete()  # cierra su sesión de inmediato
        audit(self.request, "update", "User", user.pk)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        s = UserSerializer(user, data={"password": request.data.get("password", "")}, partial=True, context={"request": request})
        s.is_valid(raise_exception=True)
        user.set_password(s.validated_data["password"])
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        Token.objects.filter(user=user).delete()
        audit(request, "update", "User", user.pk)
        return Response(UserSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="reset-mfa")
    def reset_mfa(self, request, pk=None):
        user = self.get_object()
        user.mfa_secret, user.mfa_enabled, user.mfa_last_step = "", False, 0
        user.save(update_fields=["mfa_secret", "mfa_enabled", "mfa_last_step"])
        Token.objects.filter(user=user).delete()
        audit(request, "update", "User", user.pk)
        return Response(UserSerializer(user, context={"request": request}).data)


@api_view(["POST"])
def change_password(request):
    """Autoservicio (cualquier rol): obligatorio tras una contraseña temporal. Exige la contraseña actual."""
    user = request.user
    if not user.check_password(request.data.get("current_password", "")):
        raise ValidationError({"current_password": "La contraseña actual no es correcta"})  # nosec B105 - mensaje de error
    new = request.data.get("new_password", "")
    if new == request.data.get("current_password"):
        raise ValidationError({"new_password": "La nueva contraseña debe ser distinta"})  # nosec B105 - mensaje de error
    try:
        validate_password(new, user)
    except DjangoValidationError as e:
        raise ValidationError({"new_password": list(e.messages)})
    user.set_password(new)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    return Response({"detail": "Contraseña actualizada"})


class VitalSignsViewSet(TenantViewSet):
    model = VitalSigns
    resource = "vitals"
    audited = True
    serializer_class = VitalSignsSerializer
    http_method_names = ["get", "post", "head", "options"]  # registro clínico inmutable

    def get_queryset(self):
        return super().get_queryset().select_related("recorded_by")

    def perform_create(self, serializer):
        obj = serializer.save(clinic_id=self.request.tenant, recorded_by=self.request.user)
        audit(self.request, "create", "VitalSigns", obj.pk)


class AttachmentViewSet(TenantViewSet):
    """Archivos del expediente. No se sirven como estáticos: cada descarga pasa por permisos y auditoría."""

    model = Attachment
    resource = "attachments"
    audited = True
    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().select_related("uploaded_by")

    def perform_create(self, serializer):
        obj = serializer.save(clinic_id=self.request.tenant, uploaded_by=self.request.user)
        audit(self.request, "create", "Attachment", obj.pk)

    @action(detail=True, methods=["get"])
    def content(self, request, pk=None):
        """Contenido del archivo; ?descargar=1 lo baja como archivo (exportación)."""
        a = self.get_object()
        download = request.query_params.get("descargar") == "1"
        audit(request, "export" if download else "read", "Attachment", a.pk)
        response = FileResponse(a.file.open("rb"), content_type=a.content_type, as_attachment=download, filename=a.original_name)
        response["X-Content-Type-Options"] = "nosniff"
        return response


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    resource = "audit"
    permission_classes = [RolePermission]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.filter(clinic_id=self.request.tenant).select_related("user")
        return qs[:300]  # ponytail: últimos 300; paginar cuando el volumen lo pida


MFA_SALT = "odonto-mfa"
MFA_TICKET_SECONDS = 300


def start_session(user):
    Token.objects.filter(user=user).delete()  # sesión nueva en cada ingreso
    token = Token.objects.create(user=user)
    User.objects.filter(pk=user.pk).update(last_activity=timezone.now(), last_login=timezone.now())
    return Response({
        "token": token.key, "id": user.pk, "user": user.get_full_name() or user.username, "role": user.role,
        "clinic": user.clinic.name, "must_change_password": user.must_change_password,
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def login(request):
    """Paso 1: usuario y contraseña. Con MFA activo no entrega sesión, sino un ticket de 5 min para el paso 2."""
    user = authenticate(username=request.data.get("username"), password=request.data.get("password"))
    if not user or not user.clinic_id:
        return Response({"detail": "Usuario o contraseña incorrectos"}, status=400)
    if not settings.MFA_REQUIRED:
        return start_session(user)
    ticket = signing.dumps({"u": user.pk}, salt=MFA_SALT)
    if user.mfa_enabled:
        return Response({"mfa": "verify", "ticket": ticket})
    if not user.mfa_secret:  # primer ingreso: se enrola el segundo factor
        user.mfa_secret = mfa.new_secret()
        user.save(update_fields=["mfa_secret"])
    return Response({
        "mfa": "setup", "ticket": ticket, "secret": user.mfa_secret,
        "qr": mfa.provisioning_qr(user.mfa_secret, user.username, settings.MFA_ISSUER),
    })


login.cls.throttle_scope = "login"


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def login_mfa(request):
    """Paso 2: código TOTP de la app autenticadora. El primer código válido confirma el enrolamiento."""
    try:
        data = signing.loads(str(request.data.get("ticket", "")), salt=MFA_SALT, max_age=MFA_TICKET_SECONDS)
        user = User.objects.select_related("clinic").get(pk=data["u"], is_active=True)
    except (signing.BadSignature, User.DoesNotExist):
        return Response({"detail": "El ingreso venció; vuelve a escribir tu usuario y contraseña"}, status=400)
    step = mfa.verify(user.mfa_secret, request.data.get("code", ""), user.mfa_last_step)
    if step is None:
        return Response({"detail": "Código incorrecto o ya utilizado"}, status=400)
    user.mfa_last_step, user.mfa_enabled = step, True
    user.save(update_fields=["mfa_last_step", "mfa_enabled"])
    return start_session(user)


login_mfa.cls.throttle_scope = "mfa"


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Healthcheck para el orquestador: responde 503 si la base de datos no está disponible."""
    try:
        connection.ensure_connection()
    except Exception:
        return Response({"status": "db unavailable"}, status=503)
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([RolePermission])
def dentists(request):
    users = User.objects.filter(clinic_id=request.tenant, is_active=True, role="odontologo")
    return Response([{"id": u.id, "name": u.get_full_name() or u.username} for u in users])


dentists.cls.resource = "dentists"
