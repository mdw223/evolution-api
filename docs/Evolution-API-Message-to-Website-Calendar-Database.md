# Evolution API → Website Calendar Database — Progress Log

> **Plan:** execution phases and architecture live in [`Evolution-API-Message-to-Website-Calendar-Database-Plan.md`](./Evolution-API-Message-to-Website-Calendar-Database-Plan.md)
>
> **This file:** running log of what was done, issues hit, and commands that worked.

---

## Phase 0 — Clone UI repo & local dev setup

**Status:** Done

**Goal:** Clone `nctrianglemuslims-ui` to `/mnt/1tb` next to `evolution-api` and get local dev running.

---

### SSH key setup (manual)

The server's existing deploy key (`~/.ssh/evolution_api_deploy`) only has access to `mdw223/evolution-api`, not the private `nctrianglemuslims/nctrianglemuslims-ui` repo.

**What we did:**

1. Copied personal SSH key from laptop to server via `scp`:
   ```bash
   # Run on laptop
   scp ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub abd@192.168.1.118:~/.ssh/
   ```

2. Fixed permissions on server:
   ```bash
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/id_ed25519
   chmod 644 ~/.ssh/id_ed25519.pub
   ```

3. Added `github-personal` host to `~/.ssh/config`:
   ```
   Host github-personal
     HostName github.com
     User git
     IdentityFile ~/.ssh/id_ed25519
     IdentitiesOnly yes
   ```

4. Verified GitHub access:
   ```bash
   ssh -T git@github-personal
   ```

> Key is passphrase-protected — Git prompts for passphrase on first use per session.

