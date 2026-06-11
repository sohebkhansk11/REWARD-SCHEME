Now I have everything I need. Here's the complete guide in plain language:

---

# 📦 COMPLETE DEPLOYMENT GUIDE + DEVELOPER MODE + USER MANUAL

---

## PART 1 — FIRST-TIME DEPLOYMENT (Do This Once)

### 🔵 What You Need Before Starting
- Your **GitHub account** (where your code lives)
- Your **Render account** (where the backend runs — render.com)
- Your **Vercel account** (where both websites run — vercel.com)
- Your **Supabase connection string** (from your Supabase project → Settings → Database → Connection String → URI format)

---

### STEP 1 — Push Code to GitHub

Open a terminal inside your `REWARD SCHEME` folder and run:

```bash
git add .
git commit -m "Initial deploy"
git push origin main
```

> ✅ This makes GitHub the "source of truth" that both Render and Vercel pull from.

---

### STEP 2 — Deploy the Backend (Render)

1. Go to **render.com** → click **New → Web Service**
2. Click **Connect a repository** → choose your `REWARD-SCHEME` GitHub repo
3. Fill in these settings:

   | Field | What to put |
   |---|---|
   | Name | `reward-scheme-api` |
   | Branch | `main` |
   | Root Directory | *(leave blank)* |
   | Runtime | `Python 3` |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
   | Instance Type | `Free` |

4. Click **Advanced** → Add these environment variables:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Your Supabase URI (ends with `?sslmode=require`) |
   | `ALLOWED_ORIGINS` | `*` *(change this after deploying the frontends — see Step 5)* |

5. Click **Create Web Service** and wait ~2 minutes
6. When it turns **Live**, visit your Render URL in the browser. You should see:
   ```
   {"status":"ok","message":"Reward Scheme API is running"}
   ```
   Copy this URL — you need it in the next steps.

> ⚠️ **Free tier warning:** Render free tier goes to sleep after 15 minutes of no traffic. The first visit after sleeping takes ~30 seconds to wake up. This is normal.

---

### STEP 3 — Run the Database Migrations (Supabase)

This is required only once. Go to your **Supabase project → SQL Editor** and run:

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_referrals_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS accumulated_referral_bonus_inr NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TYPE tokentype ADD VALUE IF NOT EXISTS 'Referral_Withdraw';
ALTER TYPE tokenstatus ADD VALUE IF NOT EXISTS 'Pending_Approval';
```

Click **Run**. If it says "Success" you're done.

---

### STEP 4 — Deploy the Admin Dashboard (Vercel)

1. Go to **vercel.com** → click **Add New → Project**
2. Import your `REWARD-SCHEME` GitHub repo
3. In the Configure screen set:

   | Field | What to put |
   |---|---|
   | Project Name | `reward-scheme-admin` |
   | Framework Preset | `Vite` |
   | Root Directory | `admin-dashboard` |

4. Add environment variable:

   | Name | Value |
   |---|---|
   | `VITE_API_URL` | `https://reward-scheme-api.onrender.com` *(your Render URL)* |

5. Click **Deploy**. Takes ~30 seconds. You get a URL like `reward-scheme-admin.vercel.app`

---

### STEP 5 — Deploy the User App (Vercel)

Same process as Step 4, but different folder:

1. **Add New → Project** → same GitHub repo again
2. Set Root Directory to `user-app`, Project Name to `reward-scheme-user`
3. Same environment variable: `VITE_API_URL` = your Render URL
4. Deploy. URL will be something like `reward-scheme-user.vercel.app`

---

### STEP 6 — Lock Down Security (Important!)

Once both Vercel URLs are live, go back to **Render → your service → Environment** and update:

| Key | Value |
|---|---|
| `ALLOWED_ORIGINS` | `https://reward-scheme-admin.vercel.app,https://reward-scheme-user.vercel.app` |

Render will redeploy automatically. Now only those two websites can talk to your API.

---

### STEP 7 — Set Up Admin Login

The first time, you need to create your admin account. Go to:
```
https://reward-scheme-api.onrender.com/docs
```
Find the `POST /admin/auth/setup` endpoint and call it with your chosen username, password, and the setup secret. This only works once — after setup, this endpoint is permanently disabled.

---

## PART 2 — DEVELOPER MODE

Developer Mode ("God Mode") gives you special tools to test the system: run draws instantly, create fake users, and reset data. **It is ONLY for testing. Never turn it on in production.**

---

### 🔍 HOW TO CHECK IF DEVELOPER MODE IS ON

**Two places to check:**

