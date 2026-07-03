#!/usr/bin/env bash
# Check status of NC Triangle Muslims WhatsApp stack
ROOT="/mnt/1tb/evolution-api"
PID_DIR="$ROOT/logs"
FORWARDER_DIR="$ROOT/forwarder"

# shellcheck source=lib/pids.sh
source "$ROOT/scripts/lib/pids.sh"

echo "=== Docker ==="
docker ps --filter name=evolution_ --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "Docker not running"

echo ""
echo "=== Processes ==="
API_PID=$(find_api_pid || true)
FWD_PID=$(find_forwarder_pid || true)
if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
  echo "  evolution-api: running (pid $API_PID)"
  [ -f "$PID_DIR/evolution-api.pid" ] && [ "$(cat "$PID_DIR/evolution-api.pid")" != "$API_PID" ] && \
    echo "    (note: pid file stale — run start-all.sh to refresh)"
else
  echo "  evolution-api: stopped"
fi
if [ -n "$FWD_PID" ] && kill -0 "$FWD_PID" 2>/dev/null; then
  echo "  forwarder: running (pid $FWD_PID)"
  [ -f "$PID_DIR/forwarder.pid" ] && [ "$(cat "$PID_DIR/forwarder.pid")" != "$FWD_PID" ] && \
    echo "    (note: pid file stale — run start-all.sh to refresh)"
else
  echo "  forwarder: stopped"
fi

echo ""
echo "=== Health ==="
curl -sf http://localhost:8080 >/dev/null && echo "  Evolution API (:8080): OK" || echo "  Evolution API (:8080): DOWN"
curl -sf http://localhost:5000/health 2>/dev/null && echo "" || echo "  Forwarder (:5000): DOWN"

echo ""
echo "=== Logs ==="
echo "  $ROOT/logs/evolution-api.log"
echo "  $ROOT/logs/forwarder.log"
