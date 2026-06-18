# REWARD SCHEME — COMPLETE STRATEGY WIRE DIAGRAM
## (Production-faithful · har situation included · English + Hinglish)

> Rebuilt by reading the ACTUAL production code end-to-end, not from memory.
> Yeh diagram production code ka 1:1 reflection hai — koi cheez simplify ya skip nahi ki.
> Sources read: `draw.py`, `sde_engine.py`, `brain5_lpi_engine.py`, `draw_preparation.py`,
> `waitlist.py`, `admin_elimination.py`, `scheduler.py`, `global_config.py`, `core/config.py`,
> models: `pool.py`, `user.py`, `draw_history.py`, `elimination_event.py`.
>
> PURPOSE / MAQSAD: Teen cheezo ke beech ka GAP expose karna —
>   (a) meri understanding   (b) jo code likha gaya   (c) jo strategy aapne design ki thi.
> Last section (§17) explicitly har divergence list karta hai.

---

## LEGEND / SANKET

```
[BOX]          = ek state ya entity (pool / user / token)
( decision )   = branch / if-else
──▶            = flow / next step
═══            = section divider
★              = money event (paisa move hota hai)
⚠              = GAP / defect / dead-code (design vs code mismatch) — see §17
DB:key         = runtime-configurable value (system_settings table, admin live-editable)
```

Default numbers (config.py + global_config.py defaults — admin DB se override ho sakte hain):

```
POOL_CAPACITY .............. 12         (members per pool)
WAITLIST_TRIGGER ........... 24         (base new-pool trigger)
NEW_POOL_INTAKE ............ 12
DEPOSIT_AMOUNT_INR ......... ₹1,000     DB:base_installment_inr
PAYOUT_FEE_INR ............. ₹500       DB:payout_fee_inr
REFERRAL_REWARD_INR ........ ₹250       DB:(settings.py)
LATE_FEE_DAILY_INR ......... ₹50/day    DB:late_fee_daily_inr
LATE_FEE_MAX_CAP_INR ....... ₹500       DB:late_fee_max_cap_inr   (caps at 10 days)
GRACE seat-save fee ........ ₹500       DB:grace_seat_save_fee_inr
GRACE window ............... 48 h       DB:grace_period_hours
```

Per-level payout (gross, net-after-₹500-fee) — DB:level_{N}_gross/net_inr:

```
L1: (2500, 2000)   L2: (3500, 3000)   L3: (4500, 4000)
L4: (6000, 5500)   L5: (7000, 6500)   L6: (8500, 8000)
```

LPI thresholds — DB-backed:

```
LPI = (L3+L4+L5+L6) / TotalActive × 100
< 14%   → Regular        DB:lpi_regular_max = 14.0
14–24%  → Type A         DB:lpi_type_a_min  = 14.0
≥ 25%   → SDE proactive   DB:lpi_sde_proactive = 25.0
> 50%   → L3 may win SDE lower tier   DB:lpi_l3_win_exception = 50.0
ANY flagged L4 → SDE HARD OVERRIDE (LPI chahe kuch bhi ho)
```

═══════════════════════════════════════════════════════════════════════════════
## §0 — SYSTEM CLOCK / WEEKLY TIMELINE (scheduler.py — 5 cron jobs)
═══════════════════════════════════════════════════════════════════════════════

EN: The whole engine is driven by APScheduler. Five jobs run the week. `SCHEDULER_ENABLED=true` zaroori hai warna kuch auto nahi chalega.
HI: Poora engine APScheduler se chalta hai. Paanch jobs hafte ko drive karte hain.

```
                          ── ONE WEEKLY CYCLE (default Sunday draw) ──

  every 6h         T-2H              every 5 min         T-0H            T+5 min
  ─────────        ────              ───────────         ─────           ───────
[Job5            [Job1            [Job2 watchdog      [Job3            [Job4
 data-integrity   PREPARATION      override auto-      WEEKLY DRAW      POST-CLEANUP
 auto-repair]     11:30 UTC]       select]            13:30 UTC]       13:35 UTC]
     │                │                  │                 │                │
     │                │                  │                 │                │
  pool count       acquire           if admin         execute_weekly_   reset flags,
  sync,            draw_engine       override          draw()            release lock
  orphan SDE       LOCK +            deadline passed   (see §7)
  clear,           snapshot +        → auto pick
  grace expire,    SDE pre-process   cheaper option
  L4 flag fix      (see §5)
```

⚠ GAP-0: Production scheduler ka default `SCHEDULER_ENABLED=false`. Agar koi ise true nahi
karta, to koi bhi job nahi chalega — draws manual admin trigger pe hi honge. (Operational note.)

Draw time = `DRAW_HOUR_UTC:DRAW_MINUTE_UTC` (default 13:30 UTC = 7 PM IST).
Prep = T-2H, Cleanup = T+5min. Lock held T-2H → T+0H:10 (`DRAW_LOCK_TOTAL_MINUTES=130`).

