#!/usr/bin/env bash
# Despliega Odonto DM en un servidor casero (Ubuntu/Debian) y lo publica con Tailscale Funnel.
# Idempotente: se puede volver a ejecutar para actualizar (git pull + este script).
# Guía: docs/despliegue/tailscale-funnel.md
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=.env.funnel
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.funnel.yml --env-file $ENV_FILE"
paso() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
falla() { printf '\033[31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }
valor() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }
fijar() { if grep -qE "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi; }
ts() { tailscale "$@" 2>/dev/null || sudo tailscale "$@"; }  # sin operador configurado, tailscale pide sudo

paso "1. Requisitos"
command -v docker >/dev/null || falla "Falta Docker → curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker \$USER && newgrp docker"
docker info >/dev/null 2>&1 || falla "Este usuario no puede usar Docker (servicio detenido o falta 'newgrp docker')"
compose_v=$(docker compose version --short 2>/dev/null | sed 's/^v//') || falla "Falta el plugin 'docker compose'"
printf '2.24\n%s\n' "$compose_v" | sort -V -C || falla "Docker Compose $compose_v: se necesita 2.24 o superior (usa '!override')"
command -v tailscale >/dev/null || falla "Falta Tailscale → curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
ts status >/dev/null || falla "Tailscale no está conectado → sudo tailscale up"
for bin in openssl python3 curl ss; do command -v "$bin" >/dev/null || falla "Falta '$bin'"; done
echo "Docker $(docker version --format '{{.Server.Version}}'), Compose $compose_v, Tailscale $(tailscale version | head -1)"

paso "2. Configuración ($ENV_FILE)"
if [ ! -f "$ENV_FILE" ]; then
  cp .env.funnel.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  fijar SECRET_KEY "$(openssl rand -hex 32)"
  fijar POSTGRES_PASSWORD "$(openssl rand -hex 16)"
  echo "Creado $ENV_FILE con secretos nuevos (permisos 600)."
fi
host=$(ts status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
[ -n "$host" ] || falla "No se pudo leer el nombre .ts.net de esta máquina (¿MagicDNS desactivado en la tailnet?)"
fijar SITE_ADDRESS "$host"

# puerto local libre para Caddy (solo 127.0.0.1); se respeta el de una ejecución anterior
http_port=$(valor HTTP_PORT)
if ! $C ps --status running caddy 2>/dev/null | grep -q caddy && ss -ltn "( sport = :$http_port )" | grep -q LISTEN; then
  for p in $(seq 8090 8199); do ss -ltn "( sport = :$p )" | grep -q LISTEN || { http_port=$p; break; }; done
  fijar HTTP_PORT "$http_port"
fi

# puerto público de Funnel: 443, 8443 o 10000, el primero que no use otra app de esta máquina
funnel_port=$(valor FUNNEL_PORT)
usados=$(ts funnel status --json | python3 -c '
import json, sys
cfg = json.load(sys.stdin) or {}
print(" ".join(k.rsplit(":", 1)[1] for k in (cfg.get("AllowFunnel") or {})))' 2>/dev/null || true)
if echo " $usados " | grep -q " $funnel_port " && ! ts funnel status 2>/dev/null | grep -q "127.0.0.1:$http_port"; then
  for p in 443 8443 10000; do echo " $usados " | grep -q " $p " || { funnel_port=$p; break; }; done
  echo " $usados " | grep -q " $funnel_port " && falla "Los tres puertos de Funnel (443, 8443, 10000) ya están en uso"
  fijar FUNNEL_PORT "$funnel_port"
fi
echo "Host: $host · Caddy en 127.0.0.1:$http_port · Funnel en el puerto público $funnel_port · datos demo: $(valor SEED_DEMO)"

paso "3. Construir y levantar (la primera vez tarda varios minutos)"
$C up -d --build --remove-orphans
for i in $(seq 1 90); do
  curl -sf "http://127.0.0.1:$http_port/api/health/" >/dev/null && curl -sf "http://127.0.0.1:$http_port/pay/health" >/dev/null && break
  [ "$i" = 90 ] && { $C ps; $C logs --tail 50 backend payments caddy; falla "El sistema no respondió sano en 3 minutos"; }
  sleep 2
done
$C ps --format 'table {{.Service}}\t{{.Status}}'

paso "4. Publicar con Tailscale Funnel"
ts funnel --bg --https="$funnel_port" "http://127.0.0.1:$http_port" \
  || falla "Funnel rechazado: actívalo para esta máquina en la consola de Tailscale (el mensaje anterior trae el enlace)"
url="https://$host$([ "$funnel_port" = 443 ] || echo ":$funnel_port")"

paso "5. Verificación pública"
for i in $(seq 1 30); do curl -sf "$url/api/health/" >/dev/null && break; sleep 2; done
curl -sf "$url/api/health/" >/dev/null && echo "OK: $url responde" || echo "AVISO: $url aún no responde (el certificado puede tardar 1-2 minutos la primera vez)"

clinicas=$($C exec -T backend python manage.py shell -c "from clinica.models import Clinic; print(Clinic.objects.count())" | tail -1)
paso "Listo → $url"
if [ "$clinicas" = 0 ]; then
  cat <<EOF
Falta dar de alta la clínica y su primer administrador (la contraseña se pide por teclado):
  $C exec backend python manage.py nueva_clinica "Nombre de la clínica" --sillones 2
  $C exec backend python manage.py usuario "Nombre de la clínica" admin.ti admin --nombre Nombre --apellido Apellido
El resto de usuarios se crea desde la pantalla Usuarios. En el primer ingreso cada uno activa la verificación en dos pasos.
EOF
fi
