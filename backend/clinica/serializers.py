from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import serializers

from .models import (
    FDI_TEETH, SURFACE_STATES, SURFACES, Appointment, AuditLog, Chair, ClinicalNote, Consent, ConsentTemplate,
    Patient, PerioExam, Prescription, Tooth, Treatment, Budget, BudgetItem, CommissionRule, Procedure, RecipeLine,
    StockMovement, Supply, User,
)


class TenantSerializer(serializers.ModelSerializer):
    """Limita toda FK a registros del tenant actual: evita referenciar pacientes de otra clínica."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = self.context["request"].tenant
        for field in self.fields.values():
            if isinstance(field, serializers.PrimaryKeyRelatedField) and not field.read_only:
                model = field.queryset.model
                field.queryset = field.queryset.filter(**{getattr(model, "TENANT_FIELD", "clinic_id"): tenant})


class PatientSerializer(TenantSerializer):
    alerts = serializers.ListField(read_only=True)
    is_minor = serializers.BooleanField(read_only=True)

    class Meta:
        model = Patient
        exclude = ["clinic"]
        # RF-02: anamnesis obligatoria (se puede declarar "Ninguna")
        extra_kwargs = {"allergies": {"allow_blank": False}, "systemic_diseases": {"allow_blank": False}}

    def validate_cedula(self, value):  # unicidad por clínica (clinic no está en el serializer)
        qs = Patient.objects.filter(clinic_id=self.context["request"].tenant, cedula=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ya existe un paciente con esta cédula")
        return value

    def validate(self, data):
        birth = data.get("birth_date", self.instance.birth_date if self.instance else None)
        guardian = data.get("guardian_name", self.instance.guardian_name if self.instance else "")
        if Patient(birth_date=birth).is_minor and not guardian:
            raise serializers.ValidationError({"guardian_name": "Un paciente menor de edad requiere tutor legal"})
        return data


class ChairSerializer(TenantSerializer):
    class Meta:
        model = Chair
        exclude = ["clinic"]


class AppointmentSerializer(TenantSerializer):
    budget_item = serializers.PrimaryKeyRelatedField(queryset=BudgetItem.objects.all(), required=False, allow_null=True)
    patient_name = serializers.StringRelatedField(source="patient", read_only=True)
    chair_name = serializers.StringRelatedField(source="chair", read_only=True)
    dentist_name = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        exclude = ["clinic"]
        extra_kwargs = {"chair": {"required": True, "allow_null": False}}

    def get_dentist_name(self, obj):
        return obj.dentist.get_full_name() or obj.dentist.username

    def validate_dentist(self, value):
        if value.role != "odontologo":
            raise serializers.ValidationError("El profesional asignado debe ser odontólogo")
        return value

    def validate(self, data):
        inst = self.instance
        get = lambda k, default=None: data.get(k, getattr(inst, k) if inst else default)
        item = data.get("budget_item")
        if item:  # RF-08: un ítem aprobado del presupuesto se vuelve cita
            if item.approved is not True or item.budget.patient_id != get("patient").pk:
                raise serializers.ValidationError({"budget_item": "El ítem no está aprobado para este paciente"})
            if not data.get("reason"):
                data["reason"] = f"{item.procedure.name}{f' · pieza {item.tooth}' if item.tooth else ''}"
        if get("status", "programado") in Appointment.INACTIVE:
            return data
        start, minutes, dentist, chair = get("start"), get("minutes", 30), get("dentist"), get("chair")
        end = start + timedelta(minutes=minutes)
        # 480 = duración máxima de una cita, así acotamos la búsqueda
        others = Appointment.objects.filter(
            Q(dentist=dentist) | Q(chair=chair), start__lt=end, start__gt=start - timedelta(minutes=480)
        ).exclude(status__in=Appointment.INACTIVE)
        if inst:
            others = others.exclude(pk=inst.pk)
        for o in others:
            if o.start + timedelta(minutes=o.minutes) > start:
                # RN-03: el sillón es el recurso físico; se valida aunque el odontólogo sea otro
                raise serializers.ValidationError(
                    f"El {'sillón' if o.chair_id == chair.pk else 'odontólogo'} ya tiene una cita en ese horario"
                )
        return data


class ToothSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tooth
        fields = ["number", "state", "surfaces"]

    def validate_surfaces(self, value):
        if not isinstance(value, dict) or any(k not in SURFACES or v not in SURFACE_STATES for k, v in value.items()):
            raise serializers.ValidationError(f"Superficies válidas: {', '.join(SURFACES)}; hallazgos: {', '.join(SURFACE_STATES)}")
        return value


class TreatmentSerializer(TenantSerializer):
    dentist_name = serializers.StringRelatedField(source="dentist", read_only=True)

    class Meta:
        model = Treatment
        exclude = ["clinic"]
        read_only_fields = ["dentist", "lab_cost", "material_cost"]
        extra_kwargs = {"procedure": {"required": False}, "cost": {"required": False}}

    def validate(self, data):
        """Origen del procedimiento: un ítem aprobado del presupuesto, el catálogo o texto libre con costo."""
        item, catalog = data.get("budget_item"), data.get("catalog")
        if item:
            if item.budget.patient_id != data["patient"].pk or item.approved is not True:
                raise serializers.ValidationError({"budget_item": "El ítem no está aprobado para este paciente"})
            if hasattr(item, "treatment"):
                raise serializers.ValidationError({"budget_item": "Este ítem del presupuesto ya fue realizado"})
            catalog = data["catalog"] = item.procedure
            data["tooth"] = data.get("tooth") or item.tooth
            data["cost"], data["lab_cost"] = item.net, item.lab_cost
        if catalog:
            data.setdefault("procedure", catalog.name)
            data.setdefault("cost", catalog.fee + catalog.lab_cost)
            data.setdefault("lab_cost", catalog.lab_cost)
        if not data.get("procedure") or data.get("cost") is None:
            raise serializers.ValidationError("Elige un procedimiento del catálogo o escribe el procedimiento y su costo")
        return data


class ClinicalNoteSerializer(TenantSerializer):
    author_name = serializers.SerializerMethodField()
    locked = serializers.BooleanField(read_only=True)

    class Meta:
        model = ClinicalNote
        exclude = ["clinic"]
        read_only_fields = ["author", "created_at", "signature"]

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username

    def validate(self, data):
        if self.instance and ("patient" in data or "amends" in data):
            raise serializers.ValidationError("No se puede cambiar el paciente ni la nota enmendada")
        amends = data.get("amends")
        if amends and amends.patient_id != data["patient"].pk:
            raise serializers.ValidationError({"amends": "La adenda debe ser del mismo paciente"})
        if not any(data.get(f, getattr(self.instance, f, "")) for f in ("subjective", "objective", "assessment", "plan")):
            raise serializers.ValidationError("La nota no puede estar vacía")
        return data


class UserSerializer(serializers.ModelSerializer):
    """Gestión de usuarios de la clínica (rol admin). La contraseña solo se escribe."""

    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "role", "is_active", "mfa_enabled",
                  "must_change_password", "last_login", "last_activity", "password"]
        read_only_fields = ["mfa_enabled", "must_change_password", "last_login", "last_activity"]

    def validate(self, data):
        request = self.context["request"]
        if self.instance is None and not data.get("password"):
            raise serializers.ValidationError({"password": "Asigna una contraseña temporal"})  # nosec B105 - mensaje de error, no credencial
        if "password" in data:
            try:
                validate_password(data["password"], User(username=data.get("username", getattr(self.instance, "username", ""))))
            except DjangoValidationError as e:
                raise serializers.ValidationError({"password": list(e.messages)})
        if self.instance == request.user and (data.get("is_active") is False or data.get("role", "admin") != "admin"):
            raise serializers.ValidationError("No puedes desactivarte ni quitarte el rol de administrador")
        return data

    def create(self, data):
        password = data.pop("password")
        user = User(**data, clinic_id=self.context["request"].tenant, must_change_password=True)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, data):
        data.pop("password", None)  # se cambia con la acción reset_password
        return super().update(instance, data)


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.StringRelatedField(source="user")

    class Meta:
        model = AuditLog
        exclude = ["clinic"]


class AuthoredSerializer(TenantSerializer):
    """Registro clínico firmado por su autor: autor, fecha y firma los pone el servidor."""

    author_name = serializers.SerializerMethodField()

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username


PERMANENT = {str(n) for n, _ in FDI_TEETH}


class PerioExamSerializer(AuthoredSerializer):
    summary = serializers.DictField(read_only=True)

    class Meta:
        model = PerioExam
        exclude = ["clinic"]
        read_only_fields = ["author", "created_at", "signature"]

    def validate_teeth(self, value):
        def ints(v, lo, hi, n=6):
            return isinstance(v, list) and len(v) == n and all(isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi for x in v)

        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("Registra al menos una pieza")
        for tooth, t in value.items():
            ok = (
                tooth in PERMANENT
                and isinstance(t, dict)
                and ints(t.get("pd"), 0, 15)  # profundidad al sondaje (mm)
                and ints(t.get("gm"), -10, 15)  # margen gingival (mm, + recesión)
                and isinstance(t.get("bleeding"), list) and len(t["bleeding"]) == 6 and all(isinstance(b, bool) for b in t["bleeding"])
                and t.get("mobility", 0) in (0, 1, 2, 3)
                and t.get("furcation", 0) in (0, 1, 2, 3)
            )
            if not ok:
                raise serializers.ValidationError(f"Datos inválidos en la pieza {tooth}")
        return value


# ponytail: lista corta de alergias cruzadas frecuentes en odontología; reemplazar por un vademécum cuando exista
CROSS_ALLERGIES = {
    "penicilina": ["penicilina", "amoxicilina", "ampicilina", "dicloxacilina", "oxacilina"],
    "sulfa": ["sulfametoxazol", "sulfadiazina"],
    "aine": ["ibuprofeno", "naproxeno", "diclofenaco", "ketorolaco", "aspirina", "acido acetilsalicilico", "ketoprofeno"],
    "aspirina": ["aspirina", "acido acetilsalicilico"],
    "ibuprofeno": ["ibuprofeno"],
    "lidocaina": ["lidocaina"],
    "articaina": ["articaina"],
}


def _norm(text):
    return text.lower().translate(str.maketrans("áéíóú", "aeiou"))


def allergy_conflicts(allergies, drugs):
    allergies = _norm(allergies)
    out = []
    for drug in drugs:
        d = _norm(drug)
        for key, members in CROSS_ALLERGIES.items():
            if key in allergies and any(m in d for m in members):
                out.append(drug)
                break
        else:
            if any(w and w in d for w in allergies.replace(",", " ").split() if len(w) > 4):
                out.append(drug)
    return out


class PrescriptionSerializer(AuthoredSerializer):
    class Meta:
        model = Prescription
        exclude = ["clinic"]
        read_only_fields = ["author", "created_at", "signature"]

    def validate_items(self, value):
        keys = ("drug", "dose", "frequency", "duration")
        if not isinstance(value, list) or not value or any(not isinstance(i, dict) or not all(str(i.get(k, "")).strip() for k in keys) for i in value):
            raise serializers.ValidationError("Cada medicamento necesita nombre, dosis, frecuencia y duración")
        return [{k: str(i.get(k, "")).strip() for k in (*keys, "instructions")} for i in value]

    def validate(self, data):
        conflicts = allergy_conflicts(data["patient"].allergies, [i["drug"] for i in data["items"]])
        if conflicts and not data.get("allergy_override", "").strip():
            raise serializers.ValidationError(
                {"allergy_override": f"Alerta de alergia ({data['patient'].allergies}): {', '.join(conflicts)}. Justifica para emitir."}
            )
        return data


class ConsentTemplateSerializer(TenantSerializer):
    class Meta:
        model = ConsentTemplate
        exclude = ["clinic"]


class ConsentSerializer(TenantSerializer):
    template = serializers.PrimaryKeyRelatedField(queryset=ConsentTemplate.objects.all(), write_only=True)
    created_by_name = serializers.StringRelatedField(source="created_by", read_only=True)
    signed = serializers.SerializerMethodField()

    class Meta:
        model = Consent
        exclude = ["clinic", "otp_hash", "otp_attempts"]
        read_only_fields = ["created_by", "created_at", "procedure", "text", "signer_name", "signed_at", "method", "signature_image", "otp_expires", "signature"]

    def get_signed(self, obj):
        return obj.signed_at is not None


class RecipeLineSerializer(serializers.ModelSerializer):
    supply_name = serializers.StringRelatedField(source="supply", read_only=True)
    unit = serializers.CharField(source="supply.unit", read_only=True)

    class Meta:
        model = RecipeLine
        fields = ["supply", "supply_name", "unit", "quantity"]


class ProcedureSerializer(TenantSerializer):
    recipe = RecipeLineSerializer(many=True, required=False)

    class Meta:
        model = Procedure
        exclude = ["clinic"]

    def validate_recipe(self, lines):
        tenant = self.context["request"].tenant
        if any(l["supply"].clinic_id != tenant for l in lines):
            raise serializers.ValidationError("Insumo inválido")
        return lines

    def save_recipe(self, procedure, lines):
        if lines is not None:
            procedure.recipe.all().delete()
            RecipeLine.objects.bulk_create(RecipeLine(procedure=procedure, **l) for l in lines)

    def create(self, data):
        lines = data.pop("recipe", [])
        procedure = super().create(data)
        self.save_recipe(procedure, lines)
        return procedure

    def update(self, instance, data):
        lines = data.pop("recipe", None)
        procedure = super().update(instance, data)
        self.save_recipe(procedure, lines)
        return procedure


class SupplySerializer(TenantSerializer):
    low = serializers.SerializerMethodField()

    class Meta:
        model = Supply
        exclude = ["clinic"]
        read_only_fields = ["stock"]  # el stock solo cambia por movimientos del kardex

    def get_low(self, obj):
        return obj.stock <= obj.min_stock


class StockMovementSerializer(TenantSerializer):
    supply_name = serializers.StringRelatedField(source="supply", read_only=True)
    user_name = serializers.StringRelatedField(source="user", read_only=True)

    class Meta:
        model = StockMovement
        exclude = ["clinic"]
        read_only_fields = ["user", "created_at", "treatment"]

    def validate(self, data):
        if data["reason"] == "consumo":
            raise serializers.ValidationError({"reason": "El consumo se descarga solo al registrar procedimientos"})
        if data["quantity"] == 0 or (data["reason"] == "compra" and data["quantity"] < 0):
            raise serializers.ValidationError({"quantity": "Una compra debe ser positiva; un ajuste, distinto de cero"})
        if data["reason"] == "ajuste" and not data.get("note", "").strip():
            raise serializers.ValidationError({"note": "Explica el motivo del ajuste"})
        return data


class BudgetItemSerializer(serializers.ModelSerializer):
    procedure_name = serializers.StringRelatedField(source="procedure", read_only=True)
    net = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    done = serializers.SerializerMethodField()
    scheduled = serializers.SerializerMethodField()

    class Meta:
        model = BudgetItem
        fields = ["id", "phase", "procedure", "procedure_name", "tooth", "fee", "lab_cost", "net", "approved", "done", "scheduled"]
        read_only_fields = ["fee", "lab_cost", "approved"]

    def get_done(self, obj):
        return hasattr(obj, "treatment")

    def get_scheduled(self, obj):
        return obj.appointments.exclude(status__in=Appointment.INACTIVE).exists()


class BudgetSerializer(AuthoredSerializer):
    items = BudgetItemSerializer(many=True)
    totals = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        exclude = ["clinic"]
        read_only_fields = ["author", "created_at", "status", "decided_at"]

    def get_totals(self, obj):
        items = list(obj.items.all())
        fees = sum((i.fee for i in items), 0)
        lab = sum((i.lab_cost for i in items), 0)
        total = sum((i.net for i in items), 0)
        return {"fees": fees, "lab": lab, "discount": fees + lab - total, "total": total,
                "approved": sum((i.net for i in items if i.approved), 0)}

    def validate_discount_pct(self, value):
        # RF-07: descuento autorizado; por encima del tope se requiere un presupuesto aprobado por administración
        if value > settings.MAX_DISCOUNT_PCT:
            raise serializers.ValidationError(f"El descuento máximo autorizado es {settings.MAX_DISCOUNT_PCT}%")
        return value

    def validate_items(self, items):
        tenant = self.context["request"].tenant
        if not items:
            raise serializers.ValidationError("Agrega al menos un procedimiento")
        if any(i["procedure"].clinic_id != tenant or not i["procedure"].active for i in items):
            raise serializers.ValidationError("Procedimiento inválido")
        return items

    def create(self, data):
        items = data.pop("items")
        budget = Budget.objects.create(**data)
        BudgetItem.objects.bulk_create(
            BudgetItem(budget=budget, fee=i["procedure"].fee, lab_cost=i["procedure"].lab_cost, **i) for i in items
        )
        return budget


class CommissionRuleSerializer(TenantSerializer):
    dentist_name = serializers.StringRelatedField(source="dentist", read_only=True)

    class Meta:
        model = CommissionRule
        exclude = ["clinic"]
