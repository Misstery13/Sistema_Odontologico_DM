import hashlib
import hmac
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

# Numeración FDI: cuadrantes 1-4, piezas 1-8 (11..18, 21..28, 31..38, 41..48)
FDI_TEETH = [(q * 10 + n, str(q * 10 + n)) for q in range(1, 5) for n in range(1, 9)]

ROLES = [
    ("admin", "Administrador TI"),
    ("recepcion", "Recepcionista / Cajero"),
    ("odontologo", "Odontólogo"),
    ("asistente", "Asistente dental"),
    ("auditor", "Auditor / Contador"),
]


class Clinic(models.Model):
    """Tenant: cada clínica solo ve sus propios datos."""

    name = models.CharField(max_length=120)

    def __str__(self):
        return self.name


class User(AbstractUser):
    clinic = models.ForeignKey(Clinic, null=True, blank=True, on_delete=models.PROTECT, related_name="users")
    role = models.CharField(max_length=12, choices=ROLES, default="recepcion")
    last_activity = models.DateTimeField(null=True, blank=True)  # RNF-05: cierre por inactividad


class Chair(models.Model):
    """Sillón dental físico (RF-09, RN-03)."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    name = models.CharField(max_length=40)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["clinic", "name"], name="unique_chair_per_clinic")]

    def __str__(self):
        return self.name


class Patient(models.Model):
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    cedula = models.CharField(max_length=13)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    birth_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    # RF-01: contacto de emergencia, tutor legal (menores) y convenio
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    guardian_name = models.CharField(max_length=120, blank=True)
    guardian_cedula = models.CharField(max_length=13, blank=True)
    insurance = models.CharField(max_length=120, blank=True)
    # RF-02: anamnesis
    allergies = models.TextField(blank=True)  # alergias a fármacos
    systemic_diseases = models.TextField(blank=True)
    surgical_history = models.TextField(blank=True)
    medical_history = models.TextField(blank=True)  # otros antecedentes
    anticoagulated = models.BooleanField(default=False)
    coagulopathy = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [models.UniqueConstraint(fields=["clinic", "cedula"], name="unique_cedula_per_clinic")]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"

    @property
    def is_minor(self):
        if not self.birth_date:
            return False
        today = date.today()
        age = today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return age < 18

    @property
    def alerts(self):
        """Condiciones críticas que la cabecera del expediente debe destacar (RF-02)."""
        out = []
        if self.allergies.strip().lower() not in ("", "ninguna", "ninguno", "no", "niega"):
            out.append(f"Alergia: {self.allergies}")
        if self.anticoagulated:
            out.append("Anticoagulado")
        if self.coagulopathy:
            out.append("Coagulopatía")
        return out


class Appointment(models.Model):
    STATUS = [
        ("programado", "Programado"),
        ("confirmado", "Confirmado"),
        ("en_espera", "En sala de espera"),
        ("en_atencion", "En atención"),
        ("atendido", "Atendido"),
        ("cancelado", "Cancelado"),
        ("no_asistio", "No asistió"),
    ]
    INACTIVE = ("cancelado", "no_asistio")  # no ocupan sillón ni odontólogo

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    dentist = models.ForeignKey(User, on_delete=models.PROTECT, related_name="appointments")
    chair = models.ForeignKey(Chair, null=True, on_delete=models.PROTECT, related_name="appointments")
    start = models.DateTimeField()
    minutes = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(5), MaxValueValidator(480)])
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="programado")

    class Meta:
        ordering = ["start"]


class Tooth(models.Model):
    """Estado de una pieza en el odontograma del paciente."""

    STATES = [
        ("sano", "Sano"),
        ("caries", "Caries"),
        ("obturado", "Obturado"),
        ("endodoncia", "Endodoncia"),
        ("corona", "Corona"),
        ("extraido", "Extraído"),
    ]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="teeth")
    number = models.PositiveSmallIntegerField(choices=FDI_TEETH)
    state = models.CharField(max_length=12, choices=STATES)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["patient", "number"], name="unique_tooth_per_patient")]


class Treatment(models.Model):
    """Procedimiento realizado. RN-01: nunca se borra; las correcciones van como adenda."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="treatments")
    tooth = models.PositiveSmallIntegerField(choices=FDI_TEETH, null=True, blank=True)
    procedure = models.CharField(max_length=120)
    cost = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Un procedimiento realizado no puede borrarse (RN-01)")


class ClinicalNote(models.Model):
    """Nota de evolución SOEP (RF-05): firmada, editable solo por su autor durante NOTE_LOCK_HOURS."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="notes")
    created_at = models.DateTimeField(default=timezone.now)
    subjective = models.TextField(blank=True)
    objective = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)
    amends = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="addenda")
    signature = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ["created_at"]

    @property
    def locked(self):
        return timezone.now() - self.created_at > timedelta(hours=settings.NOTE_LOCK_HOURS)

    def sign(self):
        # ponytail: firma HMAC con SECRET_KEY; cambiar por firma con certificado del profesional cuando exista PKI
        payload = "|".join([str(self.author_id), self.created_at.isoformat(), self.subjective, self.objective, self.assessment, self.plan])
        self.signature = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def save(self, *args, **kwargs):
        self.sign()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Las notas de evolución no se borran (RN-01)")


class AuditLog(models.Model):
    """Log inmutable de acciones sobre historias clínicas (RNF-06)."""

    clinic = models.ForeignKey(Clinic, null=True, on_delete=models.PROTECT)
    user = models.ForeignKey(User, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=10)  # list, read, create, update
    model = models.CharField(max_length=40)
    object_id = models.CharField(max_length=40, blank=True)
    ip = models.GenericIPAddressField(null=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied("El log de auditoría es inmutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("El log de auditoría es inmutable")


class Notification(models.Model):
    """Mensaje transaccional enviado por el adaptador de mensajería (RF-11)."""

    KINDS = [("confirmacion", "Confirmación"), ("recordatorio_48h", "Recordatorio 48h"), ("recordatorio_24h", "Recordatorio 24h")]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=KINDS)
    channel = models.CharField(max_length=10)
    recipient = models.CharField(max_length=120)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["appointment", "kind"], name="one_notification_per_kind")]
