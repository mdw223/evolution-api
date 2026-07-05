# Run Commands — NC Triangle Muslims Stack

Quick reference for starting, stopping, and checking each service.

**Project root:** `/mnt/1tb/evolution-api`

**Secrets:** copy `.env.example` → `.env` and set passwords there. See [github-prep.md](github-prep.md) before pushing to GitHub.

---

## All at once (recommended)

```bash
# Validate config before starting (optional but recommended)
/mnt/1tb/evolution-api/scripts/preflight.sh

# Start Docker + Evolution API + forwarder (detached — safe to close terminal)
/mnt/1tb/evolution-api/scripts/start-all.sh

# Production mode (stable, lower overhead — recommended for 24/7)
EVOLUTION_RUN_MODE=prod /mnt/1tb/evolution-api/scripts/start-all.sh

# Check status
/mnt/1tb/evolution-api/scripts/status.sh

# Stop everything
/mnt/1tb/evolution-api/scripts/stop-all.sh

# Tail logs
tail -f /mnt/1tb/evolution-api/logs/evolution-api.log \
        /mnt/1tb/evolution-api/logs/forwarder.log
```

### Detached / 24-7 operation

`start-all.sh` already starts Evolution API and the forwarder with `nohup` + `setsid`, so **you can close your terminal** as soon as the script prints `Done`. Processes keep running on the server.

```bash
# Optional: also detach the startup script itself and log its output
nohup /mnt/1tb/evolution-api/scripts/start-all.sh >> /mnt/1tb/evolution-api/logs/start-all.log 2>&1 &
```

For **surviving server reboots**, use pm2 (recommended) or systemd — see [24/7 uptime](#247-uptime-survive-reboots) below.

---

## Avoiding common issues

| Issue | Prevention |
|-------|------------|
| Prisma `P1000` auth error | Run `scripts/preflight.sh` — `DATABASE_CONNECTION_URI` password **must match** `POSTGRES_PASSWORD` in `.env`. See [github-prep.md](github-prep.md). |
| Forwarder `Address already in use` | Run `scripts/stop-all.sh` before restarting, or use `start-all.sh` (kills stale orphans on :5000/:8080). |
| Manager blank / broken UI | Open `http://<host>:8080/manager/#/manager/login` (note the `#`). Server URL on login = `http://<host>:8080` (**not** `/manager`). |
| Empty instance list | After a fresh DB, create the instance again (Manager or `POST /instance/create`). Run `npm run db:deploy` if schema is missing. |
| Can't open manager from laptop | Forward port **8080** in Cursor/SSH, then browse `http://localhost:<forwarded-port>/manager/#/manager/login`. |

Run preflight anytime:

```bash
/mnt/1tb/evolution-api/scripts/preflight.sh
```

---

## 24/7 uptime (survive reboots)

Docker Postgres/Redis already use `restart: always`. Node and Python **do not** auto-start after reboot unless you add a service manager.

**Option A — pm2 (recommended):**

```bash
npm install -g pm2
cd /mnt/1tb/evolution-api
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 20
npm run build
export DATABASE_PROVIDER=postgresql

# Start API + forwarder under pm2
pm2 start npm --name evolution-api --cwd /mnt/1tb/evolution-api -- run start:prod
pm2 start /mnt/1tb/evolution-api/forwarder/app.py --name evolution-forwarder --interpreter python3

pm2 save
pm2 startup   # follow the printed command (sudo) to enable on boot
```

Ensure Docker deps start on boot (`docker compose -f docker-compose.deps.yaml up -d` in `@reboot` cron or a systemd unit).

**Option B — start-all.sh on login / cron @reboot:**

```bash
# crontab -e
@reboot sleep 30 && /mnt/1tb/evolution-api/scripts/start-all.sh >> /mnt/1tb/evolution-api/logs/start-all.log 2>&1
```

Use `EVOLUTION_RUN_MODE=prod` in cron for production stability.

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

**One-time setup** (venv + easyocr — system `pip` is blocked on Ubuntu):

```bash
cd /mnt/1tb/evolution-api/forwarder
bash scripts/setup-venv.sh
```

**Start (foreground):**

```bash
cd /mnt/1tb/evolution-api/forwarder
./venv/bin/python app.py
```

**Start (background):**

```bash
cd /mnt/1tb/evolution-api/forwarder
nohup ./venv/bin/python app.py >> ../logs/forwarder.log 2>&1 &
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
- [github-prep.md](github-prep.md) — secrets and gitignore before pushing
- [push-to-github.md](push-to-github.md) — commit and push to GitHub
- [group-message-forwarder.md](group-message-forwarder.md) — forwarder design and config
- [groups-list.md](groups-list.md) — group JID reference
