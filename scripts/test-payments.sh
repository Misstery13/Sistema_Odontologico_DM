#!/bin/sh
# Tests de integración del servicio Go (cobros, caja) contra una base aislada `odonto_test`.
# Uso (con el stack levantado): sh scripts/test-payments.sh
set -e
docker compose exec -T db psql -U odonto -d odonto -tc "SELECT 1 FROM pg_database WHERE datname='odonto_test'" | grep -q 1 \
  || docker compose exec -T db psql -U odonto -d odonto -c "CREATE DATABASE odonto_test"
docker compose run --rm -T -e POSTGRES_DB=odonto_test backend python manage.py migrate --noinput >/dev/null
NETWORK=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$(docker compose ps -q db)")
MSYS_NO_PATHCONV=1 docker run --rm --network "$NETWORK" -v "$(cd payments && pwd -W 2>/dev/null || pwd):/src" -w /src \
  -e DATABASE_URL="postgres://odonto:${POSTGRES_PASSWORD:-odonto}@db:5432/odonto_test" -e REDIS_URL=redis://redis:6379/1 \
  golang:1.26-alpine go test -count=1 -cover -coverprofile=/tmp/c.out ./... "$@"
