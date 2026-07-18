#!/usr/bin/env bash
set -euo pipefail
# data-admin.sh — back up, restore, or reset the platform's stateful stores in a
# chosen environment. One tool for local dev and the EC2 deployment.
#
#   bin/data-admin.sh backup  [--env local|prod] [--dir <out>] [--keep N]
#   bin/data-admin.sh restore --dir <backup> [--env local|prod] [--yes]
#   bin/data-admin.sh reset   [--env local|prod] [--yes]
#
# Stores: PostgreSQL (techneos, keycloak, airflow), the MinIO bucket, and Valkey.
#
# --env local (default) acts on the local Docker daemon. --env prod targets the
# EC2 deployment: this script is shipped to the host and re-run there over
# SSH+sudo (SSH details from deploy/ec2/.env.prod). A prod backup is written to
# /data/techneos/backups/<ts> ON THE HOST and left there — that volume survives
# redeploys, so backups persist; copy them to S3 for off-host durability. --keep
# N prunes to the N most recent on-host backups (default 10; 0 keeps all). A prod
# restore's --dir is either an on-host backup (a name under /data/techneos/backups,
# or an absolute path — read in place, no upload) or a local directory, which it
# uploads first. Credentials are read from each container's own environment, so
# nothing assumes dev passwords and the host needs no .env for this.
#
# reset and restore are destructive: they prompt for a typed confirmation naming
# the target (skip with --yes). They quiesce the app first — stopping the service
# containers if the deployment is containerized (prod), or refusing while local
# dev services hold ports 8000-8008 (run `make dev-stop`).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DATABASES=(techneos keycloak airflow)
SERVICES=(gateway auth-service dataset-service tool-service task-service \
          pipeline-service agent-service notification-service app-service)

# ── args ─────────────────────────────────────────────────────────────────────
SUB="${1:-}"; shift 2>/dev/null || true
ENV_TARGET="local"; BACKUP_DIR=""; ASSUME_YES="no"; KEEP="${BACKUP_KEEP:-10}"
while [ $# -gt 0 ]; do
  case "$1" in
    --env)      ENV_TARGET="$2"; shift 2 ;;
    --dir)      BACKUP_DIR="$2"; shift 2 ;;
    --keep)     KEEP="$2"; shift 2 ;;
    --yes|-y)   ASSUME_YES="yes"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$SUB" in
  backup|restore|reset) ;;
  *) echo "Usage: bin/data-admin.sh <backup|restore|reset> [--env local|prod] [--dir <dir>] [--keep N] [--yes]" >&2; exit 2 ;;
esac
case "$ENV_TARGET" in local|prod) ;; *) echo "Error: --env must be local or prod" >&2; exit 2 ;; esac
case "$KEEP" in ''|*[!0-9]*) echo "Error: --keep must be a non-negative integer" >&2; exit 2 ;; esac

