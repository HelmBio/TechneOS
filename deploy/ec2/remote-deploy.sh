#!/usr/bin/env bash
set -euo pipefail

# Runs ON the host, as root, invoked by deploy.sh over SSH. Brings the stack up
# from the bundle in /tmp: extract, authenticate to the registry, configure the
# nginx edge (+ TLS), pull, start, migrate, seed.
#
# Prerequisites on the host (see deploy/ec2/README.md):
#   docker + compose plugin · nginx · certbot (certbot-nginx not required) ·
#   aws CLI + an instance IAM role that can pull from ECR and read CodeArtifact.

REMOTE_DIR="${REMOTE_DIR:-/data/techneos}"
BUNDLE="/tmp/techneos-deploy-bundle.tar.gz"
COMPOSE_DIR="$REMOTE_DIR/deploy/ec2"
COMPOSE="$COMPOSE_DIR/docker-compose.prod.yml"
ENV_FILE="$COMPOSE_DIR/.env"
DC=(docker compose -f "$COMPOSE" --env-file "$ENV_FILE")

# Isolate the Docker config for this deploy so ECR auth doesn't fight whatever
# credential helper the host has globally configured — a helper's unsupported
# "store" op otherwise breaks `docker login`, leaving the pull unauthenticated
# (403). docker and compose both honor DOCKER_CONFIG, so the login below and the
# pull share this clean, helper-free config. The Airflow worker's runtime ECR
# auth is separate (core: execution/backends/ecr_auth) and unaffected.
export DOCKER_CONFIG; DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$DOCKER_CONFIG"' EXIT

[ -f "$BUNDLE" ] || { echo "ERROR: bundle not found at $BUNDLE" >&2; exit 1; }

_envval() {  # read a var from the deployed .env, literally
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true
}
_host_of() { echo "${1#*://}" | cut -d/ -f1; }  # strip scheme + path → bare host

# --- Extract ------------------------------------------------------------------
echo "=== Extracting bundle into $REMOTE_DIR ==="
mkdir -p "$REMOTE_DIR"
# Data dirs the compose bind-mounts (postgres/minio/valkey) — a bind volume
# fails to mount if its device path doesn't exist yet, so create them here.
# These paths must match the compose's `device:` lines verbatim, so they're
# the literal /data/techneos/* the compose names, not $REMOTE_DIR-relative.
# Creating them is a no-op when they already hold data, so re-deploys are safe.
mkdir -p /data/techneos/postgres /data/techneos/minio /data/techneos/valkey
# Replace the code we ship wholesale; leave the data dirs above untouched.
rm -rf "$REMOTE_DIR/deploy" "$REMOTE_DIR/packages" "$REMOTE_DIR/setup"
tar xzf "$BUNDLE" -C "$REMOTE_DIR"
chmod 600 "$ENV_FILE"

# The docker group gid is host-specific (differs across EC2 AMIs), and the
# airflow-scheduler adds it via group_add so its uid-50000 user can reach the
# mounted docker socket to launch tool containers. Detect it on the host and
# upsert it into the env file — never bake a host-specific value into the
# templated .env. Re-derived every deploy, so a new instance just works.
DOCKER_GID="$(getent group docker | cut -d: -f3 || true)"
if [ -n "$DOCKER_GID" ]; then
  if grep -q '^DOCKER_GID=' "$ENV_FILE"; then
    sed -i "s/^DOCKER_GID=.*/DOCKER_GID=$DOCKER_GID/" "$ENV_FILE"
  else
    echo "DOCKER_GID=$DOCKER_GID" >> "$ENV_FILE"
  fi
  echo "=== Host docker group gid = $DOCKER_GID (airflow-scheduler group_add) ==="
else
  echo "WARN: no 'docker' group on host — airflow-scheduler will be denied the socket" >&2
fi

DOCKER_IMAGE_REGISTRY="$(_envval DOCKER_IMAGE_REGISTRY)"
AWS_REGION="$(_envval AWS_REGION)"; AWS_REGION="${AWS_REGION:-us-east-1}"
API_HOST="$(_host_of "$(_envval PLATFORM_API_URL)")"
PORTAL_HOST="$(_host_of "$(_envval PLATFORM_PORTAL_URL)")"
MINIO_BUCKET="$(_envval MINIO_BUCKET)"; MINIO_BUCKET="${MINIO_BUCKET:-techneos-data}"
CERTBOT_EMAIL="$(_envval CERTBOT_EMAIL)"

# The airflow worker (uid 50000) writes per-step work dirs into the shared-inputs
# bind mount, so the host dir it maps to must exist and be owned by that uid —
# another host-specific setup step that belongs here, not in a manual runbook.
SHARED_INPUT_DIR="$(_envval TECHNEOS_HOST_SHARED_INPUT_DIR)"
SHARED_INPUT_DIR="${SHARED_INPUT_DIR:-/data/techneos/airflow-inputs}"
mkdir -p "$SHARED_INPUT_DIR"
chown -R 50000:0 "$SHARED_INPUT_DIR"

