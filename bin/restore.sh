#!/usr/bin/env bash
# Restore every store from a backup directory made by bin/backup.sh.
#
# Usage:
#   make restore dir=./backups/20260716_150417
#   bash bin/restore.sh ./backups/20260716_150417 --yes
#
# Restores whatever the backup contains, skipping what it doesn't:
#   - PostgreSQL: techneos, keycloak, airflow
#   - MinIO: the techneos-data bucket
#   - Valkey: the RDB snapshot
#
# Prerequisites it handles for you:
#   - creates any target database that doesn't exist yet (a fresh volume has
#     only `techneos`; keycloak and airflow are created by their own services)
#   - stops valkey before replacing its RDB, and starts it after
#   - restarts minio, keycloak and airflow so they read what was restored
#
# Prerequisite it will not do for you: stopping the app services. They hold
# open sessions against tables this replaces, so restore refuses while they
# are up — run `make dev-stop` first.
#
# NOTE: `pg_restore --clean` replaces the objects this backup contains and
# leaves anything created since, so a restore onto a live database merges
# rather than copies. For an exact copy of the backed-up state, run
# `make reset-data` first.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BACKUP_DIR=""
ASSUME_YES="no"
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES="yes" ;;
    -*) echo "Unknown option: $arg" >&2; exit 2 ;;
    *) BACKUP_DIR="$arg" ;;
  esac
done

