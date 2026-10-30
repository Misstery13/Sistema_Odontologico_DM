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

Abrir http://localhost:8080 (usuarios en la tabla de roles más abajo). Si el puerto 8080 está ocupado en tu equipo, crea un `.env` con `HTTP_PORT=8088` (u otro libre) y pasa esa URL a los scripts de prueba, por ejemplo `python tests/uat.py http://127.0.0.1:8088`. El ingreso pide un código de verificación (MFA). Los usuarios demo comparten un secreto fijo: `python tests/totp.py` muestra el código vigente, o se puede cargar el secreto `ODONTODMDEMOMFA2` en cualquier app autenticadora. Para producción con dominio propio: [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md). En un servidor casero con Tailscale Funnel: [docs/despliegue/tailscale-funnel.md](docs/despliegue/tailscale-funnel.md) (`./scripts/desplegar-funnel.sh`).

## Alcance implementado (SRS SIGO-Dental, Fases 1 a 4)

Requisitos en `docs/Documento de Requerimientos de Software - Sistema Odontológico.md.pdf`.

| Req. | Implementación |
|---|---|
| RF-01 | Ficha única: datos, contacto de emergencia, tutor legal (obligatorio si es menor), seguro; alta y edición |
| RF-02 | Anamnesis obligatoria; badge rojo en la cabecera del expediente (alergias, anticoagulado, coagulopatía) |
| RF-03 | Odontograma SVG: dentición permanente (32) y temporal (20), notación FDI o Universal, 5 superficies (M, D, O/I, V, L/P); caries, restauración, sellante por superficie; endodoncia requerida/realizada, implante, prótesis fija/removible, exodoncia indicada/realizada por pieza. Lo rojo alimenta la lista "Por tratar". **Historial**: cada cambio queda registrado con autor y fecha, y se puede ver el odontograma tal como estaba en cualquier fecha |
| RF-04 | Periodontograma: PS y margen gingival en 6 sitios, sangrado, movilidad, furca; NIC = PS + MG; resumen (% sangrado, bolsas ≥ 4 mm, NIC promedio); firmado e inmutable |
| Recetas | Receta firmada e imprimible; bloquea medicamentos que cruzan con alergias registradas (p. ej. penicilina → amoxicilina) salvo justificación |
| RF-06 | Consentimiento por procedimiento desde catálogo; firma en pantalla táctil (canvas) o por código OTP (6 dígitos, 10 min, 5 intentos; envío **simulado**, ver `docker compose logs backend`); se firma una vez e imprime |
| RF-05 / RN-01 | Notas SOEP firmadas (HMAC), editables solo por su autor durante 24 h (`NOTE_LOCK_HOURS`), luego adendas. Nada se borra: un tratamiento o un cobro erróneo se **anula con motivo** (el cobro con nota de crédito; no se permite si la caja de ese día ya se cerró), deja de contar en saldo, honorarios y caja, y queda visible tachado |
| RF-09 | Agenda día/semana filtrable por consultorio y odontólogo; **reprogramación** (fecha, hora, consultorio, odontólogo) con validación de choques y aviso al paciente |
| RF-10 | Estados: programado, confirmado, en sala de espera, en atención, atendido, cancelado, no asistió |
| RF-11 | Confirmación al agendar y recordatorios 48 h/24 h (servicio `reminders`; adaptador **simulado**, ver `docker compose logs reminders`) |
| RF-07 | Presupuestos por fases desde el catálogo (honorario + laboratorio), con descuento autorizado hasta `MAX_DISCOUNT_PCT` (15 %); un presupuesto emitido no se edita |
| RF-08 | Aprobación total o parcial (recepción u odontólogo); lo aprobado pasa a la agenda y a "Por tratar", y se registra como tratamiento al precio neto, una sola vez |
| RF-12 | Cobros mixtos (efectivo, tarjeta de crédito, tarjeta de débito, transferencia, seguro); comprobante imprimible con datos del comprador (cédula, RUC o consumidor final), IVA 0 % de servicios de salud y código de la pasarela (SRI y pasarela **simulados**) |
| RF-13 | Liquidación de honorarios por odontólogo: % del precio, monto fijo, o % tras laboratorio y materiales |
| RF-14 / 2.2 | Inventario por ubicación (bodega central y cada consultorio), traslados, compras y ajustes; el procedimiento descarga la receta estándar del consultorio donde se hizo; consumo por consultorio y por profesional en Reportes; kardex inmutable; alerta de stock bajo |
| 2.3 / 7 | Archivos del expediente: radiografías, fotos clínicas y PDF (hasta 15 MB); se valida el tipo real del contenido, se guarda su SHA-256, no se borran y cada consulta o descarga pasa por permisos y auditoría |
| Signos vitales | Presión, pulso, respiración, temperatura, SpO₂ y glucemia, con alertas clínicas (crisis hipertensiva, saturación baja, fiebre…); las del día aparecen en la cabecera de la ficha junto a las alergias |
| Reportes | Producción, honorarios, procedimientos, ingresos por método, citas por estado y ausentismo, pacientes nuevos, consumo de insumos |
| RN-02 | Cierre de caja ciego: el total del sistema solo se muestra después de registrar el conteo |
| RN-03 | No se agendan dos citas a la vez en el mismo sillón ni con el mismo odontólogo |
| RNF-05 | RBAC con 5 roles; MFA TOTP obligatorio (enrolamiento con QR); sesión cerrada tras 15 min de inactividad (frontend y backend) |
| RNF-06 | Log de auditoría inmutable (usuario, acción, registro, timestamp ISO-8601, IP), incluidas las **exportaciones**: impresión de recetas, consentimientos y comprobantes, y descarga de archivos |
| Administrador TI | Catálogos: procedimientos y precios con su receta de consumo, insumos, consultorios y formatos de consentimiento (se desactivan, no se borran). Gestión de usuarios de la clínica: alta con contraseña temporal (cambio obligatorio al entrar), cambio de rol, desactivación (cierra su sesión), reinicio de MFA; todo auditado. Cada usuario cambia su contraseña desde «Mi cuenta» |
| RNF-01 / RNF-03 | Expediente p95 de 262 ms con 150 usuarios concurrentes, 0 errores (`tests/load.py`) |
| RNF-07 / RNF-08 | Pruebas de navegador (Playwright) en Chromium, Firefox y WebKit (motor de Safari), en 1920×1080, 1366×768 e iPad; el odontograma completo entra en una tablet |
| RNF-02 | Healthchecks, reinicio automático y monitoreo de disponibilidad con alertas (Uptime Kuma, en producción) |
| 8.2 | OpenAPI 3 en `/api/schema/` (API clínica) y `/pay/openapi.yaml` (caja) |

