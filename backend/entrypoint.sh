#!/usr/bin/env bash
# Migrate, optionally seed, then serve. Kept in one place so `docker compose up`
# is genuinely the only command needed to get a working system.
set -euo pipefail

echo "[entrypoint] running alembic migrations..."
alembic upgrade head

if [ "${RUN_SEED_ON_STARTUP:-true}" = "true" ]; then
  echo "[entrypoint] seeding database..."
  # Seeding is idempotent — it no-ops when the demo rows already exist.
  python -m app.database.seed
fi

echo "[entrypoint] starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