═══════════════════════════════════════════════════════════════════════════════
## §1 — MONEY IN: REGISTRATION → WAITLIST → DEPOSIT → REFERRAL
═══════════════════════════════════════════════════════════════════════════════

```
[New user registers]
        │
        ▼
★ pays ₹1,000 advance (100% upfront)  →  UserStatus = Waitlist, weekly_payment_status = Paid
        │
        │  (referral bonus yahan NAHI milta — Rule 39)
        ▼
[ Waits in Waitlist queue, ordered by join_date ASC (FIFO) ]
        │
        ▼
   assign_waitlist_to_pools()  →  user ENTERS an Active pool  (see §2)
        │
        ▼
★ Rule 39: NOW referrer ko ₹250 credit (DB:referral_reward_inr)
   • _credit_referral_bonus(): referrer.accumulated_referral_bonus_inr += 250
   • referrer.total_referrals_count += 1
   • reward == 0 → count phir bhi badhta hai (stats accurate), paisa nahi
   • koi alag token nahi banta — balance accumulate hota hai
   • payout on demand: POST /users/request-referral-payout
```

EN: Referral is credited at THREE pool-entry paths, never at registration:
HI: Referral teen jagah credit hota hai, registration pe kabhi nahi:
```
  1. waitlist.py  — bulk auto-scale (Phase 1/2 new pool)
  2. draw.py      — winner ke baad replacement fill
  3. admin.py     — elimination ke baad vacancy fill
```

═══════════════════════════════════════════════════════════════════════════════
## §2 — WAITLIST → POOL : DOUBLE-FIFO ENGINE (waitlist.py, 3 phases)
═══════════════════════════════════════════════════════════════════════════════

EN: `assign_waitlist_to_pools()` is THE single source of truth for placing members.
    Called after EVERY vacancy-creating or waitlist-adding event.
HI: Yeh function har vacancy/waitlist event ke baad chalta hai. Teen phase:

```
┌─ PHASE 1 — Bulk refill existing under-capacity pools ─────────────────────────┐
│  Pool priority  : created_at ASC   (sabse purana pool pehle bhare)            │
│  Member priority: join_date  ASC   (sabse purana waitlist user pehle)         │
│  For each under-cap pool: vacancy = 12 − active_count                          │
│  Bulk UPDATE users → Active, level=1, Paid, pool assigned                      │
│  ★ referral credit for each placed referred user                               │
│  If a Paused_Awaiting_Members pool refills to 12 → restore to Active           │
└───────────────────────────────────────────────────────────────────────────────┘
            │  (waitlist abhi bhi bacha?)
            ▼
┌─ PHASE 2 — Bulk auto-scale NEW pools ─────────────────────────────────────────┐
│  Gate A: get_auto_pool_creation() ON hona chahiye                              │
│  Gate B: ADAPTIVE threshold (LPI pressure ↑ → threshold ↓ toward 12)           │
│          effective = max(12, 24 × (1 − min(0.5, LPI/100)))                      │
│          LPI ≥ 50% → threshold = 12 (POINT 7 deadlock fix)                      │
│  Gate C: AI Quant reserve multiplier (ai_quant_engine.determine_reserve_*)     │
│          dynamic_reserve = operational_pools × 12 × multiplier                  │
│          available_to_spawn = max(0, waitlist − dynamic_reserve)                │
│  If available_to_spawn ≥ threshold:                                            │
│     pools_to_make = available_to_spawn // 12                                    │
│     bulk INSERT full Active pools (draw_completed_this_week EXPLICIT False)     │
│     ★ referral credit per placed user                                          │
└───────────────────────────────────────────────────────────────────────────────┘
            │  (paid waitlist == 0 AND under-cap pools still exist?)
            ▼
┌─ PHASE 3 — DYNAMIC INTER-POOL CONDENSATION (the "merge" engine) ──────────────┐
│  RUNS ONLY IF ALL true:                                                        │
│    (a) paid waitlist == 0                                                       │
│    (b) koi pool < 12 members                                                   │
│    (c) draw_engine LOCK active NAHI (T-2H→T+0:10 window me BLOCKED)            │
│  Target = under-cap Active/Paused pools, created_at ASC                        │
│  Source = FULL Active pools, created_at DESC, NOT in target set,               │
│           AND contains_flagged_l4 == False  ← L4-flagged pool IMMUNE            │
│  Transfer: FIFO within source (oldest member first)                            │
│  PRESERVE: current_level, weekly_payment_status, join_date  (NEVER touched)    │
│  ★ moved member: dynamic_merges_experienced += 1, journey_type → "merged"      │
│  Source empties out → status = Merged_Dissolved, total_members = 0             │
└───────────────────────────────────────────────────────────────────────────────┘
```

Admin manual path: `manual_create_pool()` — toggle/threshold bypass, needs ≥12 paid WL.

