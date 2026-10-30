# Informe de auditoría de seguridad y aceptación (Fase 4)

Fecha: 29/10/2026. Alcance: los servicios `backend` (Django), `payments` (Go) y `frontend` (React + Caddy) desplegados con Docker Compose.

## Resultado frente a los criterios de aceptación (SRS 8.2)

| Criterio | Resultado | Evidencia |
|---|---|---|
| Cobertura ≥ 80 % en endpoints críticos | **Cumple**: Django 89 %, Go 85,3 % | `coverage report`; `go test -cover` (CI: `.github/workflows/ci.yml`) |
| DAST/SAST sin severidad Alta o Crítica | **Cumple**: 0 altas, 0 críticas | ZAP (`zap-baseline.html`, `zap-api.html`), bandit, pip-audit, npm audit, govulncheck |
| Documentación OpenAPI 3 | **Cumple** | `GET /api/schema/` (API clínica) y `GET /pay/openapi.yaml` (caja y facturación) |
| Pruebas de aceptación (UAT) | **Cumple**: 62/62 criterios | `tests/uat.py` contra el stack desplegado |
| RNF-01: expediente en menos de 1,5 s | **Cumple**: p95 262 ms con 150 usuarios | `tests/load.py` (ver «Rendimiento») |
| RNF-03: 150 usuarios concurrentes | **Cumple**: 0 errores en 21.986 peticiones | `tests/load.py` |
| RNF-05: MFA obligatorio | **Cumple** | TOTP RFC 6238 en el login; tests y UAT |
| RNF-07: escritorio, laptop y tablet | **Cumple** | Playwright en 1920×1080, 1366×768, 1440×900 e iPad Pro 11, sin desbordes horizontales |
| RNF-08: Chrome, Firefox, Edge y Safari | **Cumple** | Playwright en Chromium (Chrome y Edge), Firefox y WebKit (motor de Safari) |
| RNF-02: disponibilidad | **Implementado** | Healthchecks, reinicio automático, backups y monitoreo con alertas (Uptime Kuma); el 99,9 % se mide en producción |

## Pruebas automatizadas

- **Django:** 32 tests (archivos: tipo real y descarga auditada; signos vitales; traslados; exportación; catálogos sin borrado), incluido el vector oficial TOTP del RFC 6238 y la gestión de usuarios (solo admin, solo su clínica, no puede autodesactivarse, la desactivación cierra la sesión, la contraseña temporal bloquea el acceso hasta cambiarla). Cubren el aislamiento entre clínicas, RBAC, la expiración por inactividad, la auditoría, los choques de sillón y de odontólogo, el bloqueo de notas SOEP, la inmutabilidad (RN-01), el odontograma, el periodontograma, las alertas de alergia, la firma de consentimientos (en pantalla y OTP), los presupuestos con aprobación parcial, el descargo de insumos, los honorarios y la operación (alta de clínica, healthcheck, errores JSON).
- **Go:** tests de integración contra PostgreSQL y Redis reales. Cubren la autenticación, la sesión inactiva, los roles, el aislamiento entre clínicas, las validaciones de cobro, el comprobante, **5 cobros simultáneos que nunca superan el saldo**, el cierre de caja ciego y el reporte de ingresos.
- **UAT:** 37 criterios de punta a punta a través de Caddy, uno o más por requisito (RF-01 a RF-14, RN-01 a RN-03, RNF-05, RNF-06).

## Hallazgos y correcciones

| Herramienta | Hallazgo | Severidad | Acción |
|---|---|---|---|
| pip-audit | 12 CVE en Django 5.1.15 y DRF 3.17.2 | Alta/Media | Actualizado a **Django 5.2 LTS (≥ 5.2.17)** y **DRF ≥ 3.18.2** → 0 |
| npm audit | react-router 6: *open redirect* en `<Link>`/`useNavigate` | Moderada | Actualizado a **react-router 7.18.5** → 0 |
| govulncheck | CVE en el toolchain Go 1.23 (`net/http`, `crypto/tls`, `crypto/x509`) y en `x/text` | Alta | Actualizado a **Go 1.26** y dependencias al día → 0 |
| ZAP baseline | Cabecera COEP ausente | Baja | Agregadas COEP, COOP y CORP en Caddy |
| ZAP baseline | Respuestas de la API cacheables | Baja | `Cache-Control: no-store` en `/api/*` y `/pay/*` (datos de salud) |
| ZAP API | Content-Type inesperado en los 404 | Baja | Handlers 404/500 de Django en JSON |
| bandit | Contraseña fija `odonto123` | Baja | Solo en datos demo; el contenedor no ejecuta `seed` en producción (`# nosec B105`) |
| Revisión manual | El contenedor cargaba usuarios demo con clave conocida en cualquier entorno | **Alta** | `seed` desactivado con `DJANGO_ENV=production`; altas con `nueva_clinica` y `usuario` |
| Revisión manual | Producción podía arrancar con `SECRET_KEY` o la clave de BD de ejemplo | **Alta** | El backend se niega a arrancar (`ImproperlyConfigured`) |
| Revisión manual | La CSP bloqueaba las imágenes `data:`: la firma de los consentimientos no se veía al reabrirlos | Media (funcional) | `img-src 'self' data:` |
| Revisión en tablet | El odontograma no entraba en una tablet: había que desplazarse para ver la arcada | Media (usabilidad) | Grilla fluida: la arcada completa entra en 768 px |

