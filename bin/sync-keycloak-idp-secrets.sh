#!/usr/bin/env bash
# bin/sync-keycloak-idp-secrets.sh — Re-sync the Google/GitHub identity
# provider client id/secret on the running Keycloak realm from the current
# environment, without touching any other data.
#
# Keycloak's realm-import env var substitution (the ${GOOGLE_CLIENT_ID} etc.
# placeholders in keycloak/techneos-realm.dev.json) only happens ONCE, when
# the realm is first created on a fresh Postgres volume. If you rotate your
# Google/GitHub OAuth app credentials afterward, the running realm keeps the
# stale values — recreating the keycloak container updates its own env vars,
# but not the identity provider config already stored in Keycloak's DB.
#
# This script does the update surgically via the Keycloak admin CLI (kcadm),
# so you don't have to `make down-v` (which wipes ALL data — users, seeded
# roles/org, everything) just to pick up new OAuth credentials.
#
# Usage:
#   bin/sync-keycloak-idp-secrets.sh
#
# Reads GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GITHUB_CLIENT_ID /
# GITHUB_CLIENT_SECRET / KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD from the
# running `keycloak` container's own environment (the same values
# docker-compose injected from .env) — always matches what Keycloak was
# actually started with, no separate .env parsing needed.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REALM="${KEYCLOAK_REALM:-techneos}"

_info() { printf "\033[36m▸\033[0m %s\n" "$*"; }
_ok()   { printf "\033[32m✓\033[0m %s\n" "$*"; }
_err()  { printf "\033[31m✗\033[0m %s\n" "$*" >&2; }

cd "$ROOT_DIR"

if ! docker compose exec -T keycloak true 2>/dev/null; then
  _err "keycloak container is not running (try: make up)"
  exit 1
fi

_container_env() {
  docker compose exec -T keycloak sh -c "echo \"\$$1\"" | tr -d '\r\n'
}

GH_ID="$(_container_env GITHUB_CLIENT_ID)"
GH_SECRET="$(_container_env GITHUB_CLIENT_SECRET)"
GOOG_ID="$(_container_env GOOGLE_CLIENT_ID)"
GOOG_SECRET="$(_container_env GOOGLE_CLIENT_SECRET)"
KC_ADMIN="$(_container_env KEYCLOAK_ADMIN)"
KC_ADMIN_PASSWORD="$(_container_env KEYCLOAK_ADMIN_PASSWORD)"

for name in GH_ID GH_SECRET GOOG_ID GOOG_SECRET KC_ADMIN KC_ADMIN_PASSWORD; do
  if [ -z "${!name}" ]; then
    _err "$name is empty in the keycloak container's environment — check .env, then 'docker compose up -d keycloak' to pick up changes, and re-run this script"
    exit 1
  fi
done

_info "Logging into the Keycloak admin CLI..."
docker compose exec -T \
  -e KC_ADMIN="$KC_ADMIN" -e KC_ADMIN_PASSWORD="$KC_ADMIN_PASSWORD" \
  -e GH_ID="$GH_ID" -e GH_SECRET="$GH_SECRET" \
  -e GOOG_ID="$GOOG_ID" -e GOOG_SECRET="$GOOG_SECRET" \
  -e REALM="$REALM" \
  keycloak sh -c '
    /opt/keycloak/bin/kcadm.sh config credentials \
      --server http://localhost:8080 --realm master \
      --user "$KC_ADMIN" --password "$KC_ADMIN_PASSWORD" &&
    /opt/keycloak/bin/kcadm.sh update identity-provider/instances/github -r "$REALM" \
      -s config.clientId="$GH_ID" -s config.clientSecret="$GH_SECRET" &&
    /opt/keycloak/bin/kcadm.sh update identity-provider/instances/google -r "$REALM" \
      -s config.clientId="$GOOG_ID" -s config.clientSecret="$GOOG_SECRET"
  '

_ok "Google and GitHub identity providers updated in the '$REALM' realm."
_info "No restart needed — try the SSO buttons on the portal's login page now."
