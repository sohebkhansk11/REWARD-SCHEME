# REWARD SCHEME — Deployment & Startup Guide

> **Quick reference for every deployment.** Follow top-to-bottom for a clean first
> deploy; jump to the relevant section for routine re-deploys or troubleshooting.

---

## Architecture at a Glance

```
┌──────────────────────────┐    HTTPS     ┌─────────────────────────────┐
│   User App (React/Vite)  │ ──────────── │                             │
│   Vercel  · user-app/    │              │  FastAPI Backend (Python)   │
└──────────────────────────┘              │  Render  ·  app/            │
                                          │                             │
┌──────────────────────────┐    HTTPS     │  POST /auth/login           │
│  Admin Dashboard (React) │ ──────────── │  GET  /draw/countdown       │
│  Vercel  · admin-dash/   │              │  ...all /admin/* routes     │
└──────────────────────────┘              └──────────┬──────────────────┘
                                                     │ SQLAlchemy
                                          ┌──────────▼──────────────────┐
                                          │  Supabase PostgreSQL         │
                                          │  db.XXXX.supabase.co:5432   │
                                          └─────────────────────────────┘
```

| Layer | Platform | Repo path | Build command |
|---|---|---|---|
| Backend API | Render (Web Service) | `/` root | `pip install -r requirements.txt` |
| Admin Dashboard | Vercel | `admin-dashboard/` | `npm run build` |
| User App | Vercel | `user-app/` | `npm run build` |

---

## 1 · Backend (Render)

### 1.1 Environment Variables

Set these in **Render → Your Service → Environment**:

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✅ | Supabase PostgreSQL connection string. Encode `@` in password as `%40` |
| `USER_JWT_SECRET` | ✅ | 32+ random chars. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_JWT_SECRET` | ✅ | 32+ random chars. **Different** from USER_JWT_SECRET |
| `ADMIN_SETUP_SECRET` | ✅ | Used once to call `POST /admin/auth/setup` to create first admin account |
| `ALLOWED_ORIGINS` | ✅ | Comma-separated Vercel URLs, e.g. `https://reward-scheme.vercel.app,https://reward-admin.vercel.app` |
| `ENABLE_DEV_MODE` | ⚠️ | `false` in production. `true` ONLY for local/staging. **NEVER true in prod.** |
| `SCHEDULER_ENABLED` | ✅ | `true` to activate APScheduler (weekly draw cron jobs). **Must be true on prod.** |
| `DRAW_HOUR_UTC` | optional | Default `13` (7:00 PM IST). Override if needed. |
| `DRAW_MINUTE_UTC` | optional | Default `30`. |
| `TELEGRAM_BOT_TOKEN` | optional | For broadcast messages to users with Telegram. |
| `WHATSAPP_PROVIDER` | optional | `twilio` or `meta` |
| `TWILIO_ACCOUNT_SID` | optional | Twilio WhatsApp credentials |
| `TWILIO_AUTH_TOKEN` | optional | |
| `TWILIO_WHATSAPP_FROM` | optional | e.g. `+14155238886` |

### 1.2 Render Service Settings

```
Runtime:          Python 3
Build Command:    pip install -r requirements.txt
Start Command:    uvicorn app.main:app --host 0.0.0.0 --port $PORT
Root Directory:   (leave blank — root of repo)
```

> **Health check path:** `/health` or `/` — Render auto-pings this to confirm the
> service is up. If you see repeated restart loops, check the DATABASE_URL first.

### 1.3 Database Auto-Migration

Tables are created automatically on first start via:
```python
Base.metadata.create_all(bind=engine)   # in app/main.py
```
No manual migrations needed. If you add a new model, just redeploy and it creates
the missing tables.

### 1.4 First Admin Account Setup

After first deploy, run this **once**:
```bash
curl -X POST https://YOUR-BACKEND.onrender.com/admin/auth/setup \
  -H "Content-Type: application/json" \
  -d '{
    "setup_secret": "YOUR_ADMIN_SETUP_SECRET",
    "username": "admin",
    "password": "StrongPassword123!"
  }'
```
Copy the `totp_uri` from the response into **Google Authenticator** (or Authy).
You'll need the TOTP code every time you log in to the Admin Dashboard.

### 1.5 APScheduler — Weekly Draw Cron Jobs

The scheduler runs **inside** the Render web process (no separate worker needed).
It starts automatically when `SCHEDULER_ENABLED=true`.

Four jobs fire every Sunday (UTC):