═══════════════════════════════════════════════════════════════════════════════
## §3 — POOL LIFECYCLE : 5 STATES (pool.py PoolStatus enum)
═══════════════════════════════════════════════════════════════════════════════

```
   [Waiting]  ──fill──▶  [Active]  ◀──restore── [Paused_Awaiting_Members]
   (initial)               │  ▲                        ▲   │
                           │  └── refill to 12 ─────────┘   │
            draw day, <12  │                                │ <12 members at draw
            members ───────┴──────────▶ pause ─────────────┘
                           │
                           │  Phase-3 condensation empties it
                           ▼
                   [Merged_Dissolved]   (total_members = 0, permanent)

   [Full]  = transient label (rarely set; capacity reached)
```

Pool-level flags (drive routing):
```
draw_completed_this_week  — TRUE after this pool drew this cycle (double-draw guard)
                            Reset FALSE by post_draw_cleanup (T+5)
pool_draw_type            — 'regular'|'type_a'|'sde'|'type_b'|'accelerated_dissolution'
                            |'sde_ext2'|'sde_ext3'|'sde_case_c'|'sde_preventive_l3'|NULL
contains_flagged_l4       — TRUE if ≥1 member has sde_required=True
                            → condensation IMMUNITY + SDE routing
```

⚠ GAP-3: Code `PoolStatus.Dissolved` ko reference karta hai (draw.py:1408) but enum me
sirf `Merged_Dissolved` hai. Accelerated dissolution jab pool ko <8 pe dissolve karega →
**AttributeError**. (See §12 + §17.)

═══════════════════════════════════════════════════════════════════════════════
## §4 — WEEKLY PAYMENT & COMPLIANCE LADDER (admin_elimination.py)
═══════════════════════════════════════════════════════════════════════════════

EN: Every Active member owes ₹1,000 each cycle. After each draw, level-advance loop sets
    everyone back to Unpaid. Non-payment escalates through a 5-rung ladder.
HI: Har Active member ko har cycle ₹1,000 dena. Draw ke baad sab Unpaid ho jaate hain.

```
[Active member, weekly_payment_status = Unpaid after draw]
        │
        │  pays ₹1,000?
        ├── YES ──▶ Paid  ──▶ eligible to ADVANCE +1 level next draw
        │
        └── NO  ──▶ due date (DB:payment_due_days=4, Mon→Thu) cross
                        │
                        ▼  ★ LATE FEE accrues ₹50/day (cap ₹500 @ 10 days)
                  [ Unpaid + late_fees ]
                        │
                        ▼  mark-at-risk (daily scheduler / admin)
                  elimination_risk = True   (unpaid AND late_fees ≥ 1 day)
                        │
              ┌─────────┴──────────┐
        grant-grace?           no grace
              │                     │
              ▼                     │
   [grace_active=True,             │
    grace_expires_at=now+48h]      │
              │                     │
        pay ₹500 + late fees?       │
        ├── YES ─▶ save-seat        │
        │   (ADMIN PASSWORD ★)      │
        │   • grace_fee_paid=True    │
        │   • elimination_risk=False │
        │   • late_fees → ₹0         │
        │   • status → Paid          │
        │   • ★ revenue counters++   │
        │   • ★ issue LFC + GF tokens│
        │   • SEAT SAVED             │
        │                            │
        └── NO / grace expires ──────┴──────▶ execute elimination (ADMIN PASSWORD ★)
                                                   │
                                                   ▼
                                        ★ UserStatus = Eliminated
                                          current_pool_id = None
                                          ★ FORFEIT = ₹1,000 deposit
                                              + accrued late fees
                                              + grace seat-save fee (if was in grace)
                                          → all forfeit = ADMIN PROFIT
                                          → EliminationEvent audit row
                                          reason = grace_expired | non_payment
```

KEY revenue distinction (revenue-summary endpoint):
```
COLLECTED  = late/grace fees members actually PAID  → real business revenue
FORFEITED  = deposit/fees members LOST (never collected) → NOT our loss, member's loss
```

Toggles: `auto_eliminate_enabled`, `grace_period_enabled` (DB).
Data-integrity job (6h) bhi expired grace ko close + elimination_risk=True set karta hai.

PAYMENT GATE inside the draw (draw.py survivor loop) — CRITICAL:
```
( survivor paid this week? )
   YES → new_level = min(level+1, 6);  reaching_L4 → sde_required flag set
   NO  → level UNCHANGED;  reaching_L4 forced False  (no spurious SDE flag)
```

═══════════════════════════════════════════════════════════════════════════════
## §5 — T-2H PREPARATION (draw_preparation.py — 10 steps, one atomic commit)
═══════════════════════════════════════════════════════════════════════════════

