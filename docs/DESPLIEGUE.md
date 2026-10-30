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
```

Con ese primer administrador, el resto de usuarios se gestiona desde la pantalla **Usuarios**: alta con contraseña temporal (se cambia obligatoriamente en el primer ingreso), cambio de rol, desactivación y reinicio de MFA.

Roles: `admin`, `recepcion`, `odontologo`, `asistente`, `auditor`. El mismo comando `usuario` cambia la contraseña de un usuario existente. El stock inicial se registra desde **Inventario** como movimientos de compra.

**Verificación en dos pasos (RNF-05):** es obligatoria. En su primer ingreso cada usuario escanea un QR con Google Authenticator, Microsoft Authenticator o Authy; desde entonces se le pide el código de 6 dígitos. Si alguien pierde el teléfono:

```bash
$P reset_mfa dra.lopez   # en su próximo ingreso vuelve a enrolarse
```

El reloj del servidor debe estar sincronizado (NTP), porque los códigos dependen de la hora.

## Qué queda corriendo

| Servicio | Función | Salud |
|---|---|---|
| `caddy` | HTTPS (TLS 1.3, HSTS), SPA y proxy inverso | — |
| `backend` | API Django (gunicorn, `GUNICORN_WORKERS`) | `/api/health/` |
| `payments` | Cobros, caja y comprobantes (Go) | `/pay/health` |
| `reminders` | Recordatorios de 48 h y 24 h, cada 15 min | — |
| `db`, `redis` | PostgreSQL 16 y Redis 7; no se exponen fuera de la red interna | `pg_isready` |
| `backup` | Diario en `./backups`: `pg_dump` de la base y `.tar.gz` de los archivos del expediente, con retención de `BACKUP_RETENTION_DAYS` días | — |
| `monitor` | Uptime Kuma: monitoreo de disponibilidad con alertas (RNF-02); solo escucha en `127.0.0.1:3001` | — |

Todos los servicios tienen `restart: unless-stopped`. Caddy espera a que backend y payments estén sanos antes de aceptar tráfico.

## Monitoreo y alertas (RNF-02)

Uptime Kuma no se publica a Internet. Para configurarlo, abre un túnel SSH y entra desde tu navegador:

```bash
ssh -L 3001:127.0.0.1:3001 usuario@servidor    # luego abrir http://localhost:3001
```

1. Crea la cuenta de administración del monitor.
2. Agrega dos monitores HTTP cada 60 s: `https://odonto.midominio.com/api/health/` y `https://odonto.midominio.com/pay/health`. Agrega también un monitor del certificado TLS.
3. En *Notificaciones*, configura email, Telegram o WhatsApp, y la página de estado si se necesita.

Uptime Kuma lleva el historial de disponibilidad, que es lo que sirve para comprobar el 99,9 % en horario clínico.

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
# archivos del expediente (radiografías, fotos, PDF):
$C run --rm -v "$PWD/backups:/backups" --entrypoint sh backend -c "tar -xzf /backups/odonto-AAAA-MM-DD-HHMM-archivos.tar.gz -C /app/media"
$C start backend payments reminders
```

Copia `./backups` fuera del servidor (almacenamiento de objetos o un segundo servidor): un respaldo que vive en el mismo disco no protege si ese disco falla.

## Verificaciones después de desplegar

```bash
python tests/uat.py https://odonto.midominio.com   # solo en un entorno con datos demo (staging)
python tests/load.py https://odonto.midominio.com 150 90   # carga: RNF-01 / RNF-03
docker compose --profile zap run --rm zap zap-baseline.py -t https://odonto.midominio.com -r zap-baseline.html -I
```

## Integraciones simuladas

SRI, pasarela de pagos, WhatsApp/SMS/email, OTP y firma con certificado están simulados; cada uno se conecta reemplazando una sola función. La tabla completa está en el README («Integraciones simuladas»).
