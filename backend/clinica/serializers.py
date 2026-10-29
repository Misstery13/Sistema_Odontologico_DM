from datetime import timedelta

from django.db.models import Q
from rest_framework import serializers

from .models import (
    FDI_TEETH, SURFACE_STATES, SURFACES, Appointment, AuditLog, Chair, ClinicalNote, Consent, ConsentTemplate,
    Patient, PerioExam, Prescription, Tooth, Treatment,
)


class TenantSerializer(serializers.ModelSerializer):
    """Limita toda FK a registros del tenant actual: evita referenciar pacientes de otra clínica."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = self.context["request"].tenant
        for field in self.fields.values():
            if isinstance(field, serializers.PrimaryKeyRelatedField) and not field.read_only:
                field.queryset = field.queryset.filter(clinic_id=tenant)


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
    class Meta:
        model = Treatment
        exclude = ["clinic"]


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
