#!/usr/bin/env bash
# Production start command for Render (and similar PaaS hosts).
set -euo pipefail

PORT="${PORT:-10000}"
HOST="${HOST:-0.0.0.0}"

# Apply database migrations when a database is configured (CATALOG_SOURCE=db).
if [ -n "${DATABASE_URL:-}" ]; then
  python -m alembic upgrade head
  # First boot only: seed products from catalog.json (never overwrites an existing database).
  python -m app.db.catalog_repo --if-empty
fi

exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
