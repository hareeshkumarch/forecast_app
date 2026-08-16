#!/usr/bin/env bash
# Pull the latest backend onto the instance, rebuild, and prove it came up.
#
# Run it on the box, over Session Manager:
#
#   aws ssm start-session --target <instance-id>
#   sudo /opt/forecast/deploy/aws/update-backend.sh
#
# or without a shell, in one call:
#
#   aws ssm send-command \
#     --instance-ids <instance-id> \
#     --document-name AWS-RunShellScript \
#     --parameters 'commands=["sudo FORCE=1 /opt/forecast/deploy/aws/update-backend.sh"]' \
#     --query 'Command.CommandId' --output text
#
# FORCE=1 there because send-command has no terminal to answer the in-flight
# prompt below. Without it the script refuses rather than guessing, which is
# the right default for an unattended run but does mean it stops.
#
# The manual equivalent is three commands (see runbook.md, "Redeploying").
# This exists for the fourth thing those three do not do: check that what came
# back up is what you meant to deploy. A rebuild that quietly drops a model
# looks exactly like a rebuild that worked — that is how Prophet went missing
# in the first place.
#
# Safe to re-run. It changes nothing until the fetch succeeds.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/forecast}"
REPO_REF="${REPO_REF:-main}"
COMPOSE_FILE="deploy/aws/docker-compose.prod.yml"
HEALTH_URL="${HEALTH_URL:-http://localhost/api/health}"
# The build installs ~1 GB of wheels on 2 vCPUs. It is slow, and it is once.
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-900}"

if [ "$(id -u)" -ne 0 ]; then
  echo "This needs root (docker, systemctl). Re-run with sudo." >&2
  exit 1
fi

cd "$APP_DIR"

echo "==> fetching $REPO_REF"
before=$(git rev-parse HEAD)
git fetch --depth 1 origin "$REPO_REF"
git checkout -f FETCH_HEAD
after=$(git rev-parse HEAD)

if [ "$before" = "$after" ]; then
  echo "    already at $after — rebuilding anyway, in case the image is older"
else
  echo "    $before -> $after"
  git --no-pager log --oneline -1 "$after" | sed 's/^/    /'
fi

# In-flight runs do not survive this. Without a Celery broker the executor has
# no durable queue, so reap_orphaned_runs fails them on the way back up with
# "The service restarted before this run finished" — clean and retryable, but
# somebody is watching a progress bar that is about to stop.
running=$(curl -fsS "$HEALTH_URL" 2>/dev/null \
  | sed -n 's/.*"running_forecast_runs":[[:space:]]*\([0-9]*\).*/\1/p' || true)
if [ -n "${running:-}" ] && [ "$running" -gt 0 ]; then
  echo "!!  $running forecast run(s) are in flight and will be failed by the restart."
  echo "    Ctrl-C now, or set FORCE=1 to go ahead."
  [ "${FORCE:-0}" = "1" ] || read -r -p "    Continue? [y/N] " reply
  case "${reply:-${FORCE:+y}}" in [yY]*) ;; *) echo "    stopped."; exit 1 ;; esac
fi

echo "==> rebuilding and restarting"
# Through systemd rather than compose directly, so the unit's view of the
# service stays true and a reboot brings back what is running now.
systemctl restart forecast.service

echo "==> waiting for health (up to ${HEALTH_TIMEOUT_SECONDS}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_SECONDS ))
health=""
until health=$(curl -fsS "$HEALTH_URL" 2>/dev/null) && [ -n "$health" ]; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "!!  never became healthy. Logs:" >&2
    journalctl -u forecast.service -n 40 --no-pager >&2 || true
    docker compose -f "$COMPOSE_FILE" logs --tail 40 backend >&2 || true
    exit 1
  fi
  sleep 5
done

echo "==> up"
echo "$health" | tr ',' '\n' | grep -E '"(status|database_target|unavailable_models)"' | sed 's/^/    /'

# The check this script exists for. An empty list is a complete roster; a
# populated one means the image built without a model it was supposed to have,
# and the reason is in the backend log rather than in this response — it is
# deliberately not served to browsers.
case "$health" in
  *'"unavailable_models":[]'*)
    echo "==> all models available, Prophet included"
    ;;
  *)
    echo "!!  some models are unavailable on this deployment:" >&2
    echo "$health" | tr ',' '\n' | grep -A2 unavailable_models | sed 's/^/    /' >&2
    echo "    why:" >&2
    docker compose -f "$COMPOSE_FILE" logs backend 2>/dev/null \
      | grep -i "is unavailable" | tail -3 | sed 's/^/    /' >&2 || true
    echo "    Full per-model detail: curl -s $HEALTH_URL/capabilities" >&2
    exit 1
    ;;
esac