**1. Backend (Render) — the real gate:**
- Go to **Render → your service → Environment**
- Look for the variable `ENABLE_DEV_MODE`
- If it's NOT there or set to anything other than `true` → Dev mode is **OFF** ✅ (correct for production)
- If it's set to `true` → Dev mode is **ON** ⚠️

**2. Admin Website (Vercel) — controls the UI:**
- Go to **Vercel → reward-scheme-admin project → Settings → Environment Variables**
- Look for `VITE_ENABLE_DEV_MODE`
- If it's NOT there or not `true` → The "Developer Tools" tab will NOT appear in the sidebar ✅
- If it's `true` → The red "Dev Tools" tab appears in the sidebar

**Quick visual check:**
Log in to the admin website. If you see a red **"Dev Tools"** tab at the bottom of the left sidebar — dev mode is ON in the frontend. If you don't see it — it's off.

---

### ✅ HOW TO ENABLE DEVELOPER MODE (For Staging/Testing Only)

You must enable it in **both** places:

#### Enable on the Backend (Render):
1. Go to **render.com → your `reward-scheme-api` service**
2. Click **Environment** in the left menu
3. Click **Add Environment Variable**
4. Set: `ENABLE_DEV_MODE` = `true`
5. Click **Save Changes**
6. Render will automatically redeploy (takes ~2 minutes)
7. Wait until the status shows **Live** again

#### Enable on the Admin Website (Vercel):
1. Go to **vercel.com → reward-scheme-admin project**
2. Click **Settings → Environment Variables**
3. Click **Add New**
4. Set: `VITE_ENABLE_DEV_MODE` = `true`
5. Make sure it's set for **Production + Preview + Development**
6. Click **Save**
7. **Important:** Go to **Deployments → the latest deployment → click the three dots → Redeploy**
   - Vercel bakes environment variables into the build, so you MUST redeploy for the change to appear
8. After redeploy, log in to the admin website — you'll see the red **"Dev Tools"** tab in the sidebar

---

### 🔴 HOW TO DISABLE DEVELOPER MODE (Required Before Going Live)

#### Disable on the Backend (Render):
1. Go to **Render → reward-scheme-api → Environment**
2. Find `ENABLE_DEV_MODE`
3. Either **delete it entirely** or change its value to `false`
4. Click **Save Changes** → wait for redeploy (~2 min)
5. To verify: try visiting `https://reward-scheme-api.onrender.com/dev/force-draw` — you should get a `403 Forbidden` error

#### Disable on the Admin Website (Vercel):
1. Go to **Vercel → reward-scheme-admin → Settings → Environment Variables**
2. Find `VITE_ENABLE_DEV_MODE` and **delete it** (or set it to `false`)
3. Save → Redeploy the project
4. To verify: log in to the admin website — the "Dev Tools" tab should be gone from the sidebar

---

### 🛠️ WHAT EACH DEVELOPER TOOL DOES

Once dev mode is on, log in to the admin website and click **Dev Tools** in the sidebar.

| Tool | What it does | When to use |
|---|---|---|
| **Force Draw** | Instantly runs the Sunday draw on any active pool without waiting for Sunday. Automatically marks all unpaid members as paid so the draw doesn't fail. | Testing that draws work correctly |
| **Time-Travel Simulator** | Creates fake users, forms a pool, and runs multiple draw cycles all at once. Shows you a full table of who won each week and how much they got. | Testing the full 6-week pool lifecycle in seconds |
| **Mass User Injection** | Creates up to 100,000 fake users with fake deposits, instantly fills pools with them. Very fast (1,000 users in ~200ms). | Load testing and stress testing |
| **Nuke Database** | Deletes ALL users, pools, and tokens. Resets the database back to zero. Admin accounts are NOT deleted. | Cleaning up after testing |

> ⚠️ **Nuke is irreversible.** The button only activates after you type `DELETE` in the text box to confirm.

---

## PART 3 — USER MANUAL (How Everything Works Day-to-Day)

---

### FOR END USERS (The App at `reward-scheme-user.vercel.app`)

#### How to Register
1. Open the user app website
2. Click **Register / Sign Up**
3. Enter your **Name**, **Mobile number**, and choose a **Username + Password**
4. If someone gave you a referral link or code, enter it in the referral field
5. Click **Create Account** — you're now registered with **Unclassified** status

#### How to Join the Waitlist
1. After registering, you need to pay your first deposit of **₹1,000**
2. Contact the admin to get a **Deposit Token** (code starting with `DEP-`)
3. Go to your **Profile page** in the app and enter the token code to redeem it
4. Your status changes to **Waitlist** — you're now in the queue to enter a pool

