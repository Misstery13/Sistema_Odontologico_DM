from datetime import date

from django.core.management.base import BaseCommand

from clinica.models import Chair, Clinic, ConsentTemplate, Patient, Treatment, User

DEMO_PASSWORD = "odonto123"

CONSENT_BODY = """Yo, {paciente}, con cédula {cedula}, declaro que el/la Dr(a). {odontologo} me explicó en lenguaje claro el procedimiento de {procedimiento}, su propósito, alternativas y los riesgos posibles: {riesgos}.

Tuve la oportunidad de hacer preguntas y fueron respondidas. Entiendo que puedo revocar este consentimiento antes del procedimiento.

Autorizo la realización del procedimiento.

Fecha: {fecha}"""

CONSENTS = {
    "Exodoncia": "dolor, inflamación, sangrado, infección, alveolitis, lesión de piezas vecinas y parestesia temporal o permanente",
    "Endodoncia": "dolor posoperatorio, fractura de instrumentos, perforación, fractura de la pieza y necesidad de retratamiento",
    "Implante dental": "dolor, inflamación, infección, falta de oseointegración, lesión nerviosa y compromiso del seno maxilar",
    "Anestesia local": "reacción alérgica, hematoma, parestesia temporal y lipotimia",
}


class Command(BaseCommand):
    help = "Crea dos clínicas de demostración con un usuario por rol, sillones y pacientes (idempotente)."

    def handle(self, *args, **options):
        data = {
            "Clínica Sonrisa": [
                ("dra.lopez", "Ana", "López", "odontologo"),
                ("dr.perez", "Luis", "Pérez", "odontologo"),
                ("recepcion", "Rosa", "Mora", "recepcion"),
                ("asistente", "Paula", "Vera", "asistente"),
                ("auditor", "Jorge", "Ibarra", "auditor"),
                ("admin", "Admin", "TI", "admin"),
            ],
            "Dental Norte": [("dr.vega", "Carlos", "Vega", "odontologo"), ("recepcion.norte", "Elsa", "Ruiz", "recepcion")],
        }
        for clinic_name, users in data.items():
            clinic, _ = Clinic.objects.get_or_create(name=clinic_name)
            for chair in ("Sillón 1", "Sillón 2"):
                Chair.objects.get_or_create(clinic=clinic, name=chair)
            for procedure, risks in CONSENTS.items():
                ConsentTemplate.objects.get_or_create(
                    clinic=clinic, procedure=procedure, defaults={"body": CONSENT_BODY.replace("{riesgos}", risks)}
                )
            for username, first, last, role in users:
                user, created = User.objects.update_or_create(
                    username=username, defaults={"first_name": first, "last_name": last, "clinic": clinic, "role": role}
                )
                if created:
                    user.set_password(DEMO_PASSWORD)
                    user.save()

        sonrisa = Clinic.objects.get(name="Clínica Sonrisa")
        p, created = Patient.objects.get_or_create(
            clinic=sonrisa,
            cedula="0912345678",
            defaults={
                "first_name": "María",
                "last_name": "Torres",
                "phone": "0991234567",
                "allergies": "Penicilina",
                "systemic_diseases": "Hipertensión controlada",
                "emergency_contact_name": "Pedro Torres",
                "emergency_contact_phone": "0997654321",
            },
        )
        if created:
            Treatment.objects.create(
                clinic=sonrisa, patient=p, tooth=36, procedure="Obturación resina", cost=45, date=date.today()
            )
        Patient.objects.get_or_create(
            clinic=Clinic.objects.get(name="Dental Norte"),
            cedula="1712345678",
            defaults={"first_name": "Jorge", "last_name": "Ramírez", "allergies": "Ninguna", "systemic_diseases": "Ninguna"},
        )
        self.stdout.write(f"Datos demo listos. Contraseña de todos los usuarios: {DEMO_PASSWORD}")
