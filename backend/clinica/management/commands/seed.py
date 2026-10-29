from datetime import date

from django.core.management.base import BaseCommand

from clinica.models import (
    Chair, Clinic, CommissionRule, ConsentTemplate, Patient, Procedure, RecipeLine, StockMovement, Supply, Treatment, User,
)

# solo datos demo: el contenedor no ejecuta seed en producción (DJANGO_ENV=production)
DEMO_PASSWORD = "odonto123"  # nosec B105

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


# insumo: (unidad, stock inicial, mínimo, costo unitario)
SUPPLIES = {
    "Resina compuesta": ("g", 40, 8, 6.5),
    "Anestesia lidocaína 2%": ("cartucho", 100, 20, 0.6),
    "Guantes de nitrilo": ("par", 200, 50, 0.12),
    "Ácido grabador": ("ml", 30, 5, 1.2),
    "Adhesivo dental": ("ml", 10, 2, 9),
    "Limas de endodoncia": ("unidad", 30, 10, 2.5),
    "Sutura reabsorbible": ("unidad", 25, 5, 1.8),
    "Pasta profiláctica": ("g", 200, 40, 0.05),
    "Sellante de fosas": ("ml", 10, 2, 8),
}
# código: (nombre, honorario, laboratorio, receta {insumo: cantidad})
PROCEDURES = {
    "PROF": ("Profilaxis", 25, 0, {"Pasta profiláctica": 5, "Guantes de nitrilo": 1}),
    "RES": ("Restauración con resina", 45, 0, {"Resina compuesta": 0.5, "Anestesia lidocaína 2%": 1, "Guantes de nitrilo": 1, "Ácido grabador": 0.2, "Adhesivo dental": 0.1}),
    "SEL": ("Sellante de fosas y fisuras", 15, 0, {"Sellante de fosas": 0.2, "Ácido grabador": 0.1, "Guantes de nitrilo": 1}),
    "END": ("Endodoncia unirradicular", 120, 0, {"Anestesia lidocaína 2%": 2, "Guantes de nitrilo": 2, "Limas de endodoncia": 3}),
    "EXO": ("Exodoncia simple", 40, 0, {"Anestesia lidocaína 2%": 2, "Guantes de nitrilo": 1, "Sutura reabsorbible": 1}),
    "COR": ("Corona de porcelana", 160, 120, {"Anestesia lidocaína 2%": 1, "Guantes de nitrilo": 2}),
    "IMP": ("Implante dental", 550, 350, {"Anestesia lidocaína 2%": 3, "Guantes de nitrilo": 2, "Sutura reabsorbible": 2}),
}
# odontólogo: (tipo de regla, valor) para la liquidación de honorarios
COMMISSIONS = {"dra.lopez": ("pct", 40), "dr.perez": ("pct_net", 50), "dr.vega": ("fixed", 20)}


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

        for clinic in Clinic.objects.all():
            first_user = clinic.users.order_by("id").first()
            for name, (unit, stock, minimum, cost) in SUPPLIES.items():
                supply, created = Supply.objects.get_or_create(
                    clinic=clinic, name=name, defaults={"unit": unit, "stock": stock, "min_stock": minimum, "unit_cost": cost}
                )
                if created:
                    StockMovement.objects.create(clinic=clinic, supply=supply, quantity=stock, reason="compra", user=first_user, note="Inventario inicial")
            for code, (name, fee, lab, recipe) in PROCEDURES.items():
                proc, created = Procedure.objects.get_or_create(clinic=clinic, code=code, defaults={"name": name, "fee": fee, "lab_cost": lab})
                if created:
                    for supply, qty in recipe.items():
                        RecipeLine.objects.create(procedure=proc, supply=Supply.objects.get(clinic=clinic, name=supply), quantity=qty)
        for username, (kind, value) in COMMISSIONS.items():
            dentist = User.objects.get(username=username)
            CommissionRule.objects.get_or_create(dentist=dentist, defaults={"clinic": dentist.clinic, "kind": kind, "value": value})

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
