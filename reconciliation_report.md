# RECONCILIATION AUDIT — Simulator ↔ Production

- **Run ID filter:** `a4243fd2`
- **Generated:** 2026-06-23T15:16:01.427170+00:00
- **Forensic rows scanned:** 3,634  (kept after run filter: 3,124)
- **Run IDs seen in forensic CSV:** `a4243fd2`=3,151, `d4db9df7`=450, `LIVE_STRESS TEST`=33

> Timeline column = strategy oracle (what should happen).  Forensic column = what the engine actually emitted.
> A divergence is not necessarily a bug — sometimes the engine ran the right action but the event emission was silent. The renderer flags those cases too.

## PHASE 1 — Per-Week Roll-Up Comparison

| W | Posture | T:drw | F:drw | T:win | F:win | T:sde | F:sde | T:pcr | F:pcr | F:mrg | F:pse | F:dis | F:l4 | L5 | L6 | Flags |
|--:|---------|------:|------:|------:|------:|------:|------:|------:|------:|------:|------:|------:|-----:|---:|---:|-------|
| 1 | BALANCED/VELOCITY_CLIFF | 4 | 4 | 8 | 8 | 0 | 0 | 4 | 2 | 3 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-2 |
| 2 | BALANCED/VELOCITY_CLIFF | 4 | 4 | 8 | 8 | 0 | 0 | 2 | 2 | 3 | 0 | 0 | 0 | 0 | 0 | ✓ |
| 3 | BALANCED/VELOCITY_CLIFF | 5 | 5 | 10 | 10 | 0 | 0 | 2 | 2 | 1 | 0 | 0 | 0 | 0 | 0 | ✓ |
| 4 | BALANCED/VELOCITY_CLIFF | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-4 |
| 5 | LIABILITY_CONTROL/DRY_PHASE | 16 | 5 | 32 | 10 | 11 | 0 | 4 | 0 | 9 | 0 | 3 | 0 | 0 | 0 | DRAW_LOG_Δ=-11; WIN_LOG_Δ=-22; POOL_NEW_Δ=-4; POOLS_DISSOLVED=3 |
| 6 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-1; DRAW_FREEZE |
| 7 | LIABILITY_CONTROL/DRY_PHASE | 17 | 8 | 34 | 16 | 9 | 0 | 4 | 0 | 8 | 0 | 2 | 0 | 0 | 0 | DRAW_LOG_Δ=-9; WIN_LOG_Δ=-18; POOL_NEW_Δ=-4; POOLS_DISSOLVED=2 |
| 8 | BALANCED/VELOCITY_CLIFF | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-2; DRAW_FREEZE |
| 9 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-4; DRAW_FREEZE |
| 10 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | DRAW_FREEZE |
| 11 | LIABILITY_CONTROL/DRY_PHASE | 27 | 12 | 54 | 24 | 15 | 0 | 4 | 0 | 5 | 0 | 1 | 0 | 0 | 0 | DRAW_LOG_Δ=-15; WIN_LOG_Δ=-30; POOL_NEW_Δ=-4; POOLS_DISSOLVED=1 |
| 12 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-6; DRAW_FREEZE |
| 13 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-2; DRAW_FREEZE |
| 14 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | DRAW_FREEZE |
| 15 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | DRAW_FREEZE |
| 16 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 4 | 3 | 0 | 1 | 0 | 0 | 0 | POOL_NEW_Δ=-4; DRAW_FREEZE; POOLS_DISSOLVED=1 |
| 17 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-4; DRAW_FREEZE |
| 18 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-4; DRAW_FREEZE |
| 19 | LIABILITY_CONTROL/DRY_PHASE | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | POOL_NEW_Δ=-4; DRAW_FREEZE |
| 20 | LIABILITY_CONTROL/DRY_PHASE | 60 | 24 | 120 | 48 | 36 | 0 | 4 | 0 | 21 | 0 | 4 | 0 | 0 | 0 | DRAW_LOG_Δ=-36; WIN_LOG_Δ=-72; POOL_NEW_Δ=-4; POOLS_DISSOLVED=4 |
| 21 | LIABILITY_CONTROL/DRY_PHASE | 57 | 40 | 114 | 80 | 17 | 0 | 4 | 0 | 26 | 0 | 6 | 0 | 0 | 0 | DRAW_LOG_Δ=-17; WIN_LOG_Δ=-34; POOL_NEW_Δ=-4; BLOWOUT[win=80]; POOLS_DISSOLVED=6 |
| 22 | LIABILITY_CONTROL/DRY_PHASE | 28 | 0 | 56 | 0 | 28 | 0 | 6 | 0 | 6 | 0 | 5 | 0 | 14 | 0 | DRAW_LOG_Δ=-28; WIN_LOG_Δ=-56; POOL_NEW_Δ=-6; L5L6_LEAK[L5=14,L6=0]; POOLS_DISSOLVED=5 |
| 23 | LIABILITY_CONTROL/DRY_PHASE | 2 | 0 | 4 | 0 | 2 | 0 | 6 | 0 | 13 | 0 | 9 | 35 | 28 | 0 | DRAW_LOG_Δ=-2; WIN_LOG_Δ=-4; POOL_NEW_Δ=-6; L5L6_LEAK[L5=28,L6=0]; POOLS_DISSOLVED=9 |
| 24 | LIABILITY_CONTROL/DRY_PHASE | 3 | 0 | 6 | 0 | 3 | 0 | 6 | 0 | 0 | 0 | 0 | 118 | 31 | 0 | DRAW_LOG_Δ=-3; WIN_LOG_Δ=-6; POOL_NEW_Δ=-6; L5L6_LEAK[L5=31,L6=0] |
| 25 | LIABILITY_CONTROL/DRY_PHASE | 4 | 0 | 8 | 0 | 4 | 0 | 6 | 0 | 4 | 0 | 2 | 136 | 34 | 0 | DRAW_LOG_Δ=-4; WIN_LOG_Δ=-8; POOL_NEW_Δ=-6; L5L6_LEAK[L5=34,L6=0]; POOLS_DISSOLVED=2 |
| 26 | LIABILITY_CONTROL/DRY_PHASE | 3 | 0 | 6 | 0 | 3 | 0 | 6 | 0 | 6 | 0 | 3 | 121 | 38 | 0 | DRAW_LOG_Δ=-3; WIN_LOG_Δ=-6; POOL_NEW_Δ=-6; L5L6_LEAK[L5=38,L6=0]; POOLS_DISSOLVED=3 |
| 27 | LIABILITY_CONTROL/DRY_PHASE | 3 | 0 | 6 | 0 | 3 | 0 | 6 | 0 | 6 | 0 | 3 | 111 | 35 | 0 | DRAW_LOG_Δ=-3; WIN_LOG_Δ=-6; POOL_NEW_Δ=-6; L5L6_LEAK[L5=35,L6=0]; POOLS_DISSOLVED=3 |
| 28 | — | 1 | 0 | 2 | 0 | 1 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | DRAW_LOG_Δ=-1; WIN_LOG_Δ=-2; POOL_NEW_Δ=-6 |

