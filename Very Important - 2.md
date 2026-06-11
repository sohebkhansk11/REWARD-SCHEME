## COMPLETE UPDATED SYSTEM WIRE DIAGRAM
### Plain Language — Input to Output

---

## THE SYSTEM IN ONE SENTENCE

> A member pays ₹1,000 to join a queue → gets placed in a 12-person pool → pays ₹1,000 every week → gets drawn as a winner within weeks → receives ₹2,000–₹5,500 → exits. The system guarantees profit on every single draw by mathematically preventing expensive payouts before they occur.

---

## PART 1 — HOW A MEMBER ENTERS

```
STEP 1: REGISTRATION
  Person visits the platform and registers an account.
  They pay ₹1,000 upfront (this is their entry deposit).
  A DEP token is created and immediately burned (recorded as paid).
  Status: WAITLIST
  
STEP 2: THE WAITING ROOM
  They join the Master Waitlist.
  Position in queue = their exact date and time of joining.
  First in, first out. No jumping the queue. No exceptions.
  
STEP 3: REFERRAL (Optional)
  If they joined through someone's referral link:
  → Their referrer is noted in the system.
  → When THIS member formally enters a pool (not just waitlist):
    the referrer receives ₹250 bonus credited to their account.
  → Referral bonus is NOT paid at registration — only at pool entry.
  → ⚠️ BUG FOUND: If a member temporarily serves as an SDE
    "shared seed" before formal pool assignment, the referral
    bonus must NOT trigger at that point. Only on permanent
    pool assignment. (Needs explicit check in the code.)
```

---

## PART 2 — THE THREE-LAYER RESERVE SYSTEM

```
Think of this as a water tank system with three chambers:

┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — ACTIVE POOLS (The Engine Room)                       │
│                                                                 │
│  12 members per pool. Draws happen here every week.            │
│  2 members exit each week (winners). 2 new members fill in.    │
│  Multiple pools run simultaneously.                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ needs refill from below
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2 — DYNAMIC RESERVE (The Safety Buffer)                  │
│                                                                 │
│  This is NOT a separate room — it's a PORTION of the waitlist  │
│  mentally reserved to keep existing pools alive.               │
│                                                                 │
│  Size = (All Active + Paused Pools) × 12 × AI Multiplier       │
│  AI Multiplier changes based on Brain 2+3 signals (0.5 to 2.0) │
│  Nobody can be spawned into new pools until buffer is satisfied │
└───────────────────────────┬─────────────────────────────────────┘
                            │ draws from below
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3 — MASTER WAITLIST (The Overflow Tank)                  │
│                                                                 │
│  Everyone lands here first. Strict FIFO order.                  │
│  New members enter here. System pulls from here.               │
└─────────────────────────────────────────────────────────────────┘
```

---

## PART 3 — HOW POOLS ARE CREATED

```
Every time someone joins OR every week after a draw:
the system runs a 3-phase assignment engine.

PHASE 1 — FILL EXISTING VACANCIES (Highest Priority)
  After each draw: 2 winners left their pool.
  2 empty seats need filling.
  System takes the 2 oldest waitlisted members → puts them in the pool.
  This is ALWAYS done first, before anything else.

PHASE 2 — SPAWN NEW POOLS (If Buffer Allows)
  Brain 2 (velocity) + Brain 3 (RDR) calculate the AI multiplier.
  Reserve needed = Operational Pools × 12 × Multiplier.
  Available = Waitlist count − Reserve needed.
  If Available ≥ Admin Threshold (default 24 people):
    → Open (Available ÷ 12) new pools simultaneously.
    → Oldest waitlisted members fill these new pools (FIFO).
  If Available < 24: do nothing. Wait for more people.

PHASE 3 — CONDENSATION (Last Resort, Only When Waitlist = 0)
  If waitlist is completely empty AND pools have empty seats:
  → Take the NEWEST pool's 12 members.
  → Dissolve that pool (mark it closed).
  → Redistribute those 12 members into the oldest pools with vacancies.
  → Members keep their levels. Each gets +1 on their "merges" counter.
  
  ⚠️ CONDENSATION TIMING BUG FOUND:
  Current architecture says "block condensation on draw day (Saturday-Sunday)."
  But "draw day" is ambiguous — does it mean the full 48 hours?
  If condensation runs at Saturday 9:50 PM (10 min before Brain 5 T-2H snapshot),
  it changes pool compositions RIGHT BEFORE Brain 5 locks the state.
  Fix: Condensation must be blocked from T-2H start until T+0H:10 post-draw.
  Specific window, not "all day." Condensation runs normally Monday–Friday.
```

---

## PART 4 — HOW POOLS ARE MANAGED WEEK TO WEEK

