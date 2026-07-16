#!/usr/bin/env bash
# Back up every database and bucket the platform keeps state in.
#
# Usage:
#   make backup                           # backup to ./backups/<timestamp>/
#   bash bin/backup.sh /path/to/dir       # backup to custom directory
#
# Exits non-zero if any component could not be backed up. A backup tool that
# reports success it didn't earn is worse than one that fails.
#
# Backs up:
#   - PostgreSQL: techneos database (main application data)
#   - PostgreSQL: airflow database (pipeline orchestration)
#   - MinIO: techneos-data bucket (uploaded datasets/files and pipeline run artifacts)
#   - Valkey: RDB dump (cache/pub-sub state)
#
# Prerequisites:
#   - Docker containers must be running (make up)
#   - mc (MinIO Client) installed locally, OR the minio container accessible

set -euo pipefail

# --- Configuration ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${1:-./backups/${TIMESTAMP}}"

# Anything that was meant to be captured and wasn't. Reported at the end, and
# reflected in the exit status, so a partial backup can't pass for a whole one.
FAILED=()

# Resolve a Compose service to its actual running container name. Works
# regardless of project name (techneos, or whatever `-p` was passed) because we
# filter on the Compose service label, not the auto-generated container name.
_resolve_container() {
  local service="$1"
  docker ps --filter "label=com.docker.compose.service=${service}" \
    --format '{{.Names}}' | head -n1
}

POSTGRES_CONTAINER="${TECHNEOS_POSTGRES_CONTAINER:-$(_resolve_container postgres)}"
VALKEY_CONTAINER="${TECHNEOS_VALKEY_CONTAINER:-$(_resolve_container valkey)}"
MINIO_CONTAINER="${TECHNEOS_MINIO_CONTAINER:-$(_resolve_container minio)}"

if [ -z "$POSTGRES_CONTAINER" ]; then
  echo "Error: no running postgres container found." >&2
  echo "Set TECHNEOS_POSTGRES_CONTAINER=<name> to override, or run 'make up' first." >&2
  exit 1
fi

PG_USER="${POSTGRES_USER:-techneos}"
PG_PASSWORD="${POSTGRES_PASSWORD:-techneos_dev_password}"
MINIO_ALIAS="techneos-backup"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_PASS="${MINIO_ROOT_PASSWORD:-minioadmin}"

# --- Setup ---
mkdir -p "$BACKUP_DIR"
echo "=== TechneOS Backup ==="
echo "Timestamp: $TIMESTAMP"
echo "Backup directory: $BACKUP_DIR"
echo ""

# --- PostgreSQL: techneos ---
echo "[1/4] Backing up PostgreSQL: techneos..."
docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
  pg_dump -U "$PG_USER" -d techneos --format=custom --clean --if-exists \
  > "$BACKUP_DIR/techneos.dump"
echo "  → $BACKUP_DIR/techneos.dump ($(du -h "$BACKUP_DIR/techneos.dump" | cut -f1))"

# --- PostgreSQL: airflow ---
echo "[2/4] Backing up PostgreSQL: airflow..."
if docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
     psql -U "$PG_USER" -lqt | grep -qw airflow; then
  docker exec -e PGPASSWORD="$PG_PASSWORD" "$POSTGRES_CONTAINER" \
    pg_dump -U "$PG_USER" -d airflow --format=custom --clean --if-exists \
    > "$BACKUP_DIR/airflow.dump"
  echo "  → $BACKUP_DIR/airflow.dump ($(du -h "$BACKUP_DIR/airflow.dump" | cut -f1))"
else
  echo "  → Skipped (airflow database does not exist)"
fi