## PHASE 2 — Smoking Guns

### 🚨 Q1 — L5/L6 Protection Broken

- **First leak week:** W22 → L5=14, L6=0
- **Peak leak week:**  W26 → L5=38, L6=0
- **Full trajectory:** W22(L5=14,L6=0), W23(L5=28,L6=0), W24(L5=31,L6=0), W25(L5=34,L6=0), W26(L5=38,L6=0), W27(L5=35,L6=0)

**Verdict:** the `SDE Ext-II/III force-exit valve` claim in `app/services/pool_reassessor.py` docstring is FALSE. The engine is allowing members to advance past L4 into L5/L6 instead of force-exiting them. Per **Q1**, the fix is *pure protection* — no member should ever reach L5/L6.

**Code refs to audit next:**
- `app/services/draw.py` — every place a non-flagged L4 winner advances
- `app/services/level_progression.py` (if exists) — survivor +1 logic
- `app/services/pool_reassessor.py` — correct the false docstring

### 🚨 Q2 — Feast-or-Famine via Posture Switching

**Posture transitions:**
- W1 → `BALANCED/VELOCITY_CLIFF`
- W5 → `LIABILITY_CONTROL/DRY_PHASE`
- W8 → `BALANCED/VELOCITY_CLIFF`
- W9 → `LIABILITY_CONTROL/DRY_PHASE`

**Blowout weeks (feast):**
- W21 posture=`LIABILITY_CONTROL/DRY_PHASE` winners=80 draws=40

**Freeze weeks (famine — zero draws):**
- W6 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W8 posture=`BALANCED/VELOCITY_CLIFF`
- W9 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W10 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W12 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W13 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W14 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W15 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W16 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W17 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W18 posture=`LIABILITY_CONTROL/DRY_PHASE`
- W19 posture=`LIABILITY_CONTROL/DRY_PHASE`

**Per Q2:** remove the posture engine entirely. One deterministic steady weekly rule. No BALANCED ↔ LIABILITY_CONTROL switching.

**Code refs to remove/rewrite:**
- `app/services/posture.py` (or wherever `decide_posture()` lives) — delete the switching logic
- Every caller of `decide_posture()` → replace with the new deterministic rule

