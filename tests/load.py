"""Prueba de carga (RNF-01 / RNF-03) contra el sistema desplegado. Solo biblioteca estándar.

Simula personal de clínica: cada usuario virtual repite una acción y "piensa" entre 2 y 5 s.
  - abrir expediente (60 %): las 8 peticiones que hace la ficha del paciente, en paralelo como el navegador
  - agenda del día (25 %) y búsqueda de paciente (15 %)

Uso:  python tests/load.py [url] [usuarios] [segundos]      (por defecto http://localhost:8080 150 90)
Compara con 10 usuarios para medir la degradación:  python tests/load.py http://localhost:8080 10 60
"""
import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from totp import totp

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
USERS = int(sys.argv[2]) if len(sys.argv) > 2 else 150
SECONDS = int(sys.argv[3]) if len(sys.argv) > 3 else 90
THINK = (2, 5)
TARGET_MS = 1500  # RNF-01: expediente y odontograma en menos de 1,5 s

lock = threading.Lock()
timings = {"expediente": [], "agenda": [], "busqueda": []}
errors = []
requests_done = 0


def get(path, token):
    global requests_done
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Token {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:  # timeouts, conexiones rechazadas
        status = type(e).__name__
    with lock:
        requests_done += 1
        if status != 200:
            errors.append(f"{status} {path}")


def login(user):
    def post(path, body):
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    step = post("/api/login/", {"username": user, "password": "odonto123"})
    if "token" in step:
        return step["token"]
    for _ in range(2):
        try:
            return post("/api/login/mfa/", {"ticket": step["ticket"], "code": totp("ODONTODMDEMOMFA2")})["token"]
        except urllib.error.HTTPError:
            time.sleep(31 - time.time() % 30)  # el código de este paso ya se usó: esperar al siguiente
    raise SystemExit(f"No se pudo ingresar como {user}")


def main():
    dentist, reception = login("dra.lopez"), login("recepcion")
    req = urllib.request.Request(BASE + "/api/patients/", headers={"Authorization": f"Token {dentist}"})
    patients = [p["id"] for p in json.loads(urllib.request.urlopen(req).read())]
    pool = ThreadPoolExecutor(max_workers=USERS * 6)
    today = date.today().isoformat()
    deadline = time.time() + SECONDS

    def timed(kind, paths, token):
        start = time.perf_counter()
        list(pool.map(lambda p: get(p, token), paths))  # en paralelo, como el navegador
        with lock:
            timings[kind].append((time.perf_counter() - start) * 1000)

    def virtual_user():
        time.sleep(random.uniform(0, THINK[1]))  # arranque escalonado
        while time.time() < deadline:
            roll, pid = random.random(), random.choice(patients)
            if roll < 0.60:
                timed("expediente", [
                    f"/api/patients/{pid}/", f"/api/patients/{pid}/odontogram/", f"/api/treatments/?patient={pid}",
                    f"/api/budgets/pending/?patient={pid}", f"/api/notes/?patient={pid}", f"/api/appointments/?patient={pid}",
                    f"/pay/patients/{pid}/payments", f"/pay/patients/{pid}/balance",
                ], dentist)
            elif roll < 0.85:
                timed("agenda", [f"/api/appointments/?from={today}&to={today}", "/api/patients/", "/api/chairs/", "/api/dentists/"], reception)
            else:
                timed("busqueda", [f"/api/patients/?q={random.choice('aeiou')}"], reception)
            time.sleep(random.uniform(*THINK))

    print(f"{USERS} usuarios concurrentes durante {SECONDS} s contra {BASE} …")
    started = time.time()
    threads = [threading.Thread(target=virtual_user) for _ in range(USERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - started

    def pct(values, p):
        return statistics.quantiles(values, n=100)[p - 1] if len(values) > 1 else (values[0] if values else 0)

    print(f"\n{'acción':<12}{'n':>6}{'p50 ms':>10}{'p95 ms':>10}{'máx ms':>10}")
    for kind, values in timings.items():
        if values:
            print(f"{kind:<12}{len(values):>6}{statistics.median(values):>10.0f}{pct(values, 95):>10.0f}{max(values):>10.0f}")
    total = requests_done
    print(f"\npeticiones: {total} ({total / elapsed:.1f}/s) · errores: {len(errors)} ({100 * len(errors) / max(total, 1):.2f} %)")
    if errors:
        print("  ejemplos:", sorted(set(errors))[:5])
    p95 = pct(timings["expediente"], 95)
    ok = p95 < TARGET_MS and not errors
    print(f"RNF-01 expediente p95 {p95:.0f} ms {'<' if p95 < TARGET_MS else '≥'} {TARGET_MS} ms → {'CUMPLE' if ok else 'NO CUMPLE'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
