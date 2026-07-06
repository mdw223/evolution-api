# Secrets rotation & Cursor privacy

Guide for **NC Triangle Muslims** stack: `evolution-api` (server + forwarder) and `nctrianglemuslims-ui` (Vite + Vercel).

Rotate everything below if secrets appeared in chat, terminal output, shell history, or a screenshot.

---

## Before you start

1. **Generate new values** (run on your machine):

   ```bash
   openssl rand -hex 32    # API keys, session secrets, passwords
   openssl rand -base64 24  # human-memorable admin password (optional)
   ```

2. **Work in order**: generate → update **all** places that use a secret → restart services → verify → revoke old credentials.

3. **Never commit** `.env`, `.env.local`, `.env.neon`, or real values in `config.yaml`.

---

## Secret inventory (both projects)

| Secret | evolution-api `.env` | nctrianglemuslims-ui | External console |
|--------|----------------------|----------------------|------------------|
| Evolution API auth | `AUTHENTICATION_API_KEY` | — | — |
| Pipeline ingest | `PIPELINE_API_KEY` | Vercel: `PIPELINE_API_KEY` | Must **match** on both sides |
| Postgres (local Docker) | `DATABASE_CONNECTION_URI`, `POSTGRES_PASSWORD` | `.env.local` `POSTGRES_URL` | `docker-compose.deps.yaml` |
| Postgres (cloud) | — | Vercel: `POSTGRES_URL`, `POSTGRES_URL_NON_POOLING` | Neon / Vercel Storage |
| Admin dashboard | — | Vercel: `ADMIN_PASSWORD`, `ADMIN_SESSION_SECRET` | — |
| R2 flyers | `R2_*` | Vercel: `R2_*` | Cloudflare R2 → API tokens |
| Gemini (Tier 3) | `GEMINI_API_KEY` | — | Google AI Studio |
| WhatsApp Meta webhook | `WA_BUSINESS_TOKEN_WEBHOOK` | — | Meta Developer Console |
| Metrics | `METRICS_PASSWORD` | — | — |
| Redis | `CACHE_REDIS_URI` (if password in URL) | — | — |
| S3 / MinIO | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | — | AWS / MinIO |
| SQS | `SQS_ACCESS_KEY_ID`, `SQS_SECRET_ACCESS_KEY` | — | AWS IAM |
| Pusher | `PUSHER_GLOBAL_SECRET`, etc. | — | Pusher dashboard |
| Proxy | `PROXY_PASSWORD` | — | — |
| Chatwoot import DB | `CHATWOOT_IMPORT_DATABASE_CONNECTION_URI` | — | — |
| SSL private key path | `SSL_CONF_PRIVKEY` | — | filesystem (re-issue cert if compromised) |
| Forwarder | reads parent `.env` via `forwarder/config.yaml` | — | same as evolution-api |

**Files to touch locally**

| Repo | Files |
|------|--------|
| evolution-api | `.env`, `forwarder/config.yaml` (no secrets inline — uses `.env`) |
| nctrianglemuslims-ui | `.env.local`, `.env.neon` |

---

## Rotation procedures

### 1. `AUTHENTICATION_API_KEY` (Evolution API)

**Used by:** Evolution REST API, forwarder (`forwarder/forwarder.py` reads from `.env`).

1. Generate: `openssl rand -hex 32`
2. Set in `evolution-api/.env` → `AUTHENTICATION_API_KEY`
3. Restart Evolution API and forwarder:

   ```bash
   cd /mnt/1tb/evolution-api
   docker compose restart evolution-api   # or your process manager
   sudo systemctl restart forwarder       # if applicable
   ```

4. Update any external clients that call Evolution with the `apikey` header.

---

### 2. `PIPELINE_API_KEY` (cross-project — rotate together)

**Used by:** `forwarder/event_pipeline` → `POST /api/events/ingest` on the UI.

1. Generate one new key: `openssl rand -hex 32`
2. Update **both**:
   - `evolution-api/.env` → `PIPELINE_API_KEY`
   - **Vercel** → `nctrianglemuslims-ui` project → Environment Variables → `PIPELINE_API_KEY` (Preview + Production)
3. Optionally mirror in `nctrianglemuslims-ui/.env.local` for local ingest tests.
4. Restart forwarder / event pipeline.
5. Redeploy Vercel (or wait for next deploy).
6. Test: pipeline log shows 201 on ingest, not 401.

---

### 3. Postgres passwords

#### Local Docker (`evolution-api`)

1. Choose new password.
2. Update **all** of these to the same value:
   - `evolution-api/.env` → `POSTGRES_PASSWORD`
   - `evolution-api/.env` → `DATABASE_CONNECTION_URI` (password in URL)
   - `nctrianglemuslims-ui/.env.local` → `POSTGRES_URL` (password in URL)