### 🚨 Q3 — Waitlist + Pool Creation + Orphan Handling

- **Draw freeze weeks:** [6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19]  (no 12/12 pool was drawable — pools shrank below capacity)
- **Pool-dissolve activity** (week → count):
  - W5 → 3 dissolved
  - W7 → 2 dissolved
  - W11 → 1 dissolved
  - W16 → 1 dissolved
  - W20 → 4 dissolved
  - W21 → 6 dissolved
  - W22 → 5 dissolved
  - W23 → 9 dissolved
  - W25 → 2 dissolved
  - W26 → 3 dissolved
  - W27 → 3 dissolved
- **Merger activity** (week → members_merged events):
  - W1 → 3 merges
  - W2 → 3 merges
  - W3 → 1 merges
  - W5 → 9 merges
  - W7 → 8 merges
  - W11 → 5 merges
  - W16 → 3 merges
  - W20 → 21 merges
  - W21 → 26 merges
  - W22 → 6 merges
  - W23 → 13 merges
  - W25 → 4 merges
  - W26 → 6 merges
  - W27 → 6 merges

**Per Q3:** the waitlist → pool-creation → orphan-handling pipeline is broken. Orphan members are not being absorbed by the merger / donor / dissolver path, so existing pools shrink without replacement, which causes the freeze and the L4 stuck pile.

**Code refs to rebuild:**
- `app/services/waitlist.py` — paid-waitlist accounting & emit-to-pool gate
- `app/services/pool_formation.py` (or wherever new pools are created) — ensure orphan-absorbing path exists
- `app/services/merger.py` — donor / receiver semantics, flagged-L4 immunity, and the orphan absorption hook
- `app/services/draw.py` :: pool eligibility predicate — confirm a fresh pool can be formed from orphans + waitlist on the same tick a draw runs

### ⚠ Forensic Logging Gaps (engine ran but did not emit events)

Per-week mismatch between `timeline.draws` and `forensic.draw_executed` count — i.e. the engine fired a draw the forensic recorder never saw:

| W | T:drw | F:drw | Δ | Likely missing emitter |
|--:|------:|------:|--:|------------------------|
| 5 | 16 | 5 | -11 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 7 | 17 | 8 | -9 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 11 | 27 | 12 | -15 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 20 | 60 | 24 | -36 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 21 | 57 | 40 | -17 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 22 | 28 | 0 | -28 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 23 | 2 | 0 | -2 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 24 | 3 | 0 | -3 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 25 | 4 | 0 | -4 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 26 | 3 | 0 | -3 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 27 | 3 | 0 | -3 | SDE / Ext-II / Ext-III / PL3 draw paths  |
| 28 | 1 | 0 | -1 | SDE / Ext-II / Ext-III / PL3 draw paths  |

**Action:** grep every `Draw` / `SdeDraw` / `Pl3Draw` / `ExtDraw` service in `app/services/` for `forensic.record(...)` calls. Every draw type must emit `draw_executed` exactly once.

## PHASE 3 — Forensic Event-Type Counts (all weeks, run-filtered)

| Event Type | Count |
|------------|------:|
| `level_advanced` | 1,120 |
| `member_joined` | 859 |
| `l4_flagged` | 521 |
| `member_won` | 204 |
| `members_merged` | 114 |
| `draw_executed` | 102 |
| `eliminated` | 41 |
| `pool_dissolved` | 39 |
| `posture_decided` | 27 |
| `week_summary` | 27 |
| `meta_pool_complete` | 24 |
| `total_members_resync` | 19 |
| `pool_created` | 14 |
| `post_sde_remerge` | 7 |
| `active_l5l6_present` | 6 |

## PHASE 4 — Next Actions (per user directive Jun-23)

1. **Q1 — L5/L6 pure protection**
   - Audit every L4 advance path; gate L4 → L5 transition.
   - Correct the false `force-exit at L5/L6` docstring in `app/services/pool_reassessor.py`.

2. **Q2 — Remove posture engine**
   - Delete `app/services/posture.py` (or its `decide_posture()` entry).
   - Replace with deterministic single-rule scheduler.

3. **Q3 — Rebuild waitlist / pool-creation / orphan-handling**
   - Trace orphan-member lifecycle end-to-end.
   - Ensure merger / donor / dissolver absorbs every orphan on every tick.

4. **(Diagnostic) Close forensic logging gaps**
   - Add `forensic.record('draw_executed', ...)` to every draw service that's currently silent (SDE / Ext-II / Ext-III / PL3).

5. **Re-run this script** after each fix — same command, regenerated forensic CSV — confirm the corresponding smoking-gun section disappears.

