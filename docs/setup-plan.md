# Evolution API — Source Install on `/mnt/1tb`

> NC Triangle Muslims automation — server setup log and runbook.
> Last updated after initial install + debugging session (Jul 2026).

## Goal

Read messages + images from Muslim community WhatsApp groups → forward to a single group → AI pipeline → calendar/DB.

**Approach chosen:** Evolution API v2 from **source** (not Docker for the API) so `src/` is editable. Docker runs **only** PostgreSQL + Redis.

---

## Progress checklist

- [x] Clone repo to `/mnt/1tb/evolution-api`
- [x] Create `docker-compose.deps.yaml` (Postgres + Redis only)
- [x] Install Node.js 20 via nvm
- [x] Configure `.env` (localhost DB/Redis, webhooks, API key)
- [x] `npm install` (required before migrations — see troubleshooting)
- [x] Add `/mnt/1tb` to `/etc/fstab` for boot persistence
- [x] `npm run db:generate` + `npm run db:deploy` (after npm install)
- [x] Instance `nc-triangle-muslims` connected (`open` state — QR scan pending)
- [ ] pm2 for 24/7 uptime
- [x] Python webhook forwarder on port 5000

**Run commands:** see [commands.md](commands.md) · **GitHub prep:** see [github-prep.md](github-prep.md)

---

## Architecture


| Component            | How it runs                   | Why                                       |
| -------------------- | ----------------------------- | ----------------------------------------- |
| Evolution API        | **Source / npm** on host      | Edit `src/`, hot reload with `dev:server` |
| PostgreSQL           | Docker (`evolution_postgres`) | Isolated, easy to reset                   |
| Redis                | Docker (`evolution_redis`)    | Cache for Evolution API                   |
| Evolution Manager UI | Optional                      | Used to view instance / QR in browser     |