```
start_draw_preparation(draw_time_utc)
   │
   ├─ idempotency: week already prepared & valid? → return existing (no-op)
   │
   ├─ acquire draw_engine LOCK (INSERT … ON CONFLICT) — blocks Phase-3 condensation
   │     fail → RuntimeError (another prep running)
   │
   ▼  _run_preparation():
   STEP 1  create/update WeeklyDrawState (reset valid/countdown flags)
   STEP 2  SNAPSHOT: LPI + level distribution (L4/L3/total) frozen into state
   STEP 3  flag_l4_members() catch-up sweep (belt-and-suspenders; normally 0)
   STEP 4  SDE demand: sessions=ceil(L4/6), L1L2_need=L4×2,
                       clearable=min(L4, L1L2//2), overflow=L4−clearable
   STEP 5  overflow > 0 → admin_override_required=True, deadline=now+2h
   STEP 6  float projection: worst-case payout sum across pools (solvency check)
   STEP 7  consecutive Type-B weeks counter; ≥2 → low-L1/L2 supply WARNING
   STEP 8  if L4>0 AND not override-blocked → run_sde_meta_pool() (see §9)
              (override-blocked → SDE DEFERRED until admin decides)
   STEP 9  two-flag activation: preparation_valid=True AND countdown_active=True
   STEP 10 single atomic db.commit()  (any failure → rollback + release lock)
```

Two-flag countdown contract: frontend timer dikhta hai ONLY when BOTH flags True.
Lock window (T-2H → T+0:10) ke andar condensation (Phase 3) hamesha SKIP.

═══════════════════════════════════════════════════════════════════════════════
## §6 — BRAIN-5 LPI ROUTING DECISION TREE (brain5_lpi_engine.decide_pool_types)
═══════════════════════════════════════════════════════════════════════════════

```
                LPI = (L3+L4+L5+L6) / TotalActive × 100
                                │
        ┌───────────────────────┼─────────────────────────────┐
        ▼                       ▼                              ▼
 ( ANY flagged L4? )    ( LPI ≥ 25%? )               (otherwise band)
        │ YES                  │ YES                          │
        ▼                      ▼                              ▼
 P1 SDE = ON           P1 SDE = ON                   ( 14% ≤ LPI < 25% AND L3>0 )
 reason=hard_override  reason=proactive_lpi                 │ YES
 (LPI ignore)                                               ▼
                                                      P2 TYPE_A = ON
                                                            │
                                              ( LPI < 14% )  ▼ YES
                                                      P3 REGULAR = ON

 SUPPLY OVERRIDE:  ( L1+L2 == 0 ) → P4 TYPE_B = ON  (L3 lower / L4 upper fallback)
 SUFFICIENCY:      L1L2_available ≥ L4 × 2  → sde_threshold_met
```

Tier-split per route (config.py):
```
regular : lower L1–L3   upper L4–L6
type_a  : lower L1–L2   upper L3–L4
type_b  : lower L3      upper L4
sde     : lower L1–L2 (L3 only if LPI>50)   upper L4 ONLY (hardcoded)
sde_ext2: lower L1–L4   upper L5 ONLY
sde_ext3: lower L1–L5   upper L6 ONLY
accel   : BOTH winners L4–L6
prev_l3 : BOTH winners L3
```

═══════════════════════════════════════════════════════════════════════════════
## §7 — THE WEEKLY DRAW ORCHESTRATION (draw.execute_weekly_draw) — ORDER IS LAW
═══════════════════════════════════════════════════════════════════════════════

EN: This is the master Sunday entry. Pre-passes run in a FIXED order before regular draws.
    Each pre-pass marks its pools draw_completed_this_week=True so the regular loop skips them.
HI: Yeh master entry hai. Pre-pass FIXED order me chalte hain; har pre-pass apne pools ko
    draw_completed mark kar deta hai taaki regular loop unhe skip kare.

