#!/usr/bin/env bash
# Deploy / update the Skooly backend on the VM.
#   ./deployment/deploy.sh
# Pulls latest backend code, (re)builds the api image, and brings up
# api + cloudflared. Idempotent — safe to re-run for every release.
set -euo pipefail

cd "$(dirname "$0")"          # → deployment/
# --env-file feeds both the ${...} interpolation in the compose file (e.g. the
# tunnel token) and is loaded by the api service's `env_file`. Compose parses
# it literally, so values with special chars are safe (no shell sourcing).
COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"

if [ ! -f .env.prod ]; then
  echo "ERROR: deployment/.env.prod not found. Copy .env.prod.example and fill it in." >&2
  exit 1
fi

echo "[deploy] pulling latest backend…"
git -C .. pull --ff-only

echo "[deploy] building + starting (migrate/collectstatic run on api start)…"
$COMPOSE up -d --build

echo "[deploy] pruning old images…"
docker image prune -f >/dev/null

echo "[deploy] status:"
$COMPOSE ps
echo "[deploy] done. Tail logs with: $COMPOSE logs -f api"
