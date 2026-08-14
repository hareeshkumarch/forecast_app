#!/bin/bash
# EC2 user-data: bring a bare Amazon Linux 2023 instance up as the API host.
#
# Paste this into "Advanced details → User data" when launching the instance.
# It runs once, as root, on first boot. Everything in it is idempotent, so
# re-running it by hand after an edit is safe.
#
# What it leaves behind:
#   /opt/forecast              the checkout
#   /opt/forecast/.env         the secrets, generated here, never in git
#   /opt/forecast/storage      uploads, Parquet and exports, on the root EBS volume
#   a systemd unit that starts compose on boot and restarts it on failure
#
# It does NOT open any port to the world. The security group does that, and it
# should allow :80 from CloudFront only — see runbook.md step 5.
set -euxo pipefail

REPO_URL="${REPO_URL:-https://github.com/hareeshkumarch/forecast_app.git}"
REPO_REF="${REPO_REF:-main}"
APP_DIR=/opt/forecast

# ---- packages -------------------------------------------------------------
dnf update -y
dnf install -y docker git

# The compose plugin is not in the AL2023 repos; install it where Docker looks.
install -d /usr/local/lib/docker/cli-plugins
curl -fsSL \
  "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

systemctl enable --now docker
usermod -aG docker ec2-user || true

# ---- swap -----------------------------------------------------------------
# 2 GB of swap on a 2 GB instance. Fitting eight candidate models across two
# processes has a peak the box cannot always meet; swap turns an OOM-kill of
# the API into a slow forecast, which is the better failure.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  # Prefer reclaiming page cache over swapping the API's working set out.
  sysctl -w vm.swappiness=10
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
fi

# ---- checkout -------------------------------------------------------------
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --depth 1 origin "$REPO_REF"
  git -C "$APP_DIR" checkout -f FETCH_HEAD
else
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$APP_DIR"
fi
mkdir -p "$APP_DIR/storage"

# ---- secrets --------------------------------------------------------------
# Written once. A rewrite would roll CREDENTIAL_SECRET_KEY, and every stored
# connector credential is encrypted with it — they would all fail to decrypt.
#
# SUPABASE_DB_URL is left blank here on purpose: a connection string with a
# password in it does not belong in user-data, which is readable from the
# instance metadata service by anything running on the box. Paste it into
# /opt/forecast/.env after first boot, or pull it from SSM Parameter Store.
if [ ! -f "$APP_DIR/.env" ]; then
  umask 077
  cat > "$APP_DIR/.env" <<EOF
# To point this at Supabase:
#   1. paste the URI from Project Settings -> Database -> Connection string
#   2. blank COMPOSE_PROFILES below, so the local Postgres stops starting
#   3. systemctl restart forecast
SUPABASE_URL=
SUPABASE_DB_URL=

# Compose reads this from ./.env by itself. 'localdb' starts the bundled
# Postgres, which is what an instance with no Supabase needs. Set it empty
# once SUPABASE_DB_URL is filled in — with Supabase as the store of record a
# local Postgres is 512 MB the fit stage would rather have.
COMPOSE_PROFILES=localdb

# Refuses the fallback rather than splitting writes. Required in production.
DATABASE_FALLBACK_ENABLED=false

CREDENTIAL_SECRET_KEY=$(openssl rand -hex 32)
FORECAST_WORKERS=2
RUN_SEED_ON_STARTUP=false
LOG_LEVEL=INFO

# Only read under the \`localdb\` compose profile.
POSTGRES_USER=forecasting
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_DB=forecasting
EOF
fi

# ---- service --------------------------------------------------------------
cat > /etc/systemd/system/forecast.service <<'EOF'
[Unit]
Description=Forecasting Platform API
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/forecast
EnvironmentFile=/opt/forecast/.env
# Building ~1 GB of scientific wheels on a 2-vCPU box is slow but happens
# once; --wait holds the unit open until the healthcheck passes.
ExecStart=/usr/bin/docker compose -f deploy/aws/docker-compose.prod.yml up -d --build --wait
ExecStop=/usr/bin/docker compose -f deploy/aws/docker-compose.prod.yml down
TimeoutStartSec=1800

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now forecast.service

# ---- housekeeping ---------------------------------------------------------
# Old build layers are the only thing on this box that grows without bound.
cat > /etc/cron.weekly/docker-prune <<'EOF'
#!/bin/sh
/usr/bin/docker image prune -af --filter "until=168h"
/usr/bin/docker builder prune -af --filter "until=168h"
EOF
chmod +x /etc/cron.weekly/docker-prune