```
Each pool runs on a weekly rhythm:

MONDAY:   Week begins. All members are "UNPAID" for this week.
TUESDAY–SATURDAY: Members pay their ₹1,000 weekly installment.
  Paid on time → status "PAID" ✓
  Not paid by deadline → status "LATE" → ₹50 penalty added
  Still not paid → risk of elimination (admin-triggered)

SATURDAY 10:00 PM (T-2H): 
  Brain 5 locks the system. Draw preparation begins.
  (Covered in detail in Part 6)

SUNDAY MIDNIGHT (T-0H):
  Draw executes. Winners selected.
  
SUNDAY 12:01 AM (T+1min):
  All results revealed simultaneously to all members.
  Winners notified. Withdraw tokens generated.
  
SUNDAY 12:05 AM (T+5min):
  10 survivors in each pool advance ONE level (L1→L2, L2→L3, etc.)
  L4 members: IMMEDIATELY FLAGGED for SDE (next week's guaranteed exit)
  Empty seats created. Waitlist assignment triggered (Phase 1).
  
SUNDAY–MONDAY: 
  Vacancies filled from waitlist.
  New pools spawned if buffer allows.
  Week resets. Everyone back to "UNPAID."
```

---

## PART 5 — THE 5-BRAIN AI DECISION ENGINE

```
The system has 5 separate "brains" that work together:

BRAIN 1 — HYDRAULIC RESERVE ENGINE
  Question it answers: "How big should the safety buffer be?"
  Calculates: Reserve = Operational Pools × 12 × (multiplier from Brain 2/3)
  Output: The minimum waitlist size before new pools can open.

BRAIN 2 — TRI-VELOCITY MOMENTUM TRACKER (Updated)
  Question: "Is the system growing or shrinking?"
  Three signals combined:
    Signal A (14-day average): What was the typical weekly join rate recently?
    Signal B (48-hour snapshot): What's the join rate right NOW?
    Signal C (Brain 5 forward): How many L2 members will become L3 soon?
    Blended = (A × 50%) + (B × 30%) + (C × 20%)
  NEW: Cliff Detection — if today's joins are less than half of 3 days ago:
    → "VELOCITY_CLIFF" warning → prevents aggressive spawning during sudden drops
  Output: Weekly join velocity + momentum direction + cliff warning if triggered

BRAIN 3 — RDR QUALITY RADAR
  Question: "Are new members organic (sustainable) or referral-driven (fragile)?"
  Measures: What % of recent joiners came through a referral link?
  Below 30% = organic growth (durable, trust)
  Above 70% = referral hype (could collapse overnight)
  Output: RDR percentage → influences AI scenario selection

BRAIN 2+3 COMBINED → 5 SCENARIOS:
  SUSTAINABLE_WAVE   : Growing fast + organic       → Multiplier 0.50 (spawn aggressively)
  BOOM_GOLDEN_CROSS  : Growing fast + mixed         → Multiplier 0.75
  FLASH_FLOOD        : Growing fast + all referrals → Multiplier 1.50 (cautious)
  REFERRAL_LIFELINE  : Slowing + referral-only      → Multiplier 2.00 (protect)
  DRY_PHASE          : Shrinking                   → Multiplier 2.00 (halt spawning)

BRAIN 4 — CONDENSATION ENGINE
  Question: "Do we need to merge pools to survive a dry spell?"
  Trigger: Waitlist = 0 AND pool vacancies exist AND NOT in draw window
  Action: Dissolve newest pool → redistribute to oldest pools
  Blocked: During T-2H to T+0H:10 draw window (condensation lock)

BRAIN 5 — LEVEL DISTRIBUTION MONITOR (Master Override)
  Question: "Are expensive members accumulating in the system?"
  Calculates: LPI = (L3 + L4 + L5 + L6 members) ÷ Total Active Members × 100
  
  LPI Thresholds:
    LPI < 15%  → Everything fine. Regular pool mode.
    LPI 15-25% → L3 building up. Activate Type A execution pools.
    LPI > 25%  → Urgent. Activate SDE for any L4 members.
    LPI > 50%  → Emergency. Stop all new spawning. Clear-only mode.
    Any L4 exists → HARD OVERRIDE: SDE activates regardless of LPI number.
  
  Also manages:
    → SDE session planning and sub-draw sequencing
    → Admin override dashboard when SDE capacity is insufficient
    → Float projection for upcoming draw payouts
    → Next week's SDE demand forecasting
```

---

## PART 6 — THE WEEKLY DRAW CYCLE (T-2H to T+5min)

