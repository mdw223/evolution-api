#!/usr/bin/env bash
# Stop NC Triangle Muslims WhatsApp stack
set -euo pipefail

ROOT="/mnt/1tb/evolution-api"
PID_DIR="$ROOT/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

stop_pidfile() {
  local name="$1"
  local pidfile="$PID_DIR/$2"
  if [ -f "$pidfile" ]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      log "Stopping $name (pid $pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  else
    log "$name: not running (no pid file)"
  fi
}

stop_pidfile "Forwarder" "forwarder.pid"
stop_pidfile "Evolution API" "evolution-api.pid"

pkill -f "${ROOT}/forwarder/app.py" 2>/dev/null || true
pkill -f "tsx watch ./src/main.ts" 2>/dev/null || true
pkill -f "node ${ROOT}/dist/main" 2>/dev/null || true
pkill -f "${ROOT}/src/main.ts" 2>/dev/null || true

log "Stopping Docker deps..."
cd "$ROOT"
docker compose -f docker-compose.deps.yaml down

log "All services stopped."
