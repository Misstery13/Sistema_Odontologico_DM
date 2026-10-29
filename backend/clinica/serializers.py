from datetime import timedelta

from rest_framework import serializers

from .models import Appointment, Patient, Tooth, Treatment


class TenantSerializer(serializers.ModelSerializer):
    """Limita toda FK a registros del tenant actual: evita referenciar pacientes de otra clínica."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = self.context["request"].tenant
        for field in self.fields.values():
            if isinstance(field, serializers.PrimaryKeyRelatedField) and not field.read_only:
                field.queryset = field.queryset.filter(clinic_id=tenant)


class PatientSerializer(TenantSerializer):
    class Meta:
        model = Patient
        exclude = ["clinic"]

    def validate_cedula(self, value):  # unicidad por clínica (clinic no está en el serializer)
        qs = Patient.objects.filter(clinic_id=self.context["request"].tenant, cedula=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ya existe un paciente con esta cédula")
        return value


class AppointmentSerializer(TenantSerializer):
    patient_name = serializers.StringRelatedField(source="patient", read_only=True)
    dentist_name = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        exclude = ["clinic"]

    def get_dentist_name(self, obj):
        return obj.dentist.get_full_name() or obj.dentist.username

    def validate(self, data):
        inst = self.instance
        status = data.get("status", inst.status if inst else "programada")
        if status == "cancelada":
            return data
        start = data.get("start", inst.start if inst else None)
        minutes = data.get("minutes", inst.minutes if inst else 30)
        dentist = data.get("dentist", inst.dentist if inst else None)
        end = start + timedelta(minutes=minutes)
        # 480 = duración máxima de una cita, así acotamos la búsqueda
        others = Appointment.objects.filter(
            dentist=dentist, start__lt=end, start__gt=start - timedelta(minutes=480)
        ).exclude(status="cancelada")
        if inst:
            others = others.exclude(pk=inst.pk)
        if any(o.start + timedelta(minutes=o.minutes) > start for o in others):
            raise serializers.ValidationError("El odontólogo ya tiene una cita en ese horario")
        return data


class ToothSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tooth
        fields = ["number", "state"]


class TreatmentSerializer(TenantSerializer):
    class Meta:
        model = Treatment
        exclude = ["clinic"]