```
execute_weekly_draw()
  │
  │ STEP 0   ── SDE Ext-II / Ext-III PRE-PASS ──────────────────────────────
  │           check_and_run_sde_extensions(): Ext-III (L6) THEN Ext-II (L5)
  │           clears any L5/L6 first → partial WL refill                  (§11)
  │           ⚠ SKIPS pools where draw_completed_this_week already True
  │
  │ STEP 0.5 ── PREVENTIVE L3 PRE-PASS ─────────────────────────────────────
  │           check_and_run_preventive_l3_draws(): cascade_risk > 2.0
  │           → exits 2 L3 from each eligible pool BEFORE they hit L4 → refill (§10)
  │
  │ STEP 0.7 ── execute_staged_sde_draws() ─────────────────────────────────
  │           T-0H commit of all SDE sub-draws STAGED at T-2H (two-phase) (§9)
  │           WIT tokens + Eliminated_Won + DrawHistory + survivor advance
  │
  │ STEP 1   ── PRE-DRAW UNCONDITIONAL REFILL (DEADLOCK FIX, Jun-16) ────────
  │           assign_waitlist_to_pools() BEFORE eligibility gate
  │           → fills/spawns pools first so draw always evaluates filled pools
  │           (prevents the self-reinforcing stall: no refill→<12→ValueError→no refill)
  │
  │ STEP 2   ── DISCOVER ELIGIBLE POOLS ────────────────────────────────────
  │           candidates = Active + Paused pools
  │           per pool:
  │             draw_completed_this_week? → SKIP (already drawn by pre-pass)
  │             active == 12? → eligible (Paused→restore Active)
  │             Active but <12? → PAUSE it (Paused_Awaiting_Members),
  │                               ★ pauses_experienced += 1 for all members
  │           if no eligible AND no pre-pass draws → ValueError
  │           if no eligible BUT pre-passes ran → log + fall through (refill+reveal)
  │
  │ STEP 3   ── (optional) auto-pay unpaid members
  │
  │ STEP 4   ── ATOMIC LPI SNAPSHOT baseline (engine_snapshot)
  │
  │ STEP 5   ── PER-POOL DRAW LOOP ─────────────────────────────────────────
  │           U-03 re-eval gate: LPI shifted ≥ 0.5pp → re-route draw_type
  │                              (cap MAX_REEVALS=3)
  │           U-04 convergence guard: LPI must be monotonic non-increasing
  │           run_dual_draw(pool, draw_type)   (§8)
  │           one bad pool → rollback + skip (never kills the whole cycle)
  │
  │ STEP 6   ── single combined FIFO refill (assign_waitlist_to_pools)
  │
  │ STEP 7   ── WINNERS REVEALED unified broadcast (reads today's DrawHistory)
  ▼
  MassDrawResult: pools_drawn, sde_draws, ext_draws, preventive_l3_draws,
                  paused_pools, skipped_pools, refill summary, event_trace
```

═══════════════════════════════════════════════════════════════════════════════
## §8 — SINGLE POOL DRAW MECHANICS (draw.run_dual_draw) — regular/type_a/type_b
═══════════════════════════════════════════════════════════════════════════════

```
run_dual_draw(pool, draw_type)
   │
   ├─ validate: Active, exactly 12 members, not already drawn this week
   │
   ├─ tier-split members by draw_type bounds (§6)
   │
   ├─ ( upper tier empty? "pool not matured" )
   │     YES → EDGE CASE: 2 random distinct winners from LOWER tier
   │             (need ≥2; uses SystemRandom os.urandom)
   │     NO  → NORMAL: winner_1 = secrets.choice(lower), winner_2 = secrets.choice(upper)
   │
   ├─ snapshot winner journey fields (deposit, merges, pauses) BEFORE mutation
   │
   ├─ _process_winner(each):
   │     ★ payout = get_level_payout(level)  (gross, net-after-₹500)
   │     ★ create WIT-XXXXXX Withdraw token (net amount, stamped pool_id)
   │     status → Eliminated_Won, detach from pool
   │     if single draw: pull next paid WL member as replacement at L1
   │                     ★ referral credit if replacement was referred
   │     (mass draw: skip_waitlist_fill=True → combined refill later)
   │
   ├─ SURVIVOR ADVANCEMENT loop (the heart of tenure):
   │     ( survivor PAID? )
   │        YES → new_level = min(level+1, 6)
   │              reaching_L4 → ★ sde_required=True + sde_flagged_week (ATOMIC)
   │                            + pool.contains_flagged_l4 = True
   │        NO  → level unchanged, reaching_L4 forced False
   │     everyone → weekly_payment_status = Unpaid (next cycle dues)
   │
   ├─ draw_completed_this_week = True, pool_draw_type = draw_type
   ├─ sync pool.total_members
   └─ DrawHistory row (winner levels, net payouts, merges/pauses/journey_type, edge flag)
```

═══════════════════════════════════════════════════════════════════════════════
## §9 — SDE SUB-DRAW + SUPPLY CASE LADDER A→E (sde_engine.py — ANTI-MATURITY CORE)
═══════════════════════════════════════════════════════════════════════════════

EN: SDE guarantees every L4 exits with certainty. Upper winner is HARDCODED to L4.
    Lower winner is AI-weighted. Supply for the lower seat escalates A→B→C→D→E.
HI: SDE guarantee deta hai ki har L4 100% exit kare. Upper winner ALWAYS L4 (hardcoded).
    Lower winner AI-weight se. Lower seat ki supply A→B→C→D→E ladder se aati hai.

```
run_sde_meta_pool(week_id):
   1. redistribute_multi_l4_pools()  — pool me 2+ L4? excess L4 ko 0-L4 pools me move
                                        (each sub-draw me sirf 1 L4 allowed)
   2. flag all L4 (sde_required)
   3. compute LPI
   4. cascade_risk = L3 / max(L1+L2, 1)
        allow_l3_supply = cascade_risk > 1.0  OR  LPI > 50
   5. AUTO PRIORITY-L3 STREAK: cascade_risk > 1.5 for 3 consecutive weeks → streak mode
   6. batch loop (≤ 6 sub-draws per session, shared seeds, idempotent checkpoint skip)
   7. Pre-batch Case C sweep
   8. Gate 5 batch-level WL promotion
   9. Case D pairing
  10. Case E defer
```

