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

    def test_odontogram_surfaces_and_temporary_teeth(self):
        self.auth(self.dentist_a)
        url = f"/api/patients/{self.patient_a.id}/odontogram/"
        self.client.post(url, {"number": 36, "state": "sano", "surfaces": {"O": "caries"}}, format="json")
        teeth = self.client.post(url, {"number": 36, "state": "endodoncia", "surfaces": {"O": "restauracion", "M": "caries"}}, format="json").json()
        self.assertEqual(teeth, [{"number": 36, "state": "endodoncia", "surfaces": {"O": "restauracion", "M": "caries"}}])
        self.assertEqual(self.client.post(url, {"number": 55, "state": "extraido", "surfaces": {}}, format="json").status_code, 200)
        self.assertEqual(self.client.post(url, {"number": 19, "state": "sano"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"number": 11, "surfaces": {"X": "caries"}}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"number": 11, "surfaces": {"O": "fractura"}}, format="json").status_code, 400)

    def test_periodontogram_summary(self):
        self.auth(self.dentist_a)
        site = lambda pd, gm, b: {"pd": [pd] * 6, "gm": [gm] * 6, "bleeding": [b] * 6, "mobility": 1, "furcation": 0}
        r = self.client.post("/api/perio/", {"patient": self.patient_a.id, "teeth": {"16": site(5, 2, True), "11": site(2, 0, False)}}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["summary"], {"teeth": 2, "sites": 12, "bleeding_pct": 50.0, "deep_sites": 6, "mean_cal": 4.5})
        bad = {"patient": self.patient_a.id, "teeth": {"16": {**site(5, 2, True), "pd": [5, 5]}}}
        self.assertEqual(self.client.post("/api/perio/", bad, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/perio/{r.json()['id']}/").status_code, 405)
        self.auth(self.recep_a)
        self.assertEqual(self.client.get("/api/perio/").status_code, 403)

    def test_prescription_allergy_check(self):
        self.patient_a.allergies = "Penicilina"
        self.patient_a.save()
        self.auth(self.dentist_a)
        item = {"drug": "Amoxicilina 500 mg", "dose": "1 cápsula", "frequency": "cada 8 h", "duration": "7 días"}
        r = self.client.post("/api/prescriptions/", {"patient": self.patient_a.id, "items": [item]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("allergy_override", r.json())
        ok = {"patient": self.patient_a.id, "items": [{**item, "drug": "Clindamicina 300 mg"}]}
        self.assertEqual(self.client.post("/api/prescriptions/", ok, format="json").status_code, 201)
        forced = {"patient": self.patient_a.id, "items": [item], "allergy_override": "Prueba cutánea negativa 2026"}
        self.assertEqual(self.client.post("/api/prescriptions/", forced, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/prescriptions/", {"patient": self.patient_a.id, "items": [{"drug": "x"}]}, format="json").status_code, 400)

    def consent(self):
        from .models import ConsentTemplate
        tpl = ConsentTemplate.objects.create(clinic=self.patient_a.clinic, procedure="Exodoncia", body="Yo {paciente} ({cedula}) autorizo {procedimiento} con {odontologo} el {fecha}.")
        r = self.client.post("/api/consents/", {"patient": self.patient_a.id, "template": tpl.id})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["text"].startswith("Yo P A (1) autorizo Exodoncia con a"))
        return r.json()["id"]

    def test_consent_biometric_signature(self):
        self.auth(self.dentist_a)
        cid = self.consent()
        url = f"/api/consents/{cid}/sign/"
        self.assertEqual(self.client.post(url, {"method": "biometrica", "signer_name": "P A", "signature_image": "nope"}).status_code, 400)
        img = "data:image/png;base64," + "A" * 400
        r = self.client.post(url, {"method": "biometrica", "signer_name": "P A", "signature_image": img})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["signed"])
        self.assertEqual(self.client.post(url, {"method": "biometrica", "signer_name": "P A", "signature_image": img}).status_code, 400)  # una sola vez

    def test_consent_otp_signature(self):
        from unittest import mock
        self.auth(self.dentist_a)
        cid = self.consent()
        with mock.patch("clinica.views.send") as send:
            self.assertEqual(self.client.post(f"/api/consents/{cid}/request-otp/").status_code, 200)
        code = send.call_args.args[2].split("es ")[1][:6]
        url = f"/api/consents/{cid}/sign/"
        wrong = "000000" if code != "000000" else "111111"
        self.assertEqual(self.client.post(url, {"method": "otp", "signer_name": "P A", "code": wrong}).status_code, 400)
        r = self.client.post(url, {"method": "otp", "signer_name": "P A", "code": code})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["method"], "otp")
        self.assertNotIn("otp_hash", r.json())
