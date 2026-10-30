import random
import time as clock
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction
from django.db.models import F, Q
from django.utils import timezone

from clinica.models import (
    Appointment, Budget, BudgetItem, Chair, Clinic, ClinicalNote, CommissionRule, Consent, ConsentTemplate, Patient, Prescription,
    Procedure, RecipeLine, StockMovement, Supply, Tooth, ToothEvent, Treatment, User, VitalSigns, sign,
)
from clinica.serializers import allergy_conflicts, location_stock
from clinica.views import consume_supplies

# solo datos demo: el contenedor no ejecuta seed en producción (DJANGO_ENV=production)
DEMO_PASSWORD = "odonto123"  # nosec B105
# secreto MFA común de los usuarios demo; el código actual se obtiene con `python tests/totp.py`
DEMO_MFA_SECRET = "ODONTODMDEMOMFA2"  # nosec B105

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
                    user.mfa_secret, user.mfa_enabled = DEMO_MFA_SECRET, True
                    user.save()
                elif not user.mfa_secret:  # usuarios demo creados antes del MFA
                    User.objects.filter(pk=user.pk).update(mfa_secret=DEMO_MFA_SECRET, mfa_enabled=True)

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
        self.stdout.write(History().run())
        self.stdout.write(f"Datos demo listos. Contraseña de todos los usuarios: {DEMO_PASSWORD}")


# --- Historial demo: pacientes, agenda, tratamientos, odontograma, notas, cobros y cierres de caja ---
# Se carga una sola vez (marcador: el primer paciente de HISTORY_PATIENTS), con semilla fija y fechas relativas a hoy.