| Job | Time (UTC default) | IST equivalent | What it does |
|---|---|---|---|
| `job_preparation` | Sunday 11:30 UTC | 5:00 PM IST | LPI snapshot, Brain-5 routing, SDE pre-processing, opens admin override window |
| `job_override_watchdog` | Every 5 min (all days) | — | Auto-selects draw type if admin missed the 2-hour override window |
| `job_weekly_draw` | Sunday 13:30 UTC | 7:00 PM IST | Executes mass draw across all eligible full pools |
| `job_post_cleanup` | Sunday 13:35 UTC | 7:05 PM IST | Resets weekly flags, releases draw lock |

To change draw time, set `DRAW_HOUR_UTC` and `DRAW_MINUTE_UTC` on Render.

---

## 2 · Admin Dashboard (Vercel)

### 2.1 Environment Variables

Set in **Vercel → admin-dashboard project → Settings → Environment Variables**:

| Variable | Value | Notes |
|---|---|---|
| `VITE_API_URL` | `https://YOUR-BACKEND.onrender.com` | No trailing slash |
| `VITE_ENABLE_DEV_MODE` | *(leave unset or `false`)* | Only `true` on personal staging deploy |

> ⚠️ If `VITE_ENABLE_DEV_MODE` is not exactly `'true'`, the **Dev Tools** tab is
> hidden from the sidebar and the `/dev-tools` route redirects to Dashboard.

### 2.2 Vercel Project Settings

```
Framework Preset:   Vite
Root Directory:     admin-dashboard
Build Command:      npm run build
Output Directory:   dist
Install Command:    npm install
```

### 2.3 Pages & Routes

| Path | Page | Notes |
|---|---|---|
| `/` | Dashboard | KPI cards, active pools, quick stats |
| `/pools` | Pool Oversight | Pool table + 12-seat Hex Grid toggle, SDE columns |
| `/users` | User Directory | Member search and management |
| `/statistics` | Statistics | Brain 5 LPI gauge, Pool Type Routing, analytics |
| `/command-center` | Command Center | HFT terminal — LPI thermometer, topology, scatter, war room modules |
| `/hydraulic-pipeline` | Hydraulic Pipeline | 3-chamber Kanban, virtualized scrolling for 1000+ users |
| `/draw-engine` | Draw Engine | Override terminal, War Room banner (auto-activates T-2H) |
| `/winning-ledger` | Winning Ledger | Winners table + Forensic Autopsy slide-over |
| `/referrals` | Referral Payouts | |
| `/diagnostics` | Diagnostics | |
| `/settings` | System Settings | |
| `/tokens` | Token Manager | |
| `/dev-tools` | Dev Tools | **Staging only.** Requires `VITE_ENABLE_DEV_MODE=true` |

---

## 3 · User App (Vercel)

### 3.1 Environment Variables

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://YOUR-BACKEND.onrender.com` |

### 3.2 Vercel Project Settings

```
Framework Preset:   Vite
Root Directory:     user-app
Build Command:      npm run build
Output Directory:   dist
Install Command:    npm install
```

### 3.3 Countdown Timer Behaviour

The `CountdownTimer` component polls `GET /draw/countdown` every 30 seconds.
It only shows the live countdown when **both** flags are true:

```
countdown_active = true   AND   preparation_valid = true
```

Outside the T-2H window it shows: *"Next Draw · Sunday 7:00 PM IST · Countdown starts 2 h before draw"*

---

## 4 · Local Development

### 4.1 Backend

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill env
cp .env.example .env
# Edit .env: set DATABASE_URL, USER_JWT_SECRET, ADMIN_JWT_SECRET, etc.
# For local dev: ENABLE_DEV_MODE=true, SCHEDULER_ENABLED=false

# 4. Start server
uvicorn app.main:app --reload --port 8000
```

API docs available at: `http://localhost:8000/docs`

### 4.2 Admin Dashboard

```bash
cd admin-dashboard
npm install
cp .env.example .env
# Edit .env: VITE_API_URL=http://localhost:8000
npm run dev
```

Runs at: `http://localhost:5173`

### 4.3 User App

```bash
cd user-app
npm install
cp .env.example .env
# Edit .env: VITE_API_URL=http://localhost:8000
npm run dev
```

Runs at: `http://localhost:5174`

---

## 5 · Post-Deploy Checklist

Run through this after every deployment:

```
Backend (Render)
  [ ] Service shows "Live" (green) in Render dashboard
  [ ] GET  https://YOUR-BACKEND.onrender.com/health  → 200 OK
  [ ] APScheduler logs visible in Render log stream (search "APScheduler")
  [ ] SCHEDULER_ENABLED=true is set

Admin Dashboard (Vercel)
  [ ] Build succeeded without errors in Vercel deployment log
  [ ] Login works (TOTP from Authenticator app)
  [ ] Dashboard loads KPI cards
  [ ] Command Center → LPI gauge shows a value
  [ ] Draw Engine → no red errors in the override panel

User App (Vercel)
  [ ] App loads at the Vercel URL
  [ ] Login / Register flow works end-to-end
  [ ] CountdownTimer shows static message outside T-2H window
  [ ] Pool status displays correctly
```

