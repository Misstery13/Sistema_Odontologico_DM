import hashlib
import hmac
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

# Numeración FDI: permanentes cuadrantes 1-4, piezas 1-8 (11..48); temporales cuadrantes 5-8, piezas 1-5 (51..85)
FDI_TEETH = [(q * 10 + n, str(q * 10 + n)) for q in range(1, 5) for n in range(1, 9)]
TEMP_TEETH = [(q * 10 + n, str(q * 10 + n)) for q in range(5, 9) for n in range(1, 6)]
ALL_TEETH = FDI_TEETH + TEMP_TEETH
SURFACES = ("M", "D", "O", "V", "L")  # mesial, distal, oclusal/incisal, vestibular, lingual/palatino
SURFACE_STATES = ("caries", "restauracion", "sellante")


def sign(*parts):
    """Firma digital del registro clínico.
    ponytail: HMAC con SECRET_KEY; cambiar por firma con certificado del profesional cuando exista PKI."""
    payload = "|".join(str(p) for p in parts)
    return hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()

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
    """Pieza del odontograma (RF-03): condición de la pieza completa + hallazgos por superficie."""

    # rojo = requerido / patología, azul = realizado (convención del catálogo)
    STATES = [
        ("sano", "Sano"),
        ("endodoncia_requerida", "Endodoncia requerida"),
        ("endodoncia", "Endodoncia realizada"),
        ("implante", "Implante"),
        ("protesis_fija", "Prótesis fija / corona"),
        ("protesis_removible", "Prótesis removible"),
        ("exodoncia_indicada", "Exodoncia indicada"),
        ("extraido", "Extraído"),
    ]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="teeth")
    number = models.PositiveSmallIntegerField(choices=ALL_TEETH)
    state = models.CharField(max_length=20, choices=STATES, default="sano")
    surfaces = models.JSONField(default=dict, blank=True)  # {"O": "caries", "M": "restauracion", ...}

    class Meta:
        constraints = [models.UniqueConstraint(fields=["patient", "number"], name="unique_tooth_per_patient")]


class Treatment(models.Model):
    """Procedimiento realizado. RN-01: nunca se borra; las correcciones van como adenda."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="treatments")
    tooth = models.PositiveSmallIntegerField(choices=ALL_TEETH, null=True, blank=True)
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

    def save(self, *args, **kwargs):
        self.signature = sign(self.author_id, self.created_at.isoformat(), self.subjective, self.objective, self.assessment, self.plan)
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


class PerioExam(models.Model):
    """Periodontograma (RF-04). `teeth`: {"16": {"pd": [6], "gm": [6], "bleeding": [6], "mobility": 0-3, "furcation": 0-3}}.
    Sitios en orden MV, V, DV, ML, L, DL. Margen gingival positivo = recesión; NIC = PS + MG."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="perio_exams")
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    teeth = models.JSONField(default=dict)
    notes = models.TextField(blank=True)
    signature = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ["-created_at"]

    @property
    def summary(self):
        sites = [(pd, gm, b) for t in self.teeth.values() for pd, gm, b in zip(t["pd"], t["gm"], t["bleeding"])]
        if not sites:
            return {"teeth": 0, "sites": 0, "bleeding_pct": 0, "deep_sites": 0, "mean_cal": 0}
        return {
            "teeth": len(self.teeth),
            "sites": len(sites),
            "bleeding_pct": round(100 * sum(b for _, _, b in sites) / len(sites), 1),
            "deep_sites": sum(pd >= 4 for pd, _, _ in sites),  # bolsas de 4 mm o más
            "mean_cal": round(sum(pd + gm for pd, gm, _ in sites) / len(sites), 2),
        }

    def save(self, *args, **kwargs):
        self.signature = sign(self.author_id, self.created_at.isoformat(), self.teeth, self.notes)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Los registros clínicos no se borran (RN-01)")


class Prescription(models.Model):
    """Receta odontológica firmada. `items`: [{"drug", "dose", "frequency", "duration", "instructions"}]."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="prescriptions")
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    items = models.JSONField()
    notes = models.TextField(blank=True)
    allergy_override = models.CharField(max_length=200, blank=True)  # justificación si contradice una alergia
    signature = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.signature = sign(self.author_id, self.created_at.isoformat(), self.items, self.notes, self.allergy_override)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Las recetas emitidas no se borran")


class ConsentTemplate(models.Model):
    """Formato legal de consentimiento por procedimiento (catálogo).
    Marcadores: {paciente} {cedula} {procedimiento} {odontologo} {fecha}."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    procedure = models.CharField(max_length=120)
    body = models.TextField()

    class Meta:
        ordering = ["procedure"]

    def __str__(self):
        return self.procedure


class Consent(models.Model):
    """Consentimiento informado (RF-06): se firma una sola vez, en pantalla táctil o con código OTP."""

    METHODS = [("biometrica", "Firma en pantalla"), ("otp", "Código OTP")]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="consents")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    procedure = models.CharField(max_length=120)
    text = models.TextField()  # copia del formato ya completado: lo firmado no cambia si cambia la plantilla
    signer_name = models.CharField(max_length=120, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    method = models.CharField(max_length=10, choices=METHODS, blank=True)
    signature_image = models.TextField(blank=True)  # PNG en data URL (firma biométrica)
    otp_hash = models.CharField(max_length=64, blank=True)
    otp_expires = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    signature = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Los consentimientos no se borran")
