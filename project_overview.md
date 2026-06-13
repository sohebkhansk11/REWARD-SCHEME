---
name: reward-scheme-project-overview
description: REWARD SCHEME — FastAPI+React+Supabase chit-fund pool system. Full architecture: pool lifecycle, user statuses, weekly loop, Phase 1/2/3 assign logic, draw pipeline, LPI/SDE engine, simulation engine.
metadata:
  type: project
---

# REWARD SCHEME — Full Project Overview

**Root:** `C:\Users\amosd\Downloads\REWARD SCHEME`
**Repo:** https://github.com/sohebkhansk11/REWARD-SCHEME.git (branch `main`)
**Deploy:** Render (auto-deploy on push to main — no manual step needed)
**Stack:** FastAPI + SQLAlchemy (ORM) + Alembic (migrations) / React (admin-dashboard) / Supabase Postgres (production) / SQLite (stress-test simulation only)
**See also:** [[feedback-process-rules]] for mandatory session process rules.

---

## Key Constants (`app/core/config.py`)
- `POOL_CAPACITY = 12` — a pool MUST have EXACTLY 12 active members to be eligible for a weekly draw
- Weekly installment = ₹1,000 per active member (creates a DEP/WK token when paid)
- A/B/C late-payer split: A = direct elimination, B = late-fee stay Unpaid, C = grace period → saved → Paid

---

## Enums

### PoolStatus
- `Active` — eligible for draw when member count == 12
- `Paused_Awaiting_Members` — under or over capacity; cannot draw
- `Dissolved` — permanently closed (Phase 3 source pool dissolution)

### UserStatus
- `Active` — in a pool, paying weekly
- `Waitlist` — registered, waiting for pool slot
- `Eliminated` — removed for non-payment (Type A) or dropout; ALSO covers what the codebase previously called "Eliminated_Unpaid" — **there is NO `Eliminated_Unpaid` enum value**; using it as a raw string crashes Postgres
- `Eliminated_Won` — exited as a draw winner

### WeeklyPaymentStatus
- `Paid` / `Unpaid` — reset to Unpaid at Monday step b every week

---

## Backend Services (`app/services/`)

| File | Key functions | Role |
|---|---|---|
| `real_simulation.py` | `RealSimEngine.run()` | 50-week stress test on isolated SQLite DB with ChronosEngine time mock |
| `waitlist.py` | `assign_waitlist_to_pools()` | Phase 1 refill + Phase 2 pool creation + Phase 3 condensation — called every step a.5 and at end of execute_weekly_draw |
| `draw.py` | `execute_weekly_draw()`, `run_dual_draw()`, `post_draw_cleanup()` | All draw logic |
| `brain5_lpi_engine.py` | `redistribute_multi_l4_pools()`, `flag_l4_members()`, LPI calc | Level Pressure Index; L4 redistribution |
| `draw_preparation.py` | `start_draw_preparation()` | Acquires draw_engine lock, freezes LPI, runs SDE meta-pool; runs at step d (T-2H) |

---

## Weekly Simulation Loop (per week — order is critical)

```
a.   inject_week()
         ↳ Injects new users (organic + referral) with ChronosEngine at monday_morning

a.5  assign_waitlist_to_pools(db)
         ↳ Phase 1: fills ALL under-capacity (Active+Paused) pools from waitlist FIFO
             • Restores Paused→Active ONLY when pool_obj.status==Paused AND total_after>=12
             • A pool already at 12 (vac=0) is SKIPPED — critical deadlock source
         ↳ Phase 2: if paid_waitlist >= adaptive_threshold → bulk-create new full pools (Active, 12 members)
             • Uses sa_insert() bulk INSERT; explicitly sets draw_completed_this_week=False
               (SQLite server_default='false' is truthy in Python → caused all new pools to skip draws)
         ↳ Phase 3: if paid_waitlist == 0 → inter-pool condensation (dissolves sparse source pools)
             • Guarded by draw_engine lock check; skipped if lock is active

b.   _fm_reset_payment_cycle(db)
         ↳ Sets ALL Active users to Unpaid (they owe this week's ₹1,000)

c.   apply_abc_model(db, late_ratio, elim_pct_a, grace_pct_c)
         ↳ From Unpaid members picks n_late% to process:
             Type A (elim_pct_a %): status → Eliminated, removed from pool
             Type B (remainder):    stay Unpaid with late-fee record
             Type C (grace_pct_c %): saved → status → Paid (grace fee charged)
         ↳ Returns: n_late, n_elim, n_saved, type_b_ids, late_fee_revenue_inr

c.2  auto_pay_installments(db, week_num, skip_ids=type_b_ids)
         ↳ Creates WK tokens for all non-B Unpaid Active members → marks them Paid
         ↳ This is what produces installments_collected_inr in the snapshot

c.5  _fm_enforce_pool_capacity(db)   ← ONLY if n_elim > 0
         ↳ Finds Active pools with actual_count < 12 → pauses them → calls assign_waitlist_to_pools
         ↳ Because Type A exits leave pools under-capacity but still Active (Phase 1 skips Active pools that need fill)
         ↳ If n_elim == 0 (common with small late_ratio): this step is SKIPPED entirely

d.   start_draw_preparation(db, draw_time_utc=sunday_midnight)   [T-2H = saturday_22h]
         ↳ Acquires draw_engine SystemLock
         ↳ Freezes LPI snapshot into WeeklyDrawState
         ↳ flag_l4_members(db) — marks members at L4 with sde_required=True
         ↳ redistribute_multi_l4_pools(db) — moves excess L4s to pools with 0 L4s
             ⚠ BUG (FIXED c26d4d8): was selecting full (12-member) receiver pools → created 13-member pools
         ↳ run_sde_meta_pool(db, week_id) — SDE sub-draws for L4 members
         ↳ If start_draw_preparation raises RuntimeError (lock conflict), fallback path runs
           flag_l4_members + redistribute + run_sde_meta_pool directly

e.   execute_weekly_draw(db, auto_pay_unpaid=False)   [T-0H = sunday_midnight]
         ↳ Candidate loop (lines 576–614):
             • Queries ALL Active+Paused pools
             • For each: counts actual active members
             • actual == 12 AND status==Paused: RESTORE to Active (fix c46feda), then → eligible
             • actual == 12 AND status==Active: → eligible
             • actual <  12 AND status==Active: PAUSE pool (draw-protection), record pauses_experienced
             • actual <  12 AND status==Paused: silently skip (Phase 1 will refill)
             ⚠ PRE-FIX behaviour: actual==12 AND Paused went to eligible but run_dual_draw rejected it
         ↳ Draw loop (lines 673–815): for each eligible pool:
             • Skip if draw_completed_this_week==True (SDE already drew it)
             • Re-evaluate LPI gate (U-03)
             • run_dual_draw(db, pool.id, skip_waitlist_fill=True, draw_type=...)
               → requires pool.status == Active (line 324) or raises ValueError
               → picks 2 winners, pays out, marks draw_completed_this_week=True
             • ValueError: pool added to skipped list
             • Other exception: db.rollback(), pool added to skipped
         ↳ Phase 1 refill (line 824): assign_waitlist_to_pools(db) runs after ALL draws complete

f.   post_draw_cleanup(db)   [T+5min = sunday_5min]
         ↳ Resets draw_completed_this_week=False on ALL non-Dissolved pools
         ↳ Resets pool_draw_type=None
         ↳ Clears contains_flagged_l4=False where L4 members exited
         ↳ Releases draw_engine SystemLock
         ↳ Clears sde_required=False on any lingering Eliminated_Won members

     _snapshot(db, week_num, ...)
         ↳ Reads current DB state into a weekly_detail dict entry
         ↳ Key fields: lpi, active_users, waitlist_count, pools_active, pools_paused, pools_formed,
           draws_this_week, winners_this_week, late_payers, eliminated, grace_saved,
           installments_collected_inr, rw_settled_inr, cash_inflow_inr, level_distribution,
           l5_count, l6_count, scenario, momentum, burn_rate, rdr_pct, multiplier
```