> **Update (Phase 1):** day-to-day pushes for `nctrianglemuslims-ui` now use a separate org deploy key (`github-nctrianglemuslims` / `nctrianglemuslims_ui_deploy`). See [Git + SSH for nctrianglemuslims-ui](#git--ssh-for-nctrianglemuslims-ui-2026-07-05) below. Personal key was only needed for the initial clone.

---

### Clone UI repo (manual)

```bash
cd /mnt/1tb
git clone git@github-personal:nctrianglemuslims/nctrianglemuslims-ui.git
```

**Result:** `/mnt/1tb/nctrianglemuslims-ui` cloned successfully.

```
/mnt/1tb/
├── evolution-api/
└── nctrianglemuslims-ui/
```

---

### Install dependencies

#### Attempt 1 — `npm install` (failed)

```bash
cd /mnt/1tb/nctrianglemuslims-ui
npm install
```

**Error:** `ERESOLVE` — `react-day-picker@8.10.1` expects `date-fns` v2/v3, but project has `date-fns@^4.1.0`.

**Note:** Repo ships with `pnpm-lock.yaml` (lockfile v9) — project was authored for **pnpm**, not npm.

#### Attempt 2 — `pnpm@latest` via corepack (failed)

```bash
corepack enable
corepack prepare pnpm@latest --activate
pnpm install
```

**Error:** Latest pnpm (v11) requires Node.js v22.13+ and uses `node:sqlite`. Server runs **Node v20.20.2**.

#### Attempt 3 — `pnpm@9.15.9` (worked)

Pin pnpm 9 to match lockfile format and Node 20:

```bash
cd /mnt/1tb/nctrianglemuslims-ui

corepack enable
corepack prepare pnpm@9.15.9 --activate

pnpm install
pnpm dev
```

**Result:** Dependencies installed. Dev server starts via Vite (default `http://localhost:5173`).

---

### Phase 0 checklist

- [x] Personal SSH key copied to `~/.ssh/`
- [x] `github-personal` host configured in `~/.ssh/config`
- [x] Repo cloned to `/mnt/1tb/nctrianglemuslims-ui`
- [x] `pnpm install` succeeded (pnpm 9.15.9 + Node 20)
- [x] `pnpm dev` runs
- [x] `.env.local` created (single local env file — see Phase 1)
- [x] Site loads in browser — calendar shows events from Postgres API (2026-07-05)

---

## Phase 1 — Vercel Postgres + public calendar API

**Status:** Done locally + **Vercel preview verified** (2026-07-05). Production merge/deploy still TODO.

**Goal:** Replace Google Sheets CSV with Postgres-backed `GET /api/events` + pipeline `POST /api/events/ingest`.

**Repo:** `/mnt/1tb/nctrianglemuslims-ui` (Vite SPA + Vercel serverless API — not Next.js)

**Test branch:** `test/postgres-calendar-api` — preview deployment shows calendar events from Neon Postgres.

---

### What was built

| Piece | Path |
|-------|------|
| Drizzle schema | `nctrianglemuslims-ui/api/lib/db/schema.ts` |
| DB client (Neon) | `nctrianglemuslims-ui/api/lib/db/client.ts` |
| Shared event mapper | `nctrianglemuslims-ui/api/lib/events.ts` |
| Public API | `nctrianglemuslims-ui/api/events.ts` → `GET /api/events` |
| Pipeline ingest API | `nctrianglemuslims-ui/api/events/ingest.ts` → `POST /api/events/ingest` |
| Sheets import script | `nctrianglemuslims-ui/scripts/import-sheets-to-postgres.ts` |
| Local API dev server | `nctrianglemuslims-ui/scripts/dev-api-server.ts` → `pnpm dev:api` |
| Local dev helper | `nctrianglemuslims-ui/scripts/dev.sh` → `pnpm dev:help` |
| Frontend store | `src/stores/eventsStore.tsx` — fetches JSON from API |
| Env template | `nctrianglemuslims-ui/.env.example` |
| Local env loader | `nctrianglemuslims-ui/lib/load-env.ts` (scripts only) |

**Stack note:** Uses `@neondatabase/serverless` + Drizzle (Vercel Postgres is Neon under the hood).

**Vercel bundling note:** Shared `db/` and `lib/events.ts` live under **`api/lib/`** — Vercel serverless functions only bundle files inside `api/`. Imports in handlers use explicit `.js` extensions for ESM (`import … from './lib/db/client.js'`).

---

### Environment setup (2026-07-04)

No Vercel Postgres yet — using **local Docker Postgres** (`evolution_postgres`) with a dedicated database `nctrianglemuslims`.

Created:
- `/mnt/1tb/nctrianglemuslims-ui/.env.local` (single local env file — copy from `.env.example`)

Contains (see file for values):
- `POSTGRES_URL` → `postgresql://evolution:***@localhost:5432/nctrianglemuslims`
- `PIPELINE_API_KEY` → generated via `openssl rand -hex 32`
- `VITE_EVENTS_API_URL=/api/events`
- `SHEETS_CSV_URL` → current Google Sheets publish URL

**When Vercel Postgres is ready:** replace `POSTGRES_URL` in Vercel project env vars + local `.env.local`, then re-run `pnpm db:push` and `pnpm db:import` against production.

**Env file policy:** use **`.env.local` only** (not both `.env` and `.env.local`). Copy from `.env.example`. Drizzle + import scripts load it via `lib/load-env.ts`.

**Local vs cloud:** `.env.local` points at Docker Postgres. Vercel Preview/Production use Neon env vars from the dashboard (`POSTGRES_URL`, `POSTGRES_URL_NON_POOLING`, etc.). Migrations against Neon use the non-pooling URL:

```bash
POSTGRES_URL="<POSTGRES_URL_NON_POOLING from Vercel>" pnpm db:push
POSTGRES_URL="<POSTGRES_URL_NON_POOLING from Vercel>" pnpm db:import
```

---

### Local development (frontend + API)

The UI repo is a **Vite SPA** with **Vercel serverless functions** in `/api/` — not Next.js. Run frontend and backend in **two separate terminals** (do not merge into one process).

**Why not `vercel dev` for local API?** It spawns a **second Vite** and fights for ports 5177–5179. Local API uses `scripts/dev-api-server.ts` instead (API-only on **5177**). Production still deploys `api/` as Vercel serverless functions.

**Why not one script?** Frontend and API stay in two terminals. Port 3000 is **Open WebUI** — proxying there caused `Unexpected token '<'` HTML errors.

**Why not Docker for the UI?** Postgres already runs in Docker via `evolution-api`. Dockerizing Vite + API adds complexity for local hot-reload and does not map to Vercel production (serverless functions, not containers).

**Helper script:**

```bash
cd /mnt/1tb/nctrianglemuslims-ui
pnpm dev:help          # or: bash scripts/dev.sh
```

`scripts/dev.sh` checks:
- `.env.local` exists
- `evolution_postgres` Docker container is running
- Ports **5177** (API) and **5178** (Vite) — free or in use (with PID)

Then prints the two commands to run:

```bash
# Terminal 1 — API (start first)
cd /mnt/1tb/nctrianglemuslims-ui
pnpm dev:api           # tsx scripts/dev-api-server.ts → :5177

# Terminal 2 — Frontend
cd /mnt/1tb/nctrianglemuslims-ui
pnpm dev               # Vite on http://localhost:5178
```

**URLs:**
- Calendar UI: `http://localhost:5178/events`
- API probe: `http://localhost:5177/api/events` (Vite proxies `/api` → `:5177`)

**Common error:** If `vite.config.ts` proxy points at the wrong port (e.g. 3000 = Open WebUI), `/api/events` returns HTML and the calendar shows `Unexpected token '<'`. Fix: proxy target must match `pnpm dev:api` listen port.

**If ports are busy:** override with `DEV_API_PORT` / `DEV_WEB_PORT` and update `vite.config.ts` (`server.port` + proxy `target`) to match.

**Stop stale servers** (if `EADDRINUSE` or port already in use):

```bash
pnpm dev:stop        # kill API (:5177) + frontend (:5178)
pnpm dev:api:stop    # API only
pnpm dev:web:stop    # frontend only
```

Always use **Ctrl+C** in each terminal when done — closing a terminal without stopping can leave Node running in the background.

---

### Local dev troubleshooting (2026-07-05)

**Symptom:** `Could not load events: Unexpected token '<', "<!doctype "... is not valid JSON`

**Cause:** Vite proxied `/api` to port **3000**, which runs **Open WebUI** on this server — not our API. The calendar received HTML instead of JSON.

**Also tried:** `vercel dev --listen 5177` — does **not** run API-only; it spawns a second Vite and competes for ports 5177–5182.

**Fix:**
1. Replaced `pnpm dev:api` with `scripts/dev-api-server.ts` (API-only on **5177**)
2. Pinned frontend to **5178** (`vite.config.ts` → `port: 5178`, `strictPort: true`)
3. Proxy `/api` → `http://localhost:5177`
4. Fixed import paths in `api/events/ingest.ts` (now `api/lib/db/client.js`)
5. Added `pnpm dev:stop` / `dev:api:stop` / `dev:web:stop`

**Verified working (2026-07-05):**
- `http://localhost:5177/api/events` → JSON with 478 events
- `http://localhost:5178/events` → calendar displays events from Postgres

**Daily dev commands:**

```bash
cd /mnt/1tb/nctrianglemuslims-ui

# Terminal 1 — API
pnpm dev:api:stop && pnpm dev:api

# Terminal 2 — Frontend
pnpm dev:web:stop && pnpm dev
```

---

### Database + import (2026-07-04)

```bash
# Created database
docker exec evolution_postgres psql -U evolution -d postgres -c "CREATE DATABASE nctrianglemuslims;"

cd /mnt/1tb/nctrianglemuslims-ui
pnpm exec drizzle-kit push --force   # creates events table + event_status enum
pnpm db:import                     # imports Google Sheets CSV
```

**Result:** `478` events imported, all `published`.

Verify:
```bash
docker exec evolution_postgres psql -U evolution -d nctrianglemuslims \
  -c "SELECT COUNT(*) FROM events;"
```

**Code fix:** `api/lib/db/client.ts` auto-detects localhost → uses `postgres.js` driver; remote Neon URL → uses `@neondatabase/serverless`.

---

### Git + SSH for `nctrianglemuslims-ui` (2026-07-05)

Initial clone used personal key (`github-personal` / `id_ed25519`). Pushes for Vercel deploys now use a **dedicated org deploy key** (separate from `evolution_api_deploy`).

**`~/.ssh/config` (relevant hosts):**

```
# Deploy key — nctrianglemuslims/nctrianglemuslims-ui only
Host github-nctrianglemuslims
  HostName github.com
  User git
  IdentityFile ~/.ssh/nctrianglemuslims_ui_deploy
  IdentitiesOnly yes

# Deploy key — mdw223/evolution-api only
Host github-evolution-api
  ...

# Personal GitHub account
Host github-personal
  ...
```

**Generate org UI deploy key (one-time):**

```bash
ssh-keygen -t ed25519 -C "deploy@nctrianglemuslims/nctrianglemuslims-ui" \
  -f ~/.ssh/nctrianglemuslims_ui_deploy -N ""
```

Add `~/.ssh/nctrianglemuslims_ui_deploy.pub` to GitHub → `nctrianglemuslims-ui` → **Settings → Deploy keys** (enable **Allow write access**).

**Git remote:**

```bash
git remote set-url origin git@github-nctrianglemuslims:nctrianglemuslims/nctrianglemuslims-ui.git
```

**Commit author for Vercel (Hobby + private repo):** commits must use the org identity that owns the Vercel project — not a personal account (`mdw223`). Local config in `nctrianglemuslims-ui`:

```
user.name  = nctrianglemuslims
user.email = nctrianglemuslims@gmail.com
```

Matches existing `main` branch commits. Vercel blocks deploys if commit author lacks contributing access on Hobby private repos.

---

### Vercel preview deployment (2026-07-05)

**Branch:** `test/postgres-calendar-api`

**Neon:** Connected via Vercel Marketplace. Env vars (`POSTGRES_URL`, etc.) scoped to **Production** and **Preview**. Disable Neon **preview branching** if you want preview and production to share the same database.

**Issues hit and fixes:**

| Issue | Fix |
|-------|-----|
| Deployment blocked — commit email `abd@abdserver…` / author `mdw223` | Set git author to `nctrianglemuslims <nctrianglemuslims@gmail.com>`; recommit on test branch |
| Hobby plan — "commit author did not have contributing access" | Same — org author must match Vercel project owner; not fixable with personal `mdw223` commits on Hobby private repos without Pro |
| Re-push same SHA after canceled deploy — no new deployment | Push a new commit (empty or fix) to trigger fresh preview |
| `GET /api/events` → 500 `ERR_MODULE_NOT_FOUND: /var/task/db/client` | Move shared modules to `api/lib/`; use `.js` extensions in API imports (commit `bc10114`) |

**Verified on Vercel preview (2026-07-05):**
- Preview deployment builds successfully
- `/api/events` returns JSON
- `/events` calendar displays events from Neon Postgres

**Vercel env vars to confirm (Preview + Production):**

| Variable | Value |
|----------|-------|
| `POSTGRES_URL` | From Neon integration (pooled) |
| `VITE_EVENTS_API_URL` | `/api/events` |
| `PIPELINE_API_KEY` | `openssl rand -hex 32` (for ingest API) |

`VITE_*` vars are baked at build time — redeploy after adding/changing them.

---

### Phase 1 checklist

- [x] Postgres schema defined (Drizzle)
- [x] `GET /api/events` (published events only)
- [x] `POST /api/events/ingest` (Bearer `PIPELINE_API_KEY`)
- [x] `eventsStore` switched from CSV/papaparse to JSON API
- [x] `App.tsx` uses `VITE_EVENTS_API_URL` (default `/api/events`)
- [x] Sheets → Postgres import script
- [x] `pnpm run build` passes
- [x] `.env.local` with `POSTGRES_URL` + `PIPELINE_API_KEY` (single env file for local dev)
- [x] `pnpm db:push` — tables created in local Postgres
- [x] `pnpm db:import` — 478 existing events migrated
- [x] `scripts/dev.sh` + `pnpm dev:help` — port checks and two-terminal dev instructions
- [x] `scripts/dev-api-server.ts` — local API on :5177 (replaces `vercel dev`)
- [x] Calendar loads events from Postgres API locally (`http://localhost:5178/events`)
- [x] Neon Postgres connected on Vercel (Preview + Production env vars)
- [x] Org deploy key (`nctrianglemuslims_ui_deploy`) + `github-nctrianglemuslims` remote
- [x] Git commit author set to `nctrianglemuslims@gmail.com` for Vercel deploys
- [x] Shared API modules under `api/lib/` (Vercel bundling fix)
- [x] Vercel preview on `test/postgres-calendar-api` — calendar shows events
- [ ] Merge test branch → `main` and verify production deployment
- [x] Add `PIPELINE_API_KEY` on Vercel if not set (needed for Phase 2 ingest)

---

### Next up (Phase 2)

Event pipeline on Linux server — keyword filter + ingest client posting to `/api/events/ingest`.

See plan: [`(plan)Evolution-API-Message-to-Website-Calendar-Database.md`](./(plan)Evolution-API-Message-to-Website-Calendar-Database.md).

---

## Phase 2 — Event pipeline on Linux server

**Status:** Tier 1–3 implemented (2026-07-05). Enable pipeline + env keys for production cutover.

**Goal:** Detect event announcements in source WhatsApp groups and POST structured events to Vercel `POST /api/events/ingest`.

**Location:** `forwarder/event_pipeline/` — dispatched in parallel from `forwarder/app.py` (same port 5000 webhook).

---

### Tier cascade (handle_webhook)

```
Message → OCR (if image) → Tier 1 keywords + regex extract
  ├─ reject (score < 0.1, no image)
  ├─ Tier 1 success → ingest (published if score ≥ 0.5)
  └─ Tier 1 incomplete → Tier 2 Ollama (llama3.1:8b)
       ├─ confidence ≥ 0.75 → ingest published
       ├─ confidence < 0.75 → Tier 3 Gemini (text + vision if image)
       └─ confidence ≥ 0.65 → ingest published, else draft
```

**Image handling:** easyocr runs in `classifier.py` before scoring when `image_base64` is present. Standalone flyer images always `force_pass` to Tier 2 even if OCR empty.

**Flyer upload:** Google Drive folder `1RRVu2N65MXZXAEbw463L4GNkqCAloWr8` via service account (`GOOGLE_SERVICE_ACCOUNT_JSON`). URL format: `https://drive.google.com/uc?id=FILE_ID` (works with frontend `normalizeFlyerUrl`).

---

### What was built (full Phase 2)

| Piece | Path |
|-------|------|
| Pipeline orchestrator | `forwarder/event_pipeline/pipeline.py` |
| Tier 1 keyword classifier (+ OCR) | `forwarder/event_pipeline/classifier.py` |
| Tier 1 regex extractor | `forwarder/event_pipeline/extractor.py` |
| Tier 2 Ollama | `forwarder/event_pipeline/local_llm.py` |
| Tier 3 Gemini | `forwarder/event_pipeline/cloud_llm.py` |
| Flyer OCR | `forwarder/event_pipeline/ocr.py` |
| Google Drive upload | `forwarder/event_pipeline/google_drive.py` |
| LLM prompts | `forwarder/event_pipeline/prompts.py` |
| Ingest URL resolver | `forwarder/event_pipeline/ingest_resolver.py` |
| Keyword dictionary | `forwarder/event_pipeline/event_keywords.yaml` |
| Vercel ingest client | `forwarder/event_pipeline/ingest_client.py` |
| Replay on Sheets data | `forwarder/scripts/test_classifier_from_sheets.py` |

---

### Environment / config to enable

**`evolution-api/.env`** (gitignored — never commit secrets):

```bash
PIPELINE_API_KEY=<same as Vercel>
GEMINI_API_KEY=<from https://aistudio.google.com/apikey>
# Path to JSON key file — NOT the JSON contents, NOT in the repo
GOOGLE_SERVICE_ACCOUNT_JSON=/home/abd/.config/nctrianglemuslims/google-drive-sa.json
```

**`forwarder/config.yaml`:** set `event_pipeline.enabled: true`

---

### Python venv + easyocr (required on Ubuntu/Debian)

System `pip install` fails with `externally-managed-environment` (PEP 668). Use the **forwarder venv**:

```bash
cd /mnt/1tb/evolution-api/forwarder
bash scripts/setup-venv.sh
```

If `python3 -m venv` fails, the script falls back to `virtualenv.pyz`. Or install venv support once:

```bash
sudo apt install python3.12-venv
bash scripts/setup-venv.sh
```

**Verify easyocr:**

```bash
./venv/bin/python -c "import easyocr; print('easyocr ok')"
```

**Run forwarder / tests with venv Python** (not system `python3`):

```bash
./venv/bin/python app.py
./venv/bin/python scripts/test_tier1.py
./venv/bin/python scripts/test_classifier_from_sheets.py --limit 20 --verbose
```

`scripts/start-all.sh` uses `forwarder/venv/bin/python` automatically when the venv exists.

First OCR run downloads ~500MB of easyocr models to `~/.EasyOCR/`.

---

### Google Drive service account (flyer uploads)

**Do not** put the JSON key in git. Store the file **outside the repo** and reference its path in `.env`.

**Folder:** [FlyerUploads](https://drive.google.com/drive/folders/1RRVu2N65MXZXAEbw463L4GNkqCAloWr8?usp=sharing)  
**Folder ID** (already in `config.yaml`): `1RRVu2N65MXZXAEbw463L4GNkqCAloWr8`

#### 1. Create credentials (Google Cloud Console)

1. [Google Cloud Console](https://console.cloud.google.com/) → create/select a project
2. **APIs & Services → Library** → enable **Google Drive API**
3. **APIs & Services → Credentials → Create credentials → Service account**
4. Name e.g. `flyer-uploader` → create
5. Open the service account → **Keys → Add key → Create new key → JSON**
6. Save the downloaded file outside the repo, e.g.:

```bash
mkdir -p ~/.config/nctrianglemuslims
mv ~/Downloads/your-project-*.json ~/.config/nctrianglemuslims/google-drive-sa.json
chmod 600 ~/.config/nctrianglemuslims/google-drive-sa.json
```

#### 2. Share the Drive folder with the service account

Open the JSON and copy `"client_email"` (e.g. `flyer-uploader@your-project.iam.gserviceaccount.com`).

In Google Drive, open **FlyerUploads** → **Share** → paste that email → role **Editor** → Send.

Without this step uploads fail with permission errors.

#### 3. Point the pipeline at the key file

In **`evolution-api/.env`**:

```bash
GOOGLE_SERVICE_ACCOUNT_JSON=/home/abd/.config/nctrianglemuslims/google-drive-sa.json
```

Optional override in `forwarder/config.yaml`:

```yaml
google_service_account_json: /home/abd/.config/nctrianglemuslims/google-drive-sa.json
google_drive_folder_id: 1RRVu2N65MXZXAEbw463L4GNkqCAloWr8
```

Uploaded flyers get URLs like `https://drive.google.com/uc?id=FILE_ID` (compatible with frontend `normalizeFlyerUrl`).

---

### Configuration

Add to `forwarder/config.yaml` (see `config.example.yaml`):

```yaml
event_pipeline:
  enabled: false   # set true when ready
  ingest_url: https://<your-preview-or-prod>.vercel.app/api/events/ingest
  pipeline_api_key:   # loaded from ../.env PIPELINE_API_KEY if empty
  min_score_pass: 0.3
  min_score_reject: 0.1
  auto_publish_min_score: 0.5
  keywords_file: event_keywords.yaml
```

Add to **`/mnt/1tb/evolution-api/.env`** (same value as Vercel `PIPELINE_API_KEY`):

```bash
PIPELINE_API_KEY=<same key as nctrianglemuslims-ui / Vercel>
```

**Enable checklist:**
1. Set `ingest_url` to your Vercel preview or production URL
2. Add `PIPELINE_API_KEY` to `evolution-api/.env`
3. Set `event_pipeline.enabled: true` in `forwarder/config.yaml`
4. Restart forwarder (`app.py`)

---

### Tier 1 behavior

| Score | Action |
|-------|--------|
| `< 0.1` | Hard reject (unless image with caption) |
| `≥ 0.3` | Pass to extraction |
| Image + caption | Always pass (`force_pass`) |

**Auto-publish** (`status=published`) when Tier 1 extracts `eventName` + `eventDate` and score ≥ `auto_publish_min_score` (default 0.5).

**Otherwise:** escalates to **Tier 2 Ollama** → **Tier 3 Gemini** if extraction or confidence is insufficient.

**Dedup:** in-memory `seen_ids` locally + `whatsappMessageId` check on ingest API.

---

### Local smoke test (no webhook)

```bash
cd /mnt/1tb/evolution-api/forwarder
./venv/bin/python scripts/test_tier1.py
```

Expected: keyword score ~0.71, extracted event name/date/location/time.

---

### Classifier replay on real Sheets data (dry-run)

Replay full Tier 1 path with **flyer OCR** and optional **Tier 2 Ollama** against the Google Sheets CSV.

```bash
cd /mnt/1tb/evolution-api/forwarder

# Default: OCR on flyerURL + Tier 2 on reject/failed extraction
./venv/bin/python scripts/test_classifier_from_sheets.py --limit 50 --verbose

# Text-only (old behavior)
./venv/bin/python scripts/test_classifier_from_sheets.py --no-ocr --no-tier2 --limit 20

# Single event by name
./venv/bin/python scripts/test_classifier_from_sheets.py --name "Being Muslim Together" --verbose

# Load from API instead of CSV
./venv/bin/python scripts/test_classifier_from_sheets.py --source api --limit 20 --verbose
```

**Flags:**

| Flag | Default | Effect |
|------|---------|--------|
| `--no-ocr` | off | Skip flyer download + easyocr |
| `--no-tier2` | off | Skip Ollama when rejected or Tier 1 extraction fails |
| `--name` | all | Filter rows by event name substring |
| `--ingest` | off | POST drafts to ingest API |

Verbose output includes `ocr=<chars>`, `tier=tier1|tier2`, `tier2=ran`.

**Ingest URL resolution** (`ingest_resolver.py`):

| Priority | URL | When |
|----------|-----|------|
| 1 | `ingest_url_local` (`http://localhost:5177/api/events/ingest`) | `prefer_local_ingest: true` and `pnpm dev:api` is up |
| 2 | `ingest_url` (Vercel preview) | Local API not reachable |

Config keys in `forwarder/config.yaml`:

```yaml
event_pipeline:
  ingest_url_local: http://localhost:5177/api/events/ingest
  ingest_url: https://<preview>.vercel.app/api/events/ingest
  prefer_local_ingest: true
```

**Optional ingest** (writes `draft` replays with `whatsappMessageId: replay-{rowId}`):

```bash
# Requires PIPELINE_API_KEY in evolution-api/.env
python3 scripts/test_classifier_from_sheets.py --limit 10 --ingest --status draft --verbose
```

---

### Phase 2 checklist

- [x] `event_pipeline/` module structure
- [x] Tier 1 keyword classifier + OCR before reject (`classifier.py`)
- [x] Tier 1 regex extractor (name, date, time, location)
- [x] Tier 2 Ollama (`llama3.1:8b`) classify + extract
- [x] Tier 3 Gemini (`gemini-2.0-flash`) text + vision fallback
- [x] easyocr flyer OCR
- [x] Google Drive flyer upload (folder `1RRVu2N65MXZXAEbw463L4GNkqCAloWr8`)
- [x] Tier cascade in `handle_webhook` (Tier 1 → 2 → 3, not stub return)
- [x] Ingest client → `POST /api/events/ingest`
- [x] Ingest URL resolver (local :5177 → Vercel fallback)
- [x] Parallel dispatch in `app.py`
- [x] Classifier replay script on Sheets CSV / API
- [x] Config + `requirements.txt` + `.env.example`
- [x] `forwarder/venv` + easyocr installed (`bash forwarder/scripts/setup-venv.sh`)
- [x] Add `GEMINI_API_KEY` + `GOOGLE_SERVICE_ACCOUNT_JSON` to `.env`
- [x] Share Drive folder with service account
- [ ] Enable pipeline + end-to-end test (real WhatsApp message → calendar)

---

### Next up (Phase 2 cutover)

1. Confirm `./forwarder/venv/bin/python -c "import easyocr"` works
2. Set `event_pipeline.enabled: true` and restart forwarder
4. Send test event message in a source group → verify on Vercel calendar

Phase 4: SQLite dedup persistence, pm2, rate limits — see plan.

**Phase 5 — Admin dashboard: recurring events**

Pipeline may extract events like “Every Monday” without a single `eventDate`. Tier cascade now infers the **next occurrence** as a draft placeholder (`event_merge.infer_recurring_date`). Admin UI should let editors mark events as **recurring** (e.g. weekly on Monday) and manage series separately from one-off dates — `nctrianglemuslims-ui` dashboard work, not forwarder.

See plan: [`(plan)Evolution-API-Message-to-Website-Calendar-Database.md`](./(plan)Evolution-API-Message-to-Website-Calendar-Database.md).