3. Recreate Postgres with new password (password is set at volume init):

   ```bash
   cd /mnt/1tb/evolution-api
   docker compose -f docker-compose.deps.yaml down
   # Only if you accept wiping local DB — backup first if needed:
   # docker volume rm evolution-api_postgres_data  # name may vary; check docker volume ls
   docker compose -f docker-compose.deps.yaml up -d
   npm run db:deploy   # evolution-api Prisma
   cd /mnt/1tb/nctrianglemuslims-ui && pnpm db:push && pnpm db:import
   ```

   **Less destructive:** change password inside running Postgres with `ALTER USER`, then update `.env` files only.

   **Less destructive Postgres password rotation** — change the password in the running database, then update your `.env` files. No volume wipe, no data loss.

## 1. Generate a new password

```bash
openssl rand -hex 32
```

Save the output as `NEW_PASSWORD`.

## 2. Connect to Postgres inside the running container

```bash
cd /mnt/1tb/evolution-api

docker exec -it evolution_postgres psql -U evolution -d evolution_db
```

If that fails (wrong current password), use the superuser inside the container:

```bash
docker exec -it evolution_postgres psql -U postgres
```

## 3. Change the password with `ALTER USER`

In the `psql` prompt:

```sql
ALTER USER evolution WITH PASSWORD 'NEW_PASSWORD';
```

Replace `NEW_PASSWORD` with the value from step 1. Use single quotes; escape any `'` in the password as `''`.

Verify:

```sql
\du evolution
\q
```

## 4. Test the new password from the host

```bash
PGPASSWORD='NEW_PASSWORD' psql -h 127.0.0.1 -p 5432 -U evolution -d evolution_db -c 'SELECT 1;'
```

If you also use database `nctrianglemuslims` (UI project), test that too:

```bash
PGPASSWORD='NEW_PASSWORD' psql -h 127.0.0.1 -p 5432 -U evolution -d nctrianglemuslims -c 'SELECT 1;'
```

## 5. Update all connection strings (same password everywhere)

Update these to use `NEW_PASSWORD`:

| File | Variable |
|------|----------|
| `evolution-api/.env` | `POSTGRES_PASSWORD` |
| `evolution-api/.env` | `DATABASE_CONNECTION_URI` |
| `nctrianglemuslims-ui/.env.local` | `POSTGRES_URL` |

Example URI format:

```
postgresql://evolution:NEW_PASSWORD@localhost:5432/evolution_db?schema=evolution_api
```

URL-encode special characters in the password if needed (`@`, `#`, `/`, etc.).

## 6. Restart apps that hold DB connections

```bash
cd /mnt/1tb/evolution-api
docker compose restart evolution-api   # if you run API in Docker

# forwarder / systemd if applicable
sudo systemctl restart forwarder
```

You do **not** need to recreate the Postgres container for this approach. `POSTGRES_PASSWORD` in `docker-compose.deps.yaml` is only used at first init; after `ALTER USER`, the live DB password is what matters.

## 7. Verify

```bash
cd /mnt/1tb/evolution-api
npm run db:deploy   # or: npx prisma db execute --stdin <<< "SELECT 1"

cd /mnt/1tb/nctrianglemuslims-ui
pnpm db:push        # optional sanity check
```

---

### One-liner (no interactive `psql`)

```bash
NEW_PASSWORD="$(openssl rand -hex 32)"
echo "New password: $NEW_PASSWORD"

docker exec -i evolution_postgres psql -U evolution -d evolution_db -c "ALTER USER evolution WITH PASSWORD '$NEW_PASSWORD';"
```

Then update `.env` files and restart apps as above.

---

### Notes

- **Order:** `ALTER USER` first, then update `.env` and restart apps. Old connections may keep working until they reconnect.
- **Multiple roles:** If another user exists (e.g. `postgres`), rotate each with `ALTER USER <name> WITH PASSWORD '...';`.
- **Neon/cloud:** Use the Neon or Vercel console to reset credentials; `ALTER USER` on local Docker does not apply there.

#### Neon (Vercel / production)

1. **Neon console** or **Vercel → Storage → Postgres → Reset credentials** (or rotate role password in Neon).
2. Vercel auto-updates `POSTGRES_URL` and `POSTGRES_URL_NON_POOLING` if integrated via marketplace.
3. Update `nctrianglemuslims-ui/.env.neon` with new `POSTGRES_URL_NON_POOLING`.
4. No app redeploy needed if Vercel env vars update in place; redeploy if you edit vars manually.
5. Test: preview `/api/events` returns JSON.

---

### 4. Admin dashboard (`nctrianglemuslims-ui` / Vercel only)

| Variable | Action |
|----------|--------|
| `ADMIN_PASSWORD` | New strong password in Vercel (+ `.env.local` for dev) |
| `ADMIN_SESSION_SECRET` | `openssl rand -hex 32` → Vercel (+ `.env.local`) |

