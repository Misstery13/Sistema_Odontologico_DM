# Sistema Odontológico

Proyecto de la asignatura *Framework Programación Web* (ver `docs/`). Es un sistema multitenant: cada clínica ve solo sus propios pacientes, citas, odontogramas, tratamientos y pagos.

| Servicio | Tecnología | Unidad del sílabo |
|---|---|---|
| `frontend` | React + Vite + Tailwind, React Router, Context para la sesión | 1 |
| `payments` | Go + Fiber, PostgreSQL (transacciones con `FOR UPDATE`), Redis (caché de tokens) | 2 |
| `backend` | Django + DRF, ORM y migraciones, middleware de tenant | 3 |
| `caddy` | Proxy inverso, cabeceras de seguridad, SSL automático con dominio; Docker Compose y OWASP ZAP | 4 |

```
navegador ──► caddy :8080 ──► /api/*  → backend (Django)  ─┐
                          ├─► /pay/*  → payments (Go) ─────┼─► PostgreSQL
                          └─► /*      → SPA React          └─► Redis (Go)
```

## Ejecutar

```bash
docker compose up --build
```

Abrir http://localhost:8080. Usuarios demo (contraseña `odonto123`):

- `dra.lopez`, `dr.perez` → Clínica Sonrisa
- `dr.vega` → Dental Norte (sirve para comprobar el aislamiento: no ve los pacientes de la otra clínica)

Escaneo de seguridad (con el sistema levantado): `docker compose --profile zap run --rm zap`

## Módulos

- **Pacientes e historia clínica**: datos, alergias, antecedentes y tratamientos realizados.
- **Agenda**: citas por odontólogo; no deja crear dos citas que se crucen para el mismo odontólogo.
- **Odontograma**: 32 piezas con numeración FDI y estado (caries, obturado, endodoncia, corona, extraído).
- **Pagos** (servicio en Go): saldo = suma de tratamientos − pagos; no permite cobrar más que el saldo, ni siquiera con dos cobros simultáneos.

## Seguridad (OWASP)

- Autenticación por token y aislamiento por clínica en el middleware (`clinica/middleware.py`), en cada consulta (`TenantViewSet`) y en cada FK (`TenantSerializer`). Así se evita el IDOR (A01).
- Límite de intentos en el login (10/min) (A07).
- ORM y consultas parametrizadas, sin SQL concatenado (A03).
- Cabeceras CSP, X-Frame-Options y nosniff en Caddy; contenedores sin root (A05).

## Desarrollo local sin Docker

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python manage.py migrate && .venv/Scripts/python manage.py seed
.venv/Scripts/python manage.py test        # tests de aislamiento, solapamiento de citas y odontograma
.venv/Scripts/python manage.py runserver
cd frontend && npm install && npm run dev  # proxy a :8000 (Django) y :8081 (Go)
```
