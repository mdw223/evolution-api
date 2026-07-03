# Preparing for Public GitHub

Checklist before pushing this repo publicly.

## 1. Rotate secrets (important)

Passwords and API keys from early setup may have appeared in chat logs or docs. **Generate new ones** before going public:

```bash
cd /mnt/1tb/evolution-api

# New API key
openssl rand -hex 32

# New Postgres password
openssl rand -base64 24 | tr -d '/+=' | head -c 24; echo
```

Update your local **`.env`** (never committed):

```bash
POSTGRES_PASSWORD=<new-password>
POSTGRES_DATABASE=evolution_db
POSTGRES_USERNAME=evolution
DATABASE_CONNECTION_URI=postgresql://evolution:<new-password>@localhost:5432/evolution_db?schema=evolution_api
AUTHENTICATION_API_KEY=<new-api-key>
METRICS_PASSWORD=<new-metrics-password>
```

If you change `POSTGRES_PASSWORD`, recreate the database volume:

```bash
docker compose -f docker-compose.deps.yaml down
sudo rm -rf postgres-data
docker compose -f docker-compose.deps.yaml up -d
npm run db:generate && npm run db:deploy
```

Re-scan WhatsApp QR if the instance session is lost.

---

## 2. Files that must stay local (gitignored)

| File / dir | Contains |
|------------|----------|
| `.env` | All secrets |
| `postgres-data/` | Database files |
| `redis-data/` | Redis persistence |
| `logs/` | Runtime logs, pid files |
| `instances/` | WhatsApp session credentials |

Verify:

```bash
git check-ignore -v .env postgres-data logs/forwarder.log
```

---

## 3. First-time clone setup (for you or others)

```bash
cp .env.example .env
cp forwarder/config.example.yaml forwarder/config.yaml
# Edit .env — set POSTGRES_PASSWORD, DATABASE_CONNECTION_URI, AUTHENTICATION_API_KEY
npm install
docker compose -f docker-compose.deps.yaml up -d
export DATABASE_PROVIDER=postgresql && npm run db:generate && npm run db:deploy
./scripts/start-all.sh
```

The forwarder loads `AUTHENTICATION_API_KEY` from `../.env` automatically (`api_key` in `forwarder/config.yaml` stays empty).

---

## 4. What uses `.env`

| Component | Variables |
|-----------|-----------|
| Evolution API | `DATABASE_CONNECTION_URI`, `AUTHENTICATION_API_KEY`, `CACHE_REDIS_URI`, webhooks, etc. |
| `docker-compose.deps.yaml` | `POSTGRES_DATABASE`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD` |
| Python forwarder | `AUTHENTICATION_API_KEY` (from `../.env`) |

---

## 5. Scan before push

```bash
cd /mnt/1tb/evolution-api
git add -A --dry-run
git diff --cached

# Search for accidental secrets in staged files
git diff --cached | grep -iE 'password|api_key|apikey' | grep -v change_me | grep -v example || true
```

Never commit `.env`, database volumes, or WhatsApp instance data.

---

## 6. Push changes

See [push-to-github.md](push-to-github.md) for commit/push steps and SSH deploy-key setup on this server.