```
SATURDAY 10:00 PM — T MINUS 2 HOURS

STEP 1: SNAPSHOT LOCK
  Brain 5 takes a photograph of the entire system state.
  All member levels are frozen. Nobody advances, nobody changes pool.
  This snapshot is what the entire draw will be based on.

STEP 2: LPI CALCULATION
  Brain 5 counts all members at each level (L1 through L4+).
  Calculates LPI. Runs L4 hard check.

STEP 3: POOL TYPE DECISION (Priority 1 → 4)
  Priority 1 — SDE: Any L4 members found? → SDE planned.
  Priority 2 — Type A: LPI 15-25%? L3 present? → Type A planned.
  Priority 3 — Regular: LPI < 15%? → Regular draws planned.
  Priority 4 — Type B: L1/L2 completely exhausted? → Type B fallback.

STEP 4: RESOURCE ALLOCATION
  Brain 5 distributes available L1/L2 members in order:
  First: Reserve for regular pool vacancy refills (most important)
  Then:  Reserve for SDE lower tier needs (L4_count × 2 minimum)
  Then:  Reserve for Type A lower tier pools
  Last:  Remainder for new pool spawning

STEP 5: SDE BACKEND PROCESSING (If L4 exists)
  All SDE sub-draws run silently in backend.
  Results held. Not revealed yet.
  (Detailed in Part 7)

STEP 6: FLOAT CHECK
  Brain 5 calculates total payout this week across all pool types.
  If float < projected payout: Admin alerted before draw runs.
  Admin can defer regular pool draws if float is tight.
  SDE draws cannot be deferred (L4 members must be processed).

STEP 7: PREPARATION CONFIRMED
  All of the above committed as ONE atomic transaction to DB.
  Either everything saves OR everything rolls back (no partial states).

STEP 8: COUNTDOWN TIMER ACTIVATED
  Only NOW does the countdown appear on user screens and admin panel.
  "Draw in 2:00:00 ⏱"
  If preparation failed: no countdown shows. "Draw being prepared."

─────────────────────────────────────────────────────────
SATURDAY 11:30 PM — T MINUS 30 MINUTES

  Final verification run:
  → Check all pools still have 12 members
  → Any pool dropped below 12? → SafeStop applied, pool paused this week
  → Confirm all installment payments recorded
  → Admin notified of any paused pools
─────────────────────────────────────────────────────────

SUNDAY MIDNIGHT — T ZERO

  All draws execute simultaneously:
  → SDE pools: results already computed, now officially confirmed
  → Type A pools: random draw runs now
  → Regular pools: random draw runs now
  → Type B pools (if active): random draw runs now
  
  ALL results held until T+1 minute.
─────────────────────────────────────────────────────────

SUNDAY 12:01 AM — RESULTS REVEALED

  Every winner sees their notification simultaneously.
  Admin panel shows full breakdown.
  Winner tokens (WIT) generated for all winners.
  [TARGETED EARLY EXIT] badge applied for SDE winners (admin view only).
─────────────────────────────────────────────────────────

SUNDAY 12:05 AM — POST-DRAW CLEANUP

  Level advancements applied to all survivors.
  L4 flags set immediately for newly-advanced L4 members.
  Pool vacancies opened.
  Waitlist assignment runs (Phase 1 FIFO).
  LPI recalculated from new state.
  Brain 5 plans next week's SDE requirements.
```

---

## PART 7 — THE 4 POOL DRAW TYPES IN DETAIL

