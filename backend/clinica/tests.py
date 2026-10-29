from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Clinic, Patient, User


class ClinicaTests(APITestCase):
    def setUp(self):
        a, b = Clinic.objects.create(name="A"), Clinic.objects.create(name="B")
        self.dentist_a = User.objects.create_user("a", password="x", clinic=a)
        self.dentist_b = User.objects.create_user("b", password="x", clinic=b)
        self.patient_a = Patient.objects.create(clinic=a, cedula="1", first_name="P", last_name="A")
        self.patient_b = Patient.objects.create(clinic=b, cedula="2", first_name="P", last_name="B")

    def auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=user).key)

    def appt(self, start, minutes=30):
        return self.client.post(
            "/api/appointments/",
            {"patient": self.patient_a.id, "dentist": self.dentist_a.id, "start": start, "minutes": minutes},
        )

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/patients/").status_code, 401)

    def test_tenant_isolation(self):
        self.auth(self.dentist_b)
        ids = [p["id"] for p in self.client.get("/api/patients/").json()]
        self.assertEqual(ids, [self.patient_b.id])
        self.assertEqual(self.client.get(f"/api/patients/{self.patient_a.id}/").status_code, 404)
        # no puede crear tratamientos para un paciente de otra clínica
        r = self.client.post(
            "/api/treatments/", {"patient": self.patient_a.id, "procedure": "x", "cost": 1, "date": "2026-01-01"}
        )
        self.assertEqual(r.status_code, 400)

    def test_appointment_overlap(self):
        self.auth(self.dentist_a)
        self.assertEqual(self.appt("2026-11-02T10:00").status_code, 201)
        self.assertEqual(self.appt("2026-11-02T10:15").status_code, 400)
        self.assertEqual(self.appt("2026-11-02T09:45", 15).status_code, 201)  # termina justo a las 10:00
        self.assertEqual(self.appt("2026-11-02T10:30").status_code, 201)

    def test_odontogram_upsert(self):
        self.auth(self.dentist_a)
        url = f"/api/patients/{self.patient_a.id}/odontogram/"
        self.client.post(url, {"number": 11, "state": "caries"})
        teeth = self.client.post(url, {"number": 11, "state": "obturado"}).json()
        self.assertEqual(teeth, [{"number": 11, "state": "obturado"}])
        self.assertEqual(self.client.post(url, {"number": 19, "state": "caries"}).status_code, 400)
