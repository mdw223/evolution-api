#!/usr/bin/env bash
# Check status of NC Triangle Muslims WhatsApp stack
ROOT="/mnt/1tb/evolution-api"
PID_DIR="$ROOT/logs"

echo "=== Docker ==="
docker ps --filter name=evolution_ --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "Docker not running"

echo ""
echo "=== Processes ==="
for name in evolution-api forwarder; do
  pidfile="$PID_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "  $name: running (pid $(cat "$pidfile"))"
  else
    echo "  $name: stopped"
  fi
done

echo ""
echo "=== Health ==="
curl -sf http://localhost:8080 >/dev/null && echo "  Evolution API (:8080): OK" || echo "  Evolution API (:8080): DOWN"
curl -sf http://localhost:5000/health 2>/dev/null && echo "" || echo "  Forwarder (:5000): DOWN"

echo ""
echo "=== Logs ==="
echo "  $ROOT/logs/evolution-api.log"
echo "  $ROOT/logs/forwarder.log"