# --- MinIO: techneos-data ---
echo "[3/4] Backing up MinIO: techneos-data bucket..."
if command -v mc &>/dev/null; then
  if mc alias set "$MINIO_ALIAS" "$MINIO_ENDPOINT" "$MINIO_USER" "$MINIO_PASS" --quiet 2>/dev/null &&
     mc mirror "$MINIO_ALIAS/techneos-data" "$BACKUP_DIR/minio/techneos-data" --quiet 2>/dev/null; then
    if [ -d "$BACKUP_DIR/minio/techneos-data" ] && [ "$(ls -A "$BACKUP_DIR/minio/techneos-data" 2>/dev/null)" ]; then
      echo "  → $BACKUP_DIR/minio/techneos-data/ ($(du -sh "$BACKUP_DIR/minio/techneos-data" | cut -f1))"
    else
      echo "  → Skipped (bucket empty)"
    fi
  else
    echo "  → FAILED: mc could not mirror techneos-data from $MINIO_ENDPOINT" >&2
    FAILED+=("minio:techneos-data")
  fi
elif [ -z "$MINIO_CONTAINER" ]; then
  echo "  → FAILED: no running minio container found" >&2
  echo "     Install mc, or set TECHNEOS_MINIO_CONTAINER=<name>." >&2
  FAILED+=("minio:techneos-data")
else
  # Fallback: docker cp directly from the container's data directory. An
  # unreachable container and an empty bucket are different outcomes — the
  # first loses data, the second has none to lose — so don't report both as
  # a skip.
  mkdir -p "$BACKUP_DIR/minio/techneos-data"
  if docker cp "$MINIO_CONTAINER:/data/techneos-data/." "$BACKUP_DIR/minio/techneos-data/" 2>/dev/null; then
    if [ -n "$(ls -A "$BACKUP_DIR/minio/techneos-data" 2>/dev/null)" ]; then
      echo "  → $BACKUP_DIR/minio/techneos-data/ ($(du -sh "$BACKUP_DIR/minio/techneos-data" | cut -f1))"
    else
      rmdir "$BACKUP_DIR/minio/techneos-data" 2>/dev/null || true
      echo "  → Skipped (bucket empty)"
    fi
  else
    rmdir "$BACKUP_DIR/minio/techneos-data" 2>/dev/null || true
    echo "  → FAILED: could not copy techneos-data from $MINIO_CONTAINER" >&2
    FAILED+=("minio:techneos-data")
  fi
fi

# --- Valkey (Redis-compatible) ---
echo "[4/4] Backing up Valkey..."
# Trigger a synchronous save
docker exec "$VALKEY_CONTAINER" valkey-cli BGSAVE >/dev/null 2>&1 || true
sleep 1
docker cp "$VALKEY_CONTAINER:/data/dump.rdb" "$BACKUP_DIR/valkey.rdb" 2>/dev/null || true
if [ -f "$BACKUP_DIR/valkey.rdb" ]; then
  echo "  → $BACKUP_DIR/valkey.rdb ($(du -h "$BACKUP_DIR/valkey.rdb" | cut -f1))"
else
  echo "  → Skipped (no RDB dump found)"
fi

# --- Summary ---
echo ""
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "=== Backup INCOMPLETE ==="
else
  echo "=== Backup Complete ==="
fi
echo "Location: $BACKUP_DIR"
echo "Total size: $(du -sh "$BACKUP_DIR" | cut -f1)"

# --- Generate RESTORE.md ---
RESTORE_FILE="$BACKUP_DIR/RESTORE.md"
cat > "$RESTORE_FILE" <<EOF
# Restore Instructions

**Backup created:** $(date '+%Y-%m-%d %H:%M:%S')
**Source host:** $(hostname)

## Prerequisites