# (nombre, apellido, año de nacimiento, alergias, enfermedades sistémicas, otros campos)
HISTORY_PATIENTS = {
    "Clínica Sonrisa": [
        ("Carlos", "Andrade", 1985, "Ninguna", "Ninguna", {}),
        ("Lucía", "Benítez", 1992, "Ninguna", "Asma leve", {}),
        ("Fernando", "Cevallos", 1958, "Ninguna", "Diabetes tipo 2, hipertensión", {"anticoagulated": True, "medical_history": "Warfarina por fibrilación auricular"}),
        ("Gabriela", "Delgado", 1990, "Látex", "Ninguna", {}),
        ("Andrés", "Espinoza", 2014, "Ninguna", "Ninguna", {"guardian_name": "Marta Espinoza"}),
        ("Valeria", "Flores", 1998, "Ninguna", "Ninguna", {"insurance": "Salud S.A."}),
        ("Miguel", "Guerrero", 1970, "Sulfas", "Hipertensión", {}),
        ("Daniela", "Herrera", 1987, "Ninguna", "Hipotiroidismo", {}),
        ("Ricardo", "Jaramillo", 1964, "Ibuprofeno", "Cardiopatía isquémica", {"anticoagulated": True, "medical_history": "Clopidogrel"}),
        ("Sofía", "Luna", 2011, "Ninguna", "Ninguna", {"guardian_name": "Jorge Luna"}),
        ("Diego", "Medina", 1995, "Ninguna", "Ninguna", {}),
        ("Paola", "Navarrete", 1983, "Penicilina", "Ninguna", {}),
        ("Javier", "Ortiz", 1977, "Ninguna", "Diabetes tipo 2", {}),
        ("Camila", "Paredes", 2001, "Ninguna", "Ninguna", {"insurance": "Salud S.A."}),
        ("Esteban", "Quintero", 1969, "Ninguna", "Hemofilia A", {"coagulopathy": True}),
        ("Natalia", "Reyes", 1993, "Ninguna", "Embarazo (segundo trimestre)", {}),
        ("Héctor", "Salazar", 1951, "Yodo", "Hipertensión, EPOC", {}),
        ("Mónica", "Vásquez", 1989, "Ninguna", "Ninguna", {}),
    ],
    "Dental Norte": [
        ("Patricia", "Cordero", 1980, "Ninguna", "Ninguna", {}),
        ("Luis", "Mendoza", 1972, "Penicilina", "Hipertensión", {}),
        ("Rosa", "Chávez", 1966, "Ninguna", "Diabetes tipo 2", {}),
        ("Tomás", "Villacís", 2013, "Ninguna", "Ninguna", {"guardian_name": "Inés Villacís"}),
        ("Elena", "Zambrano", 1997, "Ninguna", "Ninguna", {}),
    ],
}
PROVINCE = {"Clínica Sonrisa": 9, "Dental Norte": 17}  # Guayas, Pichincha
EXISTING_DEMO = ("0912345678", "1712345678")  # María Torres y Jorge Ramírez, del seed original
DENTISTS = {"Clínica Sonrisa": {"dra.lopez": "Sillón 1", "dr.perez": "Sillón 2"}, "Dental Norte": {"dr.vega": "Sillón 1"}}
# (cajero, quien repone inventario, quien toma signos vitales)
STAFF = {"Clínica Sonrisa": ("recepcion", "asistente", "asistente"), "Dental Norte": ("recepcion.norte", "recepcion.norte", "dr.vega")}
MINUTES = {"PROF": 45, "RES": 45, "SEL": 30, "END": 90, "EXO": 45, "COR": 60, "IMP": 90}
REASONS = {
    "PROF": "Limpieza y control", "RES": "Caries en pieza {t}", "SEL": "Sellantes preventivos en pieza {t}",
    "END": "Dolor en pieza {t}", "EXO": "Extracción de pieza {t}", "COR": "Corona en pieza {t}", "IMP": "Implante en pieza {t}",
}
# nota SOEP por procedimiento: (subjetivo, objetivo, análisis, plan)
NOTES = {
    "PROF": ("Acude a control y limpieza.", "Placa bacteriana y cálculo supragingival leve.", "Gingivitis asociada a placa.",
             "Profilaxis y refuerzo de técnica de cepillado. Control en 6 meses."),
    "RES": ("Sensibilidad al frío en pieza {t}.", "Lesión cariosa en pieza {t}, sin compromiso pulpar.", "Caries dentinaria en pieza {t}.",
            "Restauración con resina bajo anestesia local. Control en 6 meses."),
    "SEL": ("Control preventivo.", "Fosas y fisuras profundas en molares permanentes.", "Riesgo de caries moderado.",
            "Sellante en pieza {t} y flúor tópico."),
    "END": ("Dolor espontáneo e intenso en pieza {t}, empeora de noche.", "Caries profunda en pieza {t}, percusión positiva.",
            "Pulpitis irreversible en pieza {t}.", "Endodoncia en una sesión. Corona en la próxima cita."),
    "EXO": ("Molestia recurrente en pieza {t}.", "Pieza {t} con indicación de exodoncia.", "Pieza {t} no restaurable.",
            "Exodoncia simple y sutura. Indicaciones posoperatorias por escrito."),
    "COR": ("Acude a rehabilitar la pieza {t} tratada con endodoncia.", "Pieza {t} endodonciada, asintomática.",
            "Pieza endodonciada con pérdida de estructura.", "Cementado de corona de porcelana y ajuste oclusal."),
    "IMP": ("Desea reponer la pieza {t} ausente.", "Reborde alveolar adecuado en la zona de la pieza {t}.", "Edentulismo unitario.",
            "Colocación de implante. Control en 7 días, carga a los 3 meses."),
}
CONSENT_FOR = {"END": "Endodoncia", "EXO": "Exodoncia", "IMP": "Implante dental"}
LOW_SUPPLY = "Limas de endodoncia"  # no se repone: queda bajo el mínimo y aparece la alerta de stock
POSTERIOR = [14, 15, 16, 17, 24, 25, 26, 27, 34, 35, 36, 37, 44, 45, 46, 47]
CLOSING_DIFFS = {"Clínica Sonrisa": {2: -150, -8: 200, -3: -500}}  # posición del día cerrado: diferencia en centavos

