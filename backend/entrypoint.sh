#!/usr/bin/env bash
# Migrate, optionally seed, then serve. Kept in one place so `docker compose up`
# is genuinely the only command needed to get a working system.
#
# Given a command (as the Celery worker does) this runs it instead, without
# migrating: schema changes belong to exactly one container, and that is the
# API. Workers wait for it rather than racing it.
set -euo pipefail

if [ "$#" -gt 0 ]; then
  echo "[entrypoint] running: $*"
  exec "$@"
fi

echo "[entrypoint] running alembic migrations..."
alembic upgrade head

if [ "${RUN_SEED_ON_STARTUP:-true}" = "true" ]; then
  echo "[entrypoint] seeding database..."
  # Seeding is idempotent — it no-ops when the demo rows already exist. It exits
  # non-zero when the sample forecast fails, which is worth reporting but is not
  # worth refusing to serve over: the platform is still usable with real data.
  python -m app.database.seed || echo "[entrypoint] seed incomplete; starting anyway"
fi

echo "[entrypoint] starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