---

## assign_waitlist_to_pools() — Phase Detail

### Phase 1 (lines 155–299 of waitlist.py)
1. Fetch ALL Active+Paused pools (`active_pools`)
2. One GROUP BY query → `live_counts` dict (pool_id → actual active count)
3. Build `pools_needing_fill` = pools where `vac = 12 - actual > 0`
4. Fetch `total_vacancies` oldest paid Waitlist users → `candidates`
5. FIFO distribute: assign `min(vac, queue_len)` users per pool
6. Bulk UPDATE users (status→Active, current_pool_id, level=1, payment=Paid) → `db.commit()` (line 267)
7. For each filled pool: update total_members; if pool was Paused AND total_after >= 12 → restore Active (line 277–285) → `db.commit()` (line 286)
8. Credit referral bonuses → `db.commit()` (line 294)

**Critical:** Phase 1 only restores Paused→Active for pools it FILLED in this call. A pool that was already at 12 (vac=0) is excluded from `pools_needing_fill` and never touched.

### Phase 2 (lines 301–466 of waitlist.py)
- Fires when `_available_to_spawn >= threshold` (adaptive LPI-adjusted threshold)
- Bulk-creates new pools with exactly 12 members from waitlist
- Pool rows inserted with `draw_completed_this_week=False` explicitly (critical — SQLite default would set 'false' string which Python reads as True, skipping all new pools)
- New pools start as `status=Active, total_members=12`

### Phase 3 (lines 479+ of waitlist.py)
- Only runs when `wl_remaining == 0` (paid waitlist fully exhausted)
- Also guarded: skipped when draw_engine lock is active
- Consolidates sparse pools into denser ones; dissolves source pools

---

## run_dual_draw() — Requirements
- **Line 324:** `if pool.status != PoolStatus.Active: raise ValueError(...)` — HARD requirement; Paused pools are rejected
- **Line membership check:** `if len(members) != POOL_CAPACITY: raise ValueError(...)` — must have exactly 12
- Picks winner_1 (L1/L2 eligible) and winner_2 via dual-draw algorithm
- Sets `draw_completed_this_week=True` on pool
- Called with `skip_waitlist_fill=True` from execute_weekly_draw (refill is done separately after ALL draws)

---

## LPI — Level Pressure Index

`LPI = (L3 + L4 + L5 + L6) / Total Active × 100`

| LPI Range | Pool type decision |
|---|---|
| < 14% | Regular draw |
| 14–24% | Execution Pool Type A |
| ≥ 25% | SDE proactive (even without L4) |
| Any L4 present | SDE HARD OVERRIDE |
| > 50% | L3 allowed to win SDE lower tier |

---

## Admin Dashboard (React)

- Path: `admin-dashboard/`
- Key page: `src/pages/DevTools.jsx`
  - Line 417: reads `fm.total_collected_inr` from simulation result object
  - SimResults section: shows per-week table from `weekly_detail`
  - Summary panel: shows totals from `fm` (final metrics) object

---

## Simulation Parameters (DRY_PHASE run)
- Scenario: `DRY_PHASE`, momentum=-24, burn_rate=4–22, rdr_pct=29–54%, multiplier=2
- late_ratio drives n_late per week; elim_pct_a=8.3% of late payers eliminated
- 50 weeks, ~1,224 total members created across the run