```
┌──────────────────────────────────────────────────────────────────────┐
│  TYPE 1: REGULAR POOL (Priority 3 — Best Profit)                     │
│                                                                      │
│  When: LPI < 15%, no L3/L4 in the system                           │
│  Who: All 12 members are L1 or L2                                   │
│                                                                      │
│  Draw: Smart pairing                                                 │
│    Both winners come from L1/L2 (no upper tier exists)             │
│    Random selection, no manipulation                                 │
│                                                                      │
│  Winners: 2 L1/L2 members exit                                      │
│  Max payout: L2+L2 = ₹3,000+₹3,000 = ₹6,000                      │
│  Collection: ₹12,000                                                │
│  Profit: ₹6,000–₹8,000 per draw ← Maximum profit mode             │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  TYPE 2: EXECUTION POOL TYPE A (Priority 2)                         │
│                                                                      │
│  When: LPI 15-25%, L3 members present, L4 count = 0                │
│  Structure: 6 L1/L2 in lower tier + 6 L3/L4 in upper tier          │
│                                                                      │
│  Draw:                                                               │
│    Lower winner: AI-weighted random from 6 L1/L2                   │
│    Upper winner: random from 6 L3/L4                               │
│    Both pools draw simultaneously sharing the same 6 L1/L2 seeds   │
│                                                                      │
│  AI WEIGHTING for lower tier selection:                             │
│    Favours members who: waited longest, paid most, had more pauses  │
│    Still random — not 100% certain — but fairer than pure random   │
│                                                                      │
│  Winners: 1 L1/L2 exits + 1 L3/L4 exits                           │
│  Max payout: L2+L4 = ₹3,000+₹5,500 = ₹8,500                      │
│  Profit: ₹4,500–₹7,000 per draw                                    │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  TYPE 3: SDE — SEQUENTIAL DYNAMIC EVICTION (Priority 1 — Master)   │
│                                                                      │
│  When: ANY L4 member detected (HARD OVERRIDE — ignores LPI)        │
│  OR:   LPI > 25% proactively                                        │
│                                                                      │
│  WHAT IT DOES:                                                       │
│  The system engineers the draw results for existing pools that      │
│  contain L4 members. L4 members are GUARANTEED to win their pool's  │
│  upper tier. This prevents them from advancing to L5.               │
│                                                                      │
│  STRUCTURE (per affected pool):                                     │
│    → The pool is the SAME original pool (not a new pool)           │
│    → Upper tier slot: HARDCODED to the L4 member. They MUST win.   │
│    → Lower tier slot: AI-weighted selection from pool's L1/L2       │
│    → Remaining 10 members: survive normally, advance levels         │
│    → Max 2 winners per pool: always maintained ✅                   │
│                                                                      │
│  BACKEND PROCESS (invisible to members):                           │
│    Pool A has L4_member_X: Sub-draw 1 processes Pool A.            │
│    X wins upper. 1 L1/L2 wins lower. 10 survive.                   │
│    Pool B has L4_member_Y: Sub-draw 2 processes Pool B.            │
│    Y wins upper. 1 L1/L2 wins lower. 10 survive.                   │
│    ... continues for all pools with L4 members ...                  │
│    ALL results held. Revealed simultaneously with all other draws.  │
│                                                                      │
│  SESSIONS:                                                           │
│    Max 6 L4 pools per session (6 shared seeds for lower tier).     │
│    If L4 > 6: session 1 clears 6, recalculate, session 2 clears 6, │
│    session 3... continues until ALL L4 cleared.                     │
│    All sessions complete before results are revealed.               │
│                                                                      │
│  WHAT MEMBER SEES:                                                   │
│    "Your pool drew 2 winners this week." Completely normal.         │
│    No indication that this was an engineered SDE result.            │
│    [TARGETED EARLY EXIT] badge: admin panel ONLY.                  │
│                                                                      │
│  MAX PAYOUT: L4+L2 = ₹5,500+₹3,000 = ₹8,500                      │
│  PROFIT: ₹4,500–₹6,000 per draw, always positive ✅               │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  TYPE 4: TYPE B FALLBACK (Priority 4 — Last Resort)                 │
│                                                                      │
│  When: All of P1, P2, P3 are ineligible (no L1/L2 available)       │
│  Structure: 6 L3 in lower tier + 6 L4 in upper tier                │
│  No L1/L2 needed. Runs entirely from L3/L4 members.                │
│                                                                      │
│  Winners: 1 L3 exits (₹4,000) + 1 L4 exits (₹5,500)              │
│  Profit: ₹3,500 per draw (minimum guaranteed)                      │
│                                                                      │
│  ⚠️ WARNING: Type B survivors become L4 (L3 survivors) and L5      │
│  (L4 survivors). Next week's SDE emergency must catch them.        │
│  Type B should never run for consecutive weeks without admin alert. │
└──────────────────────────────────────────────────────────────────────┘
```

---

## PART 8 — THE ANTI-MATURITY PROTOCOL (Why L5/L6 Cannot Happen)

```
THE CORE PROBLEM IT SOLVES:
  Without this protocol, members can survive for many weeks and reach L5/L6.
  L5/L6 payouts (₹6,500–₹8,000) can exceed weekly collection (₹12,000 − ₹8,500 = ₹3,500 profit only).
  Many mature pools = system slowly loses profit margin.
  At worst: L6+L6 = ₹17,000 payout vs ₹12,000 collected = ₹5,000 LOSS per pool.

THE PROOF THAT L5 CANNOT HAPPEN (Normal Operation):

  Member journey:
  Joins → L1 (Regular pool)
  Survives → L2 (Regular pool, still cheap)
  Survives → L3 (LPI rises → Type A pool activated)
                 Type A: L3 competes in upper tier of execution pool
                 Either WINS at L3 (exits at ₹4,000) ✅
                 Or SURVIVES → advances to L4

  Becomes L4 → IMMEDIATELY FLAGGED (real-time, same transaction as level advance)
               L4 cannot participate in ANY regular draw
               Next week: SDE session guaranteed
               SDE: L4 is SOLE upper tier candidate in their pool
               L4 MUST WIN (mathematical certainty)
               L4 exits at ₹5,500 ✅

  For L4 to reach L5: L4 would need to SURVIVE the SDE draw.
  But L4 is the only upper tier candidate → wins 100% → exits.
  SURVIVAL IS IMPOSSIBLE. L5 CANNOT EXIST. ✅

WHEN L5 CAN APPEAR (Edge Cases Only):
  1. Admin Override Option A: L4 draws normally (admin explicitly accepts risk)
  2. Type B Fallback consecutive weeks: L4 survivors → L5
  3. If SDE sub-draw system fails silently (infrastructure failure)

  In all cases: L5 emergency SDE activates. Same mechanism as L4 SDE.
  L5 wins guaranteed. Exits at ₹6,500 (still profitable: ₹3,000 profit per pool).
```