ONE SDE SUB-DRAW (execute_sde_sub_draw) — upper = L4 fixed. Lower seat resolution:

```
   UPPER WINNER = the flagged L4  (★ net ₹5,500, targeted_early_exit=True)
   LOWER WINNER = ?  ── AI-weighted pick from candidates
        weight = weeks×0.30 + deposit_k×0.25 + pauses×0.20 + organic×0.15 + noise×0.10
        (organic join 1.0 / referred 0.3 ; 5% probability floor for every eligible)
                                │
        ┌───────────────────────┼───────────────────────────────────────────────┐
        ▼ CASE A                 ▼ CASE B              ▼ CASE C
   local L1/L2 present?    local empty →          still none →
   → pick lower winner     WL EMERGENCY           CROSS-POOL DONOR TRANSFER
                           PROMOTION              donor pool needs ≥3 L1/L2,
                           (pull up to 2 WL       donates 1 (keeps 2);
                            members in at L1)     moved member = lower winner
                                                  ★ edge_case_triggered=True
                                                  draw_type = 'sde_case_c'
                                │
                                ▼ CASE D (no donor for a single seat, but two L4 exist)
                          DUAL-L4 CROSS-POOL PAIRING
                          two flagged L4s paired together,
                          ★ BOTH get L4 payout ₹5,500, edge_case_triggered=True
                                │
                                ▼ CASE E (A–D sab exhaust, L4 unpaired bacha)
                          TRUE DEFER → admin alert,
                          user.case_e_deferred_week = week_id
                          (L4 is NOT exited this week — guarantee slips to next cycle)
```

TWO-PHASE COMMIT (idempotent, crash-safe):
```
T-2H staging  (run_sde_meta_pool)  → compute + checkpoint ONLY (no payout yet)
T-0H execute  (execute_staged_sde_draws) → WIT tokens + Eliminated_Won + DrawHistory
crash mid-way → get_resume_sub_draw_number() resumes from last checkpoint
```

═══════════════════════════════════════════════════════════════════════════════
## §10 — CASCADE RISK + PREVENTIVE L3 + AUTO PRIORITY-L3
═══════════════════════════════════════════════════════════════════════════════

```
cascade_risk = L3_count / max(L1+L2_count, 1)
   > 1.0  → "Forming"   → allow_l3_supply ON (L3 can win SDE lower tier)
   > 1.5  → 3-week streak → AUTO PRIORITY-L3 streak mode
   > 2.0  → "Extreme"   → PREVENTIVE L3 DRAW (DB:cascade_prevent_l3_thresh=2.0)
                          both winners from L3, exits 2 L3 BEFORE they reach L4
                          draw_type = 'sde_preventive_l3', runs as pre-pass (§7 step 0.5)
```

EN: Preventive L3 is the upstream relief valve — drain L3 so fewer L4s form next week.
HI: Preventive L3 upstream valve hai — L3 nikaalo taaki agle hafte kam L4 bane.

═══════════════════════════════════════════════════════════════════════════════
## §11 — SDE EXTENSION II / III (L5 / L6 forced exit) + DRAWDOWN PROJECTION
═══════════════════════════════════════════════════════════════════════════════

EN: L5/L6 should NEVER exist in normal operation. If they do, SDE failed somewhere and
    advancement went unchecked. Ext-II/III are the escalation valves.
HI: L5/L6 normal operation me kabhi nahi hone chahiye. Agar hain → SDE kahin fail hua.

```
check_and_run_sde_extensions(week_id):  Ext-III FIRST (L6), THEN Ext-II (L5)
   │
   ├─ Ext-III: any L6 active? → forced exit, upper=L6 (₹8,000), lower=L1–L5
   │           draw_type='sde_ext3'
   │
   └─ Ext-II : any L5 active? → forced exit, upper=L5 (₹6,500), lower=L1–L4
               draw_type='sde_ext2'
               L5 DRAWDOWN PROJECTION (always "eliminate NOW is cheaper"):
                  dual-L5 = ₹13,000  <  L5+L6 = ₹14,500  <  L6+L6 = ₹16,000
   │
   ⚠ BOTH skip any pool with draw_completed_this_week=True
```

⚠ GAP-11 (PROVEN DEFECT): Ext valve pools ko skip karta hai jo already-drawn hain.
Multi-L4 pool sirf 1 L4/week shed karta hai → survivors L4→L5→L6 climb karte hain →
stranded L5/L6 LPI ko high rakhte hain → system SDE me lock → regular L4-L6 rotation
kabhi nahi chalta → **L6 kabhi draw nahi jeet-ta** (40 week-runs me winLvl L6 = 0) →
sirf EXT valve hi L6 drain kar sakta hai, par valve already-drawn pools pe BLOCKED. (§17)