Pendientes: cifrado en reposo a nivel de aplicación (se delega al disco cifrado) y conectar los proveedores reales de las integraciones simuladas (ver abajo). Detalle en [docs/seguridad/INFORME.md](docs/seguridad/INFORME.md).

### Fase 4: calidad, seguridad y producción

| Entregable | Dónde |
|---|---|
| Pruebas de aceptación (68 criterios, contra el sistema desplegado) | `python tests/uat.py [url]` |
| Prueba de carga (150 usuarios concurrentes) | `python tests/load.py [url] [usuarios] [segundos]` |
| Pruebas de navegador (Chromium, Firefox, WebKit; escritorio, laptop, iPad) | `cd tests/e2e && npm i && npx playwright install && npx playwright test` |
| Tests Django (36 tests, cobertura 89 %) | `cd backend && coverage run manage.py test` |
| Tests de integración Go (cobertura 85,3 %) | `sh scripts/test-payments.sh` (con el stack levantado) |
| SAST, auditoría de dependencias y DAST (OWASP ZAP) | CI y `docker compose --profile zap run --rm zap`; informe en [docs/seguridad/INFORME.md](docs/seguridad/INFORME.md) |
| CI en cada push: tests, cobertura ≥ 80 %, auditorías y, con el sistema levantado en Docker, UAT, carga y navegadores | `.github/workflows/ci.yml` |
| Producción: TLS 1.3, HSTS, secretos obligatorios, healthchecks, backups diarios | `docker-compose.prod.yml`, `frontend/Caddyfile.prod`, [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md) |

### Roles demo (contraseña `odonto123`)

