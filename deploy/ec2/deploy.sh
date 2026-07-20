#!/usr/bin/env bash
set -euo pipefail

# Deploy the platform to the EC2 host, over SSH — no AWS control-plane calls
# from here (this replaces an SSM RunCommand flow with plain scp + ssh).
#
#   deploy/ec2/deploy.sh                       # uses deploy/ec2/.env.prod
#   deploy/ec2/deploy.sh --env-file <path>     # or point at another env file
#
# What it does: bundle the compose stack + the files it mounts, scp the bundle
# and remote-deploy.sh to the host, then run remote-deploy.sh there. The host
# pulls the images (built + pushed separately by build-and-push.sh) and brings
# the stack up.
#
# The SSH target and the platform config both come from the one env file — the
# SSH_* keys below, and everything the platform needs. deploy.sh reads only the
# SSH_* keys (literally, not by sourcing); the rest travels to the host as-is
# and is read there by compose's --env-file.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

# The image catalog + version helpers, shared with build-and-push.sh so the tags
# we pin here match the ones it built.
source "$HERE/_image-catalog.sh"

# Defaults to the conventional deploy/ec2/.env.prod (same file
# build-and-push.sh reads); --env-file points at another one.
ENV_FILE="$HERE/.env.prod"
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    *) echo "Usage: $0 [--env-file <path>]  (default: $HERE/.env.prod)" >&2; exit 2 ;;
  esac
done
[ -f "$ENV_FILE" ] || { echo "ERROR: env file not found: $ENV_FILE" >&2
  echo "       Create it from .env.prod.example, or pass --env-file <path>." >&2; exit 1; }

# Read one var literally — never source (the file holds secrets and would run
# as shell). A <placeholder> counts as unset so the guards below fire.
_envval() {
  local v; v="$(grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  case "$v" in *"<"*) return 0 ;; esac
  printf '%s' "$v"
}

# Validate up front — this env file is shipped verbatim and read by the remote
# stack, so a missing or <placeholder> value would otherwise surface as an opaque
# failure on the host, after the bundle + ssh round-trip. A <placeholder> reads
# as unset (via _envval). And because a placeholder is a non-empty string,
# compose's own ${VAR:?} guards wouldn't catch it — this is the check that does.
# Keep this list in sync with the REQUIRED markers in .env.prod.example.
REQUIRED_VARS=(
  SSH_HOST
  IMAGE_REGISTRY
  PLATFORM_API_URL PLATFORM_PORTAL_URL CORS_ORIGINS MINIO_PUBLIC_ENDPOINT
  POSTGRES_PASSWORD JWT_SECRET_KEY INTERNAL_SERVICE_TOKEN SECRETS_ENCRYPTION_KEY
  MINIO_ROOT_PASSWORD KEYCLOAK_ADMIN_PASSWORD KEYCLOAK_CLIENT_SECRET
  AIRFLOW_PASSWORD AIRFLOW_WEBSERVER_SECRET_KEY
)
_missing=()
for _v in "${REQUIRED_VARS[@]}"; do
  [ -n "$(_envval "$_v")" ] || _missing+=("$_v")
done
if [ "${#_missing[@]}" -gt 0 ]; then
  echo "ERROR: these required variables are unset or still <placeholders> in $ENV_FILE:" >&2
  printf '  - %s\n' "${_missing[@]}" >&2
  echo "Fill them in (see $HERE/.env.prod.example) and re-run." >&2
  exit 1
fi

# Optional but consequential — notify, don't block.
[ -n "$(_envval CERTBOT_EMAIL)" ]          || echo "NOTE: CERTBOT_EMAIL unset — deploying HTTP-only; add TLS later."
[ -n "$(_envval DEFAULT_ADMIN_PASSWORD)" ] || echo "NOTE: DEFAULT_ADMIN_PASSWORD unset — seed falls back to the weak example admin creds."
[ -n "$(_envval DEFAULT_LLM_API_KEY)" ]    || echo "NOTE: DEFAULT_LLM_API_KEY unset — the built-in Platform Assistant won't be provisioned."
[ -n "$(_envval PYTHON_PACKAGE_INDEX_URL)" ] || echo "NOTE: PYTHON_PACKAGE_INDEX_URL unset — pypi tools/agents (catalog) can't be installed."

SSH_HOST="$(_envval SSH_HOST)"
SSH_USER="$(_envval SSH_USER)";   SSH_USER="${SSH_USER:-deploy}"
SSH_PORT="$(_envval SSH_PORT)";   SSH_PORT="${SSH_PORT:-22}"
SSH_KEY="$(_envval SSH_KEY_PATH)"; SSH_KEY="${SSH_KEY/#\~/$HOME}"
REMOTE_DIR="$(_envval REMOTE_DIR)"; REMOTE_DIR="${REMOTE_DIR:-/data/techneos}"

SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=accept-new)
SCP=(scp -P "$SSH_PORT" -o StrictHostKeyChecking=accept-new)
[ -n "$SSH_KEY" ] && { SSH+=(-i "$SSH_KEY"); SCP+=(-i "$SSH_KEY"); }
TARGET="$SSH_USER@$SSH_HOST"

echo "=== Deploying to $TARGET:$REMOTE_DIR ==="

