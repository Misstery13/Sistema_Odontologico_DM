"""Pruebas de aceptación (UAT, Fase 4) contra el sistema desplegado, a través de Caddy.

Uso:  python tests/uat.py [http://localhost:8080]
Requiere los datos demo (`manage.py seed`). Solo usa la biblioteca estándar. Crea datos nuevos en cada corrida.
"""
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
PASSWORD = "odonto123"
results = []


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Token {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            is_json = "json" in r.headers.get("Content-Type", "")
            return r.status, json.loads(raw) if raw and is_json else raw, r.headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), e.headers
        except ValueError:
            return e.code, raw.decode(errors="replace"), e.headers


def check(req, name, ok, detail=""):
    results.append((req, name, bool(ok)))
    print(f"{'OK  ' if ok else 'FALLA'} [{req}] {name}{'' if ok else f' -> {detail}'}")


def login(user):
    status, data, _ = call("POST", "/api/login/", body={"username": user, "password": PASSWORD})
    assert status == 200, f"login {user}: {status} {data}"
    return data["token"]


def main():
    tag = str(int(time.time()))[-7:]
    t = {u: login(u) for u in ["dra.lopez", "dr.perez", "recepcion", "asistente", "auditor", "admin", "dr.vega"]}
    D, R, AS, AU, AD = t["dra.lopez"], t["recepcion"], t["asistente"], t["auditor"], t["admin"]

    # --- seguridad y sesión ---
    s, _, _ = call("POST", "/api/login/", body={"username": "recepcion", "password": "mala"})
    check("RNF-05", "credenciales inválidas rechazadas", s == 400, s)
    check("RNF-05", "sin token no hay acceso", call("GET", "/api/patients/")[0] == 401)
    check("RNF-05", "admin sin acceso a datos clínicos (menor privilegio)", call("GET", "/api/patients/", AD)[0] == 403)
    check("RNF-05", "recepción no escribe notas clínicas", call("POST", "/api/notes/", R, {"patient": 1, "subjective": "x"})[0] == 403)
    s, _, h = call("GET", "/")
    check("OWASP", "cabeceras CSP y X-Frame-Options", "default-src 'self'" in h.get("Content-Security-Policy", "") and h.get("X-Frame-Options") == "DENY")
    check("8.2", "especificación OpenAPI publicada", call("GET", "/api/schema/")[0] == 200)

    # --- RF-01/02: ficha y alertas ---
    patient = {
        "cedula": f"09{tag}1", "first_name": "Lucía", "last_name": f"Prueba {tag}", "phone": "0990000000",
        "allergies": "Penicilina", "systemic_diseases": "Ninguna", "anticoagulated": True,
        "emergency_contact_name": "Pedro", "emergency_contact_phone": "0991111111",
    }
    s, p, _ = call("POST", "/api/patients/", R, patient)
    check("RF-01", "recepción registra la ficha", s == 201, p)
    pid = p["id"]
    check("RF-02", "badge de alertas críticas", p["alerts"] == ["Alergia: Penicilina", "Anticoagulado"], p.get("alerts"))
    s, _, _ = call("POST", "/api/patients/", R, {**patient, "cedula": f"09{tag}2", "birth_date": str(date.today() - timedelta(days=3650))})
    check("RF-01", "menor sin tutor legal rechazado", s == 400, s)
    check("RF-01", "edición de la ficha", call("PATCH", f"/api/patients/{pid}/", R, {"insurance": "Convenio X"})[1]["insurance"] == "Convenio X")
    check("Multitenant", "otra clínica no ve la ficha", call("GET", f"/api/patients/{pid}/", t["dr.vega"])[0] == 404)

    # --- RF-09/10/11, RN-03: agenda ---
    dentists = {d["name"]: d["id"] for d in call("GET", "/api/dentists/", R)[1]}
    chairs = call("GET", "/api/chairs/", R)[1]
    start = (date.today() + timedelta(days=random.randint(200, 2000))).isoformat() + "T10:00"
    appt = {"patient": pid, "dentist": dentists["Ana López"], "chair": chairs[0]["id"], "start": start, "minutes": 30}
    s, a, _ = call("POST", "/api/appointments/", R, appt)
    check("RF-09", "cita agendada con sillón", s == 201, a)
    s, err, _ = call("POST", "/api/appointments/", R, {**appt, "dentist": dentists["Luis Pérez"]})
    check("RN-03", "mismo sillón con otro odontólogo rechazado", s == 400 and "sillón" in str(err), err)
    s, a2, _ = call("PATCH", f"/api/appointments/{a['id']}/", AS, {"status": "en_espera"})
    check("RF-10", "estado 'en sala de espera'", s == 200 and a2["status"] == "en_espera", a2)

    # --- RF-03: odontograma ---
    s, teeth, _ = call("POST", f"/api/patients/{pid}/odontogram/", D, {"number": 36, "state": "endodoncia_requerida", "surfaces": {"O": "caries", "M": "caries"}})
    check("RF-03", "hallazgos por superficie y pieza", s == 200 and teeth[0]["surfaces"] == {"O": "caries", "M": "caries"}, teeth)
    check("RF-03", "dentición temporal", call("POST", f"/api/patients/{pid}/odontogram/", D, {"number": 54, "state": "extraido", "surfaces": {}})[0] == 200)

    # --- RF-07/08 + RF-14: presupuesto → aprobación → tratamiento con descargo ---
    catalog = {p["code"]: p for p in call("GET", "/api/procedures/", D)[1]}
    items = [{"phase": 1, "procedure": catalog["RES"]["id"], "tooth": 36}, {"phase": 2, "procedure": catalog["COR"]["id"], "tooth": 36}]
    check("RF-07", "descuento sobre el tope rechazado", call("POST", "/api/budgets/", D, {"patient": pid, "discount_pct": 40, "items": items})[0] == 400)
    s, b, _ = call("POST", "/api/budgets/", D, {"patient": pid, "discount_pct": 10, "items": items})
    check("RF-07", "presupuesto por fases con descuento", s == 201 and b["totals"]["total"] == round((45 + 160 + 120) * 0.9, 2), b.get("totals"))
    res_item = next(i for i in b["items"] if i["phase"] == 1)
    s, b2, _ = call("POST", f"/api/budgets/{b['id']}/decide/", R, {"approved_items": [res_item["id"]]})
    check("RF-08", "aprobación parcial por el paciente", s == 200 and b2["status"] == "parcial", b2)
    pending = call("GET", f"/api/budgets/pending/?patient={pid}", R)[1]
    check("RF-08", "lo aprobado queda agendable", [i["id"] for i in pending] == [res_item["id"]], pending)
    resin_before = next(x for x in call("GET", "/api/supplies/", AS)[1] if x["name"] == "Resina compuesta")["stock"]
    s, tr, _ = call("POST", "/api/treatments/", D, {"patient": pid, "budget_item": res_item["id"], "date": date.today().isoformat()})
    check("RF-08", "tratamiento desde el ítem aprobado al precio neto", s == 201 and tr["cost"] == "40.50", tr)
    resin_after = next(x for x in call("GET", "/api/supplies/", AS)[1] if x["name"] == "Resina compuesta")["stock"]
    check("RF-14", "descargo automático de insumos", round(float(resin_before) - float(resin_after), 2) == 0.5, (resin_before, resin_after))
    check("RN-01", "lo realizado no se borra", call("DELETE", f"/api/treatments/{tr['id']}/", D)[0] == 405)

    # --- RF-12, RN-02: caja ---
    bal = call("GET", f"/pay/patients/{pid}/balance", R)[1]["balance"]
    check("RF-12", "no se cobra más que el saldo", call("POST", "/pay/payments", R, {"patient_id": pid, "amount": bal + 1, "method": "efectivo"})[0] == 422)
    s, pay, _ = call("POST", "/pay/payments", R, {"patient_id": pid, "amount": 10, "method": "seguro"})
    check("RF-12", "cobro con comprobante electrónico", s == 201 and pay["invoice_number"].startswith("001-001-"), pay)
    check("RF-12", "odontólogo no cobra", call("POST", "/pay/payments", D, {"patient_id": pid, "amount": 1, "method": "efectivo"})[0] == 403)
    check("RN-02", "recepción no ve totales de caja", call("GET", "/pay/cash-closings", R)[0] == 403)
    s, closing, _ = call("POST", "/pay/cash-closings", R, {"counted": 0})
    check("RN-02", "cierre ciego (o ya cerrado hoy)", s == 201 and "expected" in closing or s == 409, closing)

    # --- RF-05, recetas, RF-04, RF-06 ---
    s, note, _ = call("POST", "/api/notes/", D, {"patient": pid, "subjective": "Dolor 36", "plan": "Endodoncia"})
    check("RF-05", "nota SOEP firmada", s == 201 and len(note["signature"]) == 64, note)
    check("RF-05", "nota no se borra", call("DELETE", f"/api/notes/{note['id']}/", D)[0] == 405)
    rx = {"patient": pid, "items": [{"drug": "Amoxicilina 500 mg", "dose": "1", "frequency": "8 h", "duration": "7 días"}]}
    check("Recetas", "alerta de alergia cruzada", call("POST", "/api/prescriptions/", D, rx)[0] == 400)
    perio = {"patient": pid, "teeth": {"16": {"pd": [3, 4, 5, 3, 2, 3], "gm": [1] * 6, "bleeding": [True, False] * 3, "mobility": 1, "furcation": 0}}}
    s, ex, _ = call("POST", "/api/perio/", D, perio)
    check("RF-04", "periodontograma con resumen", s == 201 and ex["summary"]["deep_sites"] == 2, ex.get("summary"))
    tpl = call("GET", "/api/consent-templates/", D)[1][0]
    s, c, _ = call("POST", "/api/consents/", D, {"patient": pid, "template": tpl["id"]})
    s, c2, _ = call("POST", f"/api/consents/{c['id']}/sign/", D, {"method": "biometrica", "signer_name": "Lucía", "signature_image": "data:image/png;base64," + "A" * 500})
    check("RF-06", "consentimiento firmado en pantalla", s == 200 and c2["signed"], c2)
    check("RF-06", "no se firma dos veces", call("POST", f"/api/consents/{c['id']}/sign/", D, {"method": "biometrica", "signer_name": "x", "signature_image": "data:image/png;base64," + "A" * 500})[0] == 400)

    # --- RF-13, reportes, RNF-06 ---
    today = date.today().isoformat()
    s, rep, _ = call("GET", f"/api/reports/?from={today}&to={today}", AU)
    check("RF-13", "liquidación de honorarios", s == 200 and any(r["dentist"] == "Ana López" and r["commission"] > 0 for r in rep["commissions"]), rep.get("commissions") if isinstance(rep, dict) else rep)
    check("Reportes", "ingresos por método", call("GET", f"/pay/reports/income?from={today}&to={today}", AU)[0] == 200)
    logs = call("GET", "/api/audit/", AU)[1]
    check("RNF-06", "auditoría de la ficha consultada", any(l["model"] == "Patient" and l["object_id"] == str(pid) for l in logs))

    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} criterios de aceptación cumplidos")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
