#!/usr/bin/env bash
# The branch as production runs it, on this laptop: Postgres (its constraints included),
# the built page, the real model, Jev and hosted voice, behind a local access code. Call the
# printed link before a PR is merged. Ctrl-C stops it; the local database keeps its sessions.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "preview needs .env with the model, Jev and voice keys" >&2; exit 1; }
docker compose up -d --wait postgres >/dev/null
npm --prefix web run build >/dev/null
code="${PREVIEW_ACCESS_CODE:-preview}"
export CAFE_NORTE_DATABASE_URL="${PREVIEW_DATABASE_URL:-postgresql://cafe:cafe@localhost:5432/cafe_norte}"
export CAFE_NORTE_VOICE=pipecat
export CAFE_NORTE_ACCESS_CODE="$code"
export CAFE_NORTE_SIGNAL_MODEL="${CAFE_NORTE_SIGNAL_MODEL:-openrouter/typesafe/jev-1.14}"
echo
echo "Preview of $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD):"
echo "  http://localhost:8000/?store=chamberi_barista_v1&lang=es#code=$code"
echo
exec uv run uvicorn cafe_norte.main:create_default_app --factory --port 8000 --env-file .env