═══════════════════════════════════════════════════════════════════════════════
## §12 — ACCELERATED DISSOLUTION (draw.run_accelerated_dissolution_draw)
═══════════════════════════════════════════════════════════════════════════════

```
TRIGGER: pool ka L4+ ratio ≥ 60%  (DB:accel_diss_trigger_ratio=0.60)
   │
   ▼
BOTH winners from L4+ (AI-weighted: upper=highest weight, lower=next)
   ★ both targeted_early_exit, both pay their level payout
   │
   ├─ create RELIEF POOL from WL simultaneously (fresh L1 supply)
   │
   ▼
( remaining active < 8?  DB-free const ACCEL_DISS_DISSOLVE_BELOW=8 )
   YES → demote remaining → Waitlist, pool → ⚠PoolStatus.Dissolved (ENUM MISSING!),
         Phase-3 condensation redistribute
   NO  → normal refill, pool continues accelerated next week
```

⚠ GAP-12a: `run_accelerated_dissolution_draw` ko **execute_weekly_draw NEVER calls**.
   Sirf admin endpoint (admin.py:757) se manual, per-pool. Autonomous weekly path me
   60%-L4 pool ka koi auto-relief NAHI. → leak ka primary relief valve OFF by default.
⚠ GAP-12b: `PoolStatus.Dissolved` enum me nahi → <8 wala branch chalega to AttributeError.

═══════════════════════════════════════════════════════════════════════════════
## §13 — CONDENSATION / MERGE + USER JOURNEY TRACKING
═══════════════════════════════════════════════════════════════════════════════

EN: When a member is moved by Phase-3 condensation or a pool pauses, their JOURNEY is tracked.
HI: Jab Phase-3 member ko move kare ya pool pause ho, member ki JOURNEY track hoti hai.

```
USER journey fields (user.py):
   dynamic_merges_experienced  += 1  when condensation moves them to another pool
   pauses_experienced          += 1  when their pool is SafeStopped (<12 at draw)
   journey_type   = "merged" if merges>0 else "direct"
   total_deposited_inr               cumulative ₹ paid (feeds AI weight + DrawHistory)
   case_e_deferred_week              set when their SDE L4 exit deferred (§9 Case E)

DrawHistory captures, per winner, a SNAPSHOT of:
   level, net payout, total_deposited, merges_experienced, pauses_experienced, journey_type
   → so every payout is auditable against the member's full journey provenance
```

═══════════════════════════════════════════════════════════════════════════════
## §14 — POST-DRAW CLEANUP (T+5) + DATA INTEGRITY (every 6h)
═══════════════════════════════════════════════════════════════════════════════

```
post_draw_cleanup() [Job4]:
   • draw_completed_this_week → False, pool_draw_type → None (non-dissolved pools)
   • contains_flagged_l4 → False on pools with no remaining sde_required members
   • orphan sde_required → False on Eliminated/Eliminated_Won members
   • release draw_engine lock

job_data_integrity_check() [Job5, 6-hourly, idempotent]:
   1. pool.total_members = real active COUNT (sync drift)
   2. clear sde_required on non-Active users
   3. close expired grace (grace_expires_at past, unpaid) → elimination_risk=True
   4. contains_flagged_l4 consistency vs actual sde_required members
```

═══════════════════════════════════════════════════════════════════════════════
## §15 — ADMIN OVERRIDE (SDE supply shortage)
═══════════════════════════════════════════════════════════════════════════════

```
T-2H: SDE overflow > 0 (L4 count > clearable) → admin_override_required=True
        deadline = now + 2h (DB:ADMIN_OVERRIDE_TIMEOUT_HOURS)
   │
   ├─ admin chooses option before deadline → applied
   └─ deadline passes silent → job_override_watchdog (5-min) OR draw-time belt-and-
      suspenders → auto_select_on_timeout() picks the cheaper option automatically
```

═══════════════════════════════════════════════════════════════════════════════
## §16 — ECONOMICS / SOLVENCY (the money invariants)
═══════════════════════════════════════════════════════════════════════════════

```
Per pool per cycle: 12 × ₹1,000 = ₹12,000 IN
Two winners OUT (net): solvency invariant → two net payouts ≤ ₹12,000
   Normal cap: L4 upper ₹5,500 + L2 lower ₹3,000 = ₹8,500  (safe)
   ⚠ Edge stacks that BREAK invariant if they ever co-occur:
       L6+L6 = ₹16,000  (Ext-III dual)   ← > ₹12,000 pool intake
       L5+L6 = ₹14,500  (drawdown)        ← > ₹12,000
       L5+L5 = ₹13,000  (Ext-II dual)     ← > ₹12,000
   → These are exactly the states §11/§17 say should never persist but DO (L6 never wins).

★ Fee revenue: ₹500/payout fee (admin) − ₹250 referral (if referred) = ₹250 net/referred winner
★ Late fee + grace fee COLLECTED = pure admin revenue
★ Elimination FORFEIT (deposit + fees) = admin profit (member's loss, not our cost)
```

