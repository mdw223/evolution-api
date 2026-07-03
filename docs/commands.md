# Run Commands — NC Triangle Muslims Stack

Quick reference for starting, stopping, and checking each service.

**Project root:** `/mnt/1tb/evolution-api`

**Secrets:** copy `.env.example` → `.env` and set passwords there. See [github-prep.md](github-prep.md) before pushing to GitHub.

---

## All at once (recommended)

```bash
# Start Docker + Evolution API + forwarder
/mnt/1tb/evolution-api/scripts/start-all.sh

# Check status
/mnt/1tb/evolution-api/scripts/status.sh

# Stop everything
/mnt/1tb/evolution-api/scripts/stop-all.sh

# Tail logs
tail -f /mnt/1tb/evolution-api/logs/evolution-api.log \
        /mnt/1tb/evolution-api/logs/forwarder.log
```

---

## 1. Docker — PostgreSQL + Redis

**Start:**

```bash
cd /mnt/1tb/evolution-api
docker compose -f docker-compose.deps.yaml up -d
```

**Check:**

```bash
docker ps --filter name=evolution_
docker exec evolution_postgres pg_isready -U evolution -d evolution_db
docker exec evolution_redis redis-cli ping
```

**Logs:**

```bash
docker logs evolution_postgres --tail 50
docker logs evolution_redis --tail 50
```

**Stop:**

```bash
cd /mnt/1tb/evolution-api
docker compose -f docker-compose.deps.yaml down
```

**Reset Postgres** (wipes DB — only if password/schema broken):

```bash
cd /mnt/1tb/evolution-api
docker compose -f docker-compose.deps.yaml down
sudo rm -rf postgres-data
docker compose -f docker-compose.deps.yaml up -d
```

---

## 2. Evolution API (npm)

Requires Docker deps running first.

**Start (dev — hot reload, editable `src/`):**

```bash
cd /mnt/1tb/evolution-api
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
nvm use 20
export DATABASE_PROVIDER=postgresql
npm run dev:server
```

**Start (background, via start-all.sh logic):**

```bash
cd /mnt/1tb/evolution-api
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
nvm use 20
export DATABASE_PROVIDER=postgresql
nohup npm run dev:server >> logs/evolution-api.log 2>&1 &
```

**Start (production build):**

```bash
cd /mnt/1tb/evolution-api
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
nvm use 20
npm run build
npm run start:prod
```

**First-time / after schema changes:**

```bash
cd /mnt/1tb/evolution-api
npm install
export DATABASE_PROVIDER=postgresql
npm run db:generate
npm run db:deploy
```

**Check:**

```bash
curl http://localhost:8080
```

**Stop** (if started in foreground): `Ctrl+C`

**Stop** (if background):

```bash
pkill -f "tsx watch ./src/main.ts"
# or use scripts/stop-all.sh
```

---

## 3. Python forwarder

Requires Evolution API running (webhooks go to `:5000`).

**Start (foreground):**

```bash
cd /mnt/1tb/evolution-api/forwarder
python3 app.py
```

**Start (background):**

```bash
cd /mnt/1tb/evolution-api/forwarder
nohup python3 app.py >> ../logs/forwarder.log 2>&1 &
```

**Check:**

```bash
curl http://localhost:5000/health
```

**Stop:**

```bash
pkill -f "/mnt/1tb/evolution-api/forwarder/app.py"
# or use scripts/stop-all.sh
```

**Config:** `forwarder/config.yaml` — source groups, target group, `forward_own_messages`

---

## Useful API commands

Set API key once per shell:

```bash
cd /mnt/1tb/evolution-api
export APIKEY=$(grep AUTHENTICATION_API_KEY .env | cut -d= -f2)
```

**Connection state:**

```bash
curl -s http://localhost:8080/instance/connectionState/nc-triangle-muslims \
  -H "apikey: $APIKEY"
```

**List groups:**

```bash
curl -s "http://localhost:8080/group/fetchAllGroups/nc-triangle-muslims?getParticipants=false" \
  -H "apikey: $APIKEY" | jq '.[] | {subject, id}'
```

**Send test message to target group:**

```bash
curl -s -X POST http://localhost:8080/message/sendText/nc-triangle-muslims \
  -H "apikey: $APIKEY" -H "Content-Type: application/json" \
  -d '{"number":"120363429717652375@g.us","text":"Manual test message"}'
```

---

## Startup order

Always start in this order:

1. Docker (Postgres + Redis)
2. Evolution API (`:8080`)
3. Python forwarder (`:5000`)

`scripts/start-all.sh` does this automatically.

---

## Ports

| Service | Port |
|---------|------|
| Evolution API | 8080 |
| Forwarder webhook | 5000 |
| PostgreSQL | 127.0.0.1:5432 |
| Redis | 127.0.0.1:6379 |

---

## Related docs

- [setup-plan.md](setup-plan.md) — initial server install
- [group-message-forwarder.md](group-message-forwarder.md) — forwarder design and config
- [groups-list.md](groups-list.md) — group JID reference
