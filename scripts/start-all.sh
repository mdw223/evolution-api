#!/usr/bin/env bash
# Start NC Triangle Muslims WhatsApp stack:
#   1. Docker (PostgreSQL + Redis)
#   2. Evolution API (npm)
#   3. Python message forwarder
set -euo pipefail

ROOT="/mnt/1tb/evolution-api"
LOG_DIR="$ROOT/logs"
PID_DIR="$ROOT/logs"
FORWARDER_DIR="$ROOT/forwarder"

mkdir -p "$LOG_DIR" "$PID_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

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
if [ -f "$PID_DIR/evolution-api.pid" ] && kill -0 "$(cat "$PID_DIR/evolution-api.pid")" 2>/dev/null; then
  log "Evolution API already running (pid $(cat "$PID_DIR/evolution-api.pid"))."
else
  log "Starting Evolution API on :8080..."
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  nvm use 20 >/dev/null 2>&1 || true

  cd "$ROOT"
  export DATABASE_PROVIDER=postgresql
  nohup npm run dev:server >> "$LOG_DIR/evolution-api.log" 2>&1 &
  echo $! > "$PID_DIR/evolution-api.pid"
  log "Evolution API started (pid $(cat "$PID_DIR/evolution-api.pid"), log: $LOG_DIR/evolution-api.log)"
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
if [ -f "$PID_DIR/forwarder.pid" ] && kill -0 "$(cat "$PID_DIR/forwarder.pid")" 2>/dev/null; then
  log "Forwarder already running (pid $(cat "$PID_DIR/forwarder.pid"))."
else
  log "Starting Python forwarder on :5000..."
  cd "$FORWARDER_DIR"
  nohup python3 app.py >> "$LOG_DIR/forwarder.log" 2>&1 &
  echo $! > "$PID_DIR/forwarder.pid"
  log "Forwarder started (pid $(cat "$PID_DIR/forwarder.pid"), log: $LOG_DIR/forwarder.log)"
fi

sleep 1
log "Health checks:"
curl -sf http://localhost:5000/health && echo "" || echo "  forwarder: NOT READY"
curl -sf http://localhost:8080 >/dev/null && echo "  evolution-api: OK" || echo "  evolution-api: NOT READY"
docker ps --filter name=evolution_ --format '  {{.Names}}: {{.Status}}'

log "Done. Tail logs with:"
echo "  tail -f $LOG_DIR/evolution-api.log $LOG_DIR/forwarder.log"