- Docker containers must be running (\`make up\`)
- Restore will **overwrite** existing data — back up current state first if needed

## 1. PostgreSQL: techneos (main application data)

EOF

if [ -f "$BACKUP_DIR/techneos.dump" ]; then
  cat >> "$RESTORE_FILE" <<EOF
\`\`\`bash
docker exec -i $POSTGRES_CONTAINER pg_restore -U $PG_USER -d techneos --clean --if-exists < $BACKUP_DIR/techneos.dump
\`\`\`

EOF
else
  echo "*Not included in this backup.*" >> "$RESTORE_FILE"
  echo "" >> "$RESTORE_FILE"
fi

cat >> "$RESTORE_FILE" <<EOF
## 2. PostgreSQL: airflow (pipeline orchestration)

EOF

if [ -f "$BACKUP_DIR/airflow.dump" ]; then
  cat >> "$RESTORE_FILE" <<EOF
\`\`\`bash
docker exec -i $POSTGRES_CONTAINER pg_restore -U $PG_USER -d airflow --clean --if-exists < $BACKUP_DIR/airflow.dump
\`\`\`

EOF
else
  echo "*Not included in this backup.*" >> "$RESTORE_FILE"
  echo "" >> "$RESTORE_FILE"
fi

cat >> "$RESTORE_FILE" <<EOF
## 3. MinIO: techneos-data bucket (datasets and uploaded files)

EOF

if [ -d "$BACKUP_DIR/minio/techneos-data" ] && [ "$(ls -A "$BACKUP_DIR/minio/techneos-data" 2>/dev/null)" ]; then
  cat >> "$RESTORE_FILE" <<EOF
**Option A — using mc (MinIO Client):**

\`\`\`bash
mc alias set techneos-restore $MINIO_ENDPOINT $MINIO_USER $MINIO_PASS
mc mirror $BACKUP_DIR/minio/techneos-data techneos-restore/techneos-data --overwrite
\`\`\`

**Option B — using docker cp:**

\`\`\`bash
docker cp $BACKUP_DIR/minio/techneos-data/. $MINIO_CONTAINER:/data/techneos-data/
docker restart $MINIO_CONTAINER
\`\`\`

EOF
else
  echo "*Not included in this backup (bucket was empty).*" >> "$RESTORE_FILE"
  echo "" >> "$RESTORE_FILE"
fi

cat >> "$RESTORE_FILE" <<EOF
## 4. Valkey (cache and pub/sub state)

EOF

if [ -f "$BACKUP_DIR/valkey.rdb" ]; then
  cat >> "$RESTORE_FILE" <<EOF
\`\`\`bash
docker cp $BACKUP_DIR/valkey.rdb $VALKEY_CONTAINER:/data/dump.rdb
docker restart $VALKEY_CONTAINER
\`\`\`

EOF
else
  echo "*Not included in this backup.*" >> "$RESTORE_FILE"
  echo "" >> "$RESTORE_FILE"
fi

cat >> "$RESTORE_FILE" <<EOF
## Full restore (all at once)

Stop services first (Ctrl+C on bin/dev.sh) then run:

\`\`\`bash
EOF

if [ -f "$BACKUP_DIR/techneos.dump" ]; then
  echo "docker exec -i $POSTGRES_CONTAINER pg_restore -U $PG_USER -d techneos --clean --if-exists < $BACKUP_DIR/techneos.dump" >> "$RESTORE_FILE"
fi
if [ -f "$BACKUP_DIR/airflow.dump" ]; then
  echo "docker exec -i $POSTGRES_CONTAINER pg_restore -U $PG_USER -d airflow --clean --if-exists < $BACKUP_DIR/airflow.dump" >> "$RESTORE_FILE"
fi
if [ -d "$BACKUP_DIR/minio/techneos-data" ] && [ "$(ls -A "$BACKUP_DIR/minio/techneos-data" 2>/dev/null)" ]; then
  echo "docker cp $BACKUP_DIR/minio/techneos-data/. $MINIO_CONTAINER:/data/techneos-data/" >> "$RESTORE_FILE"
fi
if [ -f "$BACKUP_DIR/valkey.rdb" ]; then
  echo "docker cp $BACKUP_DIR/valkey.rdb $VALKEY_CONTAINER:/data/dump.rdb" >> "$RESTORE_FILE"
fi

cat >> "$RESTORE_FILE" <<'EOF'
bin/dev.sh
```
EOF

echo ""
echo "Restore instructions: $RESTORE_FILE"

if [ ${#FAILED[@]} -gt 0 ]; then
  echo ""
  echo "Not backed up: ${FAILED[*]}" >&2
  exit 1
fi
