---
name: session-jun13-handoff
description: Full developer handoff from Claude Session Jun-13, Soheb Khan User 2. Covers complete session history from Render crash through 4 bug fixes. Deep root-cause analysis. Exact file:line refs. Remaining work. Self-contained — no need to re-read the original conversation.
metadata:
  type: project
---

# Session Jun-13 — Complete Developer Handoff

**Date:** 2026-06-13  
**Session identity:** Claude Session Jun-13 / Soheb Khan User 2 / Sohebkhan.sk11  
**Links:** [[reward-scheme-project-overview]] | [[feedback-process-rules]]

---

## 1. How the Session Started — Render Crash

The session opened with the Render deployment crashing. The user shared Render logs showing:

```
psycopg2.errors.InvalidTextRepresentation:
  invalid input value for enum userstatus: "Eliminated_Unpaid"
```

**Root cause:** `app/routers/dev.py` live-stats endpoint at lines 2128–2129 used raw string literals in SQLAlchemy `.filter()` calls. `"Eliminated_Unpaid"` does not exist as a Postgres `userstatus` enum value. The valid enum values are only: `Active`, `Waitlist`, `Eliminated`, `Eliminated_Won`.

**Fix (commit `bcd51d8`):**
```python
# BEFORE (dev.py lines 2128-2129) — crashed Postgres:
won_count    = db.query(func.count(User.id)).filter(User.status == "Eliminated_Won").scalar()    or 0
unpaid_count = db.query(func.count(User.id)).filter(User.status == "Eliminated_Unpaid").scalar() or 0

# AFTER — correct enum member references:
# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
won_count    = db.query(func.count(User.id)).filter(User.status == UserStatus.Eliminated_Won).scalar() or 0
unpaid_count = db.query(func.count(User.id)).filter(User.status == UserStatus.Eliminated).scalar()     or 0
```

After this fix, Render redeployed successfully. The user then ran a 50-week stress test via DevTools.

---

## 2. The 50-Week Simulation — What the User Saw

User ran DRY_PHASE scenario (momentum=-24) for 50 cycles. Three critical problems were observed (user was very angry — "you are blind eyes for sure"):

### Problem A — Total collected shows ₹1,224,000 (wrong)
1,224 members × ₹1,000 = ₹1,224,000. This equals the initial deposit per member, not 50 weeks of installments. The real cumulative total over 50 weeks should be in the millions.

### Problem B — Hydraulic Pipeline missing from DevTools
The production left-nav already has a Hydraulic Pipeline visualization showing the pool ecosystem (L1=Active pools, L2=Paused/buffer pools, L3=Waitlist). The user needs this same view inside the DevTools stress-test SimResults panel so they can watch the pipeline evolve week by week.

### Problem C — Draws stop completely for consecutive weeks
From the CSV simulation output, the following weeks all showed `draws_this_week = 0` despite having active pools with hundreds of members:
- Week 4: pools_active=0, pools_paused=5, active_users=58, draws=0
- Week 7: pools_active=6, pools_paused=3, active_users=107, draws=0
- Weeks 16–24: 9 consecutive zero-draw weeks
- Weeks 31–39: 9 consecutive zero-draw weeks
- Weeks 41–50: 10 consecutive zero-draw weeks
- (Draws only happened in bursts around weeks 13–15, 25, 40)

---

## 3. Fix A — total_collected_inr (commit `b992629`)

**File:** `app/services/real_simulation.py` line 1421 (post-fix: ~line 1427)

**Root cause:** The final financials section at the end of the simulation run calculated:
```python
total_collected = Decimal(str(total_users_created * 1000))
```
This multiplies the TOTAL MEMBER COUNT by ₹1,000 exactly once — computing only the initial join deposit per member. It completely ignores the 50 weeks × N active members × ₹1,000 weekly installments.

The correct value is already computed week-by-week: each `weekly_detail` entry has `installments_collected_inr` from the actual WK-token query (`auto_pay_installments` creates these). The final total should sum those.

