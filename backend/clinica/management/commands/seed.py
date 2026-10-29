from datetime import date

from django.core.management.base import BaseCommand

from clinica.models import Clinic, Patient, Treatment, User

DEMO_PASSWORD = "odonto123"


class Command(BaseCommand):
    help = "Crea dos clínicas de demostración con usuarios y pacientes (idempotente)."

    def handle(self, *args, **options):
        data = {
            "Clínica Sonrisa": [("dra.lopez", "Ana", "López"), ("dr.perez", "Luis", "Pérez")],
            "Dental Norte": [("dr.vega", "Carlos", "Vega")],
        }
        for clinic_name, users in data.items():
            clinic, _ = Clinic.objects.get_or_create(name=clinic_name)
            for username, first, last in users:
                user, created = User.objects.get_or_create(
                    username=username, defaults={"first_name": first, "last_name": last, "clinic": clinic}
                )
                if created:
                    user.set_password(DEMO_PASSWORD)
                    user.save()

        sonrisa = Clinic.objects.get(name="Clínica Sonrisa")
        p, created = Patient.objects.get_or_create(
            clinic=sonrisa,
            cedula="0912345678",
            defaults={"first_name": "María", "last_name": "Torres", "phone": "0991234567", "allergies": "Penicilina"},
        )
        if created:
            Treatment.objects.create(
                clinic=sonrisa, patient=p, tooth=36, procedure="Obturación resina", cost=45, date=date.today()
            )
        Patient.objects.get_or_create(
            clinic=Clinic.objects.get(name="Dental Norte"),
            cedula="1712345678",
            defaults={"first_name": "Jorge", "last_name": "Ramírez"},
        )
        self.stdout.write(f"Datos demo listos. Contraseña de todos los usuarios: {DEMO_PASSWORD}")
