# Odonto DM — contexto para agentes

Sistema de gestión odontológica multitenant (proyecto de la asignatura *Framework Programación Web*). Requisitos: `docs/Documento de Requerimientos de Software - Sistema Odontológico.md.pdf`. Trazabilidad requisito → implementación: `README.md`.

## Arquitectura

| Servicio | Tecnología | Notas |
|---|---|---|
| `caddy` | Caddy 2 + SPA React/Vite/Tailwind (`frontend/`) | Proxy: `/api/*` → backend, `/pay/*` → payments. Configs: `Caddyfile` (dev), `Caddyfile.prod` (dominio propio, TLS 1.3), `Caddyfile.funnel` (detrás de Tailscale Funnel); comparten `common.caddy` |
| `backend` | Django 5.2 + DRF (`backend/`) | Clínico, agenda, inventario, usuarios, auditoría. Migraciones al arrancar. `seed` solo fuera de producción o con `SEED_DEMO=1` |
| `payments` | Go 1.26 + Fiber (`payments/`) | Cobros, comprobantes, anulaciones, cierre de caja ciego y WebSocket de la agenda en vivo (`/pay/ws`, escucha `pg_notify` de Django). Lee tablas de Django en la misma base |
| `reminders` | mismo contenedor que backend | Recordatorios cada 15 min (adaptador simulado) |
| `db`, `redis` | PostgreSQL 16, Redis 7 | Sin puertos publicados |
| `backup`, `monitor` | solo en `docker-compose.prod.yml` | Respaldo diario en `./backups`; Uptime Kuma en `127.0.0.1:3001` |

Archivos de Compose: `docker-compose.yml` (base/dev) + `docker-compose.prod.yml` (producción) + `docker-compose.funnel.yml` (servidor casero con Tailscale Funnel).

## Despliegue en el servidor casero (Tailscale Funnel)

Guía completa: **`docs/despliegue/tailscale-funnel.md`**. El camino normal es:

1. Verificar requisitos (Docker, Compose ≥ 2.24, Tailscale conectado). Si falta algo, decir qué y cómo instalarlo; instalar paquetes del sistema **solo con la confirmación del usuario**.
2. Preguntar al usuario, antes de levantar:
   - ¿Datos de demostración (`SEED_DEMO=1`, accesibles por cualquiera en internet) o clínica real vacía (`SEED_DEMO=0`, por defecto)?
   - Si es clínica real: nombre de la clínica y número de sillones/consultorios.
3. Ejecutar `./scripts/desplegar-funnel.sh`. Es idempotente; para cambiar `SEED_DEMO`, editar `.env.funnel` y volver a ejecutarlo.
4. Si es clínica real, crear la clínica con `nueva_clinica` y pedir al usuario que ejecute él mismo `manage.py usuario ... admin` (la contraseña se teclea de forma interactiva; sugerirle anteponer `!` en el prompt).
5. Entregar al usuario la URL pública que imprime el script y verificar `GET <url>/api/health/` y `GET <url>/pay/health`. En la agenda debe verse el indicador «En vivo» (WebSocket a través de Funnel).

## Reglas para operar el servidor

- **Nunca** mostrar, copiar a la conversación ni versionar el contenido de `.env.funnel` (secretos). Ya está en `.gitignore`.
- **Nunca** ejecutar `docker compose down -v`, borrar volúmenes, `./backups` ni `docker system prune -a` sin confirmación explícita: se pierden los datos clínicos.
- En este servidor pueden correr **otras aplicaciones** (por ejemplo Tienda-ReactGo con su propio Funnel o túnel). No detener contenedores ni cambiar la configuración de Funnel o `tailscale serve` de otras apps. El script solo agrega su propio puerto, sin `reset`.
- No modificar el código de la aplicación para "arreglar" un despliegue sin avisar: diagnosticar con `docker compose ... logs` y proponer el cambio.
- Publicar con Funnel expone el sistema a internet: el usuario ya lo pidió, pero si se activa `SEED_DEMO=1`, recordárselo.
- Comando base: `C="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.funnel.yml --env-file .env.funnel"`.

## Desarrollo y pruebas (en la máquina de desarrollo)

- Backend: `cd backend && python manage.py test` (36 tests).
- Servicio Go: `sh scripts/test-payments.sh` (con el stack de desarrollo levantado).
- Aceptación: `python tests/uat.py [url]`.
- Carga: `python tests/load.py [url] 150 90`.
- Navegadores: `cd tests/e2e && npx playwright test`.
- El CI (`.github/workflows/ci.yml`) corre todo en cada push.
- Integraciones externas (SRI, pasarela, WhatsApp/SMS, firma con certificado) están **simuladas**; ver la tabla en el README.
