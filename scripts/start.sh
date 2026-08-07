#!/usr/bin/env bash
# Production start command for Render (and similar PaaS hosts).
set -euo pipefail

PORT="${PORT:-10000}"
HOST="${HOST:-0.0.0.0}"

exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
