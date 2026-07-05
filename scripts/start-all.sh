#!/usr/bin/env bash
# Start NC Triangle Muslims WhatsApp stack (detached — safe to close terminal after this exits):
#   1. Docker (PostgreSQL + Redis)
#   2. Evolution API (npm)
#   3. Python message forwarder
#
# Usage:
#   ./scripts/start-all.sh              # dev mode (tsx watch, hot reload)
#   EVOLUTION_RUN_MODE=prod ./scripts/start-all.sh   # production (node dist/main)
#   nohup ./scripts/start-all.sh >> logs/start-all.log 2>&1 &   # extra log of this script
set -euo pipefail

ROOT="/mnt/1tb/evolution-api"
LOG_DIR="$ROOT/logs"
PID_DIR="$ROOT/logs"
FORWARDER_DIR="$ROOT/forwarder"
RUN_MODE="${EVOLUTION_RUN_MODE:-dev}"  # dev | prod

mkdir -p "$LOG_DIR" "$PID_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# shellcheck source=lib/pids.sh
source "$ROOT/scripts/lib/pids.sh"

find_api_pid_for_mode() {
  find_api_pid
}

port_in_use() {
  ss -tln 2>/dev/null | grep -q ":$1 "
}

stop_stale_on_port() {
  local port="$1" name="$2"
  if port_in_use "$port"; then
    local pid
    pid=$(ss -tlnp 2>/dev/null | grep ":${port} " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1)
    if [ -n "$pid" ] && [ -f "$2" ] && [ "$(cat "$2" 2>/dev/null)" != "$pid" ]; then
      if ! kill -0 "$(cat "$2" 2>/dev/null)" 2>/dev/null; then
        log "WARNING: $name port :$port held by orphan pid $pid (stale pid file). Killing orphan..."
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
  fi
}

log "Running preflight checks..."
"$ROOT/scripts/preflight.sh"

# --- 1. Docker deps (Postgres + Redis) ---
log "Starting Docker deps (PostgreSQL + Redis)..."
cd "$ROOT"
docker compose -f docker-compose.deps.yaml up -d

log "Waiting for Postgres..."
for i in $(seq 1 30); do
  if docker exec evolution_postgres pg_isready -U evolution -d evolution_db >/dev/null 2>&1; then
    log "Postgres is ready."
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo "ERROR: Postgres did not become ready in time." >&2
    exit 1
  fi
done

# --- 2. Evolution API (npm) ---
API_PID_FILE="$PID_DIR/evolution-api.pid"
EXISTING_API_PID=$(find_api_pid_for_mode || true)

if [ -n "$EXISTING_API_PID" ] && kill -0 "$EXISTING_API_PID" 2>/dev/null; then
  echo "$EXISTING_API_PID" > "$API_PID_FILE"
  log "Evolution API already running (pid $EXISTING_API_PID, mode: $RUN_MODE)."
else
  rm -f "$API_PID_FILE"
  stop_stale_on_port 8080 "Evolution API"

  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  nvm use 20 >/dev/null 2>&1 || true

  cd "$ROOT"
  export DATABASE_PROVIDER=postgresql

  if [ "$RUN_MODE" = "prod" ]; then
    log "Building Evolution API for production..."
    npm run build
    log "Starting Evolution API (production) on :8080..."
    nohup setsid npm run start:prod >> "$LOG_DIR/evolution-api.log" 2>&1 &
  else
    log "Starting Evolution API (dev / hot reload) on :8080..."
    nohup setsid npm run dev:server >> "$LOG_DIR/evolution-api.log" 2>&1 &
  fi

  sleep 3
  API_PID=$(find_api_pid_for_mode || true)
  if [ -z "$API_PID" ]; then
    echo "ERROR: Evolution API failed to start. Check $LOG_DIR/evolution-api.log" >&2
    exit 1
  fi
  echo "$API_PID" > "$API_PID_FILE"
  log "Evolution API started (pid $API_PID, mode: $RUN_MODE, log: $LOG_DIR/evolution-api.log)"
fi

log "Waiting for Evolution API..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8080 >/dev/null 2>&1; then
    log "Evolution API is up."
    break
  fi
  sleep 1
  if [ "$i" -eq 60 ]; then
    echo "WARNING: Evolution API not responding on :8080 yet. Check $LOG_DIR/evolution-api.log" >&2
  fi
done

# --- 3. Python forwarder ---
FWD_PID_FILE="$PID_DIR/forwarder.pid"
EXISTING_FWD_PID=$(find_forwarder_pid || true)

if [ -n "$EXISTING_FWD_PID" ] && kill -0 "$EXISTING_FWD_PID" 2>/dev/null; then
  echo "$EXISTING_FWD_PID" > "$FWD_PID_FILE"
  log "Forwarder already running (pid $EXISTING_FWD_PID)."
else
  rm -f "$FWD_PID_FILE"
  stop_stale_on_port 5000 "Forwarder"

  log "Starting Python forwarder on :5000..."
  cd "$FORWARDER_DIR"
  FWD_PYTHON="python3"
  if [ -x "$FORWARDER_DIR/venv/bin/python" ]; then
    FWD_PYTHON="$FORWARDER_DIR/venv/bin/python"
  else
    log "WARNING: forwarder/venv not found — run forwarder/scripts/setup-venv.sh (easyocr may be missing)"
  fi
  nohup setsid "$FWD_PYTHON" app.py >> "$LOG_DIR/forwarder.log" 2>&1 &

  sleep 1
  FWD_PID=$(find_forwarder_pid || true)
  if [ -z "$FWD_PID" ]; then
    echo "ERROR: Forwarder failed to start. Check $LOG_DIR/forwarder.log" >&2
    exit 1
  fi
  echo "$FWD_PID" > "$FWD_PID_FILE"
  log "Forwarder started (pid $FWD_PID, log: $LOG_DIR/forwarder.log)"
fi

sleep 1
log "Health checks:"
curl -sf http://localhost:5000/health && echo "" || echo "  forwarder: NOT READY"
curl -sf http://localhost:8080 >/dev/null && echo "  evolution-api: OK" || echo "  evolution-api: NOT READY"
docker ps --filter name=evolution_ --format '  {{.Names}}: {{.Status}}'

log "Done (detached — you can close this terminal)."
echo ""
echo "  Manager UI (on server):  http://localhost:8080/manager/#/manager/login"
echo "  Manager Server URL:      http://localhost:8080  (NOT /manager)"
echo "  Via SSH port-forward:    forward :8080, then use http://localhost:<port>/manager/#/manager/login"
echo ""
echo "  Status:  $ROOT/scripts/status.sh"
echo "  Logs:    tail -f $LOG_DIR/evolution-api.log $LOG_DIR/forwarder.log"
echo "  Stop:    $ROOT/scripts/stop-all.sh"