| Usuario | Rol | Ve |
|---|---|---|
| `dra.lopez`, `dr.perez` | Odontólogo | Agenda, pacientes, odontograma, tratamientos, SOEP, periodontograma, presupuestos, recetas, consentimientos, inventario |
| `asistente` | Asistente dental | Agenda, pacientes, signos vitales, SOEP, archivos, consentimientos, inventario, traslados y kardex (lectura de perio, recetas y presupuestos) |
| `recepcion` | Recepcionista / cajero | Agenda, pacientes, aprobación de presupuestos, cobros, cierre de caja |
| `auditor` | Auditor / contador | Reportes (incluido consumo por consultorio y profesional), honorarios, inventario, cierres de caja, auditoría |
| `admin` | Administrador TI | Usuarios (alta, rol, desactivar, contraseña temporal, reinicio de MFA), catálogos, reportes, inventario, cierres de caja, auditoría (sin datos clínicos) |
| `dr.vega`, `recepcion.norte` | Dental Norte | Otra clínica: sirve para comprobar el aislamiento |

### Datos demo

`manage.py seed` (se ejecuta al arrancar el backend fuera de producción o con `SEED_DEMO=1`) carga, además de usuarios y catálogos, un historial ficticio con fechas relativas al día de arranque:

- **Pacientes:** 20 en Clínica Sonrisa y 6 en Dental Norte, con cédulas válidas. Algunos tienen alergias, anticoagulación, coagulopatía o enfermedades sistémicas, para que se vean las alertas.
- **Agenda:** cinco semanas de citas pasadas (atendidas, canceladas y no asistidas), las de hoy en distintos estados y las de las dos semanas siguientes. No hay solapes de odontólogo ni de sillón.
- **Registro clínico:** tratamientos del catálogo con descargo de insumos (dos anulados por registro duplicado), odontograma con su historial, notas SOEP firmadas, signos vitales, consentimientos firmados, recetas y presupuestos pendientes. Las limas de endodoncia quedan bajo el mínimo, para que aparezca la alerta de stock.
- **Caja:** cobros en efectivo, con tarjeta y por transferencia (dos por clínica anulados con nota de crédito) y cierres de caja de los días pasados, tres de ellos con faltante o sobrante. Algunos pacientes quedan con saldo pendiente. La caja de **hoy** queda abierta, para probar el cierre ciego.

El historial se carga una sola vez; los arranques siguientes no duplican nada. Con SQLite (desarrollo sin Docker) se omiten los cobros y cierres, que viven en las tablas del servicio de caja en PostgreSQL.

## Integraciones simuladas

Las integraciones que necesitan cuentas o certificados reales funcionan con **adaptadores simulados**: el flujo completo corre, pero en vez de llamar al proveedor se escribe en el log. Para conectar un proveedor real se reemplaza una sola función, sin tocar el resto del sistema.

| Integración | Qué hace hoy | Dónde se ve | Función a reemplazar |
|---|---|---|---|
| Facturación electrónica (SRI) | Numera el comprobante `001-001-NNNNNNNNN` | `docker compose logs payments` | `issueInvoice` en `payments/main.go` |
| Pasarela de pagos (tarjeta) | Aprueba y devuelve un código `SIM-NNNNNN`; si la pasarela rechaza, el cobro no se registra | `docker compose logs payments` | `authorizeCard` en `payments/main.go` |
| WhatsApp / SMS / email | Confirmación de cita y recordatorios de 48 h y 24 h | `docker compose logs reminders backend` | `send` en `backend/clinica/notify.py` |
| OTP del consentimiento | Envía el código de 6 dígitos por el mismo canal | `docker compose logs backend` | `send` en `backend/clinica/notify.py` |
| Firma digital del profesional | HMAC-SHA256 del servidor sobre el contenido del registro | campo `signature` | `sign` en `backend/clinica/models.py` (certificado personal / PKI) |

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
.venv/Scripts/python manage.py test        # 36 tests de reglas de negocio, RBAC, MFA, usuarios, archivos, inventario y aislamiento
.venv/Scripts/python manage.py runserver
cd frontend && npm install && npm run dev  # proxy a :8000 (Django) y :8081 (Go)
```
