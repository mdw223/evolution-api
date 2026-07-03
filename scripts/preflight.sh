#!/usr/bin/env bash
# Validate .env, DB credentials, manager UI, and optional DB connectivity.
# Exit 0 = OK, 1 = fix required before starting the stack.
set -euo pipefail

ROOT="/mnt/1tb/evolution-api"
ENV_FILE="$ROOT/.env"
ERRORS=0

warn() { echo "WARNING: $*" >&2; }
fail() { echo "ERROR: $*" >&2; ERRORS=$((ERRORS + 1)); }
ok() { echo "  OK: $*"; }

echo "=== Evolution stack preflight ==="

if [ ! -f "$ENV_FILE" ]; then
  fail "Missing $ENV_FILE — copy .env.example to .env and set secrets."
  exit 1
fi

read_env() {
  grep -E "^${1}=" "$ENV_FILE" | head -1 | cut -d= -f2-
}

POSTGRES_PASSWORD=$(read_env POSTGRES_PASSWORD)
DATABASE_CONNECTION_URI=$(read_env DATABASE_CONNECTION_URI)
AUTHENTICATION_API_KEY=$(read_env AUTHENTICATION_API_KEY)
POSTGRES_USERNAME=$(read_env POSTGRES_USERNAME)
POSTGRES_DATABASE=$(read_env POSTGRES_DATABASE)
POSTGRES_USERNAME=${POSTGRES_USERNAME:-evolution}
POSTGRES_DATABASE=${POSTGRES_DATABASE:-evolution_db}
export DATABASE_CONNECTION_URI POSTGRES_PASSWORD

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  fail "POSTGRES_PASSWORD is empty in .env"
else
  ok "POSTGRES_PASSWORD is set"
fi

if [ -z "${DATABASE_CONNECTION_URI:-}" ]; then
  fail "DATABASE_CONNECTION_URI is empty in .env"
else
  URI_PASS=$(python3 - <<'PY'
import os
from urllib.parse import urlparse
uri = os.environ.get("DATABASE_CONNECTION_URI", "")
print(urlparse(uri).password or "")
PY
)
  if [ "$URI_PASS" != "$POSTGRES_PASSWORD" ]; then
    fail "DATABASE_CONNECTION_URI password does not match POSTGRES_PASSWORD."
    echo "       Update DATABASE_CONNECTION_URI to use the same password as POSTGRES_PASSWORD." >&2
    echo "       See docs/github-prep.md — do NOT change POSTGRES_PASSWORD alone (requires DB wipe)." >&2
  else
    ok "DATABASE_CONNECTION_URI password matches POSTGRES_PASSWORD"
  fi
fi

if [ -z "${AUTHENTICATION_API_KEY:-}" ]; then
  fail "AUTHENTICATION_API_KEY is empty in .env"
else
  ok "AUTHENTICATION_API_KEY is set"
fi

if [ ! -f "$ROOT/manager/dist/index.html" ]; then
  fail "Manager UI missing at manager/dist/ — run ./manager_install.sh or copy a built manager/dist."
else
  ok "Manager UI (manager/dist) present"
fi

if ! command -v docker >/dev/null 2>&1; then
  fail "docker not found in PATH"
elif ! docker info >/dev/null 2>&1; then
  fail "docker daemon not running"
else
  ok "docker available"
fi

if command -v ss >/dev/null 2>&1; then
  if ss -tln | grep -q ':8080 '; then
    warn "Port 8080 already in use (Evolution API may already be running)"
  fi
  if ss -tln | grep -q ':5000 '; then
    warn "Port 5000 already in use (forwarder may already be running)"
  fi
fi

# Optional: test DB auth when Postgres container is up
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx evolution_postgres; then
  if docker exec evolution_postgres pg_isready -U "${POSTGRES_USERNAME:-evolution}" -d "${POSTGRES_DATABASE:-evolution_db}" >/dev/null 2>&1; then
    if docker run --rm --network host postgres:15 \
      psql "postgresql://${POSTGRES_USERNAME}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DATABASE}" \
      -c 'SELECT 1' >/dev/null 2>&1; then
      ok "Postgres accepts credentials from host"
    else
      fail "Postgres is up but password auth fails from host (Prisma P1000 risk)"
    fi
    if ! docker run --rm --network host postgres:15 \
      psql "postgresql://${POSTGRES_USERNAME}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DATABASE}" \
      -c 'SELECT 1 FROM evolution_api."Instance" LIMIT 1' >/dev/null 2>&1; then
      warn "evolution_api schema empty or missing — run: npm run db:deploy"
    else
      ok "evolution_api schema has Instance table"
    fi
  fi
fi

echo ""
if [ "$ERRORS" -gt 0 ]; then
  echo "Preflight FAILED ($ERRORS error(s)). Fix the issues above before starting."
  exit 1
fi

echo "Preflight passed."
exit 0
