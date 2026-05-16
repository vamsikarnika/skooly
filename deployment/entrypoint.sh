#!/usr/bin/env bash
# Container entrypoint: wait for Postgres, migrate, seed demo (idempotent), then exec command.
set -euo pipefail

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"

echo "[entrypoint] waiting for postgres at ${DB_HOST}:${DB_PORT}…"
attempts=0
until python -c "import socket; s=socket.socket(); s.connect(('${DB_HOST}', ${DB_PORT}))" >/dev/null 2>&1; do
  attempts=$((attempts + 1))
  if [ "$attempts" -gt 30 ]; then
    echo "[entrypoint] postgres unreachable after 30 attempts — aborting" >&2
    exit 1
  fi
  sleep 1
done
echo "[entrypoint] postgres up."

echo "[entrypoint] applying migrations…"
python manage.py migrate --noinput

if [ "${SKOOLY_SEED_DEMO:-true}" = "true" ]; then
  echo "[entrypoint] seeding demo data (idempotent)…"
  python manage.py seed_demo
fi

case "$1" in
  runserver)
    echo "[entrypoint] starting Django dev server on 0.0.0.0:8000"
    exec python manage.py runserver 0.0.0.0:8000
    ;;
  gunicorn)
    echo "[entrypoint] starting gunicorn"
    exec gunicorn config.wsgi:application -b 0.0.0.0:8000 --workers 3
    ;;
  *)
    echo "[entrypoint] exec: $*"
    exec "$@"
    ;;
esac