# --- Build the bundle ---------------------------------------------------------
# Paths are preserved repo-relative so the compose's ../../packages/execution
# resolves the same on the host as it does here — the file tested is the file
# that runs. The filled env travels as deploy/ec2/.env (what compose
# reads); the git-tracked .env.prod.example never leaves.
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/deploy/ec2" "$STAGE/packages"

cp deploy/ec2/docker-compose.prod.yml         "$STAGE/deploy/ec2/"
cp deploy/ec2/techneos.nginx.conf.template    "$STAGE/deploy/ec2/"
cp deploy/ec2/techneos-realm.keycloak.prod.json "$STAGE/deploy/ec2/"
cp "$ENV_FILE"                                        "$STAGE/deploy/ec2/.env"
cp -R packages/execution "$STAGE/packages/execution"           # mounted by airflow
# The seed no longer travels in the bundle: it ships inside the gateway image
# (COPY migrations -> migrations/seed/) and remote-deploy.sh runs it in-container.

# Pin each image to its package version (the host has no source tree to read, so
# compose reads these from the shipped .env). An explicit <SERVICE>_IMAGE_TAG in
# the env file wins and is left untouched — that is how you roll back or hold
# back a single service (e.g. AUTH_SERVICE_IMAGE_TAG=0.1.0 while source is 0.2.0).
SHIPPED_ENV="$STAGE/deploy/ec2/.env"
echo "=== Pinning image tags from package versions ==="
for _row in "${PLATFORM_IMAGES[@]}"; do
  IFS='|' read -r _name _manifest _ _ _ <<<"$_row"
  _var="$(image_tag_var "$_name")"
  if [ -n "$(_envval "$_var")" ]; then
    echo "  $_name: $_var pinned in env file — leaving as-is"
    continue
  fi
  _version="$(pkg_version "$_manifest")"
  [ -n "$_version" ] || { echo "ERROR: no version found in $_manifest" >&2; exit 1; }
  printf '%s=%s\n' "$_var" "$_version" >> "$SHIPPED_ENV"
  echo "  $_name -> $_version"
done

BUNDLE="$STAGE/techneos-deploy-bundle.tar.gz"
# Exclude caches so the bundle is small and reproducible.
tar --exclude='__pycache__' --exclude='*.pyc' \
    -czf "$BUNDLE" -C "$STAGE" deploy packages
echo "  bundle: $(du -h "$BUNDLE" | cut -f1)"

# --- Ship + run ---------------------------------------------------------------
echo "=== Copying bundle + remote-deploy.sh to $SSH_HOST ==="
"${SCP[@]}" "$BUNDLE" "$TARGET:/tmp/techneos-deploy-bundle.tar.gz"
"${SCP[@]}" "$HERE/remote-deploy.sh" "$TARGET:/tmp/techneos-remote-deploy.sh"

echo "=== Running remote deploy on $SSH_HOST ==="
# Root for nginx/systemctl and to own /data/techneos; docker via that root.
# The deploy user needs passwordless sudo (see README).
"${SSH[@]}" "$TARGET" "sudo REMOTE_DIR='$REMOTE_DIR' bash /tmp/techneos-remote-deploy.sh"

"${SSH[@]}" "$TARGET" "rm -f /tmp/techneos-deploy-bundle.tar.gz /tmp/techneos-remote-deploy.sh" || true

# --- Register the built-in Platform Assistant ---------------------------------
# Runs HERE, on the workstation, not on the host: it drives the gateway's public
# API (login + POST) through the `management` toolkit, which only exists in this
# repo checkout — no service image ships it, so it can't run in a container on
# the host the way migrate/seed do. Doing it from deploy.sh keeps the whole
# deploy one command.
#
# register discovers the seeded LLM provider via the API and self-skips (with a
# hint) when none exists. A provider is only seeded when DEFAULT_LLM_API_KEY is
# set, so we use that here as an early-skip signal — no key, nothing to register.
API_URL="$(_envval PLATFORM_API_URL)"
LLM_KEY="$(_envval DEFAULT_LLM_API_KEY)"
if [ -z "$LLM_KEY" ]; then
  echo "=== Skipping assistant registration: DEFAULT_LLM_API_KEY not set in $ENV_FILE ==="
elif ! command -v uv >/dev/null 2>&1; then
  echo "=== Skipping assistant registration: uv not found (needed to run the management toolkit) ==="
else
  echo "=== Registering the Platform Assistant against $API_URL ==="
  ADMIN_EMAIL="$(_envval DEFAULT_ADMIN_EMAIL)";    ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
  ADMIN_PASSWORD="$(_envval DEFAULT_ADMIN_PASSWORD)"; ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme123}"
  # register reads only PLATFORM_API_URL from the environment (to resolve the
  # gateway URL); the provider and its key now live server-side, seeded
  # in-container. Our env lives at deploy/ec2/.env.prod, not the
  # deploy/.env.prod that management's own loader looks for, so hand the value
  # over directly. Read literally (never sourced): it may contain spaces or
  # shell metacharacters.
  _val="$(_envval PLATFORM_API_URL)"; [ -n "$_val" ] && export "PLATFORM_API_URL=$_val"
  uv run python setup/register_platform_assistant.py \
    --env prod --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD" \
    || echo "  WARN: assistant registration did not complete — re-run: make register-platform-assistant (pointed at prod)"
fi

echo "=== Deploy to $SSH_HOST complete ==="