After rotation, all existing admin cookies are invalid (users must log in again).

---

### 5. Cloudflare R2

**Used by:** evolution forwarder (flyer upload) + UI public submit (`R2_*` on Vercel).

1. Cloudflare Dashboard → **R2** → **Manage R2 API tokens** → **Create API token** (or roll existing).
2. Update **both**:
   - `evolution-api/.env` → `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL_BASE`
   - **Vercel** → same `R2_*` vars for `nctrianglemuslims-ui`
3. Delete old API token in Cloudflare.
4. Test: submit event with flyer on preview; pipeline flyer upload still works.

`R2_PUBLIC_URL_BASE` is not secret but must stay consistent with bucket public URL.

---

### 6. `GEMINI_API_KEY`

1. [Google AI Studio](https://aistudio.googlR2_ACCESS_KEY_IDe.com/apikey) → create new key → delete old.
2. `evolution-api/.env` → `GEMINI_API_KEY`
3. Restart forwarder / pipeline.

---

### 7. Other evolution-api secrets (if enabled)

| Variable | Where to rotate |
|----------|-----------------|
| `WA_BUSINESS_TOKEN_WEBHOOK` | Meta App → WhatsApp → Webhook verify token |
| `METRICS_PASSWORD` | `.env` only |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | AWS IAM / MinIO console |
| `SQS_ACCESS_KEY_ID` / `SQS_SECRET_ACCESS_KEY` | AWS IAM |
| `PUSHER_GLOBAL_SECRET` | Pusher app settings |
| `CACHE_REDIS_URI` | Redis `CONFIG SET requirepass` + update URL |
| `PROXY_PASSWORD` | Proxy provider |
| `CHATWOOT_IMPORT_DATABASE_CONNECTION_URI` | Chatwoot DB admin |

---

## Post-rotation checklist

- [ ] Evolution API health / instance list works with new `apikey`
- [ ] Forwarder still forwards messages
- [ ] Pipeline ingest returns 201 on Vercel preview
- [ ] `/api/events` loads on preview
- [ ] `/admin` login works with new password
- [ ] Flyer upload works (R2)
- [ ] Old API keys / tokens **revoked** in provider consoles
- [ ] Shell history: consider `history -c` or remove lines containing secrets
- [ ] Git: `git log -p` and branches never contained `.env` (they should be gitignored)

---

## Prevent Cursor from reading `.env*` files

### 1. `.cursorignore` (recommended — both repos)

Each repo now includes `.cursorignore` entries for env files. Cursor treats this like `.gitignore` for **indexing and Agent file access**.

Patterns used:

```gitignore
**/.env
**/.env.*
!**/.env.example
!**/.env.neon.example
```

After adding or editing `.cursorignore`, **reload the Cursor window** (Command Palette → “Developer: Reload Window”) so indexing picks up changes.

### 2. Do not open env files during Agent chats

If `.env.local` is **open in an editor tab**, Cursor may still include it in context. Close those tabs before using Agent.

### 3. User Rule (optional, global)

Cursor → **Settings → Rules** → add:

> Never read, open, cat, grep, or cite contents of `.env`, `.env.local`, `.env.neon`, or any file matching `.env.*` except `.env.example` and `.env.neon.example`. If configuration is needed, refer to `.env.example` variable names only and ask the user to set values locally.

### 4. `.gitignore` (already required)

Both projects gitignore `*.local` and `.env.neon`. **Never** force-add env files to git.

### 5. What `.cursorignore` does *not* do

- Does not redact secrets already pasted in **chat history**
- Does not block **you** from manually `@`-mentioning a file
- Does not replace **Vercel / Neon / Cloudflare** access controls
- Agent in **terminal** can still run `cat .env` unless you avoid that — prefer `grep '^VAR_NAME=' .env.example` for structure

### 6. If secrets already leaked in Cursor chat

1. Rotate using this doc (assume compromised).
2. Start a **new chat** for future work (old transcripts may retain context).
3. Rotate Neon password if DB URL appeared in terminal output.

---

## Quick command reference

```bash
# Generate secrets
openssl rand -hex 32

# UI: push schema to Neon (uses .env.neon, not .env.local)
cd /mnt/1tb/nctrianglemuslims-ui
cp .env.neon.example .env.neon   # once
pnpm db:push:neon
pnpm db:import:neon

# Verify which DB a script targets (look for log line)
pnpm db:push:neon   # → "remote — ep-....neon.tech"
pnpm db:push        # → "local Postgres (localhost)"
```

---

## Related docs

- [commands.md](./commands.md) — ops commands
- [Evolution-API-Message-to-Website-Calendar-Database.md](./Evolution-API-Message-to-Website-Calendar-Database.md) — pipeline + Vercel setup
- `nctrianglemuslims-ui/.env.example` — UI env template
- `evolution-api/.env.example` — full Evolution + pipeline template
