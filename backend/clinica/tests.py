from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import AuditLog, Chair, Clinic, ClinicalNote, Notification, Patient, User


class ClinicaTests(APITestCase):
    def setUp(self):
        a, b = Clinic.objects.create(name="A"), Clinic.objects.create(name="B")
        self.dentist_a = User.objects.create_user("a", password="x", clinic=a, role="odontologo")
        self.dentist_a2 = User.objects.create_user("a2", password="x", clinic=a, role="odontologo")
        self.recep_a = User.objects.create_user("ra", password="x", clinic=a, role="recepcion")
        self.dentist_b = User.objects.create_user("b", password="x", clinic=b, role="odontologo")
        self.chair1, self.chair2 = Chair.objects.create(clinic=a, name="S1"), Chair.objects.create(clinic=a, name="S2")
        self.patient_a = Patient.objects.create(clinic=a, cedula="1", first_name="P", last_name="A", phone="0990000000")
        self.patient_b = Patient.objects.create(clinic=b, cedula="2", first_name="P", last_name="B")

    def auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.get_or_create(user=user)[0].key)

    def appt(self, start, dentist=None, chair=None, minutes=30):
        return self.client.post("/api/appointments/", {
            "patient": self.patient_a.id, "dentist": (dentist or self.dentist_a).id,
            "chair": (chair or self.chair1).id, "start": start, "minutes": minutes,
        })

    def note(self, **extra):
        return self.client.post("/api/notes/", {"patient": self.patient_a.id, "subjective": "Dolor en 36", **extra})

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/patients/").status_code, 401)

    def test_tenant_isolation(self):
        self.auth(self.dentist_b)
        ids = [p["id"] for p in self.client.get("/api/patients/").json()]
        self.assertEqual(ids, [self.patient_b.id])
        self.assertEqual(self.client.get(f"/api/patients/{self.patient_a.id}/").status_code, 404)
        r = self.client.post("/api/treatments/", {"patient": self.patient_a.id, "procedure": "x", "cost": 1, "date": "2026-01-01"})
        self.assertEqual(r.status_code, 400)

    def test_overlap_by_dentist_and_by_chair(self):
        self.auth(self.recep_a)
        self.assertEqual(self.appt("2026-11-02T10:00").status_code, 201)
        self.assertEqual(self.appt("2026-11-02T10:15", chair=self.chair2).status_code, 400)  # mismo odontólogo
        r = self.appt("2026-11-02T10:15", dentist=self.dentist_a2)  # RN-03: mismo sillón, otro odontólogo
        self.assertEqual(r.status_code, 400)
        self.assertIn("sillón", str(r.json()))
        self.assertEqual(self.appt("2026-11-02T10:15", dentist=self.dentist_a2, chair=self.chair2).status_code, 201)
        self.assertEqual(self.appt("2026-11-02T09:30").status_code, 201)  # termina justo a las 10:00

    def test_rbac(self):
        self.auth(self.recep_a)
        self.assertEqual(self.note().status_code, 403)  # recepción no escribe notas clínicas
        self.assertEqual(self.client.post(f"/api/patients/{self.patient_a.id}/odontogram/", {"number": 11, "state": "caries"}).status_code, 403)
        self.assertEqual(self.client.get("/api/audit/").status_code, 403)
        self.auth(self.dentist_a)
        self.assertEqual(self.note().status_code, 201)

    def test_note_lock_and_addendum(self):
        self.auth(self.dentist_a)
        note_id = self.note().json()["id"]
        self.assertEqual(self.client.patch(f"/api/notes/{note_id}/", {"plan": "Obturar"}).status_code, 200)
        self.auth(self.dentist_a2)
        self.assertEqual(self.client.patch(f"/api/notes/{note_id}/", {"plan": "x"}).status_code, 403)  # no es el autor
        ClinicalNote.objects.filter(pk=note_id).update(created_at=timezone.now() - timedelta(hours=25))
        self.auth(self.dentist_a)
        self.assertEqual(self.client.patch(f"/api/notes/{note_id}/", {"plan": "x"}).status_code, 403)  # bloqueada
        self.assertEqual(self.client.delete(f"/api/notes/{note_id}/").status_code, 405)
        self.assertEqual(self.note(amends=note_id, plan="Corrige plan").status_code, 201)

    def test_treatments_are_immutable(self):
        self.auth(self.dentist_a)
        t = self.client.post("/api/treatments/", {"patient": self.patient_a.id, "procedure": "x", "cost": 1, "date": "2026-01-01"}).json()
        self.assertEqual(self.client.delete(f"/api/treatments/{t['id']}/").status_code, 405)
        self.assertEqual(self.client.patch(f"/api/treatments/{t['id']}/", {"cost": 0}).status_code, 405)

    def test_audit_log(self):
        self.auth(self.dentist_a)
        self.client.get(f"/api/patients/{self.patient_a.id}/", HTTP_X_FORWARDED_FOR="10.0.0.7")
        log = AuditLog.objects.get(action="read", model="Patient")
        self.assertEqual((log.user, log.object_id, log.ip), (self.dentist_a, str(self.patient_a.id), "10.0.0.7"))

    def test_idle_session_expires(self):
        self.auth(self.dentist_a)
        User.objects.filter(pk=self.dentist_a.pk).update(last_activity=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.client.get("/api/patients/").status_code, 401)
        self.assertFalse(Token.objects.filter(user=self.dentist_a).exists())

    def test_minor_requires_guardian_and_alerts(self):
        self.auth(self.recep_a)
        data = {"cedula": "9", "first_name": "N", "last_name": "M", "birth_date": "2020-01-01", "allergies": "Ninguna", "systemic_diseases": "Ninguna"}
        self.assertEqual(self.client.post("/api/patients/", data).status_code, 400)
        r = self.client.post("/api/patients/", {**data, "guardian_name": "Madre", "anticoagulated": True})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["alerts"], ["Anticoagulado"])

    def test_confirmation_and_reminders(self):
        self.auth(self.recep_a)
        start = timezone.localtime() + timedelta(hours=30)
        self.appt(start.strftime("%Y-%m-%dT%H:%M"))
        call_command("send_reminders")
        call_command("send_reminders")  # idempotente
        kinds = sorted(Notification.objects.values_list("kind", flat=True))
        self.assertEqual(kinds, ["confirmacion", "recordatorio_48h"])

    def test_odontogram_upsert(self):
        self.auth(self.dentist_a)
        url = f"/api/patients/{self.patient_a.id}/odontogram/"
        self.client.post(url, {"number": 11, "state": "caries"})
        teeth = self.client.post(url, {"number": 11, "state": "obturado"}).json()
        self.assertEqual(teeth, [{"number": 11, "state": "obturado"}])
        self.assertEqual(self.client.post(url, {"number": 19, "state": "caries"}).status_code, 400)