---

## 6 · Draw Lifecycle — At a Glance

```
Sunday  5:00 PM IST (11:30 UTC)
  └─ Backend: start_draw_preparation()
       • Brain 5 LPI snapshot
       • SDE pre-processing (L4 targets selected)
       • Pool type routing (P1/P2/P3/P4)
       • WeeklyDrawState created — admin override window opens

  Admin Dashboard shows WAR ROOM banner on Draw Engine page
  CountdownTimer in User App goes live

Sunday  5:00 PM – 7:00 PM IST
  └─ Admin can submit override (SDE / Regular / Type A / Type B)
     Override Deadline Ring depletes over 2 hours

Sunday  7:00 PM IST (13:30 UTC)  ← DRAW TIME
  └─ If no admin override: auto-resolve fires (job_override_watchdog)
  └─ execute_weekly_draw()
       • All eligible full pools processed
       • Winners recorded in draw_history
       • Payout amounts calculated

Sunday  7:05 PM IST (13:35 UTC)
  └─ post_draw_cleanup()
       • Weekly flags reset (draw_completed_this_week)
       • Draw lock released
       • CountdownTimer returns to static message
```

---

## 7 · Security Notes

| Rule | Detail |
|---|---|
| `ENABLE_DEV_MODE` | **NEVER** `true` in production. All `/dev/*` endpoints return 403 when false. |
| Sensitive actions | `DELETE /admin/users/:id` and token delete require the admin's **password** in the request payload — not just the JWT. |
| CORS | Set `ALLOWED_ORIGINS` to your exact Vercel URLs in production. Use `*` only during initial testing. |
| JWT secrets | `USER_JWT_SECRET` and `ADMIN_JWT_SECRET` must be different, 32+ char random strings. |
| TOTP 2FA | Admin login uses TOTP (Google Authenticator / Authy). No SMS or Telegram for 2FA. |

---

## 8 · Common Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Backend cold starts / slow first request | Render free tier spins down after 15 min idle | Upgrade to Render paid tier or accept the cold start |
| "CORS error" in browser console | `ALLOWED_ORIGINS` missing your Vercel URL | Add the exact URL (no trailing slash) to `ALLOWED_ORIGINS` on Render |
| Countdown timer stuck on static message | `preparation_valid` or `countdown_active` is false | Check Draw Engine page — confirm preparation ran at T-2H |
| APScheduler jobs not firing | `SCHEDULER_ENABLED` not set to `true` | Set env var on Render and redeploy |
| "Invalid TOTP" on admin login | Phone time drifted | Sync phone time: Settings → Date & Time → Automatic |
| Dev Tools tab not visible | `VITE_ENABLE_DEV_MODE` not `'true'` | Only appears in staging. Set env var on that Vercel project only |
| Render shows "Build failed" | Missing env var or `requirements.txt` issue | Check Render build logs, ensure all env vars are set |
| Tables not created on fresh DB | `Base.metadata.create_all` skipped | Check `DATABASE_URL` is correct and DB is reachable from Render |
| Brain 5 LPI shows 0 | No active members in DB yet | Expected on a fresh deploy — populates as users join pools |

---

## 9 · Key API Endpoints Reference

```
Auth
  POST /user/auth/register          Register new user
  POST /user/auth/login             User login → JWT
  POST /admin/auth/setup            First-time admin creation (one-time)
  POST /admin/auth/login/password   Admin login step 1 (password)
  POST /admin/auth/login/totp       Admin login step 2 (TOTP) → admin JWT

Draw
  GET  /draw/countdown              Two-flag countdown status (user + admin)
  GET  /draw/state                  Current WeeklyDrawState

Admin Analytics
  GET  /admin/analytics/ai-snapshot        Brain 1-4 AI metrics
  GET  /admin/analytics/brain5-lpi         Brain 5 LPI + pool routing
  GET  /admin/analytics/financials         Float, liability, sinking fund
  GET  /admin/analytics/pool-stats         Per-pool statistics
  GET  /admin/analytics/chart-data         Time-series chart data

Admin Override
  POST /admin/draw/override/submit  Submit draw type choice
  GET  /admin/draw/override/status  Current override status

Dev (staging only — requires ENABLE_DEV_MODE=true)
  POST /dev/simulate                Run draw simulation
  POST /dev/advanced-simulation     N-cycle stress test
  POST /dev/reset                   Reset dev state
```

---

*Last updated: June 2026 — Quantitative Command Center release*
