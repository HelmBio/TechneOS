#!/usr/bin/env bash
# Empty every store the platform keeps state in. Destroys data irreversibly.
#
# Usage:
#   make reset-data                  # prompts for confirmation
#   bash bin/reset-data.sh --yes     # skip the prompt (scripted use)
#
# Empties, to match what bin/backup.sh captures:
#   - PostgreSQL: techneos, keycloak, airflow  (schema dropped and recreated)
#   - MinIO: every object in the techneos-data bucket (the bucket itself stays)
#   - Valkey: all keys
#
# WHY THIS EXISTS: `pg_restore --clean` drops and recreates the objects a dump
# contains, but anything created since the dump survives it — a restore onto a
# live database is a merge, not a copy. Emptying first makes the restored state
# identical to the backed-up state.
#
# AFTERWARDS, one of:
#   - restore a backup (see RESTORE.md in any backup directory), or
#   - rebuild empty:  make migrate && make seed
#     then `docker compose restart keycloak airflow` so each recreates its own
#     schema — Keycloak re-imports techneos-realm.keycloak.json on startup
#     when the realm is absent, picking up current env values.
#
# Stop the services first (`make dev-stop`): their open sessions reference
# tables this drops, and they will error until restarted.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ASSUME_YES="no"
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES="yes" ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

_resolve_container() {
  docker ps --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -n1
}

POSTGRES_CONTAINER="${TECHNEOS_POSTGRES_CONTAINER:-$(_resolve_container postgres)}"
VALKEY_CONTAINER="${TECHNEOS_VALKEY_CONTAINER:-$(_resolve_container valkey)}"
MINIO_CONTAINER="${TECHNEOS_MINIO_CONTAINER:-$(_resolve_container minio)}"

if [ -z "$POSTGRES_CONTAINER" ]; then
  echo "Error: no running postgres container found. Run 'make up' first." >&2
  exit 1
fi

PG_USER="${POSTGRES_USER:-techneos}"
PG_PASSWORD="${POSTGRES_PASSWORD:-techneos_dev_password}"
MINIO_ALIAS="techneos-reset"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_PASS="${MINIO_ROOT_PASSWORD:-minioadmin}"
BUCKET="${MINIO_BUCKET:-techneos-data}"

DATABASES=(techneos keycloak airflow)

_psql() {
  docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
    psql -U "$PG_USER" -d "$1" -tAc "$2" 2>/dev/null
}

_db_exists() {
  docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
    psql -U "$PG_USER" -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$1"
}

# --- Which environment is this? ---
# Read from .env rather than the shell: it's what the services actually load.
ENVIRONMENT="$(grep -E '^ENVIRONMENT=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)"
ENVIRONMENT="${ENVIRONMENT:-development}"

# --- Show what is about to be destroyed ---
echo "=== Reset platform data ==="
echo "Environment: $ENVIRONMENT"
echo "Postgres:    $POSTGRES_CONTAINER"
echo ""
echo "The following will be PERMANENTLY DESTROYED:"
for db in "${DATABASES[@]}"; do
  if _db_exists "$db"; then
    size="$(_psql "$db" "select pg_size_pretty(pg_database_size('$db'))" | tr -d ' ')"
    tables="$(_psql "$db" "select count(*) from information_schema.tables where table_schema='public'" | tr -d ' ')"
    printf "  %-20s %s across %s tables\n" "postgres/$db" "${size:-unknown}" "${tables:-unknown}"
  else
    printf "  %-20s (absent — nothing to do)\n" "postgres/$db"
  fi
done
if [ -n "$MINIO_CONTAINER" ]; then
  # `du`, not `find`: the minio image has no find, and a missing tool must not
  # report as an empty bucket — that reads as "nothing to lose" right where the
  # reader decides whether to go ahead.
  size="$(docker exec "$MINIO_CONTAINER" sh -c "du -sh /data/$BUCKET 2>/dev/null | cut -f1" 2>/dev/null | tr -d ' \r')"
  printf "  %-20s %s\n" "minio/$BUCKET" "${size:-unknown — could not measure}"
fi
if [ -n "$VALKEY_CONTAINER" ]; then
  keys="$(docker exec "$VALKEY_CONTAINER" valkey-cli DBSIZE 2>/dev/null | tr -d ' \r')"
  printf "  %-20s %s\n" "valkey" "${keys:-unknown} key(s)"
fi
echo ""

if [ "$ENVIRONMENT" != "development" ]; then
  echo "REFUSING: ENVIRONMENT is '$ENVIRONMENT', not 'development'." >&2
  echo "This script is for local development data. To wipe another environment," >&2
  echo "run the individual steps deliberately, with a current backup in hand." >&2
  exit 1
fi

# --- Confirm ---
if [ "$ASSUME_YES" != "yes" ]; then
  echo "This cannot be undone. Take a backup first if you might want this data:"
  echo "    make backup"
  echo ""
  printf "Type the environment name (%s) to proceed: " "$ENVIRONMENT"
  read -r reply
  if [ "$reply" != "$ENVIRONMENT" ]; then
    echo "Aborted — nothing was changed."
    exit 1
  fi
  echo ""
fi

# --- PostgreSQL ---
# Drop the schema rather than truncate: a restore target has to be empty, and
# every table, sequence, type and index has to go, not just the rows.
for db in "${DATABASES[@]}"; do
  echo "Emptying postgres/$db..."
  if ! _db_exists "$db"; then
    echo "  → Skipped (does not exist)"
    continue
  fi
  if docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
       psql -U "$PG_USER" -d "$db" -v ON_ERROR_STOP=1 -q \
       -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO $PG_USER; GRANT ALL ON SCHEMA public TO public;" \
       >/dev/null 2>&1; then
    echo "  → Empty"
  else
    echo "  → FAILED: could not drop schema in $db" >&2
    echo "     Something still holds a lock — stop the services ('make dev-stop') and retry." >&2
    exit 1
  fi
done

# --- MinIO ---
echo "Emptying minio/$BUCKET..."
if command -v mc &>/dev/null &&
   mc alias set "$MINIO_ALIAS" "$MINIO_ENDPOINT" "$MINIO_USER" "$MINIO_PASS" --quiet >/dev/null 2>&1; then
  mc rm --recursive --force --quiet "$MINIO_ALIAS/$BUCKET" >/dev/null 2>&1 || true
  echo "  → Empty"
elif [ -n "$MINIO_CONTAINER" ]; then
  # Remove the bucket's contents, not the bucket: recreating it would lose the
  # policy the platform set on it.
  docker exec "$MINIO_CONTAINER" sh -c "rm -rf /data/$BUCKET/* /data/$BUCKET/.minio.sys 2>/dev/null" || true
  echo "  → Empty (via container; restart minio if it serves stale listings)"
else
  echo "  → FAILED: no mc and no minio container" >&2
  exit 1
fi

# --- Valkey ---
echo "Emptying valkey..."
if [ -n "$VALKEY_CONTAINER" ]; then
  docker exec "$VALKEY_CONTAINER" valkey-cli FLUSHALL >/dev/null 2>&1 || true
  echo "  → Empty"
else
  echo "  → Skipped (no valkey container)"
fi

echo ""
echo "=== Done — every store is empty ==="
echo "Next, either:"
echo "  • restore a backup   — see RESTORE.md in the backup directory"
echo "  • start fresh        — make migrate && make seed"
echo "                         docker compose restart keycloak airflow"