---

## PART 9 — THE ADMIN OVERRIDE SYSTEM

```
WHEN IT TRIGGERS:
  SDE sessions exhausted but some L4 still remain.
  Not enough L1/L2 supply to run more sessions this week.

WHAT ADMIN SEES:
  ┌──────────────────────────────────────────────────────┐
  │  5 L4 members cannot be cleared via SDE this week.  │
  │                                                      │
  │  OPTION A — Let them draw normally this week        │
  │  Expected L5 from this: ~4 members (83% survive)   │
  │  Expected extra cost next week: ~₹4,000             │
  │  (Probabilistic — might be less if some win)        │
  │                                                      │
  │  OPTION B — Promote all 5 to L5 now                │
  │  Certain extra cost this week: ₹5,000              │
  │  (Certain — but cleared in one shot)                │
  │                                                      │
  │  RECOMMENDATION: Option A (lower expected cost)     │
  │  TIME TO DECIDE: 01:47:32                          │
  │  [OPTION A]           [OPTION B]                   │
  └──────────────────────────────────────────────────────┘

IF ADMIN DOESN'T DECIDE WITHIN 2 HOURS:
  System auto-selects the option with lower expected financial impact.
  This prevents draw delays due to admin unavailability.

⚠️ BUG FOUND: No time limit currently specified for admin decision.
  If admin is unreachable: draw waits indefinitely.
  Fix: 2-hour auto-selection fallback must be built.
```

---

## PART 10 — THE LEVEL SYSTEM AND PAYOUTS

```
LEVEL PROGRESSION:
  Members advance 1 level every time they survive a draw.
  Maximum in normal operation: L4 (SDE prevents L5+).
  Maximum in edge cases: L5 (admin override) or L6 (cascading failure).

PAYOUT TABLE:
  L1 winner: ₹2,500 gross → ₹2,000 net (₹500 platform fee)
  L2 winner: ₹3,500 gross → ₹3,000 net (₹500 platform fee)
  L3 winner: ₹4,500 gross → ₹4,000 net (₹500 platform fee)
  L4 winner: ₹6,000 gross → ₹5,500 net (₹500 platform fee)
  L5 winner: ₹7,000 gross → ₹6,500 net (₹500 fee) [edge case]
  L6 winner: ₹8,500 gross → ₹8,000 net (₹500 fee) [extreme edge case]

FINANCIAL PROFITABILITY PER DRAW:
  Weekly collection per pool: 12 × ₹1,000 = ₹12,000
  
  Regular pool (L1+L1): ₹4,000 paid → ₹8,000 profit + ₹1,000 fees = ₹9,000 ✅
  Regular pool (L2+L2): ₹6,000 paid → ₹6,000 profit + ₹1,000 fees = ₹7,000 ✅
  Type A (L1+L4):       ₹7,500 paid → ₹4,500 profit + ₹1,000 fees = ₹5,500 ✅
  SDE (L2+L4):          ₹8,500 paid → ₹3,500 profit + ₹1,000 fees = ₹4,500 ✅
  Type B (L3+L4):       ₹9,500 paid → ₹2,500 profit + ₹1,000 fees = ₹3,500 ✅
  
  ABSOLUTE MINIMUM PROFIT: ₹3,500 per draw, every pool, every week.
  SYSTEM CANNOT LOSE MONEY PER DRAW under normal operation.

⚠️ BUG FOUND: Regular pool tier definition ambiguity.
  The new tier definition (L1-L2 lower, L3-L4 upper) applies to Type A and SDE.
  But if LPI = 12% and some pools still have a few L3 members from natural advancement,
  those L3 members in regular pools draw under the OLD smart pairing rule
  (L1-L3 lower, L4-L6 upper). Under old rule, L3 is in the lower tier and competes
  with L1/L2 for a cheap lower-tier win slot.
  
  But if the NEW rule is applied to regular pools: L3 becomes upper tier.
  If L3 is the ONLY upper tier member in a regular pool (no L4): L3 wins at ₹4,000.
  This is MORE expensive than the regular pool was supposed to be.
  
  Fix needed: Regular pool draws use OLD tier rule (L1-L3 lower, L4-L6 upper).
  Type A and SDE use NEW tier rule (L1-L2 lower, L3-L4 upper).
  The tier rules must be explicitly pool-type-specific, not universal.
```

---

## PART 11 — COMPLETE FINANCIAL FLOW