**Fix:**
```python
# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
# FIX: was total_users_created×1000 = initial deposits only (wrong).
# Correct value is the sum of weekly installments actually collected.
total_collected = sum(
    Decimal(str(w.get("installments_collected_inr", 0)))
    for w in weekly_detail
)
```

**Where `installments_collected_inr` comes from:** `_snapshot()` in `real_simulation.py` (lines 781–794) queries the WK-token table to count paid installments for the current week. This is already accurate per-week. Only the final summary aggregation was wrong.

**DevTools impact:** `admin-dashboard/src/pages/DevTools.jsx` line 417 reads `fm.total_collected_inr` for the Summary panel. After this fix, the Summary panel will show real cumulative revenue.

---

## 4. Fix B — Draw Blackouts: Primary Root Cause (commit `c26d4d8`)

**File:** `app/services/brain5_lpi_engine.py` — `redistribute_multi_l4_pools()` lines 393–404

### What redistribute_multi_l4_pools does
At step d (draw preparation), this function ensures no pool contains more than 1 L4-flagged member. The SDE architecture constraint is: each SDE sub-draw handles exactly 1 L4 (upper winner). A pool with 2+ L4s would require two sub-draws for the same pool — violating the "max 2 winners per pool" rule.

Algorithm:
1. Find pools with ≥ 2 L4-flagged members; collect the "excess" L4 members
2. Find "receiver pools" — Active or Paused pools with 0 L4-flagged members
3. Move excess L4 members one-by-one into receiver pools

### The bug
The receiver pool query (original lines 395–404) had NO capacity check:
```python
receiver_pools: list[Pool] = (
    db.query(Pool)
    .filter(
        Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]),
        Pool.contains_flagged_l4 == False,
        Pool.id.notin_(occupied_pool_ids),
    )
    .order_by(Pool.id.asc())
    .all()
)
```

If the selected receiver pool already had 12 members (POOL_CAPACITY), adding the L4 member brought it to **13 members**. This triggers a permanent deadlock chain:

```
Pool Q: 12 members (Active) → receives L4 move → 13 members (Active)
  ↓
execute_weekly_draw candidate loop:
  actual=13 ≠ POOL_CAPACITY(12) AND status==Active → PAUSE Pool Q
  ↓
Phase 1 refill after draws:
  vac = 12 - 13 = -1 → vac > 0 is False → SKIP Pool Q
  ↓
Next week candidate loop:
  actual=13, status==Paused → not eligible (13≠12), not paused (already Paused)
  → SILENTLY SKIPPED
  ↓
PERMANENT DEADLOCK: Pool Q stays Paused with 13 members forever
```

### Why draws burst then stop (weeks 25, 40 had draws)
Only freshly created Phase 2 pools (status=Active, exactly 12 members, draw_completed_this_week=False) could draw. Once those Phase 2 pools also went through a draw cycle and their refill+redistribution cycle landed some of them in the Paused+13 state, draws stopped again.

As the simulation progressed, the fraction of pools in the Paused+over-capacity deadlock grew week over week, collapsing the draw rate to zero.

### Fix
Pre-compute live active member counts for candidate receiver pools with one GROUP BY query; exclude any pool already at capacity:
```python
# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
# BUG FIX: original query had no capacity check — a receiver pool already at
# POOL_CAPACITY members would become capacity+1 after the move.  The candidate
# loop in execute_weekly_draw then pauses it (actual≠12) and Phase 1 skips it
# (vacancy=-1), creating a permanent Paused+over-capacity deadlock.
from app.core.config import POOL_CAPACITY as _RPOOL_CAP
occupied_pool_ids = set(pool_l4_counts.keys())
_all_receivers: list[Pool] = (
    db.query(Pool)
    .filter(
        Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]),
        Pool.contains_flagged_l4 == False,   # noqa: E712
        Pool.id.notin_(occupied_pool_ids),
    )
    .order_by(Pool.id.asc())
    .all()
)
_recv_ids = [p.id for p in _all_receivers]
_recv_counts: dict[int, int] = {}
if _recv_ids:
    for _row in (
        db.query(User.current_pool_id, func.count(User.id))
        .filter(
            User.current_pool_id.in_(_recv_ids),
            User.status == UserStatus.Active,
        )
        .group_by(User.current_pool_id)
        .all()
    ):
        _recv_counts[_row[0]] = _row[1]
# Only pools with room for one more member are valid receivers
receiver_pools: list[Pool] = [
    p for p in _all_receivers if _recv_counts.get(p.id, 0) < _RPOOL_CAP
]
```

