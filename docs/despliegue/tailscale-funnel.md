# Desplegar Odonto DM en un servidor casero con Tailscale Funnel

Instrucciones para ejecutar **en el servidor** (Ubuntu/Debian). El sistema completo corre en Docker y se publica en internet con **Tailscale Funnel** en `https://<máquina>.<tailnet>.ts.net`, sin abrir puertos del router y sin dominio propio. Tailscale gestiona el certificado HTTPS.

```
Internet ──HTTPS──► Tailscale Funnel ──► 127.0.0.1:HTTP_PORT ──► caddy
                    (443, 8443 o 10000)                           ├─ /api/* ──► backend (Django)
                                                                  ├─ /pay/* ──► payments (Go)
                                                                  └─ /*     ──► SPA React
                                                     postgres 16 + redis + reminders + backup + monitor
```

- **Funnel:** solo publica Caddy, que escucha en `127.0.0.1` y no es visible ni en la red de la casa.
- **Bases de datos:** PostgreSQL y Redis no publican puertos.
- **Monitor:** Uptime Kuma queda en `127.0.0.1:3001`, accesible solo por la tailnet (paso 6).

> Si en el mismo servidor ya corre otra aplicación con Funnel (por ejemplo la Tienda en el puerto público 443), el script elige solo otro puerto libre (8443 o 10000) y otro puerto local. No toca la configuración de Funnel de las otras apps.

---

## 1. Requisitos (una sola vez)

```bash
docker --version && docker compose version     # Compose 2.24 o superior
tailscale version && tailscale status          # la máquina debe estar conectada a la tailnet
```

Si falta algo:

```bash
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER && newgrp docker
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
sudo tailscale set --operator=$USER            # opcional: usar tailscale sin sudo
```

En la **consola de Tailscale** (navegador, https://login.tailscale.com/admin):

1. **DNS** → activar **MagicDNS** y **HTTPS Certificates**.
2. **Access controls** → permitir Funnel a esta máquina. La primera vez que se ejecuta `tailscale funnel`, la terminal muestra un enlace que lo hace automáticamente.

## 2. Clonar el repositorio

```bash
git clone https://github.com/Misstery13/Sistema_Odontologico_DM.git
cd Sistema_Odontologico_DM
```

Si ya estaba clonado: `cd Sistema_Odontologico_DM && git pull`.

## 3. Decidir: ¿datos de demostración?

Por defecto **no** se cargan (`SEED_DEMO=0`): la clínica se crea vacía y con contraseñas propias.

Para **exhibir el proyecto** (revisión, presentación) se puede poner `SEED_DEMO=1` en `.env.funnel` después del primer arranque y repetir el paso 4. Se cargan los usuarios demo (`dra.lopez`, `recepcion`, `asistente`, `auditor`, `admin`; clave `odonto123`) con el secreto MFA público `ODONTODMDEMOMFA2`.

> **Advertencia:** con `SEED_DEMO=1`, cualquiera en internet que lea el README puede entrar a la clínica demo. Úsalo solo con datos ficticios.

## 4. Desplegar

```bash
./scripts/desplegar-funnel.sh
```

El script:

1. Verifica Docker, Compose ≥ 2.24 y Tailscale.
2. Crea `.env.funnel` (permisos 600) con `SECRET_KEY` y `POSTGRES_PASSWORD` aleatorios, y con el nombre `.ts.net` de la máquina.
3. Elige un puerto local libre y un puerto de Funnel libre.
4. Construye y levanta todo con la configuración de producción y espera a que backend y caja estén sanos.
5. Publica con `tailscale funnel --bg` y verifica la URL pública.
6. Si aún no hay clínica, muestra los comandos para crearla.

La primera vez tarda varios minutos (compila Go, instala Python y construye React).

## 5. Crear la clínica y el primer administrador

Solo si **no** se usan datos demo. La contraseña se pide por teclado: mínimo 10 caracteres y no puede ser común.

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.funnel.yml --env-file .env.funnel"
$C exec backend python manage.py nueva_clinica "Clínica Sonrisa" --sillones 2
$C exec backend python manage.py usuario "Clínica Sonrisa" admin.ti admin --nombre Ana --apellido Ruiz
```

Luego se entra a la URL con ese usuario. En el primer ingreso se escanea el QR con una app autenticadora y se cambia la contraseña temporal. Desde **Usuarios** se crea el resto del personal.

## 6. Monitor de disponibilidad (opcional, solo dentro de la tailnet)

```bash
tailscale serve --bg --https=3001 http://127.0.0.1:3001
```

Abrir `https://<máquina>.<tailnet>.ts.net:3001` desde un dispositivo de la tailnet (no es público). Ahí se agregan dos monitores HTTP a `/api/health/` y `/pay/health` de la URL pública, y alertas por email o Telegram.

## Operación

| Acción | Comando |
|---|---|
| Estado | `$C ps` |
| Logs | `$C logs -f --tail 100 backend payments caddy` |
| Actualizar a la última versión | `git pull && ./scripts/desplegar-funnel.sh` |
| Ver qué publica Funnel | `tailscale funnel status` |
| Dejar de publicar (el sistema sigue corriendo) | `tailscale funnel --https=<FUNNEL_PORT> off` |
| Detener todo (los datos se conservan) | `$C down` |
| Respaldos | carpeta `./backups` (diarios: base de datos + archivos del expediente; retención de 14 días) |
| Restaurar | ver `docs/DESPLIEGUE.md`, sección «Respaldo y restauración» |

Nunca usar `down -v` salvo que se quiera **borrar todos los datos** (borra los volúmenes de base de datos y archivos).

## Problemas comunes

| Síntoma | Causa y solución |
|---|---|
| `Funnel not available` / pide habilitar | Falta permitir Funnel en la política de la tailnet: abrir el enlace que muestra el comando. |
| La URL responde «no se puede conectar» los primeros minutos | Tailscale está emitiendo el certificado; esperar 1-2 minutos. |
| `ImproperlyConfigured: En producción define SECRET_KEY...` | `.env.funnel` incompleto: borrarlo y volver a ejecutar el script (genera secretos nuevos; **solo** antes de tener datos, porque cambia la contraseña de la base). |
| `DisallowedHost` en los logs | `SITE_ADDRESS` no coincide con el nombre `.ts.net`; el script lo corrige al volver a ejecutarse. |
| El código de verificación siempre es incorrecto | El reloj del servidor está desfasado: `timedatectl set-ntp true`. |
| Disco lleno | `docker system df`, `docker builder prune` (caché de compilación) y revisar `./backups`. |