```
MONEY IN:
  ₹1,000 per new member joining (DEP token burned) → INTO system
  ₹1,000 per active member per week (installment) → INTO system
  ₹50 per late payment (penalty fee) → INTO system

MONEY OUT:
  Winner payouts (L1=₹2,000 to L4=₹5,500 net) → OUT of system
  Referral bonuses (₹250 per referred member on pool entry) → OUT of system

PLATFORM KEEPS:
  ₹500 per winner per draw (maintenance fee, both winners)
  = ₹1,000 per pool per draw GUARANTEED
  ₹50 late fees
  Float interest (money sitting between collection and payout)

PLATFORM'S NET CALCULATION:
  Net Profit = All DEP tokens collected
             + All weekly installments collected
             + All late fees
             − All winner payouts
             − All referral bonuses paid
             = The float (projected ultimate liability)

PROJECTED ULTIMATE LIABILITY (shown in admin dashboard):
  If every active member wins at their current level tomorrow:
  Total payout = Sum of (each member's current level payout)
  This is the maximum possible outflow. Shown in RED as a warning.
  
  With Anti-Maturity Protocol: max level = L4.
  Worst case liability = Active members × ₹5,500.
  This is MUCH lower than old worst case (× ₹8,000 at L6).
```

---

## PART 12 — COMPLETE MEMBER JOURNEY (One Person, Start to Finish)

```
DAY 1 — JOINING
  Priya registers. Pays ₹1,000. Status: WAITLIST.
  Position: #47 in queue (47 people joined before her).
  Referred by Ravi → Ravi's ₹250 bonus will trigger when Priya enters a pool.

DAYS 1–14 — WAITING
  System checks after each draw whether buffer allows new pool spawning.
  Brain 2: velocity is healthy. LPI is clean.
  New pool opens with 12 members. Priya (#47) is included.
  Priya's status: ACTIVE. Level: L1.
  Ravi receives ₹250 referral bonus NOW (Priya formally entered a pool).

WEEK 1 IN POOL
  Priya pays ₹1,000 installment. Status: PAID.
  Sunday: Draw runs. Pool has all L1 members.
  LPI = 0% → Regular pool draw.
  2 random L1 members win (₹2,000 each). Priya doesn't win.
  Priya survives → advances to L2.

WEEK 2 IN POOL
  Priya pays ₹1,000 installment. Level: L2.
  LPI still clean → Regular pool draw.
  2 members win (some L1, some L2). Priya doesn't win.
  Priya survives → advances to L3.
  Total paid by Priya so far: ₹3,000 (initial + 2 installments).

WEEK 3 IN POOL
  Priya is now L3. LPI rises (more members reaching L3 across all pools).
  LPI = 18% → Type A pool activated for this draw.
  T-2H: Brain 5 includes Priya's pool in Type A.
  Pool composition: 6 L1/L2 lower tier + 6 L3/L4 upper tier.
  Priya is in the upper tier (L3). Competing with 5 other L3/L4 members.
  
  Draw: 1 of 6 upper tier wins. Priya has 1/6 = 16.7% chance.
  Say Priya doesn't win. Priya survives → advances to L4.
  Total paid: ₹4,000. Still hasn't won.

  ⚡ AT T+0H:05: Level advancement sets Priya to L4.
  IMMEDIATELY: sde_required flag = TRUE on Priya's account.
  Priya is LOCKED OUT of all regular and Type A draws.

WEEK 4 — PRIYA'S GUARANTEED EXIT
  T-2H: Brain 5 sees Priya flagged L4.
  SDE session planned for Priya's pool.
  Brain 5 selects Priya as the hardcoded upper-tier winner.
  AI-weighted selection picks 1 L1/L2 member as lower-tier winner.
  
  Sunday: SDE sub-draw runs for Priya's pool.
  Priya wins upper tier. 100% guaranteed.
  She receives: ₹5,500 net payout.
  Withdraw token created.
  
  Priya's net profit:
    Total deposited: ₹5,000 (₹1,000 + 4 installments)
    Total received:  ₹5,500
    NET PROFIT:      +₹500 ✅
  
  Status: ELIMINATED (WON).
  Pool history records: "Won at L4 via draw. Payout ₹5,500."
  Admin view shows: [TARGETED EARLY EXIT] badge.
  Priya's view shows: "Congratulations! You won ₹5,500."
  
  Admin processes the withdrawal. Cash paid.
  WIT token burned (settled).
  Priya's journey complete.
```

---

## PART 13 — SYSTEM PAUSE CONDITIONS

```
THE SYSTEM PAUSES A POOL WHEN:
  A pool drops below 12 members (SafeStop).
  Waitlist can't provide a replacement.
  → Pool pauses. Draw skipped. Members get +1 on "pauses counter."
  → Resumes automatically when 12 members confirmed.

THE SYSTEM PAUSES ALL DRAWS WHEN:
  New member registrations (paid, confirmed) < 2 per week.
  → This is the ONLY reason for a full system pause.
  → Countdown timer shows: "Draw paused — awaiting new members."
  → Resumes automatically when weekly inflow ≥ 2.

THE SYSTEM DOES NOT PAUSE FOR:
  L4 backlog (admin override handles this instead).
  High LPI (system switches pool types, doesn't pause).
  Low waitlist (condensation handles this, or admin is alerted).
  Float concerns (admin alerted, can defer regular pools, never SDE).
```