Note: `func` and `User/UserStatus` are already imported at module level in `brain5_lpi_engine.py`. Only `POOL_CAPACITY` needed an inline import.

---

## 5. Fix C — Draw Blackouts: Secondary Deadlock (commit `c46feda`)

**File:** `app/services/draw.py` — `execute_weekly_draw()` candidate loop lines 586–611

### The bug
The candidate loop (lines 576–614) processes all Active+Paused pools:
```python
if actual == POOL_CAPACITY:
    eligible.append(pool)          # ← NO status check — adds Paused pools!
elif pool.status == PoolStatus.Active:
    pool.status = PoolStatus.Paused_Awaiting_Members  # pause under-capacity
# Already Paused with <12 → silently skipped
```

When a Paused pool has exactly 12 members:
1. It passes `actual == POOL_CAPACITY` → added to `eligible`
2. In draw loop: `run_dual_draw(db, pool.id, ...)` called
3. `run_dual_draw` line 324: `if pool.status != PoolStatus.Active: raise ValueError(...)` → **rejected**
4. Pool added to `skipped` list, draw does not happen
5. Phase 1 after draws: `vac = 12 - 12 = 0` → excluded from `pools_needing_fill` → **skipped**
6. Pool stays Paused+12 forever — **permanent deadlock**