# ─────────────────────────────────────────────────────────────────────────────
# PROD: ship this script to the host and run its local mode there over SSH+sudo.
# ─────────────────────────────────────────────────────────────────────────────
if [ "$ENV_TARGET" = "prod" ]; then
  ENV_FILE="$REPO_ROOT/deploy/ec2/.env.prod"
  [ -f "$ENV_FILE" ] || { echo "Error: $ENV_FILE not found (needed for the SSH target)" >&2; exit 1; }
  _envval() { local v; v="$(grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"; case "$v" in *"<"*) return 0 ;; esac; printf '%s' "$v"; }

  SSH_HOST="$(_envval SSH_HOST)"; [ -n "$SSH_HOST" ] || { echo "Error: SSH_HOST not set in $ENV_FILE" >&2; exit 1; }
  SSH_USER="$(_envval SSH_USER)"; SSH_USER="${SSH_USER:-deploy}"
  SSH_PORT="$(_envval SSH_PORT)"; SSH_PORT="${SSH_PORT:-22}"
  SSH_KEY="$(_envval SSH_KEY_PATH)"; SSH_KEY="${SSH_KEY/#\~/$HOME}"
  SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=accept-new)
  SCP=(scp -P "$SSH_PORT" -o StrictHostKeyChecking=accept-new)
  [ -n "$SSH_KEY" ] && { SSH+=(-i "$SSH_KEY"); SCP+=(-i "$SSH_KEY"); }
  TARGET="$SSH_USER@$SSH_HOST"
  REMOTE_SELF="/tmp/techneos-data-admin.sh"

  # Fail on a missing restore target before prompting or shipping anything.
  if [ "$SUB" = "restore" ] && [ -z "$BACKUP_DIR" ]; then
    echo "Error: --dir is required (an on-host backup name, or a local directory)." >&2
    echo "Backups on $SSH_HOST:" >&2
    "${SSH[@]}" "$TARGET" "sudo ls -1 /data/techneos/backups 2>/dev/null" >&2 || true
    exit 2
  fi

  # Destructive ops confirm HERE (naming prod), then run non-interactively there.
  if [ "$SUB" != "backup" ] && [ "$ASSUME_YES" != "yes" ]; then
    echo "This will $SUB data on the PRODUCTION host ($SSH_HOST). This cannot be undone."
    printf "Type 'prod' to proceed: "; read -r reply
    [ "$reply" = "prod" ] || { echo "Aborted — nothing was changed."; exit 1; }
  fi

  "${SCP[@]}" "${BASH_SOURCE[0]}" "$TARGET:$REMOTE_SELF"
  _cleanup_remote() { "${SSH[@]}" "$TARGET" "sudo rm -f $REMOTE_SELF" >/dev/null 2>&1 || true; }

  case "$SUB" in
    backup)
      TS="$(date +%Y%m%d_%H%M%S)"
      REMOTE_ROOT="/data/techneos/backups"
      # The backup stays on the host's data volume (survives redeploys). --dir may
      # override the location; otherwise it lands under the default root by timestamp.
      REMOTE_OUT="${BACKUP_DIR:-$REMOTE_ROOT/$TS}"
      echo "=== Backing up $SSH_HOST → host:$REMOTE_OUT ==="
      "${SSH[@]}" "$TARGET" "sudo bash $REMOTE_SELF backup --env local --dir $REMOTE_OUT"
      # Retention: keep the N most recent backups under the default root, prune the
      # rest. Skipped for --keep 0, or when --dir pointed the backup elsewhere.
      if [ "$KEEP" -gt 0 ] && [ -z "$BACKUP_DIR" ]; then
        "${SSH[@]}" "$TARGET" \
          "sudo bash -c 'ls -1dt $REMOTE_ROOT/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf'"
      fi
      _cleanup_remote
      echo "=== Backup stored on host at $REMOTE_OUT ==="
      echo "    (on the EC2 data volume — copy it to S3 for off-host durability)"
      ;;
    restore)
      # --dir presence is validated up front (before the confirm/ship).
      if [ -d "$BACKUP_DIR" ]; then
        # A directory on THIS workstation → upload it, restore, clean up.
        REMOTE_IN="/tmp/techneos-restore-$$"
        "${SSH[@]}" "$TARGET" "mkdir -p $REMOTE_IN"
        "${SCP[@]}" -r "${BACKUP_DIR%/}/." "$TARGET:$REMOTE_IN/"
        "${SSH[@]}" "$TARGET" "sudo bash $REMOTE_SELF restore --env local --yes --dir $REMOTE_IN"
        "${SSH[@]}" "$TARGET" "sudo rm -rf $REMOTE_IN" || true
      else
        # Otherwise an on-host backup: absolute path, or a name under the default
        # root. Restored in place — nothing is uploaded.
        case "$BACKUP_DIR" in
          /*) REMOTE_IN="$BACKUP_DIR" ;;
          *)  REMOTE_IN="/data/techneos/backups/$BACKUP_DIR" ;;
        esac
        if ! "${SSH[@]}" "$TARGET" "sudo test -d $REMOTE_IN"; then
          echo "Error: no such on-host backup: $REMOTE_IN" >&2
          echo "Backups on $SSH_HOST:" >&2
          "${SSH[@]}" "$TARGET" "sudo ls -1 /data/techneos/backups 2>/dev/null" >&2 || true
          _cleanup_remote; exit 1
        fi
        "${SSH[@]}" "$TARGET" "sudo bash $REMOTE_SELF restore --env local --yes --dir $REMOTE_IN"
      fi
      _cleanup_remote
      ;;
    reset)
      "${SSH[@]}" "$TARGET" "sudo bash $REMOTE_SELF reset --env local --yes"
      _cleanup_remote
      ;;
  esac
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# LOCAL: operate on the local Docker daemon (this is also what runs on the host
# in prod mode, where "local" is the deployment's own daemon).
# ─────────────────────────────────────────────────────────────────────────────
_resolve() { docker ps -a --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -n1; }
_running() { docker ps    --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -n1; }

POSTGRES_CONTAINER="${TECHNEOS_POSTGRES_CONTAINER:-$(_resolve postgres)}"
VALKEY_CONTAINER="${TECHNEOS_VALKEY_CONTAINER:-$(_resolve valkey)}"
MINIO_CONTAINER="${TECHNEOS_MINIO_CONTAINER:-$(_resolve minio)}"
[ -n "$POSTGRES_CONTAINER" ] || { echo "Error: no postgres container found (is the stack up?)." >&2; exit 1; }

# Credentials + bucket from the containers' own env — never the shell's, so this
# is correct in any environment and needs no .env alongside it.
_cenv() { docker exec "$1" printenv "$2" 2>/dev/null || true; }
PG_USER="$(_cenv "$POSTGRES_CONTAINER" POSTGRES_USER)";     PG_USER="${PG_USER:-techneos}"
PG_PASSWORD="$(_cenv "$POSTGRES_CONTAINER" POSTGRES_PASSWORD)"
BUCKET="$(_cenv "$MINIO_CONTAINER" MINIO_BUCKET)";          BUCKET="${BUCKET:-techneos-data}"

_pg()  { docker exec    -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" "$@"; }
_pgi() { docker exec -i -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" "$@"; }
_db_exists() { _pg psql -U "$PG_USER" -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$1"; }

# Which app services are running as containers (prod) vs not (local dev uvicorn)?
# Ends with `return 0`: the loop's last `[ -n "$c" ] && echo` is non-zero when the
# final service isn't a container (the common local-dev case), and without this
# the caller's `containers="$(...)"` would inherit that and trip `set -e`.
_running_service_containers() {
  local s c; for s in "${SERVICES[@]}"; do c="$(_running "$s")"; [ -n "$c" ] && echo "$c"; done
  return 0
}

# Stop the app before a destructive op so no session blocks the drop/replace.
# Containerized deployment: stop those containers (and start them after).
# Local dev (services as host processes): refuse while they hold their ports.
STOPPED_SERVICES=()
_quiesce() {
  local containers; containers="$(_running_service_containers)"
  if [ -n "$containers" ]; then
    echo "Stopping service containers..."
    # shellcheck disable=SC2206
    STOPPED_SERVICES=($containers)
    docker stop "${STOPPED_SERVICES[@]}" >/dev/null
  else
    local busy=() port
    for port in 8000 8001 8002 8003 8004 8005 8006 8007 8008; do
      lsof -ti tcp:"$port" -sTCP:LISTEN >/dev/null 2>&1 && busy+=("$port")
    done
    if [ "${#busy[@]}" -gt 0 ]; then
      echo "REFUSING: local services are running (ports: ${busy[*]}) and hold open DB sessions." >&2
      echo "Stop them first:  make dev-stop" >&2
      exit 1
    fi
  fi
}
_unquiesce() {
  [ "${#STOPPED_SERVICES[@]}" -gt 0 ] && { echo "Starting service containers..."; docker start "${STOPPED_SERVICES[@]}" >/dev/null || true; }
  # keycloak + airflow own their own schema; restart so they re-read what changed.
  docker restart "$(_resolve keycloak)" >/dev/null 2>&1 || true
  for s in airflow airflow-scheduler airflow-webserver; do
    c="$(_resolve "$s")"; [ -n "$c" ] && docker restart "$c" >/dev/null 2>&1 || true
  done
}

_confirm() {  # $1 = action word; skipped with --yes
  [ "$ASSUME_YES" = "yes" ] && return 0
  echo "This will $1 the ${ENV_TARGET} data. This cannot be undone."
  printf "Type '%s' to proceed: " "$ENV_TARGET"; read -r reply
  [ "$reply" = "$ENV_TARGET" ] || { echo "Aborted — nothing was changed."; exit 1; }
}

# ── backup ───────────────────────────────────────────────────────────────────
do_backup() {
  local dir="${BACKUP_DIR:-$REPO_ROOT/backups/$(date +%Y%m%d_%H%M%S)}"
  mkdir -p "$dir"
  echo "=== Backup → $dir ==="
  local failed=()

  local db req
  for db in "${DATABASES[@]}"; do
    req="no"; [ "$db" = "techneos" ] && req="yes"
    if ! _db_exists "$db"; then
      [ "$req" = "yes" ] && { echo "  postgres/$db: FAILED (does not exist)"; failed+=("postgres:$db"); } \
                         || echo "  postgres/$db: skipped (absent)"
      continue
    fi
    if _pg pg_dump -U "$PG_USER" -d "$db" --format=custom --clean --if-exists > "$dir/$db.dump" 2>/dev/null; then
      echo "  postgres/$db: $(du -h "$dir/$db.dump" | cut -f1)"
    else
      rm -f "$dir/$db.dump"; echo "  postgres/$db: FAILED"; failed+=("postgres:$db")
    fi
  done

  if [ -n "$MINIO_CONTAINER" ]; then
    mkdir -p "$dir/minio/$BUCKET"
    if docker cp "$MINIO_CONTAINER:/data/$BUCKET/." "$dir/minio/$BUCKET/" 2>/dev/null && \
       [ -n "$(ls -A "$dir/minio/$BUCKET" 2>/dev/null)" ]; then
      echo "  minio/$BUCKET: $(du -sh "$dir/minio/$BUCKET" | cut -f1)"
    else
      rm -rf "$dir/minio"; echo "  minio/$BUCKET: skipped (empty or absent)"
    fi
  fi

  if [ -n "$VALKEY_CONTAINER" ]; then
    docker exec "$VALKEY_CONTAINER" valkey-cli SAVE >/dev/null 2>&1 || true
    if docker cp "$VALKEY_CONTAINER:/data/dump.rdb" "$dir/valkey.rdb" 2>/dev/null; then
      echo "  valkey: $(du -h "$dir/valkey.rdb" | cut -f1)"
    else
      echo "  valkey: skipped (no RDB)"
    fi
  fi

  echo ""
  if [ "${#failed[@]}" -gt 0 ]; then echo "=== Backup INCOMPLETE: ${failed[*]} ==="; exit 1; fi
  echo "=== Backup complete ($(du -sh "$dir" | cut -f1)) → $dir ==="
}

# ── restore ──────────────────────────────────────────────────────────────────
do_restore() {
  [ -n "$BACKUP_DIR" ] || { echo "Error: --dir <backup-dir> is required" >&2; exit 2; }
  local dir="${BACKUP_DIR%/}"
  [ -d "$dir" ] || { echo "Error: no such backup directory: $dir" >&2; exit 1; }

  local present=() db
  for db in "${DATABASES[@]}"; do [ -f "$dir/$db.dump" ] && present+=("postgres/$db"); done
  [ -d "$dir/minio/$BUCKET" ] && present+=("minio/$BUCKET")
  [ -f "$dir/valkey.rdb" ] && present+=("valkey")
  [ "${#present[@]}" -gt 0 ] || { echo "Error: $dir holds nothing recognisable." >&2; exit 1; }

  echo "=== Restore ($ENV_TARGET) from $dir ==="
  printf '  %s\n' "${present[@]}"
  _confirm "restore over"
  _quiesce
  local failed=()

  for db in "${DATABASES[@]}"; do
    [ -f "$dir/$db.dump" ] || continue
    echo "postgres/$db..."
    if ! _db_exists "$db"; then
      _pg psql -U "$PG_USER" -d postgres -q -c "CREATE DATABASE $db" >/dev/null 2>&1 \
        && echo "  · created $db" || { echo "  FAILED: cannot create $db"; failed+=("postgres:$db"); continue; }
    fi
    if _pgi pg_restore -U "$PG_USER" -d "$db" --clean --if-exists --no-owner < "$dir/$db.dump" >/dev/null 2>/tmp/.da_err_$$; then
      echo "  restored"
    elif grep -qiE "error:" /tmp/.da_err_$$; then
      echo "  FAILED:"; grep -iE "error:" /tmp/.da_err_$$ | head -3 | sed 's/^/    /'; failed+=("postgres:$db")
    else
      echo "  restored (with warnings)"
    fi
    rm -f /tmp/.da_err_$$
  done

  if [ -d "$dir/minio/$BUCKET" ] && [ -n "$MINIO_CONTAINER" ]; then
    echo "minio/$BUCKET..."
    docker cp "$dir/minio/$BUCKET/." "$MINIO_CONTAINER:/data/$BUCKET/" 2>/dev/null \
      && { docker restart "$MINIO_CONTAINER" >/dev/null 2>&1 || true; echo "  restored"; } \
      || { echo "  FAILED"; failed+=("minio:$BUCKET"); }
  fi

  if [ -f "$dir/valkey.rdb" ] && [ -n "$VALKEY_CONTAINER" ]; then
    echo "valkey..."
    docker stop "$VALKEY_CONTAINER" >/dev/null 2>&1 || true
    docker cp "$dir/valkey.rdb" "$VALKEY_CONTAINER:/data/dump.rdb" 2>/dev/null \
      && echo "  restored" || { echo "  FAILED"; failed+=("valkey"); }
    docker start "$VALKEY_CONTAINER" >/dev/null 2>&1 || true
  fi

  _unquiesce
  echo ""
  if [ "${#failed[@]}" -gt 0 ]; then echo "=== Restore INCOMPLETE: ${failed[*]} ==="; exit 1; fi
  echo "=== Restore complete ==="
}

# ── reset ────────────────────────────────────────────────────────────────────
do_reset() {
  echo "=== Reset ($ENV_TARGET) — empties every database, bucket and cache ==="
  _confirm "wipe"
  _quiesce

  local db
  for db in "${DATABASES[@]}"; do
    _db_exists "$db" || { echo "postgres/$db: absent"; continue; }
    _pg psql -U "$PG_USER" -d "$db" -v ON_ERROR_STOP=1 -q \
      -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO $PG_USER; GRANT ALL ON SCHEMA public TO public;" \
      >/dev/null 2>&1 && echo "postgres/$db: emptied" || echo "postgres/$db: FAILED (locked? stop services)"
  done

  if [ -n "$MINIO_CONTAINER" ]; then
    docker exec "$MINIO_CONTAINER" sh -c "rm -rf /data/$BUCKET/* /data/$BUCKET/.minio.sys 2>/dev/null" || true
    docker restart "$MINIO_CONTAINER" >/dev/null 2>&1 || true
    echo "minio/$BUCKET: emptied"
  fi
  if [ -n "$VALKEY_CONTAINER" ]; then
    docker exec "$VALKEY_CONTAINER" valkey-cli FLUSHALL >/dev/null 2>&1 || true
    echo "valkey: emptied"
  fi

  _unquiesce
  echo ""
  echo "=== Reset complete — rebuild with: make migrate && make seed ==="
}

case "$SUB" in
  backup)  do_backup ;;
  restore) do_restore ;;
  reset)   do_reset ;;
esac
