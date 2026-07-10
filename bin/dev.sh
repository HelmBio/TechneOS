#!/usr/bin/env bash
# bin/dev.sh — Start (or restart) all platform services for local development
#
# Usage:
#   ./bin/dev.sh          # start all backend services
#   ./bin/dev.sh --portal # also start the Next.js web portal
#   ./bin/dev.sh --stop   # stop all running services
#
# Logs are written to .dev-logs/<service>.log
# PIDs are tracked in .dev-pids/<service>.pid

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT_DIR/.dev-pids"
LOG_DIR="$ROOT_DIR/.dev-logs"

# Format: "name:module:port:package"
SERVICES=(
  "gateway:gateway.main:8000:gateway"
  "auth:auth_service.main:8001:auth-service"
  "dataset:dataset_service.main:8002:dataset-service"
  "tool:tool_service.main:8003:tool-service"
  "pipeline:pipeline_service.main:8004:pipeline-service"
  "agent:agent_service.main:8005:agent-service"
  "notification:notification_service.main:8006:notification-service"
  "app:app_service.main:8007:app-service"
  "task:task_service.main:8008:task-service"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

_info()  { printf "\033[36m▸\033[0m %s\n" "$*"; }
_ok()    { printf "\033[32m✓\033[0m %s\n" "$*"; }
_warn()  { printf "\033[33m!\033[0m %s\n" "$*"; }
_err()   { printf "\033[31m✗\033[0m %s\n" "$*"; }

_kill_by_port() {
  local port=$1 name=$2
  local pids
  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN -P -n 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    for pid in $pids; do
      _info "Killing process on port $port ($name, PID $pid)..."
      kill "$pid" 2>/dev/null || true
    done
    # Wait briefly for processes to exit, then force-kill survivors
    sleep 0.3
    for pid in $pids; do
      if kill -0 "$pid" 2>/dev/null; then
        _warn "$name (PID $pid) still alive on port $port — sending SIGKILL"
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
  fi
}

_kill_pidfile() {
  local pidfile=$1
  [ -f "$pidfile" ] || return 0
  local name
  name="$(basename "$pidfile" .pid)"
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    _ok "Stopped $name (PID $pid)"
  else
    _warn "$name (PID $pid) was not running"
  fi
  rm -f "$pidfile"
}

_stop_ports() {
  local ports=("8000" "8001" "8002" "8003" "8004" "8005" "8006" "8007" "8008" "3000")
  local names=("gateway" "auth" "dataset" "tool" "pipeline" "agent" "notification" "app" "task" "portal")
  for i in "${!ports[@]}"; do
    _kill_by_port "${ports[$i]}" "${names[$i]}"
  done
}

stop_all() {
  _info "Stopping all services..."

  # 1. Kill by PID file (graceful stop)
  if [ -d "$PID_DIR" ]; then
    for pidfile in "$PID_DIR"/*.pid; do
      _kill_pidfile "$pidfile"
    done
    sleep 0.5
  fi

  # 2. Kill any remaining process on the designated ports (orphans / hot-reload leftovers)
  _stop_ports

  # 3. Clean up PID directory
  rm -rf "$PID_DIR"

  _ok "All services stopped"
}

wait_for_port() {
  local port=$1 name=$2 retries=30
  while ! lsof -iTCP:"$port" -sTCP:LISTEN -P -n >/dev/null 2>&1; do
    retries=$((retries - 1))
    if [ "$retries" -le 0 ]; then
      _err "$name failed to start on port $port (see $LOG_DIR/$name.log)"
      return 1
    fi
    sleep 0.3
  done
}

start_service() {
  local name=$1 module=$2 port=$3 pkg=$4

  # Kill existing process on this port (PID file or orphan)
  _kill_by_port "$port" "$name"
  rm -f "$PID_DIR/$name.pid"

  _info "Starting $name on port $port..."
  uv run --package "$pkg" uvicorn "$module:app" --reload --host 0.0.0.0 --port "$port" \
    >> "$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_DIR/$name.pid"

  wait_for_port "$port" "$name"
  _ok "$name running (PID $pid, port $port)"
}

start_portal() {
  local name="portal" port=3000

  _kill_by_port "$port" "$name"
  rm -f "$PID_DIR/$name.pid"

  _info "Starting Next.js web portal on port $port..."

  bash "$ROOT_DIR/bin/generate-portal-env.sh" "$ROOT_DIR/.env"

  (cd "$ROOT_DIR/packages/portal" && npx next dev --webpack --hostname 0.0.0.0 --port "$port") \
    >> "$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_DIR/$name.pid"

  wait_for_port "$port" "$name"
  _ok "$name running (PID $pid, port $port)"
}

# ── Main ─────────────────────────────────────────────────────────────────────

include_portal=false

for arg in "$@"; do
  case "$arg" in
    --stop)
      stop_all
      exit 0
      ;;
    --portal)
      include_portal=true
      ;;
    -h|--help)
      echo "Usage: $0 [--portal] [--stop]"
      echo ""
      echo "  --portal Also start the Next.js web portal (port 3000)"
      echo "  --stop   Stop all running services"
      exit 0
      ;;
    *)
      _err "Unknown argument: $arg"
      exit 1
      ;;
  esac
done

# Stop any previously running services
stop_all

mkdir -p "$PID_DIR" "$LOG_DIR"

# Truncate log files
for svc in "${SERVICES[@]}"; do
  IFS=: read -r name _ _ _ <<< "$svc"
  : > "$LOG_DIR/$name.log"
done
: > "$LOG_DIR/portal.log"

_info "Starting infrastructure (Docker Compose)..."
# Note: --wait exits non-zero when the one-shot minio-init container stops,
# so we start infra without --wait and poll health manually.
(cd "$ROOT_DIR" && docker compose up -d) >> "$LOG_DIR/infra.log" 2>&1

# Wait for core services to be healthy
for svc_name in postgres minio valkey; do
  retries=30
  while [ "$retries" -gt 0 ]; do
    status=$(cd "$ROOT_DIR" && docker compose ps "$svc_name" --format '{{.Health}}' 2>/dev/null || echo "unknown")
    [ "$status" = "healthy" ] && break
    retries=$((retries - 1))
    sleep 1
  done
  if [ "$retries" -le 0 ]; then
    _warn "$svc_name did not become healthy in time (continuing anyway)"
  fi
done

# Wait for optional profiled services (keycloak) if running
for svc_name in keycloak; do
  running=$(cd "$ROOT_DIR" && docker compose ps "$svc_name" --format '{{.Name}}' 2>/dev/null || true)
  if [ -n "$running" ]; then
    retries=60
    while [ "$retries" -gt 0 ]; do
      status=$(cd "$ROOT_DIR" && docker compose ps "$svc_name" --format '{{.Health}}' 2>/dev/null || echo "unknown")
      [ "$status" = "healthy" ] && break
      retries=$((retries - 1))
      sleep 1
    done
    if [ "$retries" -le 0 ]; then
      _warn "$svc_name did not become healthy in time (continuing anyway)"
    fi
  fi
done
_ok "Infrastructure ready"

# Start all backend services
for svc in "${SERVICES[@]}"; do
  IFS=: read -r name module port pkg <<< "$svc"
  start_service "$name" "$module" "$port" "$pkg"
done

if [ "$include_portal" = true ]; then
  start_portal
fi

echo ""
_ok "All services running. Logs in $LOG_DIR/"
echo ""
echo "  Gateway:   http://localhost:8000/api/v1/health"
echo "  Auth:      http://localhost:8001/api/v1/health"
echo "  Dataset:   http://localhost:8002/api/v1/health"
echo "  Tool:      http://localhost:8003/api/v1/health"
echo "  Pipeline:  http://localhost:8004/api/v1/health"
echo "  Agent:     http://localhost:8005/api/v1/health"
echo "  Notify:    http://localhost:8006/api/v1/health"
echo "  App:       http://localhost:8007/api/v1/health"
echo "  Task:      http://localhost:8008/api/v1/health"
if [ "$include_portal" = true ]; then
  echo "  Portal:    http://localhost:3000"
fi
echo ""
echo "  Stop all:  $0 --stop"
echo "  Tail logs: tail -f $LOG_DIR/*.log"
