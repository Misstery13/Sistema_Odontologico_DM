# Despliegue en producción (Fase 4)

Odonto DM se despliega con Docker Compose en un servidor Linux. Caddy publica el sitio con HTTPS automático (Let's Encrypt), restringido a TLS 1.3.

## Requisitos

- Servidor con Docker Engine 24+ y el plugin Compose v2.24+ (para `!override`).
- Un dominio cuyo registro DNS A/AAAA apunte al servidor, y los puertos 80 y 443 abiertos.
- **Cifrado en reposo (RNF-04):** el volumen de datos de Docker (`/var/lib/docker`) debe estar en un disco cifrado con AES-256 (LUKS en Linux, o el cifrado de disco del proveedor cloud). La aplicación no cifra la base por su cuenta.

## Primera instalación

```bash
git clone https://github.com/Misstery13/Sistema_Odontologico_DM.git && cd Sistema_Odontologico_DM
cp .env.example .env
# completar SITE_ADDRESS, SECRET_KEY y POSTGRES_PASSWORD
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build
```

El backend **se niega a arrancar** si `SECRET_KEY` o `POSTGRES_PASSWORD` son las de ejemplo, si `SECRET_KEY` tiene menos de 40 caracteres o si `DEBUG` está activo. En producción no se cargan datos demo.

Dar de alta la clínica y sus usuarios (la contraseña se pide por teclado; mínimo 10 caracteres y no puede ser común):

```bash
P="docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python manage.py"
$P nueva_clinica "Clínica Sonrisa" --sillones 3     # sillones, catálogo de procedimientos, insumos, formatos de consentimiento
$P usuario "Clínica Sonrisa" admin.ti admin --nombre Ana --apellido Ruiz
$P usuario "Clínica Sonrisa" dra.lopez odontologo --nombre Ana --apellido López
$P usuario "Clínica Sonrisa" recepcion1 recepcion
```

Roles: `admin`, `recepcion`, `odontologo`, `asistente`, `auditor`. El mismo comando `usuario` cambia la contraseña de un usuario existente. El stock inicial se registra desde **Inventario** como movimientos de compra.

## Qué queda corriendo

| Servicio | Función | Salud |
|---|---|---|
| `caddy` | HTTPS (TLS 1.3, HSTS), SPA y proxy inverso | — |
| `backend` | API Django (gunicorn, `GUNICORN_WORKERS`) | `/api/health/` |
| `payments` | Cobros, caja y comprobantes (Go) | `/pay/health` |
| `reminders` | Recordatorios de 48 h y 24 h, cada 15 min | — |
| `db`, `redis` | PostgreSQL 16 y Redis 7; no se exponen fuera de la red interna | `pg_isready` |
| `backup` | `pg_dump` diario en `./backups`, con retención de `BACKUP_RETENTION_DAYS` días | — |

Todos los servicios tienen `restart: unless-stopped`. Caddy espera a que backend y payments estén sanos antes de aceptar tráfico.

## Actualizar a una nueva versión

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build
```

Las migraciones de base de datos se aplican solas al arrancar el backend. Los certificados se conservan en el volumen `caddy_data`.

## Respaldo y restauración

Además del respaldo diario automático, se puede generar uno manual:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup sh -c 'pg_dump -h db -U odonto -Fc odonto > /backups/manual.dump'
```

Para restaurar, primero se detienen los servicios que escriben en la base:

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C stop backend payments reminders
$C exec backup pg_restore -h db -U odonto -d odonto --clean --if-exists /backups/odonto-AAAA-MM-DD-HHMM.dump
$C start backend payments reminders
```

Copia `./backups` fuera del servidor (almacenamiento de objetos o un segundo servidor): un respaldo que vive en el mismo disco no protege si ese disco falla.

## Verificaciones después de desplegar

```bash
python tests/uat.py https://odonto.midominio.com   # solo en un entorno con datos demo (staging)
docker compose --profile zap run --rm zap zap-baseline.py -t https://odonto.midominio.com -r zap-baseline.html -I
```

## Integraciones simuladas

La facturación electrónica (SRI), WhatsApp/SMS y el OTP de consentimientos usan adaptadores **simulados**: solo escriben en los logs. Para conectar los proveedores reales hay que reemplazar:

- `issueInvoice` en `payments/main.go` (SRI);
- `send` en `backend/clinica/notify.py` (Meta Cloud API / Twilio).

Esos son los únicos puntos de integración.
