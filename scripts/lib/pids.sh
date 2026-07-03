#!/usr/bin/env bash
# Shared PID helpers for evolution-api stack scripts.
# Process cmdlines are often relative (./src/main.ts, python3 app.py) — match loosely,
# then confirm via /proc when needed.

ROOT="${ROOT:-/mnt/1tb/evolution-api}"
FORWARDER_DIR="${FORWARDER_DIR:-$ROOT/forwarder}"

# PID listening on a TCP port (from ss), or empty.
pid_on_port() {
  ss -tlnp 2>/dev/null | grep ":$1 " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1
}

find_api_pid() {
  local p port_pid
  # Prefer whoever is actually listening (matches Health check)
  port_pid=$(pid_on_port 8080)
  [ -n "$port_pid" ] && { echo "$port_pid"; return; }
  p=$(pgrep -f "${ROOT}/dist/main" 2>/dev/null | head -1) && { echo "$p"; return; }
  p=$(pgrep -f "dist/main" 2>/dev/null | head -1) && { echo "$p"; return; }
  for p in $(pgrep -f "src/main.ts" 2>/dev/null); do
    [ "$(basename "$(readlink -f "/proc/$p/exe" 2>/dev/null)" 2>/dev/null)" = "node" ] && { echo "$p"; return; }
  done
}

find_forwarder_pid() {
  local p port_pid cwd
  port_pid=$(pid_on_port 5000)
  [ -n "$port_pid" ] && { echo "$port_pid"; return; }
  for p in $(pgrep -x python3 2>/dev/null); do
    cwd=$(readlink -f "/proc/$p/cwd" 2>/dev/null || true)
    if [ "$cwd" = "$FORWARDER_DIR" ] && tr '\0' ' ' < "/proc/$p/cmdline" | grep -q 'app.py'; then
      echo "$p"
      return
    fi
  done
}