═══════════════════════════════════════════════════════════════════════════════
## §17 — THE GAP : DESIGN vs CODE (jahan code aapki strategy se diverge karta hai)
═══════════════════════════════════════════════════════════════════════════════

EN: This is the section you asked for — every place where (b) the code and (c) your
    designed strategy do NOT line up, made explicit. NOTHING is being fixed here — only mapped.
HI: Yeh wahi section hai jo aapne maanga — har jagah jahan (b) code aur (c) aapki strategy
    match NAHI karte. Yahan kuch FIX nahi kar raha — sirf expose kar raha hoon.

```
GAP-A  LEAK (multi-L4 shed rate):
   Design intent → har L4 guaranteed exit, pool 6 hafte me clear.
   Code reality  → ek pool ek cycle me sirf 1 L4 shed karta hai (1 SDE sub-draw/pool).
                   Agar pool me 2+ survivors L4 ban gaye, baaki L4→L5→L6 climb karte hain.
   redistribute_multi_l4_pools isse spread karta hai PAR agar receiver pools na ho → stuck.

GAP-B  LPI SELF-LOCK:
   Stranded L5/L6 LPI numerator me रहते hain → LPI high → system permanently SDE mode me →
   regular L4-L6 rotation (jo V1.0 ka base tha) kabhi nahi chalta.
   Measured: 75–78% draws SDE, winLvl L6 = 0 across all 40 week-runs.

GAP-C  EXT VALVE BLOCKED:
   Ext-II/III is the ONLY path that drains L5/L6, but it SKIPS draw_completed_this_week pools.
   SDE pre-pass already pool ko draw_completed mark kar deta hai → us hafte us pool ka
   L5/L6 drain nahi hota. Valve aur leak ek doosre ko reinforce karte hain.

GAP-D  ACCELERATED DISSOLUTION DEAD-WIRED:
   60%-L4 relief valve execute_weekly_draw se kabhi auto-trigger NAHI hota (sirf admin manual).
   → leak ka biggest structural relief autonomous mode me OFF.

GAP-E  PoolStatus.Dissolved ENUM MISSING:
   draw.py:1408 → AttributeError jaise hi koi accelerated pool <8 pe dissolve hoga.
   (Abhi tak fire nahi hua kyunki GAP-D ke kaaran path hi reachable nahi.)

GAP-F  SCHEDULER OFF BY DEFAULT:
   SCHEDULER_ENABLED=false default → bina manual enable ke koi weekly automation nahi.

GAP-G  SOLVENCY EDGE STACKS (§16):
   L5+L5 / L5+L6 / L6+L6 dual payouts > ₹12,000 pool intake. Inhe kabhi co-occur nahi
   hona chahiye — par GAP-B ke kaaran L5/L6 persist karte hain, to risk theoretical nahi.

GAP-H  REFERRAL vs ELIMINATION FORFEIT timing — design clarity:
   Referral ₹250 pool-entry pe credit hota hai (registration pe nahi). Confirm karein
   ki yeh aapki strategy se match karta hai (kuch designs registration-time maante hain).
```

### Konsi cheezein code me hain jo shayad aapki original strategy me NAHI thi
(ya jinpe aapko decide karna hai — "uske baad hum sochenge"):

```
1. AI-weighted lower-tier selection (time/deposit/pause/organic/noise) — kya yeh aapne
   design kiya tha ya yeh meri addition thi?
2. Cascade Risk + Preventive L3 + Auto Priority-L3 streak — purely engine-side construct.
3. Two-phase T-2H/T-0H SDE commit — operational safety, strategy nahi.
4. Case C / Case D / Case E supply ladder — kya itni deep escalation aapki design thi?
5. Adaptive pool-creation threshold + AI Quant reserve multiplier (Phase 2 gates).
6. SafeStop (Paused_Awaiting_Members) + dynamic_merges journey tracking.
7. Ext-II/III L5/L6 escalation — aapne L5/L6 ko "edge-case only" kaha tha; code unhe
   first-class draw types bana deta hai.
```

═══════════════════════════════════════════════════════════════════════════════
## DECISION POINT / AGLA KADAM
═══════════════════════════════════════════════════════════════════════════════

EN: Per your instruction, I have ONLY mapped every situation — no engine code changed.
    Tell me which of these are faithful to your design and which are my drift, and we
    decide together what to actually fix.
HI: Aapke kehne ke mutabik maine SIRF har situation map ki hai — engine ka koi code
    change NAHI kiya. Ab aap bataiye in §17 gaps me se konse aapki strategy se sahi hain
    aur konse meri galti/drift hai — phir hum saath me decide karenge kya actually fix karna hai.
```
```