---

## PART 14 — COMPLETE WEEK TIMELINE (Visual)

```
MON     TUE     WED     THU     FRI     SAT              SUN
────────────────────────────────────────────────────────────────
Members pay weekly ₹1,000 installments throughout week

                                        Brain 2+3 run
                                        velocity/RDR calcs
                                        continuously

                                        10:00 PM:
                                        ┌────────────────┐
                                        │ T-2H START     │
                                        │ Brain 5 locks  │
                                        │ snapshot       │
                                        │ LPI calculated │
                                        │ Pool types set │
                                        │ SDE runs in    │
                                        │ backend        │
                                        │ Timer set      │
                                        │ Countdown live │
                                        └────────┬───────┘
                                                 │
                                        11:30 PM:│
                                        Final    │
                                        verify   │
                                                 │       12:00 AM
                                                 │       ┌──────────┐
                                                 │       │ DRAW!    │
                                                 │       │ All types│
                                                 │       │ execute  │
                                                 └──────►│ Results  │
                                                         │ revealed │
                                                         └────┬─────┘
                                                              │12:05 AM
                                                              │Levels advance
                                                              │L4 flags set
                                                              │Vacancies open
                                                              │Waitlist fills
                                                              │LPI recalculated
                                                         Next week begins ▶
```

---

## PART 15 — BUGS FOUND IN ARCHITECTURE REVIEW

```
🔴 BUG 1 — TIER RULE NOT POOL-TYPE SPECIFIC
  Problem: New tier (L1-L2 lower, L3-L4 upper) is intended for Type A and SDE.
           Regular pools should use old tier (L1-L3 lower, L4-L6 upper).
           This is not explicitly defined anywhere in the architecture.
           If new tier accidentally applied to regular pools: L3 members
           end up in upper tier and can win expensive payouts in "regular" draws.
  Fix: Each pool type must store its own tier definition.
       Regular pool → old tier. Type A/SDE → new tier.
       Not a global setting.

🔴 BUG 2 — MULTIPLE L4 IN SAME POOL
  Problem: Pool A has 2 L4 members. SDE plans 2 sub-draws for Pool A.
           Max 2 winners per pool. Both L4 cannot win in same draw.
           Architecture doesn't specify what happens.
  Fix: Brain 5 redistribution logic: if same pool_id appears in >1
       SDE sub-draw, move the second L4 to a different pool (temporarily).
       They win in that pool instead. Max 2 per pool always maintained.

🔴 BUG 3 — SDE SEED AND TYPE A POOL OVERLAP
  Problem: Brain 5 selects L1a as a shared seed for SDE.
           Brain 5 ALSO selects L1a as part of a Type A pool's lower tier.
           L1a is in two draws simultaneously.
  Fix: Seeds must be locked BEFORE Type A pool formation begins.
       Order: (1) SDE seed selection + lock, (2) Type A pool formation
       (excluding locked seeds). Brain 5 must enforce this sequence.

🔴 BUG 4 — ADMIN OVERRIDE HAS NO TIME LIMIT
  Problem: Admin override dashboard appears when SDE can't clear all L4.
           If admin is unreachable, the draw waits indefinitely.
           No timeout specified in architecture.
  Fix: 2-hour auto-selection: if admin doesn't decide within 2 hours,
       system auto-picks the option with lower EXPECTED financial impact
       (usually Option A). Draw proceeds automatically.

🟠 BUG 5 — TYPE B CONSECUTIVE WEEK CASCADE
  Problem: If L1/L2 supply is chronically low (multiple weeks):
           Week 1: Type B runs → creates L5 members.
           Week 2: L1/L2 still low → Type B runs again → creates L6 members.
           Week 3: L6 members cannot be cleared profitably.
           No automatic halt after consecutive Type B weeks.
  Fix: Auto-escalate to admin alert after 2 consecutive Type B weeks.
       Flag: "Type B has run 2 consecutive weeks. L5/L6 risk increasing.
       Admin action required." System presents same Option A/B dashboard.

🟠 BUG 6 — REFERRAL BONUS TRIGGERS ON SDE SEED PARTICIPATION
  Problem: A waitlisted member is used as a shared seed for SDE.
           If the referral bonus rule says "triggers when member is placed
           in a pool," the SDE temporary assignment might trigger it early.
           The actual referrer gets credited before the referred member is
           formally a pool member.
  Fix: Referral bonus triggers ONLY on permanent pool assignment
       (status changes from WAITLIST to ACTIVE in their home pool).
       SDE seed participation does not change home pool status.
       Explicit check: referral_trigger = (status = 'ACTIVE' AND home_pool_assigned).

🟠 BUG 7 — SDE POOL'S WEEKLY DRAW FLAG NOT SET
  Problem: SDE processes Pool A in backend sub-draw.
           At T-0H, the regular draw job fires for all active pools.
           Pool A gets drawn AGAIN by the regular job (double draw).
           Pool A has 4 winners instead of 2.
  Fix: Each SDE sub-draw must set:
       pool.draw_completed_this_week = TRUE immediately after commit.
       Regular draw job checks this flag. If TRUE: skips that pool.
       SDE draw IS Pool A's weekly draw. Not additive.

🟡 BUG 8 — PAUSE RULE "< 2 MEMBERS PER WEEK" IS AMBIGUOUS
  Problem: "New member inflow < 2 per week" — what counts as a member?
           Someone who registered but hasn't paid? Someone on waitlist?
           Someone whose token is pending?
  Fix: Count ONLY confirmed DEP tokens burned in the last 7 days.
       Registration without payment = does not count.
       Pending/processing payments = does not count.
       Only fully completed DEP token burns = counts toward the 2/week threshold.

🟡 BUG 9 — CONDENSATION TIMING WINDOW TOO VAGUE
  Problem: "Block condensation on draw day (Saturday-Sunday)" is imprecise.
           Does it mean all 48 hours? From Saturday midnight?
           From T-2H start? The architecture is unclear.
  Fix: Condensation is blocked from T-2H preparation start (Saturday 10:00 PM)
       until T+0H:10 post-draw cleanup complete (Sunday ~12:10 AM).
       Total block window: ~2 hours 10 minutes.
       NOT all of Saturday-Sunday. Condensation runs normally all other times.

🟡 BUG 10 — BRAIN 5 FORWARD SIGNAL (SIGNAL C) WEIGHT IS ARBITRARY
  Problem: Signal C weight = 20% ("current L2 count predicts future L3 demand").
           But the conversion rate (L2→L3) depends on how many L2 members
           survive their draw. Brain 5 currently uses a fixed 83.3% survival rate.
           In reality, survival rate varies week to week.
  Fix: Signal C should use ACTUAL historical survival rate from the last 4 weeks
       (rolling average) rather than theoretical 5/6.
       Actual_survival = (members_who_advanced_last_4_weeks) ÷ (total_survivors_last_4_weeks)
       Signal C = Current_L2_count × Actual_survival_rate

🟢 BUG 11 — MINOR: LEVEL 6 PAYOUT TABLE EXISTS BUT IS THEORETICALLY UNREACHABLE
  Problem: Payout table has L5 and L6 entries. Architecture says L5/L6 are
           impossible in normal operation. But they ARE reachable in edge cases.
           If someone reads the code and sees "Level 6 payout = ₹8,500," they
           might conclude the Anti-Maturity Protocol isn't working.
  Fix: Add comments in payout table: "L5/L6 only reachable via admin override
       or Type B cascade. SDE emergency handles these when they appear."
       These are not dead code — they're emergency fallback entries.
```

