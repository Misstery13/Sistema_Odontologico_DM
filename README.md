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

Abrir http://localhost:8080 (usuarios en la tabla de roles más abajo). Para producción: [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md).

## Alcance implementado (SRS SIGO-Dental, Fases 1 a 4)

Requisitos en `docs/Documento de Requerimientos de Software - Sistema Odontológico.md.pdf`.

| Req. | Implementación |
|---|---|
| RF-01 | Ficha única: datos, contacto de emergencia, tutor legal (obligatorio si es menor), seguro; alta y edición |
| RF-02 | Anamnesis obligatoria; badge rojo en la cabecera del expediente (alergias, anticoagulado, coagulopatía) |
| RF-03 | Odontograma SVG: dentición permanente (32) y temporal (20), notación FDI o Universal, 5 superficies (M, D, O/I, V, L/P); caries, restauración, sellante por superficie; endodoncia requerida/realizada, implante, prótesis fija/removible, exodoncia indicada/realizada por pieza. Lo rojo alimenta la lista "Por tratar" |
| RF-04 | Periodontograma: PS y margen gingival en 6 sitios, sangrado, movilidad, furca; NIC = PS + MG; resumen (% sangrado, bolsas ≥ 4 mm, NIC promedio); firmado e inmutable |
| Recetas | Receta firmada e imprimible; bloquea medicamentos que cruzan con alergias registradas (p. ej. penicilina → amoxicilina) salvo justificación |
| RF-06 | Consentimiento por procedimiento desde catálogo; firma en pantalla táctil (canvas) o por código OTP (6 dígitos, 10 min, 5 intentos; envío **simulado**, ver `docker compose logs backend`); se firma una vez e imprime |
| RF-05 / RN-01 | Notas SOEP firmadas (HMAC), editables solo por su autor durante 24 h (`NOTE_LOCK_HOURS`), luego adendas; tratamientos y notas no se borran |
| RF-09 | Agenda día/semana filtrable por sillón y odontólogo |
| RF-10 | Estados: programado, confirmado, en sala de espera, en atención, atendido, cancelado, no asistió |
| RF-11 | Confirmación al agendar y recordatorios 48 h/24 h (servicio `reminders`; adaptador **simulado**, ver `docker compose logs reminders`) |
| RF-07 | Presupuestos por fases desde el catálogo (honorario + laboratorio), con descuento autorizado hasta `MAX_DISCOUNT_PCT` (15 %); un presupuesto emitido no se edita |
| RF-08 | Aprobación total o parcial (recepción u odontólogo); lo aprobado pasa a la agenda y a "Por tratar", y se registra como tratamiento al precio neto, una sola vez |
| RF-12 (básico) | Cobros mixtos (efectivo, tarjeta, transferencia, seguro) con comprobante numerado (SRI **simulado**) |
| RF-13 | Liquidación de honorarios por odontólogo: % del precio, monto fijo, o % tras laboratorio y materiales |
| RF-14 | Receta estándar de consumo por procedimiento; descargo automático de insumos al registrar el tratamiento; kardex inmutable; alerta de stock bajo |
| Reportes | Producción, honorarios, procedimientos, ingresos por método, citas por estado y ausentismo, pacientes nuevos, consumo de insumos |
| RN-02 | Cierre de caja ciego: el total del sistema solo se muestra después de registrar el conteo |
| RN-03 | No se agendan dos citas a la vez en el mismo sillón ni con el mismo odontólogo |
| RNF-05 | RBAC con 5 roles; sesión cerrada tras 15 min de inactividad (frontend y backend) |
| RNF-06 | Log de auditoría inmutable (usuario, acción, registro, timestamp ISO-8601, IP) |
| 8.2 | OpenAPI 3 en `/api/schema/` |

Pendientes: MFA, cifrado en reposo a nivel de aplicación (se delega al disco cifrado), firma con certificado personal (hoy HMAC del servidor), pantalla de gestión de usuarios (hoy por CLI), integraciones reales (SRI, WhatsApp/SMS, pasarela) y prueba de carga. Detalle en [docs/seguridad/INFORME.md](docs/seguridad/INFORME.md).

### Fase 4: calidad, seguridad y producción

| Entregable | Dónde |
|---|---|
| Pruebas de aceptación (37 criterios, contra el sistema desplegado) | `python tests/uat.py [url]` |
| Tests Django (cobertura 89 %) | `cd backend && coverage run manage.py test` |
| Tests de integración Go (cobertura 83,9 %) | `sh scripts/test-payments.sh` (con el stack levantado) |
| SAST, auditoría de dependencias y DAST (OWASP ZAP) | CI y `docker compose --profile zap run --rm zap`; informe en [docs/seguridad/INFORME.md](docs/seguridad/INFORME.md) |
| CI en cada push (tests, cobertura ≥ 80 %, auditorías) | `.github/workflows/ci.yml` |
| Producción: TLS 1.3, HSTS, secretos obligatorios, healthchecks, backups diarios | `docker-compose.prod.yml`, `frontend/Caddyfile.prod`, [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md) |

### Roles demo (contraseña `odonto123`)

| Usuario | Rol | Ve |
|---|---|---|
| `dra.lopez`, `dr.perez` | Odontólogo | Agenda, pacientes, odontograma, tratamientos, SOEP, periodontograma, presupuestos, recetas, consentimientos, inventario |
| `asistente` | Asistente dental | Agenda, pacientes, SOEP, consentimientos, inventario y kardex (lectura de perio, recetas y presupuestos) |
| `recepcion` | Recepcionista / cajero | Agenda, pacientes, aprobación de presupuestos, cobros, cierre de caja |
| `auditor` | Auditor / contador | Reportes, honorarios, inventario, cierres de caja, auditoría |
| `admin` | Administrador TI | Reportes, inventario, cierres de caja, auditoría (sin datos clínicos) |
| `dr.vega`, `recepcion.norte` | Dental Norte | Otra clínica: sirve para comprobar el aislamiento |

## Seguridad (OWASP)

- Autenticación por token y aislamiento por clínica en el middleware (`clinica/middleware.py`), en cada consulta (`TenantViewSet`) y en cada FK (`TenantSerializer`). Así se evita el IDOR (A01).
- Límite de intentos en el login (10/min) (A07).
- ORM y consultas parametrizadas, sin SQL concatenado (A03).
- Cabeceras CSP, X-Frame-Options, nosniff, COOP/COEP/CORP y `no-store` en la API; contenedores sin root (A05).
- Informe completo de la auditoría: [docs/seguridad/INFORME.md](docs/seguridad/INFORME.md).

## Desarrollo local sin Docker

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python manage.py migrate && .venv/Scripts/python manage.py seed
.venv/Scripts/python manage.py test        # 21 tests de reglas de negocio, RBAC y aislamiento
.venv/Scripts/python manage.py runserver
cd frontend && npm install && npm run dev  # proxy a :8000 (Django) y :8081 (Go)
```
