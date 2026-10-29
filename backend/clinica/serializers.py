from datetime import timedelta

from django.db.models import Q
from rest_framework import serializers

from .models import Appointment, AuditLog, Chair, ClinicalNote, Patient, Tooth, Treatment


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
        fields = ["number", "state"]


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