Official repo: [evolution-foundation/evolution-api](https://github.com/evolution-foundation/evolution-api)

---

## Storage: `/mnt/1tb` vs internal NVMe

**Use `/mnt/1tb`** — ~870 GB free vs ~200 GB on root (`/`).

Running on the SSD does **not** keep services "always on". For 24/7 uptime you need:

1. **fstab auto-mount** — so `/mnt/1tb` mounts on boot
2. **pm2 or systemd** — restart Node if it crashes
3. **Docker `restart: always`** — for Postgres + Redis

### `/etc/fstab` entry (ext4)

**Do not use** `UUID=260811EE0811BDAD` — that is leftover **NTFS** metadata. The drive is **ext4**.

**Do not use** `uid=1000,gid=1000,umask=002` — those are NTFS-3g options (like the Immich line). ext4 uses native Unix permissions.

```
UUID=7a8e89f1-f758-42a3-bcb7-40b2cb1cecb1  /mnt/1tb  ext4  defaults,nofail  0  2
```

Verify with `lsblk -f /dev/sdb1`, then:

```bash
sudo mount -a
findmnt /mnt/1tb
df -h /mnt/1tb
```

---

## Step 1 — Clone the repo

```bash
cd /mnt/1tb
git clone https://github.com/evolution-foundation/evolution-api.git
cd evolution-api
```

---

## Step 2 — Docker for PostgreSQL + Redis only

File: `docker-compose.deps.yaml`

```yaml
services:
  evolution-postgres:
    environment:
      POSTGRES_DB: ${POSTGRES_DATABASE:-evolution_db}
      POSTGRES_USER: ${POSTGRES_USERNAME:-evolution}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
    env_file:
      - .env
```

```bash
docker compose -f docker-compose.deps.yaml up -d
```

### Postgres password gotcha

If Postgres was first started with the literal placeholder `<generate-strong-password>`, changing `.env` alone is **not enough**. Postgres only reads the password at **first init**. To apply a new password:

```bash
docker compose -f docker-compose.deps.yaml down
sudo rm -rf postgres-data
docker compose -f docker-compose.deps.yaml up -d
```

Redis data can stay; only Postgres needs reset if the password changed.

---

## Step 3 — Install Node.js

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20
```

---

## Step 4 — Configure `.env`

```bash
cp .env.example .env
```

**Critical:** defaults use Docker hostnames (`postgres:5432`). When running the API **from source on the host**, use `localhost`:

```bash
SERVER_URL=http://localhost:8080
DATABASE_PROVIDER=postgresql
DATABASE_CONNECTION_URI=postgresql://evolution:<password>@localhost:5432/evolution_db?schema=evolution_api
CACHE_REDIS_ENABLED=true
CACHE_REDIS_URI=redis://localhost:6379/6

# Self-defined secret — NOT from WhatsApp. Generate with: openssl rand -hex 32
AUTHENTICATION_API_KEY=<your-generated-key>

# For NC Triangle Muslims automation (future Python script):
WEBHOOK_GLOBAL_ENABLED=true
WEBHOOK_GLOBAL_URL=http://localhost:5000/webhook
DATABASE_SAVE_DATA_NEW_MESSAGE=true
```

Find your API key anytime:

```bash
grep AUTHENTICATION_API_KEY /mnt/1tb/evolution-api/.env
```

**Do not commit `.env`** — it contains DB password and API key.

---

## Step 5 — Install dependencies (do this first!)

```bash
cd /mnt/1tb/evolution-api
npm install
```

### Troubleshooting: `Cannot find module 'dotenv'` / `tsx: not found`

**Cause:** `node_modules/` missing — `npm install` was skipped or failed.

**Fix:** run `npm install` before any other npm scripts.

If root disk was full (we hit `no space left on device` during Immich cleanup), free space first, then retry:

```bash
NODE_OPTIONS=--max-old-space-size=4096 npm install
```

---

## Step 6 — Database migrations

```bash
export DATABASE_PROVIDER=postgresql
npm run db:generate
npm run db:deploy
```

---

## Step 7 — Run the API

**Development (editable code + hot reload):**

```bash
npm run dev:server
```

API listens on `http://localhost:8080`.

**Production (24/7):**

```bash
npm run build
npm run start:prod
# or with pm2:
pm2 start npm --name evolution-api -- run start:prod
pm2 save && pm2 startup
```

---

## Step 8 — WhatsApp instance

### What is an instance?

One **linked WhatsApp session** — like WhatsApp Web / a linked device on your iPhone. One instance = one phone number connection managed by the API.

Our instance name: `**nc-triangle-muslims`**

### Create instance

```bash
curl -X POST http://localhost:8080/instance/create \
  -H "apikey: $(grep AUTHENTICATION_API_KEY .env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"instanceName":"nc-triangle-muslims","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'
```

### Connection states


| State        | Meaning                               |
| ------------ | ------------------------------------- |
| `connecting` | Waiting for QR scan (or reconnecting) |
| `open`       | Connected — ready to send/receive     |
| `close`      | Disconnected / logged out             |


`**connecting` = scan the QR code first.** Use iPhone: WhatsApp → Settings → Linked Devices → Link a Device.

### Check connection (use curl, not bare `GET` in shell)

```bash
curl -s http://localhost:8080/instance/connectionState/nc-triangle-muslims \
  -H "apikey: $(grep AUTHENTICATION_API_KEY .env | cut -d= -f2)"
```

### Get / refresh QR code

```bash
curl -s http://localhost:8080/instance/connect/nc-triangle-muslims \
  -H "apikey: $(grep AUTHENTICATION_API_KEY .env | cut -d= -f2)"
```

QR codes expire in ~30–60 seconds — fetch a fresh one if scan fails.

---

## Server cleanup (done during setup)

Freed root disk space by removing old Immich stack:

```bash
cd ~/immich-app
docker compose down
cd ~
sudo rm -rf ~/immich-app
rm ~/cloudflared.deb
```

**Lesson:** stop Docker containers before deleting data dirs. `postgres/` and `library/` had root-owned files from containers — `sudo rm -rf ~/immich-app` from home dir removes everything including hidden `.env`.

---

## What comes next

1. **Scan QR** → get `nc-triangle-muslims` to `open` state
2. **Python webhook receiver** on port 5000 — filter by group `remoteJid`, forward text/images to target group
3. **AI pipeline** — process message + image data from webhooks
4. **Calendar/DB** — store structured events
5. **pm2 + fstab** — survive reboots

---

## Risks

- **WhatsApp ban risk** with unofficial APIs — linked-device mode is lower risk but not zero
- **iPhone + Baileys** can be flaky — monitor `connection.update` webhooks
- **API key** protects your Evolution server — anyone with it can control your WhatsApp instance