#### How Pool Entry Works
- When 24 paid waitlist members have accumulated, the system automatically creates a new pool of 12 members
- The first 12 people in line move from Waitlist → Active (Level 1 inside a pool)
- The remaining 12 stay on the waitlist for the next pool

#### How the Draw Works (Every Sunday 7 PM IST)
- Every week, 2 people win from each pool:
  - **Winner 1** — randomly picked from Levels 1–3
  - **Winner 2** — randomly picked from Levels 4–6
- Winners get a payout and leave the pool
- Everyone else moves up one level
- 2 new members from the waitlist fill the empty slots

#### How to Collect Your Payout
- If you win, you receive a **Withdraw Token** (code starting with `WIT-`)
- Show this token code to the admin
- The admin pays you the cash/UPI and marks the token as "Burned"

#### How Referrals Work
1. Go to your **Profile page** → find your **Referral Code**
2. Share this code with friends
3. When a friend registers using your code AND then enters an active pool, you earn **₹250** per friend
4. Your earnings show on your Profile page under "Referral Program"
5. Once you've accumulated **₹1,000 or more**, the **REQUEST BONUS PAYOUT** button becomes active
6. Click it to request your payout → the admin will approve and pay you

#### How Late Fees Work
- You must pay **₹1,000 every week** while you're in an active pool
- If you miss a payment, you get charged **₹50 per day** as a late fee
- If you still haven't paid by the time the Sunday draw happens, you are **eliminated** — no refund
- A paid waitlist member takes your slot

---

### FOR ADMIN (The Console at `reward-scheme.vercel.app`)

#### How to Log In
1. Open the admin website
2. Enter your **username** and **password**
3. Enter the **6-digit OTP** from your Google Authenticator app
4. You're in — session lasts until you sign out

#### Dashboard
- Shows live counts: active users, waitlist size, running pools, total capital collected
- **Check Waitlist Threshold** button — manually triggers pool creation if 24+ paid users are waiting

#### Token Manager
- **Generate tokens** — create Deposit (DEP), Withdraw (WIT), or Referral (REF) tokens for specific users
- **Burn tokens** — mark a token as paid/completed after giving the user their money
- Search and filter all tokens by type and status

#### Pool Oversight
- See all active pools and their members
- Click a pool to see who's in it, what level everyone is at, and who's paid/unpaid
- **Run Draw** button — triggers the Sunday dual-draw for that pool

#### User Directory
- Search and view all users
- See each user's status, level, payment status, late fees
- Edit user details, fix mistakes, or delete users if needed

#### Penalty Controls
- **Apply Daily Penalty** — adds ₹50 to all unpaid active members (run this Mon–Sat)
- **Eliminate Unpaid** — removes all still-unpaid members before the Sunday draw and fills their slots from the waitlist

#### Referral Payouts
- Shows all pending referral payout requests from users
- **Approve** → marks it paid (user gets their ₹1,000+)
- **Reject** → declines the request and refunds the balance back to the user's account

#### Statistics
- Full financial breakdown: capital collected, total payouts issued, pending liabilities
- Pool-level analytics, token breakdown, AI forecast for waitlist velocity
- Charts showing growth over time

#### Diagnostics
- Live API health check
- Shows database connection status
- Use this when something seems broken — it tells you exactly what's wrong

---

### 🔄 KEEPING THINGS UPDATED (After First Deploy)

Every time you make a code change:
1. Save your files
2. Run in terminal:
   ```bash
   git add .
   git commit -m "describe what you changed"
   git push origin main
   ```
3. **Render** automatically picks up the change and redeploys the backend (~2 min)
4. **Vercel** automatically picks up the change and redeploys both websites (~30 sec)

---

### 🆘 QUICK TROUBLESHOOTING

| What you see | What's wrong | Fix |
|---|---|---|
| "Cannot reach API" on admin dashboard | Render is sleeping (waking up) | Wait 30 seconds and refresh the page |
| "Cannot reach API" persists after refresh | CORS not configured or Render crashed | Check Render logs; verify `ALLOWED_ORIGINS` is set |
| Dev Tools tab not visible | `VITE_ENABLE_DEV_MODE` not set or Vercel not redeployed | Add the env var in Vercel and **redeploy** |
| Dev tools visible but all actions fail with "403" | `ENABLE_DEV_MODE` not set on Render backend | Add `ENABLE_DEV_MODE=true` to Render env vars and redeploy |
| Referral payout request fails | Supabase migrations not run | Run the 4 SQL lines from Step 3 in Supabase SQL Editor |
| Login works but all data is empty | Fresh database, no data yet | Use Dev Tools → Mass User Injection to populate test data |
| OTP login fails | Phone clock is not synced | Open your phone's Date & Time settings → enable "Automatic" / "Set automatically" |