# --- Registry auth ------------------------------------------------------------
# Only for ECR. With the isolated DOCKER_CONFIG above, `docker login` stores the
# token in a clean plaintext config (no host credential helper to break its
# "store" step), and the pull below reuses it. A non-ECR registry is assumed
# already logged in.
if [[ "$DOCKER_IMAGE_REGISTRY" == *.dkr.ecr.*.amazonaws.com* ]]; then
  echo "=== Logging into ECR ==="
  if ! aws ecr get-login-password --region "$AWS_REGION" \
       | docker login --username AWS --password-stdin "$DOCKER_IMAGE_REGISTRY"; then
    echo "ERROR: could not authenticate to ECR ($DOCKER_IMAGE_REGISTRY)." >&2
    echo "  The instance IAM role needs ecr:GetAuthorizationToken in $AWS_REGION," >&2
    echo "  and the pull needs ecr:BatchGetImage + ecr:GetDownloadUrlForLayer on the repos." >&2
    exit 1
  fi
fi

# --- nginx edge + TLS ---------------------------------------------------------
# Best-effort: a missing nginx/certbot warns and skips rather than aborting the
# whole deploy — the stack below still comes up (reachable on 127.0.0.1).
if command -v nginx >/dev/null 2>&1; then
  echo "=== Configuring nginx edge ==="
  CERT_NAME="$API_HOST"
  mkdir -p /var/www/certbot
  RENDERED=/etc/nginx/sites-available/techneos

  if [ ! -d "/etc/letsencrypt/live/$CERT_NAME" ]; then
    # No cert yet: stand up an http-only config so certbot can answer the ACME
    # challenge over :80, obtain the cert, then install the full :443 config.
    # (The full template's 443 blocks would fail nginx -t without the cert.)
    echo "  No cert for $CERT_NAME — bootstrapping over HTTP first"
    cat > "$RENDERED" <<NGINX
server {
    listen 80;
    server_name $API_HOST $PORTAL_HOST;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 200 'techneos: awaiting TLS'; add_header Content-Type text/plain; }
}
NGINX
    ln -sf "$RENDERED" /etc/nginx/sites-enabled/techneos
    nginx -t && systemctl reload nginx
    if command -v certbot >/dev/null 2>&1 && [ -n "$CERTBOT_EMAIL" ]; then
      certbot certonly --webroot -w /var/www/certbot \
        -d "$API_HOST" -d "$PORTAL_HOST" \
        --non-interactive --agree-tos -m "$CERTBOT_EMAIL" || echo "  WARN: certbot failed — leaving HTTP-only"
    else
      echo "  WARN: certbot or CERTBOT_EMAIL missing — leaving HTTP-only; obtain a cert then re-run"
    fi
  fi

  if [ -d "/etc/letsencrypt/live/$CERT_NAME" ]; then
    echo "  Installing full TLS config"
    PORTAL_HOST="$PORTAL_HOST" API_HOST="$API_HOST" MINIO_BUCKET="$MINIO_BUCKET" CERT_NAME="$CERT_NAME" \
      envsubst '${PORTAL_HOST} ${API_HOST} ${MINIO_BUCKET} ${CERT_NAME}' \
      < "$COMPOSE_DIR/techneos.nginx.conf.template" > "$RENDERED"
    ln -sf "$RENDERED" /etc/nginx/sites-enabled/techneos
    nginx -t && systemctl reload nginx
  fi
else
  echo "=== nginx not installed — skipping edge config (stack still binds 127.0.0.1) ==="
fi

# --- Bring the stack up -------------------------------------------------------
echo "=== Pulling images ==="
# Dangling only (-f, not -af): reclaim orphaned layers from previous pulls/builds
# without deleting other projects' tagged images. `-af` would remove any image no
# running container references — which, if another deployment on this host is
# stopped, is all of its images. To reclaim a superseded deployment's images,
# prune deliberately once it's decommissioned: docker image prune -af
docker image prune -f >/dev/null 2>&1 || true
"${DC[@]}" pull

echo "=== Starting services ==="
"${DC[@]}" up -d --remove-orphans
"${DC[@]}" restart airflow-scheduler >/dev/null 2>&1 || true  # re-read mounted DAGs

echo "=== Waiting for postgres ==="
for _ in $(seq 1 30); do
  "${DC[@]}" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1 && break
  sleep 2
done

# --- Schema + seed ------------------------------------------------------------
# Both ship inside the gateway image: migrations (COPY alembic.ini + migrations/)
# and the seed, which lives at migrations/seed/. So both run in-container, with
# `core` and the DEFAULT_*/SECRETS_ENCRYPTION_KEY env (from compose) available —
# no docker cp. seed.py is idempotent (add-if-absent / upsert), so running it on
# every deploy is safe.
echo "=== Applying migrations ==="
"${DC[@]}" exec -T gateway uv run alembic upgrade head

echo "=== Seeding roles / org / admin / LLM provider (idempotent) ==="
"${DC[@]}" exec -T gateway uv run python migrations/seed/seed.py || echo "  WARN: seed reported an error"

# --- Report -------------------------------------------------------------------
echo "=== Service status ==="
"${DC[@]}" ps
echo ""
echo "=== Deploy complete ==="
echo "Next, from your workstation (goes through the public API, needs DEFAULT_LLM_API_KEY):"
echo "  make register-platform-assistant   # register the built-in assistant + its LLM provider"