## Riesgos aceptados y falsos positivos (ZAP)

- **"Storable and Cacheable Content"** en `index.html`, `robots.txt` y `sitemap.xml`: son estáticos públicos de la SPA, sin datos de pacientes.
- **"Unexpected Content-Type"** (API scan): son rutas fuera de `/api/` que devuelven la SPA en HTML (necesario para el enrutado del cliente), incluidas las sondas de metadatos cloud, que no exponen nada. `/api/schema/` devuelve YAML de OpenAPI.
- **"Modern Web Application"**: es informativo.
- **Alcance del API scan:** el escaneo de la API se hizo sin autenticar, así que la mayoría de los endpoints respondió 401. La autorización de cada endpoint autenticado está cubierta por los tests de RBAC y aislamiento.

## Controles implementados (OWASP Top 10 2021)

| Riesgo | Control |
|---|---|
| A01 Control de acceso | RBAC de 5 roles con menor privilegio. Aislamiento multitenant en el middleware, en cada consulta y en cada FK (incluye el servicio Go). Registros clínicos inmutables. |
| A02 Fallos criptográficos | TLS 1.3 únicamente y HSTS. Firma HMAC-SHA256 de los registros clínicos. Códigos OTP guardados como HMAC con comparación en tiempo constante. |
| A03 Inyección | ORM de Django y consultas parametrizadas en pgx. CSP `default-src 'self'`. |
| A04 Diseño inseguro | Bloqueo de fila (`FOR UPDATE`) contra cobros concurrentes. Cierre de caja ciego. OTP con vencimiento de 10 min y 5 intentos. |
| A05 Configuración | DEBUG apagado y secretos validados al arrancar. Contenedores sin root. BD y Redis sin puertos públicos. Cabeceras de seguridad. |
| A06 Componentes vulnerables | Auditoría de dependencias en cada push (CI). |
| A07 Autenticación | Contraseñas temporales asignadas por el administrador con cambio obligatorio (también en el servicio Go). **MFA TOTP obligatorio** (enrolamiento con QR en el primer ingreso; el ticket entre pasos vence en 5 min; cada código sirve una sola vez). Límite de 10 intentos por minuto en cada paso. Validadores de contraseña (mínimo 10, no comunes). Sesión cerrada tras 15 min de inactividad. Token nuevo en cada ingreso. |
| A09 Registro y monitoreo | Log de auditoría inmutable: quién, qué, cuándo (ISO-8601), IP y exportaciones. Kardex inmutable. Logs de acceso de gunicorn. Monitoreo de disponibilidad con alertas. |
| A08 Integridad de datos | Archivos del expediente validados por su firma binaria (no por la extensión), con SHA-256 guardado y servidos solo por la API, con `nosniff` y sin borrado. |

## Pendientes conocidos (fuera del alcance de esta entrega)

- **Secreto MFA:** se guarda en la BD protegida por el cifrado del disco; si se exige, cifrarlo con un KMS.
- **Cifrado en reposo (RNF-04):** se delega al disco cifrado del servidor o al proveedor (ver `docs/DESPLIEGUE.md`).
- **Firma de los registros clínicos:** es HMAC del servidor, no un certificado personal del profesional (PKI).
- **Integraciones:** SRI, pasarela de pagos, WhatsApp/SMS/email, OTP y firma con certificado están simuladas (ver README).

## Rendimiento (RNF-01, RNF-03)

`python tests/load.py <url> <usuarios> <segundos>`. Simula personal de clínica con 2-5 s de reflexión entre acciones: abrir expediente (60 %, las 8 peticiones de la ficha en paralelo), agenda del día (25 %) y búsqueda (15 %).

| Usuarios concurrentes | Peticiones | Errores | Expediente p50 | Expediente p95 | Expediente máx. |
|---|---|---|---|---|---|
| 10 (línea base, 60 s) | 1.024 (16/s) | 0 | 33 ms | 52 ms | 202 ms |
| **150 (90 s)** | **21.986 (231/s)** | **0** | **96 ms** | **262 ms** | **487 ms** |

Medido en una laptop con Docker Desktop (Windows), con cliente y servidor en la misma máquina y gunicorn con 3 workers × 4 hilos. La latencia sube con la carga (p95 de 52 a 262 ms), pero queda 5,7 veces por debajo del límite de 1,5 s. En producción hay que repetir la prueba contra el servidor real (`GUNICORN_WORKERS`, `GUNICORN_THREADS`).
