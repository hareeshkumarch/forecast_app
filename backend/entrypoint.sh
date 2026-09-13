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
#
# --timeout-graceful-shutdown bounds the first half of a redeploy. Uvicorn waits
# for every open connection before it runs lifespan shutdown, and an SSE stream
# is an open connection for as long as it is held — so without a bound, one open
# dashboard tab defers the forecast drain past the SIGKILL and it never runs.
# The streams now close themselves within a second of SIGTERM; this is the
# backstop for one that does not. It is the first of four numbers that must
# agree: 10s here + SHUTDOWN_DRAIN_SECONDS (45s) fits inside the container's
# stop_grace_period (75s), which fits inside the unit's TimeoutStopSec (120s).
# Raise one and raise the rest.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10