---

## SYSTEM HEALTH AT A GLANCE

```
┌────────────────────────────────────────────────────────────────┐
│  WHAT THE SYSTEM GUARANTEES (MATHEMATICALLY LOCKED):          │
│                                                                │
│  ✅ Minimum ₹3,500 profit per draw per pool, always           │
│  ✅ Maximum payout ₹8,500 (L4 upper + L2 lower)              │
│  ✅ L5/L6 payouts impossible in normal operation              │
│  ✅ Every L4 member exits within 1 week of reaching L4        │
│  ✅ System only pauses for genuine inflow drought (<2/week)   │
│  ✅ All draw results revealed simultaneously (no leaks)       │
│  ✅ Max 2 winners per pool, always                            │
│  ✅ FIFO waiting — no queue jumping                           │
│                                                                │
│  WHAT REQUIRES ADMIN JUDGMENT (Cannot Be Automated):         │
│                                                                │
│  ⚠️  L4 overflow when SDE capacity exceeded (Option A/B)     │
│  ⚠️  Terminal state (≤ 11 members: pause, refund, or merge)  │
│  ⚠️  Consecutive Type B weeks (L5/L6 accumulation risk)      │
│  ⚠️  Float insufficient for mass payout week                 │
│                                                                │
│  BUGS FOUND: 11 total                                         │
│    🔴 Critical (must fix before any draw): 4 (B1, B2, B3, B4)│
│    🟠 Important (fix before launch): 3 (B5, B6, B7)          │
│    🟡 Should fix (within 2 weeks): 3 (B8, B9, B10)           │
│    🟢 Minor/documentation: 1 (B11)                            │
└────────────────────────────────────────────────────────────────┘
```

That is the complete updated system. Every piece of the machine from the moment someone walks in to the moment they walk out with their money — including the AI brain decisions, the anti-maturity safeguards, and all 11 bugs found during the review.

The 4 critical bugs (tier rule specificity, multiple L4 same pool, seed-pool overlap, admin override timeout) should be resolved before any draw logic is implemented. The remaining bugs are important but won't cause draws to fail immediately.

Ready to move to implementation planning?