if [ -z "$BACKUP_DIR" ]; then
  echo "Usage: bin/restore.sh <backup-dir> [--yes]" >&2
  echo "" >&2
  echo "Available backups:" >&2
  ls -1d ./backups/*/ 2>/dev/null | sed 's/^/  /' >&2 || echo "  (none in ./backups/)" >&2
  exit 2
fi

BACKUP_DIR="${BACKUP_DIR%/}"
if [ ! -d "$BACKUP_DIR" ]; then
  echo "Error: no such backup directory: $BACKUP_DIR" >&2
  exit 1
fi

_resolve_container() {
  docker ps -a --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -n1
}

POSTGRES_CONTAINER="${TECHNEOS_POSTGRES_CONTAINER:-$(_resolve_container postgres)}"
VALKEY_CONTAINER="${TECHNEOS_VALKEY_CONTAINER:-$(_resolve_container valkey)}"
MINIO_CONTAINER="${TECHNEOS_MINIO_CONTAINER:-$(_resolve_container minio)}"

if [ -z "$POSTGRES_CONTAINER" ]; then
  echo "Error: no postgres container found. Run 'make up' first." >&2
  exit 1
fi

PG_USER="${POSTGRES_USER:-techneos}"
PG_PASSWORD="${POSTGRES_PASSWORD:-techneos_dev_password}"
BUCKET="${MINIO_BUCKET:-techneos-data}"
DATABASES=(techneos keycloak airflow)

FAILED=()

_db_exists() {
  docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
    psql -U "$PG_USER" -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$1"
}

# --- What does this backup hold? ---
present=()
for db in "${DATABASES[@]}"; do
  [ -f "$BACKUP_DIR/$db.dump" ] && present+=("postgres/$db")
done
[ -d "$BACKUP_DIR/minio/$BUCKET" ] && present+=("minio/$BUCKET")
[ -f "$BACKUP_DIR/valkey.rdb" ] && present+=("valkey")

if [ ${#present[@]} -eq 0 ]; then
  echo "Error: $BACKUP_DIR holds nothing this script recognises." >&2
  echo "Expected some of: techneos.dump, keycloak.dump, airflow.dump, minio/, valkey.rdb" >&2
  exit 1
fi

ENVIRONMENT="$(grep -E '^ENVIRONMENT=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)"
ENVIRONMENT="${ENVIRONMENT:-development}"

echo "=== Restore platform data ==="
echo "From:        $BACKUP_DIR"
[ -f "$BACKUP_DIR/RESTORE.md" ] &&
  echo "Taken:       $(grep -m1 'Backup created' "$BACKUP_DIR/RESTORE.md" | sed 's/.*:\*\* //')"
echo "Environment: $ENVIRONMENT"
echo ""
echo "Will restore, overwriting what is there now:"
for p in "${present[@]}"; do echo "  $p"; done
echo ""

if [ "$ENVIRONMENT" != "development" ]; then
  echo "REFUSING: ENVIRONMENT is '$ENVIRONMENT', not 'development'." >&2
  echo "Restore the individual components deliberately instead — see RESTORE.md." >&2
  exit 1
fi

# --- Prerequisite: the app services must not be holding sessions open ---
# pg_restore --clean drops each object before recreating it, which a live
# session blocks. Better to say so now than to fail halfway through.
busy_ports=()
for port in 8000 8001 8002 8003 8004 8005 8006 8007 8008; do
  if lsof -ti tcp:"$port" -sTCP:LISTEN >/dev/null 2>&1; then busy_ports+=("$port"); fi
done
if [ ${#busy_ports[@]} -gt 0 ]; then
  echo "REFUSING: platform services are running (ports: ${busy_ports[*]})." >&2
  echo "They hold open sessions against the tables this replaces." >&2
  echo "Stop them first:  make dev-stop" >&2
  exit 1
fi

if [ "$ASSUME_YES" != "yes" ]; then
  printf "Type the environment name (%s) to proceed: " "$ENVIRONMENT"
  read -r reply
  if [ "$reply" != "$ENVIRONMENT" ]; then
    echo "Aborted — nothing was changed."
    exit 1
  fi
  echo ""
fi

# --- PostgreSQL ---
for db in "${DATABASES[@]}"; do
  [ -f "$BACKUP_DIR/$db.dump" ] || continue
  echo "Restoring postgres/$db..."

  # Prerequisite: pg_restore needs the database to exist. On a fresh volume
  # only `techneos` does — keycloak and airflow are created by their own
  # services' init, which hasn't run yet.
  if ! _db_exists "$db"; then
    if docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
         psql -U "$PG_USER" -d postgres -q -c "CREATE DATABASE $db" >/dev/null 2>&1; then
      echo "  · created database $db (did not exist)"
    else
      echo "  → FAILED: $db does not exist and could not be created" >&2
      FAILED+=("postgres:$db")
      continue
    fi
  fi

  if docker exec -i -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
       pg_restore -U "$PG_USER" -d "$db" --clean --if-exists --no-owner \
       < "$BACKUP_DIR/$db.dump" >/dev/null 2>/tmp/.restore_err_$$; then
    echo "  → Restored"
  else
    # pg_restore exits non-zero for benign noise too (an object the dump drops
    # that was never there). Only a genuine error should count as a failure.
    if grep -qiE "error:" /tmp/.restore_err_$$; then
      echo "  → FAILED: pg_restore reported errors" >&2
      grep -iE "error:" /tmp/.restore_err_$$ | head -3 | sed 's/^/       /' >&2
      FAILED+=("postgres:$db")
    else
      echo "  → Restored (with warnings)"
    fi
  fi
  rm -f /tmp/.restore_err_$$
done

# --- MinIO ---
if [ -d "$BACKUP_DIR/minio/$BUCKET" ]; then
  echo "Restoring minio/$BUCKET..."
  if [ -z "$MINIO_CONTAINER" ]; then
    echo "  → FAILED: no minio container" >&2
    FAILED+=("minio:$BUCKET")
  elif docker cp "$BACKUP_DIR/minio/$BUCKET/." "$MINIO_CONTAINER:/data/$BUCKET/" 2>/dev/null; then
    docker restart "$MINIO_CONTAINER" >/dev/null 2>&1 || true
    echo "  → Restored (minio restarted to re-read its data directory)"
  else
    echo "  → FAILED: could not copy into $MINIO_CONTAINER" >&2
    FAILED+=("minio:$BUCKET")
  fi
fi

# --- Valkey ---
if [ -f "$BACKUP_DIR/valkey.rdb" ]; then
  echo "Restoring valkey..."
  if [ -z "$VALKEY_CONTAINER" ]; then
    echo "  → FAILED: no valkey container" >&2
    FAILED+=("valkey")
  else
    # Stop first. Valkey writes its in-memory state to dump.rdb as it shuts
    # down, so copying into a running container and restarting would have the
    # shutdown save overwrite the file we just placed — and then load it back,
    # empty. Replacing the RDB while stopped is the only ordering that holds.
    docker stop "$VALKEY_CONTAINER" >/dev/null 2>&1 || true
    if docker cp "$BACKUP_DIR/valkey.rdb" "$VALKEY_CONTAINER:/data/dump.rdb" 2>/dev/null; then
      docker start "$VALKEY_CONTAINER" >/dev/null 2>&1 || true
      echo "  → Restored (replaced while stopped, then started)"
    else
      docker start "$VALKEY_CONTAINER" >/dev/null 2>&1 || true
      echo "  → FAILED: could not copy the RDB into $VALKEY_CONTAINER" >&2
      FAILED+=("valkey")
    fi
  fi
fi

# --- Let the services that own their own schema catch up ---
echo "Restarting keycloak and airflow..."
docker compose restart keycloak airflow airflow-scheduler airflow-webserver >/dev/null 2>&1 || true
echo "  → Restarted (each re-reads the schema that was restored)"

# --- Summary ---
echo ""
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "=== Restore INCOMPLETE ==="
  echo "Not restored: ${FAILED[*]}" >&2
  echo ""
  echo "Start the platform with:  make dev-all-portal"
  exit 1
fi

echo "=== Restore Complete ==="
echo "Start the platform with:  make dev-all-portal"