# Idénticas a connect() en payments/main.go: el seed corre en paralelo con el servicio de caja, que es quien las crea.
PAYMENTS_DDL = [
    """CREATE TABLE IF NOT EXISTS payments (
        id BIGSERIAL PRIMARY KEY,
        clinic_id BIGINT NOT NULL,
        patient_id BIGINT NOT NULL,
        amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
        method TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS invoice_number TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS authorization_code TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS buyer_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS buyer_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS voided BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS void_reason TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS voided_by BIGINT",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS credit_note TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS payments_patient_idx ON payments (clinic_id, patient_id)",
    """CREATE TABLE IF NOT EXISTS cash_closings (
        id BIGSERIAL PRIMARY KEY,
        clinic_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        day DATE NOT NULL,
        counted_cents BIGINT NOT NULL CHECK (counted_cents >= 0),
        expected_cents BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (clinic_id, day))""",
]
# balanceCents de Go: Go rechaza (422) un cobro mayor al saldo
BALANCE_SQL = """SELECT
    (SELECT COALESCE(SUM(cost), 0) * 100 FROM clinica_treatment WHERE clinic_id = %s AND patient_id = %s AND NOT voided)::bigint -
    (SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE clinic_id = %s AND patient_id = %s AND NOT voided)::bigint"""
# closeCash de Go, con el día y la hora del cierre en vez de now()
CLOSING_SQL = """INSERT INTO cash_closings (clinic_id, user_id, day, counted_cents, expected_cents, created_at)
    SELECT %s, %s, d, GREATEST(e + %s, 0), e, %s FROM (SELECT %s::date AS d, (SELECT COALESCE(SUM(amount_cents), 0) FROM payments
        WHERE clinic_id = %s AND method = 'efectivo' AND NOT voided AND (created_at AT TIME ZONE 'America/Guayaquil')::date = %s::date) AS e) t
    ON CONFLICT (clinic_id, day) DO NOTHING"""


def cedula(n):
    """Cédula ecuatoriana con dígito verificador válido (módulo 10) a partir de sus 9 primeros dígitos."""
    digits = f"{n:09d}"
    total = sum(p - 9 if p > 9 else p for p in (int(d) * (2 if i % 2 == 0 else 1) for i, d in enumerate(digits)))
    return digits + str((10 - total % 10) % 10)


class History:
    def run(self):
        self.rng = random.Random(2026)
        self.tz = timezone.get_current_timezone()
        self.today = timezone.localdate()
        self.pay = connection.vendor == "postgresql"  # cobros y cierres viven en tablas del servicio Go (PostgreSQL)
        defs = {name: [self.patient_def(name, *row) for row in rows] for name, rows in HISTORY_PATIENTS.items()}
        if Patient.objects.filter(clinic__name="Clínica Sonrisa", cedula=defs["Clínica Sonrisa"][0]["cedula"]).exists():
            return "Historial demo ya cargado."
        if self.pay:
            self.payment_tables()
        with transaction.atomic():
            return "Historial demo: " + "; ".join(self.clinic(Clinic.objects.get(name=name), d) for name, d in defs.items())

    def payment_tables(self):
        for attempt in range(5):
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    for stmt in PAYMENTS_DDL:
                        cur.execute(stmt)
                return
            except DatabaseError:  # payments puede estar creando las mismas tablas en este momento
                if attempt == 4:
                    raise
                clock.sleep(2)

    def at(self, day, hour, minute=0):
        # en UTC, como timezone.now(): las firmas usan created_at.isoformat() y deben coincidir con lo que se lee de la base
        return datetime.combine(day, time(hour, minute), tzinfo=self.tz).astimezone(dt_timezone.utc)

    def patient_def(self, clinic_name, first, last, year, allergies, systemic, extra):
        rng, prov = self.rng, PROVINCE[clinic_name]
        d = {"first_name": first, "last_name": last, "cedula": cedula(prov * 10**7 + rng.randrange(6 * 10**6)),
             "birth_date": date(year, rng.randint(1, 12), rng.randint(1, 28)), "phone": f"09{rng.randrange(10**8):08d}",
             "allergies": allergies, "systemic_diseases": systemic, **extra}
        if "guardian_name" in extra:
            d.update(guardian_cedula=cedula(prov * 10**7 + rng.randrange(6 * 10**6)), emergency_contact_name=extra["guardian_name"],
                     emergency_contact_phone=f"09{rng.randrange(10**8):08d}")
        return d

    def clinic(self, clinic, defs):
        rng = self.rng
        self.clinic_id = clinic.pk
        dentists = {User.objects.get(username=u): Chair.objects.get(clinic=clinic, name=c) for u, c in DENTISTS[clinic.name].items()}
        self.cashier, self.stocker, self.nurse = (User.objects.get(username=u) for u in STAFF[clinic.name])
        self.catalog = {p.code: p for p in Procedure.objects.filter(clinic=clinic)}
        self.counts = dict.fromkeys(("citas", "tratamientos", "notas", "cobros", "anulados", "cierres"), 0)
        first = self.today - timedelta(weeks=5)
        # el inventario inicial va antes del primer consumo del historial
        StockMovement.objects.filter(clinic=clinic, note="Inventario inicial", created_at__gt=self.at(first, 7)).update(created_at=self.at(first, 7))

        patients = list(Patient.objects.filter(clinic=clinic, cedula__in=EXISTING_DEMO)) + [Patient.objects.create(clinic=clinic, **d) for d in defs]
        owner = {p.pk: list(dentists)[i % len(dentists)] for i, p in enumerate(patients)}  # cada paciente con su odontólogo
        self.state = {p.pk: self.exam_plan(p) for p in patients}
        self.closed = set()
        if self.pay:
            with connection.cursor() as cur:
                cur.execute("SELECT day FROM cash_closings WHERE clinic_id = %s", [clinic.pk])
                self.closed = {r[0] for r in cur.fetchall()}  # días ya cerrados en el servidor: ahí no se agrega efectivo
        self.paid_days, self.cash = set(), {}  # efectivo vigente por día

        attended = []
        day = first
        while day <= self.today + timedelta(days=14):
            if day.weekday() < 5:
                for dentist, chair in dentists.items():
                    attended += self.agenda(day, dentist, chair, [p for p in patients if owner[p.pk] == dentist])
            day += timedelta(days=1)
        attended.sort(key=lambda x: x[0].start)
        last_visit = {a.patient_id: a.pk for a, _, _ in attended}
        voids = {4, 27} if clinic.name == "Clínica Sonrisa" else set()  # tratamientos registrados por error
        for i, (a, code, tooth) in enumerate(attended):
            # María Torres (paciente de las pruebas de navegador) conserva saldo pendiente
            self.attend(a, code, tooth, i in voids, skip_payment=a.patient.cedula == EXISTING_DEMO[0] and last_visit[a.patient_id] == a.pk)
        for p in patients:
            self.budget(p, owner[p.pk])
        for supply in Supply.objects.filter(clinic=clinic).exclude(name=LOW_SUPPLY):  # bodega con existencias para traslados
            if location_stock(supply, None) < self.lot(supply):
                self.purchase(supply, self.at(self.today, 7))
        self.discard_low(Supply.objects.get(clinic=clinic, name=LOW_SUPPLY), [None, *dentists.values()])
        if self.pay:
            self.closings(clinic)
        c = self.counts
        return (f"{clinic.name}: {len(defs)} pacientes nuevos, {c['citas']} citas, {c['tratamientos']} tratamientos, {c['notas']} notas, "
                f"{c['cobros']} cobros ({c['anulados']} anulados), {c['cierres']} cierres de caja")

    def exam_plan(self, p):
        """Hallazgos del primer examen y el plan de tratamiento que se desprende de ellos."""
        rng = self.rng
        st = {"findings": {}, "plan": [("PROF", None)], "pending": [], "teeth": {}, "exam_at": None}
        if p.teeth.exists():  # odontograma ya cargado a mano: solo controles
            return st
        free = [t for t in POSTERIOR if t not in (16, 26, 36, 46)] if p.is_minor else POSTERIOR[:]
        rng.shuffle(free)
        f, plan = st["findings"], st["plan"]
        if p.is_minor:
            plan += [("SEL", n) for n in sorted(rng.sample([16, 26, 36, 46], 2))]
        elif rng.random() < 0.45:
            n = free.pop()
            f[n] = ("endodoncia_requerida", {"O": "caries", "D": "caries"})
            plan += [("END", n), ("COR", n)]
        for _ in range(rng.randint(0, 1 if p.is_minor else 3)):
            n = free.pop()
            f[n] = ("sano", {s: "caries" for s in rng.sample(["O", "M", "D"], rng.randint(1, 2))})
            plan.append(("RES", n))
        if not p.is_minor and rng.random() < 0.3:
            n = rng.choice([18, 28, 38, 48])
            f[n] = ("exodoncia_indicada", {})
            plan.append(("EXO", n))
        if not p.is_minor and rng.random() < 0.15:
            n = free.pop()
            f[n] = ("extraido", {})
            plan.append(("IMP", n))
        # urgencias primero; la corona, después de lo demás
        order = {"PROF": 0, "END": 1, "RES": 2, "SEL": 2, "EXO": 3, "COR": 4, "IMP": 5}
        plan.sort(key=lambda x: order[x[0]])
        st["pending"] = plan[1:]
        return st

    def agenda(self, day, dentist, chair, patients):
        """Citas de un odontólogo en un día, sin solapes de odontólogo ni de sillón; devuelve las atendidas."""
        rng, today = self.rng, self.today
        n = 4 if day == today else rng.randint(1, 3)
        start, attended = self.at(day, *rng.choice([(8, 0), (8, 30), (9, 0), (10, 0), (14, 0)])), []
        pool = patients[:]
        for k in range(n):
            if not pool:
                break
            p = pool.pop(rng.randrange(len(pool)))
            st = self.state[p.pk]
            if day < today:
                r = rng.random()
                status = "cancelado" if r < 0.08 else "no_asistio" if r < 0.15 else "atendido"
            elif day == today:
                status = ["en_atencion", "en_espera", "confirmado", "programado"][k]
            else:
                status = "confirmado" if day <= today + timedelta(days=4) and rng.random() < 0.6 else "programado"
            # una cita que no se realiza no avanza el plan del paciente
            code, tooth = (st["plan"][0] if status in Appointment.INACTIVE else st["plan"].pop(0)) if st["plan"] else ("PROF", None)
            minutes = MINUTES[code]
            if start < self.at(day, 13) < start + timedelta(minutes=minutes):
                start = self.at(day, 14)  # almuerzo
            if start + timedelta(minutes=minutes) > self.at(day, 17, 30):
                break
            if not self.free(dentist, chair, start, minutes):  # p. ej. una cita creada a mano en el servidor demo
                start += timedelta(minutes=minutes + 30)
                continue
            a = Appointment.objects.create(clinic_id=self.clinic_id, patient=p, dentist=dentist, chair=chair, start=start, minutes=minutes,
                                           reason=REASONS[code].format(t=tooth), status=status)
            self.counts["citas"] += 1
            if status == "atendido":
                attended.append((a, code, tooth))
            start += timedelta(minutes=minutes + rng.choice([0, 0, 15, 30, 60]))
        return attended

    def free(self, dentist, chair, start, minutes):
        """Mismo criterio que AppointmentSerializer.validate (las canceladas y no asistidas no ocupan)."""
        end = start + timedelta(minutes=minutes)
        others = Appointment.objects.filter(Q(dentist=dentist) | Q(chair=chair), start__lt=end, start__gt=start - timedelta(minutes=480))
        return not any(o.start + timedelta(minutes=o.minutes) > start for o in others.exclude(status__in=Appointment.INACTIVE))

    def attend(self, a, code, tooth, void, skip_payment):
        rng, p, st = self.rng, a.patient, self.state[a.patient_id]
        end = a.start + timedelta(minutes=a.minutes)
        if st["exam_at"] is None:
            st["exam_at"] = a.start + timedelta(minutes=10)
            for n, (state, surfaces) in st["findings"].items():
                self.tooth(p, n, state, surfaces, a.dentist, st["exam_at"])
        if rng.random() < 0.6:
            self.vitals(p, a.start - timedelta(minutes=5))
        if code in CONSENT_FOR:
            self.consent(a, CONSENT_FOR[code])
        proc = self.catalog[code]
        t = self.treatment(a, proc, tooth)
        if (code, tooth) in st["pending"]:
            st["pending"].remove((code, tooth))
        self.odontogram(p, code, tooth, a.dentist, end)
        if rng.random() < 0.75:
            s, o, an, pl = (x.format(t=tooth) for x in NOTES[code])
            ClinicalNote(clinic_id=self.clinic_id, patient=p, author=a.dentist, created_at=end + timedelta(minutes=5),
                         subjective=s, objective=o, assessment=an, plan=pl).save()  # save() calcula la firma
            self.counts["notas"] += 1
        if code in CONSENT_FOR:
            self.prescription(a, code, end + timedelta(minutes=5))
        if void:  # RN-01: el duplicado se anula con motivo; los insumos ya consumidos no se reponen (igual que la vista)
            dup = self.treatment(a, proc, tooth)
            dup.voided, dup.void_reason, dup.voided_by, dup.voided_at = True, "Procedimiento registrado dos veces por error", a.dentist, end + timedelta(minutes=30)
            dup.save(update_fields=["voided", "void_reason", "voided_by", "voided_at"])
        if self.pay and not skip_payment:
            self.payment(p, int(t.cost * 100), end + timedelta(minutes=10))

    def treatment(self, a, proc, tooth):
        """Como TreatmentViewSet.perform_create: precio del catálogo y descargo de insumos con consume_supplies."""
        when = a.start + timedelta(minutes=a.minutes)
        self.stock_up(proc, a.chair, a.start - timedelta(minutes=15))
        t = Treatment.objects.create(clinic_id=self.clinic_id, patient=a.patient, tooth=tooth, procedure=proc.name, cost=proc.fee + proc.lab_cost,
                                     lab_cost=proc.lab_cost, date=timezone.localdate(a.start), catalog=proc, dentist=a.dentist, chair=a.chair)
        t.material_cost = consume_supplies(t, a.dentist)
        t.save(update_fields=["material_cost"])
        StockMovement.objects.filter(treatment=t).update(created_at=when)
        self.counts["tratamientos"] += 1
        return t

    def lot(self, supply):
        return Decimal(SUPPLIES[supply.name][1]) / 5

    def stock_up(self, proc, chair, when):
        """Antes de consumir: compra si el stock total bajaría del mínimo y traslada de bodega al sillón lo que falte."""
        for line in proc.recipe.all():
            supply = Supply.objects.get(pk=line.supply_id)
            low = supply.name == LOW_SUPPLY
            if not low and supply.stock - line.quantity < supply.min_stock:
                self.purchase(supply, when)
            need = line.quantity - location_stock(supply, chair)
            if need > 0:
                if not low and location_stock(supply, None) < need:
                    self.purchase(supply, when)
                qty = min(location_stock(supply, None), max(need, self.lot(supply)))
                if qty > 0:
                    note = f"Bodega central → {chair.name}"
                    for c, q in ((None, -qty), (chair, qty)):
                        StockMovement.objects.create(clinic_id=self.clinic_id, supply=supply, chair=c, quantity=q, reason="traslado",
                                                     user=self.stocker, note=note, created_at=when)

    def purchase(self, supply, when):
        qty = Decimal(SUPPLIES[supply.name][1])
        StockMovement.objects.create(clinic_id=self.clinic_id, supply=supply, quantity=qty, reason="compra", user=self.stocker,
                                     note="Reposición del proveedor", created_at=when)
        Supply.objects.filter(pk=supply.pk).update(stock=F("stock") + qty)

    def discard_low(self, supply, locations):
        """Ajuste por conteo físico (limas desechadas por desgaste) que deja el insumo bajo el mínimo, sin existencias negativas."""
        left = supply.stock - supply.min_stock + 2
        for chair in locations:
            qty = min(left, location_stock(supply, chair))
            if qty > 0:
                StockMovement.objects.create(clinic_id=self.clinic_id, supply=supply, chair=chair, quantity=-qty, reason="ajuste",
                                             user=self.stocker, note="Conteo físico: desechadas por desgaste", created_at=self.at(self.today, 7))
                Supply.objects.filter(pk=supply.pk).update(stock=F("stock") - qty)
                left -= qty

    def tooth(self, p, number, state, surfaces, user, when):
        """Como la vista del odontograma: estado actual + evento en el historial."""
        self.state[p.pk]["teeth"][number] = (state, surfaces)
        Tooth.objects.update_or_create(patient=p, number=number, defaults={"state": state, "surfaces": surfaces, "clinic_id": p.clinic_id})
        ToothEvent.objects.create(clinic_id=p.clinic_id, patient=p, number=number, state=state, surfaces=surfaces, user=user, created_at=when)

    def odontogram(self, p, code, tooth, user, when):
        if tooth is None:
            return
        state, surfaces = self.state[p.pk]["teeth"].get(tooth, ("sano", {}))
        new = {
            "RES": (state, {**surfaces, **({s: "restauracion" for s, v in surfaces.items() if v == "caries"} or {"O": "restauracion"})}),
            "SEL": ("sano", {**surfaces, "O": "sellante"}),
            "END": ("endodoncia", {"O": "restauracion"}),
            "COR": ("protesis_fija", {}),
            "EXO": ("extraido", {}),
            "IMP": ("implante", {}),
        }[code]
        self.tooth(p, tooth, *new, user, when)

    def vitals(self, p, when):
        rng, conditions = self.rng, p.systemic_diseases.lower()
        hyper = "hipertens" in conditions
        VitalSigns.objects.create(
            clinic_id=self.clinic_id, patient=p, recorded_by=self.nurse, created_at=when,
            systolic=rng.randint(138, 152) if hyper else rng.randint(105, 128), diastolic=rng.randint(86, 95) if hyper else rng.randint(65, 82),
            heart_rate=rng.randint(62, 92), spo2=rng.randint(95, 99), temperature=Decimal(f"36.{rng.randint(2, 8)}"),
            glucose=rng.randint(130, 185) if "diabetes" in conditions else None,
        )

    def consent(self, a, procedure):
        """Consentimiento firmado con OTP: misma plantilla y misma firma que ConsentViewSet."""
        p, dentist, when = a.patient, a.dentist, a.start - timedelta(minutes=10)
        tpl = ConsentTemplate.objects.get(clinic_id=self.clinic_id, procedure=procedure)
        text = tpl.body.format_map({"paciente": f"{p.first_name} {p.last_name}", "cedula": p.cedula, "procedimiento": tpl.procedure,
                                    "odontologo": dentist.get_full_name() or dentist.username, "fecha": timezone.localdate(when).strftime("%d/%m/%Y")})
        c = Consent.objects.create(clinic_id=self.clinic_id, patient=p, created_by=dentist, created_at=when, procedure=tpl.procedure, text=text)
        c.otp_hash = sign("otp", c.pk, f"{self.rng.randrange(10**6):06d}")
        c.method, c.signer_name, c.signed_at = "otp", p.guardian_name or f"{p.first_name} {p.last_name}", when + timedelta(minutes=3)
        c.signature = sign(c.pk, c.text, c.signer_name, c.method, c.signed_at.isoformat(), c.otp_hash)
        c.save()

    def prescription(self, a, code, when):
        drugs = [{"drug": "Paracetamol 500 mg", "dose": "1 tableta", "frequency": "cada 8 horas", "duration": "3 días", "instructions": "Si hay dolor"}]
        if code in ("EXO", "IMP"):
            drugs.append({"drug": "Amoxicilina 500 mg", "dose": "1 cápsula", "frequency": "cada 8 horas", "duration": "7 días", "instructions": ""})
        items = [d for d in drugs if not allergy_conflicts(a.patient.allergies, [d["drug"]])]
        Prescription(clinic_id=self.clinic_id, patient=a.patient, author=a.dentist, created_at=when, items=items).save()

    def budget(self, p, dentist):
        """Presupuesto pendiente de aprobación con lo que queda del plan."""
        st = self.state[p.pk]
        if not st["pending"] or st["exam_at"] is None:
            return
        b = Budget.objects.create(clinic_id=self.clinic_id, patient=p, author=dentist, created_at=st["exam_at"] + timedelta(minutes=20))
        for code, tooth in st["pending"]:
            proc = self.catalog[code]
            BudgetItem.objects.create(budget=b, phase=1 if code in ("END", "RES", "EXO", "SEL") else 2, procedure=proc, tooth=tooth,
                                      fee=proc.fee, lab_cost=proc.lab_cost)

    def payment(self, p, cost_cents, when):
        rng, day = self.rng, timezone.localdate(when)
        r = rng.random()
        cents = cost_cents if r < 0.7 else cost_cents // 200 * 100 if r < 0.85 else 0  # pago total, abono o queda debiendo
        if not cents:
            return
        method = rng.choices(["efectivo", "tarjeta_credito", "tarjeta_debito", "transferencia"], [45, 20, 20, 15])[0]
        if day in self.closed:  # la caja de ese día ya se cerró en el servidor: no cambiar su efectivo
            method = "tarjeta_debito"
        elif self.counts["cobros"] in (5, 22):  # cobro con método equivocado, anulado antes de cerrar la caja
            wrong = self.charge(p, cents, "efectivo", when)
            if wrong:
                with connection.cursor() as cur:
                    cur.execute("""UPDATE payments SET voided = true, void_reason = %s, voided_by = %s, voided_at = %s,
                        credit_note = 'NC-001-001-' || lpad(id::text, 9, '0') WHERE id = %s""",
                                ["Método equivocado: el paciente pagó con tarjeta de débito", self.cashier.pk, when + timedelta(minutes=4), wrong])
                self.counts["anulados"] += 1
                self.cash[day] -= cents
            method, when = "tarjeta_debito", when + timedelta(minutes=5)
        self.charge(p, cents, method, when)

    def charge(self, p, cents, method, when):
        """Como createPayment de Go: tope en el saldo, comprobante 001-001-<id> y autorización SIM- para tarjeta."""
        with connection.cursor() as cur:
            cur.execute(BALANCE_SQL, [self.clinic_id, p.pk] * 2)
            cents = min(cents, cur.fetchone()[0])
            if cents <= 0:
                return None
            buyer = (p.guardian_cedula, p.guardian_name) if p.is_minor and p.guardian_cedula else (p.cedula, f"{p.first_name} {p.last_name}")
            auth = f"SIM-{self.rng.randrange(10**6):06d}" if method.startswith("tarjeta") else ""
            cur.execute("""INSERT INTO payments (clinic_id, patient_id, amount_cents, method, buyer_id, buyer_name, authorization_code, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""", [self.clinic_id, p.pk, cents, method, *buyer, auth, when])
            pid = cur.fetchone()[0]
            cur.execute("UPDATE payments SET invoice_number = '001-001-' || lpad(id::text, 9, '0') WHERE id = %s", [pid])
        self.counts["cobros"] += 1
        self.paid_days.add(timezone.localdate(when))
        if method == "efectivo":
            self.cash[timezone.localdate(when)] = self.cash.get(timezone.localdate(when), 0) + cents
        return pid

    def closings(self, clinic):
        """Cierre ciego de casi todos los días pasados con cobros; hoy queda abierto para probarlo en vivo."""
        days = sorted(d for d in self.paid_days if d < self.today and d not in self.closed)
        skip = {days[len(days) // 2]} if clinic.name == "Clínica Sonrisa" and days else set()  # un día quedó sin cerrar
        cash = sorted(d for d, c in self.cash.items() if c > 0 and d in days and d not in skip)  # faltantes y sobrantes solo donde hubo efectivo
        diffs = {cash[i]: v for i, v in CLOSING_DIFFS.get(clinic.name, {}).items() if -len(cash) <= i < len(cash)}
        with connection.cursor() as cur:
            for d in days:
                if d not in skip:
                    cur.execute(CLOSING_SQL, [clinic.pk, self.cashier.pk, diffs.get(d, 0), self.at(d, 18, 30), d, clinic.pk, d])
                    self.counts["cierres"] += cur.rowcount