### How a pool gets into Paused+12 state
Primary path (from Fix B above): `redistribute_multi_l4_pools` moves an L4 member into a pool with 11 members → pool becomes 12 members Active → eligible in candidate loop → draw happens → pool drops to 10 members → candidate loop pauses it → Phase 1 refills to 12 → Paused+12 restoration fails (Phase 1 only restores when it FILLS in the current call; a pool refilled to exactly 12 has its status restored, but if Phase 1's commit at line 286 is interrupted after line 267, users are assigned but status stays Paused).

Secondary path: SQLAlchemy session cache can leave a pool object stale between Phase 1's two commit points (line 267 and line 286), causing the restoration check to see an outdated status.

### Fix
In the candidate loop, when `actual == POOL_CAPACITY` and pool is still Paused, restore it to Active before appending to eligible:
```python
if actual == POOL_CAPACITY:
    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Defensive recovery: a Paused pool already at capacity has vacancy=0 so
    # Phase 1 never refills it, and run_dual_draw rejects it (status≠Active),
    # creating a permanent deadlock.  Restore to Active here so the draw runs.
    if pool.status == PoolStatus.Paused_Awaiting_Members:
        pool.status = PoolStatus.Active
        db.flush()
        _logger.info(
            "execute_weekly_draw: ♻  %s was Paused but has %d/%d members — "
            "restored to Active for draw.",
            pool.name, actual, POOL_CAPACITY,
        )
    eligible.append(pool)
```

---

## 6. Complete Commit Log — This Session

| Commit | File changed | What and why |
|---|---|---|
| `bcd51d8` | `app/routers/dev.py` lines 2128–2129 | Postgres crash: replaced raw string `"Eliminated_Unpaid"` (invalid enum) with `UserStatus.Eliminated`; replaced `"Eliminated_Won"` with `UserStatus.Eliminated_Won` |
| `b992629` | `app/services/real_simulation.py` ~line 1421 | Summary panel: replaced `total_users_created × 1000` with `sum(weekly_detail[w].installments_collected_inr)` |
| `c26d4d8` | `app/services/brain5_lpi_engine.py` lines 393–404 | Primary draw-blackout fix: added capacity filter to receiver pools in `redistribute_multi_l4_pools`; prevents Paused+13 permanent deadlock |
| `c46feda` | `app/services/draw.py` lines 592–593 | Secondary draw-blackout fix: candidate loop now restores Paused+12 pools to Active before draw instead of letting them fail in run_dual_draw |

---

## 7. Files — Complete Reference

| File | Lines | What's there |
|---|---|---|
| `app/routers/dev.py` | 2128–2129 | live-stats user count queries (fixed this session) |
| `app/services/real_simulation.py` | 1055–1134 | Step a (inject) + step a.5 (assign_waitlist) |
| `app/services/real_simulation.py` | 1151–1237 | Steps b (FM reset), c (abc model), c.2 (auto_pay), c.5 (enforce capacity) |
| `app/services/real_simulation.py` | 1239–1305 | Step d (draw preparation with fallback) |
| `app/services/real_simulation.py` | 1307–1347 | Steps e (execute_weekly_draw) and f (post_draw_cleanup) |
| `app/services/real_simulation.py` | 1414–1430 | Final financials (total_collected fixed here) |
| `app/services/real_simulation.py` | 679–732 | `_fm_enforce_pool_capacity()` — only called when n_elim > 0 |
| `app/services/waitlist.py` | 155–299 | Phase 1: fill under-capacity pools |
| `app/services/waitlist.py` | 267 | `db.commit()` — bulk user UPDATE committed here (before pool status restoration) |
| `app/services/waitlist.py` | 272–285 | Phase 1 pool status restoration: Paused→Active ONLY when filled in this call |
| `app/services/waitlist.py` | 286 | `db.commit()` — pool status restoration committed here |
| `app/services/waitlist.py` | 301–466 | Phase 2: bulk pool creation |
| `app/services/waitlist.py` | 383–390 | Phase 2 pool_rows: `draw_completed_this_week=False` explicit (critical SQLite boolean fix) |
| `app/services/waitlist.py` | 479–600 | Phase 3: condensation (only when wl_remaining==0 and lock not active) |
| `app/services/draw.py` | 292–346 | `run_dual_draw()` — line 324 requires pool.status==Active |
| `app/services/draw.py` | 570–614 | `execute_weekly_draw()` candidate loop (fixed c46feda) |
| `app/services/draw.py` | 673–689 | Draw loop: skip if draw_completed_this_week==True |
| `app/services/draw.py` | 745–815 | Draw loop body: run_dual_draw + exception handling |
| `app/services/draw.py` | 823–824 | Phase 1 refill after all draws: `assign_waitlist_to_pools(db)` |
| `app/services/draw.py` | 846+ | `post_draw_cleanup()` — resets flags, releases lock |
| `app/services/brain5_lpi_engine.py` | 343–462 | `redistribute_multi_l4_pools()` (fixed c26d4d8) |
| `admin-dashboard/src/pages/DevTools.jsx` | 417 | Reads `fm.total_collected_inr` for Summary panel |

---

## 8. Important Architectural Gotchas (Don't Repeat These Mistakes)

### Paused+over-capacity deadlock mechanism
```
Pool at POOL_CAPACITY members + Paused status = PERMANENT DEADLOCK
  → Phase 1 skips it (vac ≤ 0)
  → run_dual_draw rejects it (not Active)
  → candidate loop silently includes it in eligible but draw fails
  → no recovery without the Fix C defensive restore
```

### Phase 1 dual-commit danger zone
Phase 1 commits user assignments at line 267 (users in pool, but pool still Paused), then commits pool status restoration at line 286. If anything interrupts between these two commits, pools can end up with 12 assigned members but still Paused status. Fix C (candidate loop restore) handles this defensively.

### _fm_enforce_pool_capacity only fires when n_elim > 0
`app/services/real_simulation.py` line 1230: `if compliance.get("n_elim", 0) > 0:`. With A=8.3% elimination rate on small n_late, many weeks have 0 eliminations. This means under-capacity Active pools from OTHER causes (redistribution moving members out) are NOT proactively fixed before draw prep. They get caught later by the candidate loop's draw-protection pause, but they miss this week's draw.

### draw_completed_this_week=False must be explicit in Phase 2 bulk INSERT
SQLite's `server_default='false'` for this Boolean column stores the string `'false'`. Python's `bool('false')` returns `True` (non-empty string). Without the explicit `False` in the `pool_rows` dict, all new Phase 2 pools would have `draw_completed_this_week=True` and be skipped by every draw cycle until `post_draw_cleanup` resets them. The fix is at `waitlist.py` line 390.

### run_dual_draw is called with skip_waitlist_fill=True from execute_weekly_draw
The individual pool refill is skipped inside run_dual_draw. A single combined Phase 1 refill runs after ALL draws complete (draw.py line 824). This is intentional — FIFO waitlist assignment is more efficient in one batch.

---

## 9. Remaining Work (Not Done This Session)

### P1 — Hydraulic Pipeline in DevTools SimResults (NOT STARTED)

**What it is:** The production left-nav has a Hydraulic Pipeline page showing:
- Layer 3 (input): Waitlist count (new users waiting)
- Layer 2 (buffer): Paused_Awaiting_Members pools (filling up)
- Layer 1 (output): Active pools (drawing weekly)
- Threshold line: `phase2_threshold` = `get_adaptive_threshold(db)` (Brain 2 LPI-adjusted)

User wants this visualization inside the DevTools stress-test SimResults panel so they can see the pipeline state for each of the 50 weeks.

**What needs to change:**
1. `_snapshot()` in `real_simulation.py` — add `phase2_threshold` and `phase2_can_create` to each weekly snapshot dict
   - `phase2_threshold = get_adaptive_threshold(db)` (import from waitlist.py)
   - `phase2_can_create = waitlist_count >= phase2_threshold`
   - Already have: `pools_active`, `pools_paused`, `waitlist_count`
2. `admin-dashboard/src/pages/DevTools.jsx` — in SimResults section, render a pipeline visualization per week using `weekly_detail` data
   - L3 = `w.waitlist_count`
   - L2 = `w.pools_paused × POOL_CAPACITY` (or just `w.pools_paused`)
   - L1 = `w.pools_active`
   - Threshold = `w.phase2_threshold` (new field)
   - Use existing pipeline component from production view (or re-implement as SVG/chart)

### P2 — Verify simulation correctness after Render redeploy (NOT DONE)

After Render picks up commits `c26d4d8` and `c46feda`:
1. Run fresh 50-week stress test in DevTools
2. Verify: no week shows `draws_this_week=0` when `pools_active > 0`
3. Verify: Summary panel `total_collected_inr` ≈ SUM of all `installments_collected_inr` column in CSV
4. Verify: no "Paused+12" or "Paused+13" pool states visible in per-week data

---

## 10. Pre-Session Bug Fix Context (Commits Before This Session)

The session summary referenced "A1-A3/B/C/D1-D3 fixes deployed to Render" before this session started. These were earlier simulation correctness fixes. Key one noted in code comments:

**FIX A3** (`real_simulation.py` lines 1152–1168): Corrected FM payment-cycle order
```
OLD (wrong) order:
  Monday — reset ALL → Unpaid
  Monday — auto_pay ALL → Paid + WK tokens (even future late payers!)
  Thursday — apply_abc → re-mark n_late% Unpaid (tokens already issued!)

NEW (correct) order:
  Monday    — reset ALL → Unpaid
  Thursday  — apply_abc → A eliminated, B late-fee stays Unpaid, C grace → Paid
  Thursday  — auto_pay(skip_ids=type_b_ids) → non-late Unpaid → Paid
```
Effect: WK installment tokens are only created for members who ACTUALLY paid. `installments_collected_inr` became accurate per week after this fix.

There was also a noted fix for `draw_completed_this_week=False` in Phase 2 pool creation (the SQLite boolean bug described above in section 8).
