from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

# Numeración FDI: cuadrantes 1-4, piezas 1-8 (11..18, 21..28, 31..38, 41..48)
FDI_TEETH = [(q * 10 + n, str(q * 10 + n)) for q in range(1, 5) for n in range(1, 9)]


class Clinic(models.Model):
    """Tenant: cada clínica solo ve sus propios datos."""

    name = models.CharField(max_length=120)

    def __str__(self):
        return self.name


class User(AbstractUser):
    clinic = models.ForeignKey(Clinic, null=True, blank=True, on_delete=models.PROTECT, related_name="users")


class Patient(models.Model):
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    cedula = models.CharField(max_length=13)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    birth_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    allergies = models.TextField(blank=True)
    medical_history = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [models.UniqueConstraint(fields=["clinic", "cedula"], name="unique_cedula_per_clinic")]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"


class Appointment(models.Model):
    STATUS = [("programada", "Programada"), ("completada", "Completada"), ("cancelada", "Cancelada")]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    dentist = models.ForeignKey(User, on_delete=models.PROTECT, related_name="appointments")
    start = models.DateTimeField()
    minutes = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(5), MaxValueValidator(480)])
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="programada")

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
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="treatments")
    tooth = models.PositiveSmallIntegerField(choices=FDI_TEETH, null=True, blank=True)
    procedure = models.CharField(max_length=120)
    cost = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
