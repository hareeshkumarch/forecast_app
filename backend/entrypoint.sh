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
# One uvicorn process, deliberately. Live progress is held in memory by the
# process that runs the forecast, and a browser watching /events is attached to
# whichever process accepted that connection. Add --workers and the two stop
# being the same process for most requests: the stream would sit at whatever
# the database last recorded and fill in only at the checkpoints.
#
# Concurrency comes from FORECAST_WORKERS instead, which is the process pool
# that does the fitting — those workers report back over a pipe this process
# reads (see ExecutorRegistry.start_relay). Scaling past one API process needs
# the Celery + Redis path, where progress travels over the broker.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
