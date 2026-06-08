# Deployment Guide

This monorepo ships three separate services. Deploy them in order — backend first,
then the two frontends (they need the live API URL).

| Service | Stack | Host | Free tier |
|---|---|---|---|
| **Backend API** | FastAPI + PostgreSQL (Supabase) | Render.com | ✓ |
| **Admin Dashboard** | React + Vite + Tailwind | Vercel | ✓ |
| **User App** | React + Vite + Framer Motion | Vercel | ✓ |

---

## Prerequisites

- [Git](https://git-scm.com/) installed locally
- A [GitHub](https://github.com) account
- A [Render.com](https://render.com) account
- A [Vercel](https://vercel.com) account
- Your Supabase **Connection String** (URI format) ready

---

## Step 1 — Push the project to GitHub

Open a terminal in the `REWARD SCHEME` folder and run:

```bash
git init
git add .
git commit -m "Initial commit — Reward Scheme full stack"
```

Create a **new empty repository** on GitHub (no README, no .gitignore), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/reward-scheme.git
git branch -M main
git push -u origin main
```

> The `.gitignore` already excludes all `.env` files and `node_modules/`.

---

## Step 2 — Deploy the FastAPI Backend to Render

### 2.1 Create the Web Service

1. Log in to [render.com](https://render.com) and click **New → Web Service**.
2. Click **Connect a repository** → authorise GitHub → select `reward-scheme`.
3. Fill in the service settings:

   | Field | Value |
   |---|---|
   | **Name** | `reward-scheme-api` (or any name) |
   | **Region** | Closest to your users |
   | **Branch** | `main` |
   | **Root Directory** | *(leave blank — repo root)* |
   | **Runtime** | `Python 3` |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
   | **Instance Type** | `Free` |

4. Click **Advanced** to expand environment variables.

### 2.2 Set Environment Variables

Click **Add Environment Variable** for each of the following:

| Key | Value |
|---|---|
| `DATABASE_URL` | Your Supabase connection URI, e.g. `postgresql://postgres:YOUR_PASSWORD@db.XXXX.supabase.co:5432/postgres?sslmode=require` |
| `ALLOWED_ORIGINS` | `*` *(change this after both frontends are deployed — see Step 5)* |

> **Note:** The `DATABASE_URL` must end with `?sslmode=require` for Supabase.
> If your Supabase password contains special characters (e.g. `@`, `#`), URL-encode them
> (`@` → `%40`, `#` → `%23`).

### 2.3 Deploy

Click **Create Web Service**. Render will:
1. Clone the repo
2. Run `pip install -r requirements.txt`
3. Start uvicorn

Wait ~2 minutes. When the status turns **Live**, open the service URL and verify:

```
https://reward-scheme-api.onrender.com/
→ {"status":"ok","message":"Reward Scheme API is running"}
```

Copy this URL — you'll need it in the next two steps.

> **Free tier note:** Render's free tier spins down after 15 minutes of inactivity.
> The first request after sleep takes ~30 seconds. Upgrade to the Starter plan ($7/mo) to avoid this.

---

## Step 3 — Deploy the Admin Dashboard to Vercel

### 3.1 Import the project

1. Log in to [vercel.com](https://vercel.com) and click **Add New → Project**.
2. Click **Import** next to your `reward-scheme` GitHub repository.
3. In the **Configure Project** screen:

   | Field | Value |
   |---|---|
   | **Project Name** | `reward-scheme-admin` |
   | **Framework Preset** | `Vite` |
   | **Root Directory** | `admin-dashboard` |
   | **Build Command** | `npm run build` *(auto-detected)* |
   | **Output Directory** | `dist` *(auto-detected)* |
   | **Install Command** | `npm install` *(auto-detected)* |

### 3.2 Set Environment Variables

Before clicking Deploy, expand **Environment Variables** and add:

| Name | Value |
|---|---|
| `VITE_API_URL` | `https://reward-scheme-api.onrender.com` *(your Render URL from Step 2)* |

### 3.3 Deploy

Click **Deploy**. Vercel builds the app (~30 seconds) and gives you a URL like:

```
https://reward-scheme-admin.vercel.app
```

Open it — the Admin Dashboard should load and connect to your live API.

---

## Step 4 — Deploy the User App to Vercel

Repeat Step 3 for the second frontend:

1. From the Vercel dashboard click **Add New → Project** → import `reward-scheme` again.
2. Configure:

   | Field | Value |
   |---|---|
   | **Project Name** | `reward-scheme-user` |
   | **Framework Preset** | `Vite` |
   | **Root Directory** | `user-app` |

3. Add the same environment variable:

   | Name | Value |
   |---|---|
   | `VITE_API_URL` | `https://reward-scheme-api.onrender.com` |

4. Click **Deploy**.

Your user-facing app will be live at something like:

```
https://reward-scheme-user.vercel.app
```

---

## Step 5 — Lock Down CORS (Important!)

Once both Vercel deployments are live, go back to Render and update the
`ALLOWED_ORIGINS` environment variable to the exact Vercel URLs:

```
https://reward-scheme-admin.vercel.app,https://reward-scheme-user.vercel.app
```

Render will automatically redeploy. From that point:
- Only those two origins can make cross-origin requests to the API.
- `allow_credentials` will automatically enable (needed for cookies/auth later).

---

## Step 6 — Automatic Redeploys

Both Render and Vercel watch the `main` branch. Every `git push origin main` triggers:

- Render: rebuilds and restarts the API (~2 min)
- Vercel: rebuilds both frontends (~30 sec each)

---

## Environment Variable Reference

### Backend (set in Render → Environment)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | **Yes** | Supabase PostgreSQL URI with `?sslmode=require` |
| `ALLOWED_ORIGINS` | No | Comma-separated allowed CORS origins. Defaults to `*` |

### Frontends (set in Vercel → Project Settings → Environment Variables)

| Variable | Required | Description |
|---|---|---|
| `VITE_API_URL` | **Yes** | Full URL of the deployed Render backend |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Render build fails with `ModuleNotFoundError` | Check `requirements.txt` is in the repo root and not `.gitignore`d |
| `could not translate host name` error | Your `DATABASE_URL` password contains `@` — replace with `%40` |
| Vercel shows blank page / 404 on reload | Confirm `vercel.json` exists in the project root (`admin-dashboard/vercel.json`) |
| API returns 422 / CORS error in browser | `VITE_API_URL` is missing or misspelled in Vercel env vars — must start with `VITE_` |
| Render sleeps between requests | Upgrade from Free to Starter tier, or use a free uptime monitor (e.g. UptimeRobot) to ping `/` every 10 min |
| Tables don't exist on first boot | Render logs should show SQLAlchemy `CREATE TABLE` statements; if not, check `DATABASE_URL` |
