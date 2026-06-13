Let me read the core production files first to ensure the wire diagram is 100% accurate.

Let me read the core production files first to ensure the wire diagram is 100% accurate.

Now I have everything I need. Here is the complete wire diagram — every detail, easy language.

---

# ══════════════════════════════════════════════════════
# REWARD SCHEME — COMPLETE SYSTEM WIRE DIAGRAM
# Every Rule, Formula, and Flow — Plain Language
# ══════════════════════════════════════════════════════

---

## SECTION 1 — THE BIG PICTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WHAT THIS SYSTEM DOES (IN ONE LINE)                      │
│                                                                             │
│  People pay ₹1,000 to join.  Every week, 2 people from each group win      │
│  and get paid out.  New people keep joining to replace them.  The system    │
│  uses 5 AI brains to make sure money never runs out and everyone gets a    │
│  fair turn — not just the people who joined early.                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## SECTION 2 — THE THREE LAYERS (The Hydraulic Pipeline)

Think of this like a water tank system. Water (people) flows DOWN through 3 layers.

```
                         NEW PEOPLE JOIN HERE
                               │
                               ▼
╔══════════════════════════════════════════════════════╗
║         LAYER 1 — WAITLIST / RESERVOIR               ║
║                                                      ║
║  • Everyone starts here                              ║
║  • Pay ₹1,000 deposit → get a queue number (WL-01)   ║
║  • Wait your turn — FIFO: first joined = first moved ║
║  • Queue size: unlimited                             ║
║                                                      ║
║  Like: railway waiting room. You sit, wait, get      ║
║  called in order.                                    ║
╚══════════════════════════════════════════════════════╝
                               │
               When enough people ready (24 minimum)
                               │
                               ▼
╔══════════════════════════════════════════════════════╗
║         LAYER 2 — ACTIVE POOLS (The Main Game)       ║
║                                                      ║
║  • Groups of exactly 12 people                       ║
║  • Each group = one "Pool" (Pool A, Pool B…)         ║
║  • Every week, 2 people from each pool WIN & EXIT    ║
║  • Remaining 10 people ADVANCE one level up          ║
║  • Empty spots filled by next people from Waitlist   ║
║                                                      ║
║  Like: a cricket team — 12 players, 2 retire each   ║
║  week, 2 new ones called up from the bench.          ║
╚══════════════════════════════════════════════════════╝
                               │
               When someone wins the draw
                               │
                               ▼
╔══════════════════════════════════════════════════════╗
║         LAYER 3 — EXIT / WINNERS                     ║
║                                                      ║
║  • Winner gets their payout token (WIT-XXXXXX)       ║
║  • They leave the system permanently                 ║
║  • Status: "Eliminated_Won"                          ║
║  • Their ₹1,000 + system earnings = payout           ║
╚══════════════════════════════════════════════════════╝
```

---

## SECTION 3 — THE 6 LEVELS INSIDE EVERY POOL

Each pool has 12 people spread across 6 levels. When you survive a draw week, you move up one level.

```
  LEVEL 1  (L1)  ───── Just joined.  Payout if won: ₹2,000 net
  LEVEL 2  (L2)  ───── Survived 1 week.  Payout: ₹3,000 net
  LEVEL 3  (L3)  ───── Survived 2 weeks. Payout: ₹4,000 net
  LEVEL 4  (L4)  ───── Survived 3 weeks. Payout: ₹5,500 net  ⚠️ DANGER ZONE
  LEVEL 5  (L5)  ───── Survived 4 weeks. Payout: ₹6,500 net  🔴 EMERGENCY
  LEVEL 6  (L6)  ───── Survived 5 weeks. Payout: ₹8,000 net  🔴🔴 EXTREME

  Gross payouts before ₹500 fee:
    L1=₹2,500   L2=₹3,500   L3=₹4,500
    L4=₹6,000   L5=₹7,000   L6=₹8,500

  NOTE: In a healthy system, L5 and L6 should NEVER exist.
  If someone reaches L4, the Anti-Maturity Protocol immediately fires.
```

---

## SECTION 4 — HOW SOMEONE JOINS (Registration → Active Pool)

```
  STEP 1: Person signs up
          → Creates account
          → Generates a Deposit Token: SD0000000001 (unique code)
          → Token Type = "Deposit",  Value = ₹1,000,  Status = "Burned"
          → User Status = WAITLIST

  STEP 2: Gets a queue number
          → WL-68  (means 67 people are ahead of them)
          → This number UPDATES in real-time as people ahead enter pools

  STEP 3: Waits for enough people to accumulate
          → System needs 24 paid waitlist members before creating a new pool
          → This "24" threshold can DROP under pressure (see Section 9)

  STEP 4: Enters a Pool
          → First 12 from the waitlist (FIFO) → fill one pool
          → Status changes: WAITLIST → ACTIVE
          → Level set to: L1
          → WL queue number is "discharged" (shown as historical)
          → If this person was referred by someone → referrer gets ₹250 credited
            (Rule 39: credit happens at pool entry, NOT at registration)

  STEP 5: Plays the weekly game
          → Every week pays ₹50/day late fee if they don't pay (max ₹500 cap)
          → Draw happens Sunday midnight
          → Either WIN (exit with payout) or SURVIVE (advance one level)
```

---

## SECTION 5 — THE WEEKLY CALENDAR (7-Day Cycle)

```
  MONDAY
  ───────
  • New people join waitlist
  • All Active members' payment status reset to "Unpaid"
  • Late fee clock starts ticking: ₹50/day after due date

  TUESDAY – THURSDAY
  ──────────────────
  • Members pay their weekly installment
  • AI monitors join rate, referral ratio, velocity trends

  THURSDAY (Payment Due Date)
  ───────────────────────────
  • Unpaid members past due date → flagged "Elimination Risk"
  • Grace period opens: 48 hours to pay or lose seat

  SATURDAY 22:00 (T-2H = 2 Hours Before Draw)
  ─────────────────────────────────────────────
  • System acquires a LOCK (prevents duplicate draws)
  • Brain 5 calculates LPI (see Section 7)
  • L4 members get flagged as "SDE Required"
  • Multi-L4 pools get split up (only 1 L4 allowed per pool)
  • SDE Meta-Pool builds (collects all L4 people system-wide)
  • WeeklyDrawState written (snapshot of what will happen)
  • All of this takes up to 2 hours to complete

  SUNDAY 00:00 (T-0H = Draw Time)
  ────────────────────────────────
  • SDE Extensions run first (L5/L6 emergency exits if any exist)
  • All Active pools checked: need exactly 12 members to draw
    → Less than 12 → Pool PAUSED (SafeStop). No draw this week.
  • Draw runs for every eligible pool
  • 2 winners picked per pool (see Section 6 for HOW)
  • Winners exit, Waitlist refill happens
  • Draw guard set: "draw_completed_this_week = True"
    → Cannot draw same pool twice this week

  SUNDAY 00:05 (T+5m = Post-Draw Cleanup)
  ────────────────────────────────────────
  • "draw_completed_this_week" reset to False on all pools
  • L4/SDE flags cleared
  • System LOCK released
  • Ready for next week
```

---

## SECTION 6 — HOW THE DRAW WORKS (Smart Pairing Dual-Draw)

Every draw picks exactly **2 winners** from a pool of 12. The 2 winners always come from **different halves** of the pool (lower levels vs higher levels). This is called "Smart Pairing."

```
┌────────────────────────────────────────────────────────────────────────┐
│                    THE 7 DRAW TYPES                                    │
└────────────────────────────────────────────────────────────────────────┘

DRAW TYPE 1 — REGULAR (Normal Conditions, LPI < 14%)
─────────────────────────────────────────────────────
  Lower half: L1, L2, L3 members  →  Winner 1 picked randomly
  Upper half: L4, L5, L6 members  →  Winner 2 picked randomly
  
  If NO upper-half members exist yet (brand new pool):
    → Both winners from lower half (edge case, 2 random from L1-L3)


DRAW TYPE 2 — TYPE A EXECUTION POOL (Medium Pressure, LPI 14–24%)
──────────────────────────────────────────────────────────────────
  Lower half: L1, L2 only  →  Winner 1
  Upper half: L3, L4 only  →  Winner 2
  
  Why different? Because L3 people are getting older. Pulling them
  as "upper tier winners" gets them out earlier, reducing pressure.


DRAW TYPE 3 — SDE (Sequential Dynamic Eviction, LPI ≥ 25% or any L4 exists)
─────────────────────────────────────────────────────────────────────────────
  This is NOT a normal draw. It is a forced exit for the oldest people.
  
  Upper winner: ALWAYS L4 (the person in danger zone)
  Lower winner: L1 or L2 (the newest person)
  
  Exception: If LPI > 50%, L3 is also allowed as the lower winner.
  
  Why? L4 people cost the most (₹5,500). If they don't exit now,
  they'll become L5 (₹6,500) or L6 (₹8,000) — losing more money.
  SDE guarantees L4 exits every single week.


DRAW TYPE 4 — TYPE B FALLBACK (When No L1/L2 Left)
────────────────────────────────────────────────────
  Lower half: L3 only  →  Winner 1
  Upper half: L4 only  →  Winner 2
  
  Happens when the waitlist is empty and pool only has L3/L4 people.


DRAW TYPE 5 — SDE EXTENSION II (Emergency L5 Exit)
────────────────────────────────────────────────────
  Triggered: When ANY member reaches L5 (should never happen normally)
  
  Upper winner: EXACTLY L5 (force them out NOW)
  Lower winner: Anyone from L1–L4
  
  Why urgency? If you wait 1 more week, L5 becomes L6:
    Cost now (L5+L5): ₹6,500 × 2 = ₹13,000
    Cost later (L5+L6): ₹6,500 + ₹8,000 = ₹14,500  → ₹1,500 more wasted
  Always cheaper to exit L5 immediately.


DRAW TYPE 6 — SDE EXTENSION III (Extreme L6 Exit)
────────────────────────────────────────────────────
  Triggered: When ANY member reaches L6 (admin override edge case only)
  
  Upper winner: EXACTLY L6 (emergency exit)
  Lower winner: Anyone from L1–L5
  
  This should never happen in a properly managed system.
  If it does, it means SDE failed 2 consecutive weeks.


DRAW TYPE 7 — ACCELERATED DISSOLUTION (Pool Collapse Mode)
───────────────────────────────────────────────────────────
  Triggered: When 60% or more of a pool's 12 members are L4+
  
  BOTH Winner 1 AND Winner 2 come from L4+ (not split between tiers)
  
  After draw, if pool drops below 8 members → pool DISSOLVED
  → Remaining members redistributed to other pools
  → A brand new "relief pool" created from the waitlist simultaneously
  
  Why? A pool where 7 of 12 people are at L4 is too expensive to
  sustain. Getting all of them out fast is cheaper than keeping the
  pool running for 3–4 more weeks.
```

---

## SECTION 7 — LPI (THE SYSTEM'S HEALTH METER)

LPI = **Level Pressure Index**. It's the single number that tells the system how "stressed" it is.

```
                    ┌─────────────────────────────────┐
                    │          LPI FORMULA             │
                    │                                  │
                    │   (L3 + L4 + L5 + L6) members   │
                    │   ─────────────────────────────  │
                    │     Total Active Members         │
                    │              × 100               │
                    │                                  │
                    │   Result: a % from 0 to 100      │
                    └─────────────────────────────────┘

  WHAT EACH LPI RANGE MEANS:

  LPI < 14%   ──── 🟢 GREEN  — Healthy. Run regular draws.
              ────────────────────────────────────────────
              Most members are still at L1/L2 (fresh, cheap to pay out).
              System is young and safe.

  LPI 14–24%  ──── 🟡 AMBER  — Caution. Switch to Type A pools.
              ────────────────────────────────────────────
              More L3/L4 people than ideal. Time to start pushing
              older members out faster via Type A draws.

  LPI ≥ 25%   ──── 🟠 ORANGE — Stress. Activate SDE proactively.
              ────────────────────────────────────────────
              Too many people at dangerous levels. Even if no L4 exists,
              SDE mode activates to drain the backlog before it gets worse.

  LPI > 50%   ──── 🔴 RED    — L3 exception kicks in.
              ────────────────────────────────────────────
              So many mid-high level members that L3 is now allowed to
              be the "lower tier" SDE winner (normally only L1/L2).

  ANY L4 EXISTS  — HARD OVERRIDE. SDE activates immediately.
              ────────────────────────────────────────────
              Does not matter what the LPI% says. Even 1 L4 person
              anywhere in the system = SDE mode for that pool.
```

---

## SECTION 8 — THE SDE ENGINE (Anti-Maturity Protocol)

SDE = **Sequential Dynamic Eviction**. It's the most important safety mechanism. It prevents the system from getting "old and expensive."

```
  PROBLEM IT SOLVES:
  ─────────────────
  Without SDE, a person could sit at L3 forever, survive draw after draw,
  eventually reach L4, L5, L6 — and cost ₹8,000 when they finally exit.
  That's 8× more expensive than an L1 winner (₹2,000).

  SDE GUARANTEE:
  ─────────────
  No matter what, at least 1 L4 person EXITS every single week.
  This hard guarantee prevents the pool from aging.

  HOW SDE PICKS WHO EXITS (AI Weighting):
  ─────────────────────────────────────────
  For the LOWER tier (L1/L2 winner), the system doesn't just pick randomly.
  It calculates a "weight score" for each eligible person:

  ┌─────────────────────────────────────────────────────────────┐
  │  Weight = (Weeks in Pool × 30%)                            │
  │         + (Total Deposited ÷ 1000 × 25%)                   │
  │         + (Pauses Experienced × 20%)                       │
  │         + (Organic Join Score × 15%)                       │
  │         + (Random Noise × 10%)                             │
  │                                                             │
  │  Organic Join Score:                                       │
  │    Joined directly (no referral) = 1.0                     │
  │    Joined via referral code       = 0.3                    │
  │                                                             │
  │  Everyone gets a minimum floor of 0.05 (nobody excluded)   │
  └─────────────────────────────────────────────────────────────┘

  WHY THESE WEIGHTS?
  People who waited longer, deposited more, experienced pauses,
  and joined organically (not just from referral hype) get a
  HIGHER chance to win. It rewards loyalty and genuine participation.

  WHAT HAPPENS WHEN L1/L2 SUPPLY IS TOO LOW FOR SDE?
  ─────────────────────────────────────────────────────
  Rule: Each L4 person needs at least 2 L1/L2 candidates as "lower pool"
  
  If not enough L1/L2 exist:
    → Emergency: Pull up to 2 people from the waitlist immediately
    → This is the SDE Emergency WL Promotion
  
  If still not enough:
    → Admin Override Required flag is set
    → Admin manually approves or system auto-selects after 2 hours

  MULTI-L4 POOL PROBLEM (Fixed):
  ─────────────────────────────
  If one pool accidentally has 2 or more L4 members:
    → System detects this at T-2H
    → Moves excess L4 people to OTHER pools that have zero L4 members
    → This is the "Multi-L4 Redistribution" step
    → Keeps exactly 1 L4 per pool (maximum 1 SDE draw per pool per week)

  SDE SESSION LIMIT:
  ─────────────────
  Maximum 6 pools can be processed per SDE session.
  If more than 6 pools have L4 members:
    → Multiple SDE sessions run back-to-back
    → Sessions needed = CEILING(L4 count ÷ 6)
```

---

## SECTION 9 — THE 5 BRAINS (AI System)

The system has 5 AI Brains that work together to manage the pool economy.

```
╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 1 — HYDRAULIC ENGINE                           ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Manages the 3-layer (Waitlist → Active → Exit) flow
  
  It calculates:
    • How many vacancies exist in active pools
    • How many new pools need to be created
    • Whether pools should be condensed (merged) when waitlist is empty
  
  Output: Drives all 3 Phases of the Waitlist Refill Engine (see Section 10)


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 2 — MOMENTUM TRACKER (Tri-Velocity)            ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Measures how fast people are joining vs how fast 
                the system is paying them out.

  It calculates 3 velocity signals and BLENDS them:

  ┌─────────────────────────────────────────────────────────────────────┐
  │  BLENDED VELOCITY = (Slow14d × 50%) + (Fast48h × 30%) + (Fwd × 20%)│
  │                                                                     │
  │  Slow 14-Day SMA (50%):   Average new users per week, last 14 days  │
  │  Fast 48-Hour (30%):      New users in last 48 hours × 7 (weekly)   │
  │  Forward Signal (20%):    From Brain 5 — projected new L3 next week  │
  └─────────────────────────────────────────────────────────────────────┘

  CLIFF DETECTION (Emergency Override):
    If today's rate < 3 days ago rate × 50% → VELOCITY CLIFF
    → Forces system to "NEUTRAL" mode regardless of other signals
    → Prevents over-optimistic decisions during sudden drops

  BURN RATE (Weekly Drain):
    = Active Pools × 2  (exactly 2 winners exit per pool per week)
    Example: 10 pools → burn rate = 20 people/week leaving


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 3 — QUALITY RADAR (RDR)                        ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Distinguishes REAL organic growth from referral-hype bubbles

  ┌─────────────────────────────────────────────────────────────────────┐
  │  RDR = (People who joined via referral link ÷ Total joins) × 100   │
  │  Measured over last 7 days                                          │
  └─────────────────────────────────────────────────────────────────────┘

  RDR < 30%   → Genuine organic growth (healthy, sustainable)
  RDR 30–70%  → Mixed traffic (moderate, watch carefully)
  RDR > 70%   → Referral hype bubble (dangerous, temporary spike)


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 4 — CONDENSATION ENGINE                        ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Emergency pool merger when waitlist runs completely empty

  If paid waitlist = 0 AND some pools have < 12 members:
    → Take members from the NEWEST full pools
    → Move them into the OLDEST under-capacity pools
    → Until all pools are full
    → The emptied newest pool is dissolved
  
  IMMUNITY RULE: Pools with L4 flagged members (SDE-protected) are
  NEVER touched by condensation. They are immune.


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 5 — LPI ENGINE (Level Pressure Index)          ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Calculates LPI (see Section 7) and feeds the Forward
               Signal into Brain 2's tri-velocity blend

  Forward Signal Formula:
  ┌──────────────────────────────────────────────────────────────────┐
  │  Forward Signal = Current L2 Count × Survival Rate              │
  │                                                                  │
  │  Survival Rate:                                                  │
  │    Theoretical: 10/12 = 0.833 (10 survive out of 12 each week)  │
  │    Actual: adjusted downward if pools have been pausing          │
  │                                                                  │
  │  Meaning: "How many NEW L3 members will exist next week?"        │
  │  This gives Brain 2 a FORWARD-LOOKING view, not just history.    │
  └──────────────────────────────────────────────────────────────────┘
```

---

## SECTION 10 — THE AI SCENARIO MATRIX

Brain 2 + 3 combined produce one of 6 "Scenarios." Each scenario changes the Reserve Multiplier, which controls how aggressively the system creates new pools.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AI SCENARIO DECISION MATRIX                         │
├────────────────────────┬──────────────┬────────────────────────────────────┤
│       SCENARIO         │  MULTIPLIER  │         WHEN IT TRIGGERS           │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 🌊 SUSTAINABLE_WAVE    │    × 0.50    │ Growth > Burn AND RDR < 30%        │
│  (Most Aggressive)     │              │ Real organic growth. Very safe.    │
│                        │              │ Reserve requirement cut by half.   │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 💥 BOOM_GOLDEN_CROSS   │    × 0.75    │ Growth > Burn AND RDR 30–70%       │
│                        │              │ Good growth, mixed traffic.        │
│                        │              │ Slightly relaxed reserves.         │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ ⚡ VELOCITY_CLIFF       │    × 1.00    │ Growth > Burn BUT cliff detected   │
│  (Override)            │              │ Sudden 50%+ drop in 3 days.        │
│                        │              │ System halts optimism, stays safe. │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ ⚠️  FLASH_FLOOD         │    × 1.50    │ Growth > Burn AND RDR > 70%        │
│                        │              │ Referral hype spike. Dangerous.    │
│                        │              │ Extra large reserve held back.     │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 🔴 DRY_PHASE           │    × 2.00    │ Growth < Burn (any RDR)            │
│  (Liquidity Protection)│              │ Paying out MORE than coming in.    │
│                        │              │ Double reserve. No new pools.      │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 🆘 REFERRAL_LIFELINE   │    × 2.00    │ Growth < Burn AND RDR > 60%        │
│  (Liquidity Protection)│              │ Organic traffic DEAD. Only bots.   │
│                        │              │ Maximum protection mode.           │
└────────────────────────┴──────────────┴────────────────────────────────────┘

HOW THE MULTIPLIER IS USED:
─────────────────────────────
  Dynamic Reserve Needed = Active Pools × 12 × Multiplier

  Example: 5 pools, SUSTAINABLE_WAVE (×0.50):
    Reserve = 5 × 12 × 0.50 = 30 people must stay in waitlist as buffer

  Remaining waitlist (after reserve subtracted) can form new pools.
  So lower multiplier = more pools can be created = more winners paid out.
```

---

## SECTION 11 — THE WAITLIST REFILL ENGINE (3-Phase System)

After every draw, empty seats need to be filled. This happens in exactly 3 phases, in order.

```
══════════════════════════════════════════════
PHASE 1 — FILL EXISTING POOLS (Double-FIFO)
══════════════════════════════════════════════

  Goal: Bring all under-capacity active pools back to 12 members.

  Pool Priority:  Oldest pool created → filled FIRST (FIFO by creation date)
  Person Priority: Longest waiting person → moved FIRST (FIFO by join date)

  Steps (all done in bulk, not one-by-one — very fast):
    1. Count vacancies in every pool (one database query)
    2. Fetch enough waiting people to fill all vacancies (one query)
    3. Assign people to pools in memory (Python loop)
    4. Update all assignments at once (one update per pool, not 100 updates)
    5. Paused pools that are now full → reactivated to "Active"

  After this phase: every existing pool is either full (12) or still
  short if the waitlist ran out.


══════════════════════════════════════════════
PHASE 2 — CREATE NEW POOLS (Auto-Scale)
══════════════════════════════════════════════

  Goal: If enough extra people are still waiting, create new pools.

  Trigger: After filling all existing pools, if waitlist still has
           enough people for at least one new pool.

  Adaptive Threshold Formula:
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Effective Threshold = MAX(12, 24 × (1 − Pressure Factor))          │
  │                                                                      │
  │  Pressure Factor = MIN(0.50, LPI ÷ 100)                            │
  │                                                                      │
  │  Meaning:                                                            │
  │    LPI 0%  → Need 24 people to trigger new pool (normal)            │
  │    LPI 25% → Need 18 people to trigger new pool (reduced pressure)  │
  │    LPI 50% → Need 12 people to trigger new pool (minimum floor)     │
  │                                                                      │
  │  Also: AI Reserve is subtracted first.                              │
  │    Available for new pools = Waitlist - (Pools × 12 × Multiplier)  │
  └──────────────────────────────────────────────────────────────────────┘

  Steps:
    1. Calculate how many new pools can be made
    2. Create all pools at once (one bulk database insert)
    3. Move 12 people into each new pool (one update per pool)
    4. Rule 39: credit ₹250 to each new member's referrer (if referred)


══════════════════════════════════════════════
PHASE 3 — CONDENSATION (Emergency Merge)
══════════════════════════════════════════════

  Goal: When there's NO waitlist, consolidate half-empty pools.

  Only fires if: Paid waitlist = 0 AND some pools still have < 12 members.

  Algorithm:
    → Take members from the NEWEST full pools ("donors")
    → Move them into the OLDEST under-capacity pools ("receivers")
    → Keep their level, payment status, join date — EXACTLY unchanged
    → The emptied new pool is dissolved
    → SDE-protected pools are IMMUNE (never touched)

  Example:
    Pool A (oldest): 10 members  ← receiver
    Pool Z (newest): 12 members  ← donor
    → Move 2 from Pool Z → Pool A
    → Pool A now has 12 (draws again)
    → Pool Z now has 10 (if further condensation needed, continues)
```

---

## SECTION 12 — THE MONEY FLOW (Financial System)

```
  MONEY IN:
  ─────────
  Every new person pays ₹1,000
  This burns a DEP (Deposit) Token: code SD0000000001
  The ₹1,000 stays in the system as float (working capital)

  LATE FEES:
  ──────────
  ₹50 per day after payment due date
  Maximum cap: ₹500 (no matter how many days late)
  Goes into system as additional float

  GRACE PERIOD FEE:
  ─────────────────
  ₹500 extra to save your seat during the 48-hour grace window
  Paid on top of ₹1,000 weekly installment + any accrued late fees

  MONEY OUT (PAYOUTS):
  ─────────────────────
  Level 1 winner → receives ₹2,000 net  (gross ₹2,500 – fee ₹500)
  Level 2 winner → receives ₹3,000 net  (gross ₹3,500 – fee ₹500)
  Level 3 winner → receives ₹4,000 net  (gross ₹4,500 – fee ₹500)
  Level 4 winner → receives ₹5,500 net  (gross ₹6,000 – fee ₹500)
  Level 5 winner → receives ₹6,500 net  (gross ₹7,000 – fee ₹500)
  Level 6 winner → receives ₹8,000 net  (gross ₹8,500 – fee ₹500)

  Each payout creates a Withdraw Token: WIT-XXXXXX (cryptographically unique)

  REFERRAL PAYOUTS:
  ─────────────────
  ₹250 credited when a referred person ENTERS an active pool
  (NOT when they register — must actually play)
  Accumulates in referrer's account balance
  Redeemable via payout request

  WHAT THE ₹500 FEE COVERS:
  ──────────────────────────
  Operational cost, admin, platform maintenance
  Deducted from every winner's gross payout
```

---

## SECTION 13 — PAYMENT COMPLIANCE SYSTEM (A/B/C Model)

```
  "A" = Elimination Percentage
  ────────────────────────────
  What % of non-payers actually get eliminated.
  Default: 80% (not 100% — some leniency built in)
  Configurable by admin.

  "B" = Late Fee Rate
  ───────────────────
  How much per day: ₹50/day
  Maximum cap: ₹500 total (10 days max accumulation)

  "C" = Grace Saver Percentage
  ─────────────────────────────
  What % of at-risk members successfully save their seat
  during the grace period.
  Default: 15% (most people do lose their seat — this is intentional)

  A, B, and C are CIRCULAR — they affect each other:
    More strict A (higher elimination%) → more pressure on B (late fees rise)
    More lenient C (more grace saves) → reduces effective A
    Higher B (higher late fees) → incentivizes faster payment, reduces need for A

  PAYMENT TIMELINE:
  ─────────────────
  Day 0 (Monday):   Payment window opens. Status = Unpaid.
  Day 4 (Thursday): Due date. Unpaid = Elimination Risk flagged.
  Day 4–6 (Thu-Sat): GRACE PERIOD (48 hours).
                      Pay ₹500 grace fee + accumulated late fee to save seat.
  Day 7 (Saturday 22:00): Grace window closes.
  Day 7 (Sunday 00:00): All still-unpaid + grace-unsaved members → ELIMINATED.
```

---

## SECTION 14 — SECURITY SAFEGUARDS

```
  DRAW LOCK (System Lock):
  ────────────────────────
  • Only ONE draw can run at a time system-wide
  • Lock acquired at Saturday 22:00
  • Lock released at Sunday 00:05 (after cleanup)
  • If lock already exists → error raised, admin notified
  • Total lock window: 2 hours prep + draw + 10 minutes cleanup = 130 minutes

  DOUBLE-DRAW GUARD:
  ──────────────────
  • "draw_completed_this_week" flag on each pool
  • If True → draw refused ("already drew this week")
  • Reset by post_draw_cleanup at 00:05
  • Prevents any pool from drawing twice in one week

  CRYPTOGRAPHIC DRAW RANDOMNESS:
  ────────────────────────────────
  • Winners are picked using os.urandom (hardware random from OS)
  • NOT using Python's standard random (which is predictable)
  • Token codes use same os.urandom source (secrets module)
  • All token codes checked for uniqueness before issuing

  ADMIN PASSWORD REQUIRED FOR:
  ──────────────────────────────
  • Deleting tokens
  • Deleting users
  • Updating elimination settings
  • Confirming grace period seat saves
  • Executing manual elimination

  SAFE-STOP (Pool Pausing):
  ─────────────────────────
  • Pool with < 12 members → draw REFUSED automatically
  • Pool status set to "Paused_Awaiting_Members"
  • No override possible — 12 members is a hard requirement
  • Paused pools get filled first in Phase 1 refill
```

---

## SECTION 15 — COMPLETE END-TO-END FLOW (From Zero to Winner)

```
  ┌───────────────────────────────────────────────────────────────────────┐
  │  PERSON'S JOURNEY: Day 1 to Exit                                     │
  └───────────────────────────────────────────────────────────────────────┘

  DAY 1:
  User registers → pays ₹1,000 → DEP token burned
  Status = WAITLIST, Queue = WL-68
  
  WEEK 1 (if enough people in queue):
  24+ paid waitlist members accumulate
  AI checks: Reserve needed = Pools × 12 × Multiplier
  If remaining waitlist ≥ Adaptive Threshold → New pool created
  Person moves from Waitlist → Pool A at Level 1
  WL-68 → discharged
  If they were referred → their referrer gets ₹250 credited
  
  WEEK 1 DRAW (if in pool, pool has 12):
  LPI calculated: say 5% (healthy)
  Draw type: REGULAR
  Lower tier: L1 people  |  Upper tier: (none yet — new pool)
  Edge case: 2 random winners from L1 pool
  
  IF THEY WIN (Week 1):
    → Level 1 winner → ₹2,000 net payout
    → WIT-XXXXXX token generated
    → Status: Eliminated_Won
    → Exit. Done.
  
  IF THEY SURVIVE (Week 1):
    → Level advances: L1 → L2
    → Weekly payment status reset: Paid → Unpaid for next week
    → Pool refilled: next waitlist person takes the 2 winner spots
  
  WEEK 2 DRAW (if survived):
  They're now L2.
  LPI might be 15% now (more people have survived, getting older)
  Draw type: TYPE A (L1-L2 lower / L3-L4 upper)
  They are in the "lower tier" — random chance to be Winner 1
  
  IF THEY WIN (Week 2):
    → Level 2 winner → ₹3,000 net payout → Exit.
  
  IF THEY SURVIVE (Week 2):
    → Level advances: L2 → L3
  
  WEEK 3 DRAW (if survived):
  They're now L3. LPI might be 26% (getting stressed)
  Draw type: SDE (LPI ≥ 25%)
  → L4 members (if any) are guaranteed upper winners
  → L1/L2 compete for lower tier using AI weights
  
  IF THEY WIN (Week 3 as L3):
    Only possible if LPI > 50% (L3 exception rule activated)
    → ₹4,000 net payout → Exit.
  
  IF THEY SURVIVE (Week 3):
    → Level advances: L3 → L4
    → ⚠️ IMMEDIATE FLAG: sde_required = True (atomically, same DB write)
    → Their pool gets flagged: contains_flagged_l4 = True
  
  WEEK 4 (as L4 person — now in SDE mode):
  Saturday 22:00 T-2H:
    → Brain 5 flags them (catch-up sweep)
    → If their pool has multiple L4 people → some moved to other pools
    → SDE Meta-Pool built — they are the "upper tier" candidate
    → Draw type: SDE
  
  SUNDAY DRAW:
    → L4 (them) = guaranteed upper winner if SDE runs
    → They EXIT at L4 → ₹5,500 net payout
    → WIT-XXXXXX issued
    → Status: Eliminated_Won
    → Journey ends. Total time: ~4 weeks.

  ┌──────────────────────────────────────────────────────────────────────┐
  │  WHAT PREVENTS THEM REACHING L5 or L6?                              │
  │                                                                      │
  │  The SDE hard guarantee: L4 people ALWAYS exit in their FIRST week  │
  │  as L4. They cannot survive to L5 unless SDE completely fails AND   │
  │  no admin override happens AND emergency extension also fails.       │
  │  This triple-safety makes L5/L6 essentially impossible in practice. │
  └──────────────────────────────────────────────────────────────────────┘
```

---

## SECTION 16 — FULL SYSTEM MAP (Everything Connected)

```
  NEW USERS ──────────────────────────────────────────────────────────────────►
                                                                              │
  REGISTRATION                                                                │
  ├── Pay ₹1,000 → DEP Token burned (SD0000000001)                           │
  ├── Status = WAITLIST, Queue position = WL-XX                              │
  └── Referred by someone? → Referrer gets ₹250 when THIS person enters pool │
                                                                              │
  BRAIN 2 monitors join rate:                                                 │
  Blended = (14d-SMA × 50%) + (48h-EMA × 30%) + (Brain5-Forward × 20%)      │
                         │                                                    │
                         ▼                                                    │
  BRAIN 3 checks quality: RDR = referred% of all joins last 7 days           │
                         │                                                    │
                         ▼                                                    │
  SCENARIO DECIDED (one of 6) → MULTIPLIER chosen                            │
                         │                                                    │
                         ▼                                                    │
  PHASE 2 POOL CREATION: Available WL = Total WL − (Pools × 12 × Multiplier)│
       If Available ≥ Adaptive Threshold (12–24) → Create new pool           │
                         │                                                    │
                         ▼                                                    │
  ┌───────────────────────────────────────────────────────────────────────┐  │
  │                        POOL (12 MEMBERS)                              │◄─┘
  │   L1 ─ L1 ─ L1 ─ L1                                                  │
  │   L2 ─ L2 ─ L2                                                        │
  │   L3 ─ L3                                                             │
  │   L4                    ← if ANY L4: SDE fires                        │
  │   L5  ← should not exist. Ext-II fires if it does.                   │
  │   L6  ← should never exist. Ext-III fires if it does.                │
  └───────────────────────────────────────────────────────────────────────┘
                         │
  EVERY SATURDAY 22:00:  │
  BRAIN 5 calculates LPI: (L3+L4+L5+L6) ÷ Total Active × 100
                         │
       ┌─────────────────┼─────────────────────────────┐
       │                 │                             │
    LPI < 14%        LPI 14–24%                  LPI ≥ 25%
       │                 │                        or L4 exists
       ▼                 ▼                             │
   REGULAR          TYPE A DRAW                        ▼
   L1-L3 low        L1-L2 low                       SDE DRAW
   L4-L6 high       L3-L4 high                      L4 high (forced)
                                                     L1-L2 low (AI-weighted)
                         │
  EVERY SUNDAY 00:00     │
  DRAW EXECUTES:         │
  1. SDE Ext-II/III run first (L5/L6 emergency)
  2. Safety check: pool has exactly 12? If not → PAUSE (SafeStop)
  3. Check draw_completed_this_week = True? → SKIP (double-draw guard)
  4. Run Smart Pairing Dual-Draw → 2 winners per pool
  5. Winners get WIT-XXXXXX payout token
  6. Winners exit → Status: Eliminated_Won
  7. Surviving 10 members advance +1 level
  8. L3→L4 advance? → sde_required=True set ATOMICALLY
  9. Pool refill (Phases 1+2+3 as needed from waitlist)
  10. Rule 39: ₹250 credited to referrers of newly active members
                         │
  EVERY SUNDAY 00:05     │
  CLEANUP:               │
  1. draw_completed_this_week → False (all pools)
  2. SDE flags cleared
  3. System LOCK released
  4. Next week begins
```

---

## SECTION 17 — WHAT CAN GO WRONG AND HOW IT'S HANDLED

```
  PROBLEM: Pool has < 12 members at draw time
  SOLUTION: SafeStop — pool automatically PAUSED. No draw. Gets filled
            first in Phase 1 refill next time anyone joins.

  PROBLEM: System lock already held (crash from last week)
  SOLUTION: T-2H preparation detects stale lock → admin notified → 
            auto-clear after timeout. Simulation: lock deleted before retry.

  PROBLEM: Two pools both have the same L4 person (shouldn't happen but...)
  SOLUTION: Multi-L4 redistribution at T-2H moves excess L4 people to
            different pools. Exactly 1 L4 per pool max.

  PROBLEM: Not enough L1/L2 people for SDE lower tier
  SOLUTION: Emergency Waitlist Promotion — pull up to 2 waitlist people
            immediately (mid-week, outside normal refill cycle).

  PROBLEM: Someone reaches L5 (SDE failed somehow)
  SOLUTION: SDE Extension II fires FIRST at Sunday 00:00 (before all other draws)
            Forces L5 exit immediately. Costs ₹13,000 total (L5+L5 dual draw).
            Much cheaper than waiting: L5+L6 = ₹14,500 → saved ₹1,500.

  PROBLEM: Someone reaches L6 (SDE + Ext-II both failed — extreme case)
  SOLUTION: SDE Extension III — L6 forced exit. Costs ₹16,000 total.
            If this happens, something went seriously wrong with administration.

  PROBLEM: Pool becomes 60%+ L4+ (7 of 12 people are old)
  SOLUTION: Accelerated Dissolution — BOTH winners from L4+, not normal split.
            Pool rapidly drained. New relief pool created from waitlist simultaneously.
            Pool dissolved when it drops below 8 members.

  PROBLEM: Waitlist completely empty, some pools still not full
  SOLUTION: Brain 4 Condensation — merge newest pools into oldest pools.
            Fewer but fully-staffed pools is better than many half-empty ones.

  PROBLEM: Join rate suddenly drops 50%+ in 3 days
  SOLUTION: Brain 2 Cliff Detection — scenario forced to VELOCITY_CLIFF (neutral 1.0×).
            System doesn't over-confidently maintain aggressive pool creation.
```

---

## SECTION 18 — THE REFERRAL SYSTEM (Complete)

```
  How referrals work:
  ────────────────────
  1. Person A shares their referral code
  2. Person B registers using Person A's code
  3. Person B's record: referred_by_user_id = Person A's ID

  WHEN IS THE ₹250 PAID? (Rule 39 — Critical)
  ─────────────────────────────────────────────
  NOT at registration (too easy to game — register 100 fake accounts)
  ONLY when Person B actually enters an active pool (pays ₹1,000 and joins)

  Paths that trigger the ₹250 credit:
    ✓ Path 1: Phase 1 refill after a draw (normal waitlist → pool movement)
    ✓ Path 2: Phase 2 auto-scale (new pool created from waitlist)
    ✓ Path 3: Admin vacancy fill (manual admin operation)

  The ₹250 accumulates in Person A's account balance
  Person A requests payout separately via /users/request-referral-payout

  HOW BRAIN 3 USES THIS DATA:
  ────────────────────────────
  RDR = (people who joined via referral ÷ total joins) × 100
  This feeds into the scenario decision:
    High RDR = volatile hype = more conservative AI response
    Low RDR = organic = more aggressive pool creation
```

---

```
══════════════════════════════════════════════════════════════
  SUMMARY: THE 5 RULES THAT GOVERN EVERYTHING

  RULE 1: 12 members exactly — no more, no less, per pool
  RULE 2: 2 winners per pool per week — always, always, always
  RULE 3: L4 ALWAYS exits via SDE — the hard guarantee
  RULE 4: FIFO everywhere — first joined = first served
  RULE 5: ₹250 referral only at pool entry, never at registration
══════════════════════════════════════════════════════════════
```

---

That is the **complete system** — every formula, every rule, every safeguard, every AI brain, every flow — from the moment someone pays ₹1,000 to the moment they receive their payout token. Nothing omitted.

Now I have everything I need. Here is the complete wire diagram — every detail, easy language.

---

# ══════════════════════════════════════════════════════
# REWARD SCHEME — COMPLETE SYSTEM WIRE DIAGRAM
# Every Rule, Formula, and Flow — Plain Language
# ══════════════════════════════════════════════════════

---

## SECTION 1 — THE BIG PICTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WHAT THIS SYSTEM DOES (IN ONE LINE)                      │
│                                                                             │
│  People pay ₹1,000 to join.  Every week, 2 people from each group win      │
│  and get paid out.  New people keep joining to replace them.  The system    │
│  uses 5 AI brains to make sure money never runs out and everyone gets a    │
│  fair turn — not just the people who joined early.                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## SECTION 2 — THE THREE LAYERS (The Hydraulic Pipeline)

Think of this like a water tank system. Water (people) flows DOWN through 3 layers.

```
                         NEW PEOPLE JOIN HERE
                               │
                               ▼
╔══════════════════════════════════════════════════════╗
║         LAYER 1 — WAITLIST / RESERVOIR               ║
║                                                      ║
║  • Everyone starts here                              ║
║  • Pay ₹1,000 deposit → get a queue number (WL-01)   ║
║  • Wait your turn — FIFO: first joined = first moved ║
║  • Queue size: unlimited                             ║
║                                                      ║
║  Like: railway waiting room. You sit, wait, get      ║
║  called in order.                                    ║
╚══════════════════════════════════════════════════════╝
                               │
               When enough people ready (24 minimum)
                               │
                               ▼
╔══════════════════════════════════════════════════════╗
║         LAYER 2 — ACTIVE POOLS (The Main Game)       ║
║                                                      ║
║  • Groups of exactly 12 people                       ║
║  • Each group = one "Pool" (Pool A, Pool B…)         ║
║  • Every week, 2 people from each pool WIN & EXIT    ║
║  • Remaining 10 people ADVANCE one level up          ║
║  • Empty spots filled by next people from Waitlist   ║
║                                                      ║
║  Like: a cricket team — 12 players, 2 retire each   ║
║  week, 2 new ones called up from the bench.          ║
╚══════════════════════════════════════════════════════╝
                               │
               When someone wins the draw
                               │
                               ▼
╔══════════════════════════════════════════════════════╗
║         LAYER 3 — EXIT / WINNERS                     ║
║                                                      ║
║  • Winner gets their payout token (WIT-XXXXXX)       ║
║  • They leave the system permanently                 ║
║  • Status: "Eliminated_Won"                          ║
║  • Their ₹1,000 + system earnings = payout           ║
╚══════════════════════════════════════════════════════╝
```

---

## SECTION 3 — THE 6 LEVELS INSIDE EVERY POOL

Each pool has 12 people spread across 6 levels. When you survive a draw week, you move up one level.

```
  LEVEL 1  (L1)  ───── Just joined.  Payout if won: ₹2,000 net
  LEVEL 2  (L2)  ───── Survived 1 week.  Payout: ₹3,000 net
  LEVEL 3  (L3)  ───── Survived 2 weeks. Payout: ₹4,000 net
  LEVEL 4  (L4)  ───── Survived 3 weeks. Payout: ₹5,500 net  ⚠️ DANGER ZONE
  LEVEL 5  (L5)  ───── Survived 4 weeks. Payout: ₹6,500 net  🔴 EMERGENCY
  LEVEL 6  (L6)  ───── Survived 5 weeks. Payout: ₹8,000 net  🔴🔴 EXTREME

  Gross payouts before ₹500 fee:
    L1=₹2,500   L2=₹3,500   L3=₹4,500
    L4=₹6,000   L5=₹7,000   L6=₹8,500

  NOTE: In a healthy system, L5 and L6 should NEVER exist.
  If someone reaches L4, the Anti-Maturity Protocol immediately fires.
```

---

## SECTION 4 — HOW SOMEONE JOINS (Registration → Active Pool)

```
  STEP 1: Person signs up
          → Creates account
          → Generates a Deposit Token: SD0000000001 (unique code)
          → Token Type = "Deposit",  Value = ₹1,000,  Status = "Burned"
          → User Status = WAITLIST

  STEP 2: Gets a queue number
          → WL-68  (means 67 people are ahead of them)
          → This number UPDATES in real-time as people ahead enter pools

  STEP 3: Waits for enough people to accumulate
          → System needs 24 paid waitlist members before creating a new pool
          → This "24" threshold can DROP under pressure (see Section 9)

  STEP 4: Enters a Pool
          → First 12 from the waitlist (FIFO) → fill one pool
          → Status changes: WAITLIST → ACTIVE
          → Level set to: L1
          → WL queue number is "discharged" (shown as historical)
          → If this person was referred by someone → referrer gets ₹250 credited
            (Rule 39: credit happens at pool entry, NOT at registration)

  STEP 5: Plays the weekly game
          → Every week pays ₹50/day late fee if they don't pay (max ₹500 cap)
          → Draw happens Sunday midnight
          → Either WIN (exit with payout) or SURVIVE (advance one level)
```

---

## SECTION 5 — THE WEEKLY CALENDAR (7-Day Cycle)

```
  MONDAY
  ───────
  • New people join waitlist
  • All Active members' payment status reset to "Unpaid"
  • Late fee clock starts ticking: ₹50/day after due date

  TUESDAY – THURSDAY
  ──────────────────
  • Members pay their weekly installment
  • AI monitors join rate, referral ratio, velocity trends

  THURSDAY (Payment Due Date)
  ───────────────────────────
  • Unpaid members past due date → flagged "Elimination Risk"
  • Grace period opens: 48 hours to pay or lose seat

  SATURDAY 22:00 (T-2H = 2 Hours Before Draw)
  ─────────────────────────────────────────────
  • System acquires a LOCK (prevents duplicate draws)
  • Brain 5 calculates LPI (see Section 7)
  • L4 members get flagged as "SDE Required"
  • Multi-L4 pools get split up (only 1 L4 allowed per pool)
  • SDE Meta-Pool builds (collects all L4 people system-wide)
  • WeeklyDrawState written (snapshot of what will happen)
  • All of this takes up to 2 hours to complete

  SUNDAY 00:00 (T-0H = Draw Time)
  ────────────────────────────────
  • SDE Extensions run first (L5/L6 emergency exits if any exist)
  • All Active pools checked: need exactly 12 members to draw
    → Less than 12 → Pool PAUSED (SafeStop). No draw this week.
  • Draw runs for every eligible pool
  • 2 winners picked per pool (see Section 6 for HOW)
  • Winners exit, Waitlist refill happens
  • Draw guard set: "draw_completed_this_week = True"
    → Cannot draw same pool twice this week

  SUNDAY 00:05 (T+5m = Post-Draw Cleanup)
  ────────────────────────────────────────
  • "draw_completed_this_week" reset to False on all pools
  • L4/SDE flags cleared
  • System LOCK released
  • Ready for next week
```

---

## SECTION 6 — HOW THE DRAW WORKS (Smart Pairing Dual-Draw)

Every draw picks exactly **2 winners** from a pool of 12. The 2 winners always come from **different halves** of the pool (lower levels vs higher levels). This is called "Smart Pairing."

```
┌────────────────────────────────────────────────────────────────────────┐
│                    THE 7 DRAW TYPES                                    │
└────────────────────────────────────────────────────────────────────────┘

DRAW TYPE 1 — REGULAR (Normal Conditions, LPI < 14%)
─────────────────────────────────────────────────────
  Lower half: L1, L2, L3 members  →  Winner 1 picked randomly
  Upper half: L4, L5, L6 members  →  Winner 2 picked randomly
  
  If NO upper-half members exist yet (brand new pool):
    → Both winners from lower half (edge case, 2 random from L1-L3)


DRAW TYPE 2 — TYPE A EXECUTION POOL (Medium Pressure, LPI 14–24%)
──────────────────────────────────────────────────────────────────
  Lower half: L1, L2 only  →  Winner 1
  Upper half: L3, L4 only  →  Winner 2
  
  Why different? Because L3 people are getting older. Pulling them
  as "upper tier winners" gets them out earlier, reducing pressure.


DRAW TYPE 3 — SDE (Sequential Dynamic Eviction, LPI ≥ 25% or any L4 exists)
─────────────────────────────────────────────────────────────────────────────
  This is NOT a normal draw. It is a forced exit for the oldest people.
  
  Upper winner: ALWAYS L4 (the person in danger zone)
  Lower winner: L1 or L2 (the newest person)
  
  Exception: If LPI > 50%, L3 is also allowed as the lower winner.
  
  Why? L4 people cost the most (₹5,500). If they don't exit now,
  they'll become L5 (₹6,500) or L6 (₹8,000) — losing more money.
  SDE guarantees L4 exits every single week.


DRAW TYPE 4 — TYPE B FALLBACK (When No L1/L2 Left)
────────────────────────────────────────────────────
  Lower half: L3 only  →  Winner 1
  Upper half: L4 only  →  Winner 2
  
  Happens when the waitlist is empty and pool only has L3/L4 people.


DRAW TYPE 5 — SDE EXTENSION II (Emergency L5 Exit)
────────────────────────────────────────────────────
  Triggered: When ANY member reaches L5 (should never happen normally)
  
  Upper winner: EXACTLY L5 (force them out NOW)
  Lower winner: Anyone from L1–L4
  
  Why urgency? If you wait 1 more week, L5 becomes L6:
    Cost now (L5+L5): ₹6,500 × 2 = ₹13,000
    Cost later (L5+L6): ₹6,500 + ₹8,000 = ₹14,500  → ₹1,500 more wasted
  Always cheaper to exit L5 immediately.


DRAW TYPE 6 — SDE EXTENSION III (Extreme L6 Exit)
────────────────────────────────────────────────────
  Triggered: When ANY member reaches L6 (admin override edge case only)
  
  Upper winner: EXACTLY L6 (emergency exit)
  Lower winner: Anyone from L1–L5
  
  This should never happen in a properly managed system.
  If it does, it means SDE failed 2 consecutive weeks.


DRAW TYPE 7 — ACCELERATED DISSOLUTION (Pool Collapse Mode)
───────────────────────────────────────────────────────────
  Triggered: When 60% or more of a pool's 12 members are L4+
  
  BOTH Winner 1 AND Winner 2 come from L4+ (not split between tiers)
  
  After draw, if pool drops below 8 members → pool DISSOLVED
  → Remaining members redistributed to other pools
  → A brand new "relief pool" created from the waitlist simultaneously
  
  Why? A pool where 7 of 12 people are at L4 is too expensive to
  sustain. Getting all of them out fast is cheaper than keeping the
  pool running for 3–4 more weeks.
```

---

## SECTION 7 — LPI (THE SYSTEM'S HEALTH METER)

LPI = **Level Pressure Index**. It's the single number that tells the system how "stressed" it is.

```
                    ┌─────────────────────────────────┐
                    │          LPI FORMULA             │
                    │                                  │
                    │   (L3 + L4 + L5 + L6) members   │
                    │   ─────────────────────────────  │
                    │     Total Active Members         │
                    │              × 100               │
                    │                                  │
                    │   Result: a % from 0 to 100      │
                    └─────────────────────────────────┘

  WHAT EACH LPI RANGE MEANS:

  LPI < 14%   ──── 🟢 GREEN  — Healthy. Run regular draws.
              ────────────────────────────────────────────
              Most members are still at L1/L2 (fresh, cheap to pay out).
              System is young and safe.

  LPI 14–24%  ──── 🟡 AMBER  — Caution. Switch to Type A pools.
              ────────────────────────────────────────────
              More L3/L4 people than ideal. Time to start pushing
              older members out faster via Type A draws.

  LPI ≥ 25%   ──── 🟠 ORANGE — Stress. Activate SDE proactively.
              ────────────────────────────────────────────
              Too many people at dangerous levels. Even if no L4 exists,
              SDE mode activates to drain the backlog before it gets worse.

  LPI > 50%   ──── 🔴 RED    — L3 exception kicks in.
              ────────────────────────────────────────────
              So many mid-high level members that L3 is now allowed to
              be the "lower tier" SDE winner (normally only L1/L2).

  ANY L4 EXISTS  — HARD OVERRIDE. SDE activates immediately.
              ────────────────────────────────────────────
              Does not matter what the LPI% says. Even 1 L4 person
              anywhere in the system = SDE mode for that pool.
```

---

## SECTION 8 — THE SDE ENGINE (Anti-Maturity Protocol)

SDE = **Sequential Dynamic Eviction**. It's the most important safety mechanism. It prevents the system from getting "old and expensive."

```
  PROBLEM IT SOLVES:
  ─────────────────
  Without SDE, a person could sit at L3 forever, survive draw after draw,
  eventually reach L4, L5, L6 — and cost ₹8,000 when they finally exit.
  That's 8× more expensive than an L1 winner (₹2,000).

  SDE GUARANTEE:
  ─────────────
  No matter what, at least 1 L4 person EXITS every single week.
  This hard guarantee prevents the pool from aging.

  HOW SDE PICKS WHO EXITS (AI Weighting):
  ─────────────────────────────────────────
  For the LOWER tier (L1/L2 winner), the system doesn't just pick randomly.
  It calculates a "weight score" for each eligible person:

  ┌─────────────────────────────────────────────────────────────┐
  │  Weight = (Weeks in Pool × 30%)                            │
  │         + (Total Deposited ÷ 1000 × 25%)                   │
  │         + (Pauses Experienced × 20%)                       │
  │         + (Organic Join Score × 15%)                       │
  │         + (Random Noise × 10%)                             │
  │                                                             │
  │  Organic Join Score:                                       │
  │    Joined directly (no referral) = 1.0                     │
  │    Joined via referral code       = 0.3                    │
  │                                                             │
  │  Everyone gets a minimum floor of 0.05 (nobody excluded)   │
  └─────────────────────────────────────────────────────────────┘

  WHY THESE WEIGHTS?
  People who waited longer, deposited more, experienced pauses,
  and joined organically (not just from referral hype) get a
  HIGHER chance to win. It rewards loyalty and genuine participation.

  WHAT HAPPENS WHEN L1/L2 SUPPLY IS TOO LOW FOR SDE?
  ─────────────────────────────────────────────────────
  Rule: Each L4 person needs at least 2 L1/L2 candidates as "lower pool"
  
  If not enough L1/L2 exist:
    → Emergency: Pull up to 2 people from the waitlist immediately
    → This is the SDE Emergency WL Promotion
  
  If still not enough:
    → Admin Override Required flag is set
    → Admin manually approves or system auto-selects after 2 hours

  MULTI-L4 POOL PROBLEM (Fixed):
  ─────────────────────────────
  If one pool accidentally has 2 or more L4 members:
    → System detects this at T-2H
    → Moves excess L4 people to OTHER pools that have zero L4 members
    → This is the "Multi-L4 Redistribution" step
    → Keeps exactly 1 L4 per pool (maximum 1 SDE draw per pool per week)

  SDE SESSION LIMIT:
  ─────────────────
  Maximum 6 pools can be processed per SDE session.
  If more than 6 pools have L4 members:
    → Multiple SDE sessions run back-to-back
    → Sessions needed = CEILING(L4 count ÷ 6)
```

---

## SECTION 9 — THE 5 BRAINS (AI System)

The system has 5 AI Brains that work together to manage the pool economy.

```
╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 1 — HYDRAULIC ENGINE                           ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Manages the 3-layer (Waitlist → Active → Exit) flow
  
  It calculates:
    • How many vacancies exist in active pools
    • How many new pools need to be created
    • Whether pools should be condensed (merged) when waitlist is empty
  
  Output: Drives all 3 Phases of the Waitlist Refill Engine (see Section 10)


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 2 — MOMENTUM TRACKER (Tri-Velocity)            ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Measures how fast people are joining vs how fast 
                the system is paying them out.

  It calculates 3 velocity signals and BLENDS them:

  ┌─────────────────────────────────────────────────────────────────────┐
  │  BLENDED VELOCITY = (Slow14d × 50%) + (Fast48h × 30%) + (Fwd × 20%)│
  │                                                                     │
  │  Slow 14-Day SMA (50%):   Average new users per week, last 14 days  │
  │  Fast 48-Hour (30%):      New users in last 48 hours × 7 (weekly)   │
  │  Forward Signal (20%):    From Brain 5 — projected new L3 next week  │
  └─────────────────────────────────────────────────────────────────────┘

  CLIFF DETECTION (Emergency Override):
    If today's rate < 3 days ago rate × 50% → VELOCITY CLIFF
    → Forces system to "NEUTRAL" mode regardless of other signals
    → Prevents over-optimistic decisions during sudden drops

  BURN RATE (Weekly Drain):
    = Active Pools × 2  (exactly 2 winners exit per pool per week)
    Example: 10 pools → burn rate = 20 people/week leaving


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 3 — QUALITY RADAR (RDR)                        ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Distinguishes REAL organic growth from referral-hype bubbles

  ┌─────────────────────────────────────────────────────────────────────┐
  │  RDR = (People who joined via referral link ÷ Total joins) × 100   │
  │  Measured over last 7 days                                          │
  └─────────────────────────────────────────────────────────────────────┘

  RDR < 30%   → Genuine organic growth (healthy, sustainable)
  RDR 30–70%  → Mixed traffic (moderate, watch carefully)
  RDR > 70%   → Referral hype bubble (dangerous, temporary spike)


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 4 — CONDENSATION ENGINE                        ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Emergency pool merger when waitlist runs completely empty

  If paid waitlist = 0 AND some pools have < 12 members:
    → Take members from the NEWEST full pools
    → Move them into the OLDEST under-capacity pools
    → Until all pools are full
    → The emptied newest pool is dissolved
  
  IMMUNITY RULE: Pools with L4 flagged members (SDE-protected) are
  NEVER touched by condensation. They are immune.


╔══════════════════════════════════════════════════════════════════════════╗
║                    BRAIN 5 — LPI ENGINE (Level Pressure Index)          ║
╚══════════════════════════════════════════════════════════════════════════╝

  What it does: Calculates LPI (see Section 7) and feeds the Forward
               Signal into Brain 2's tri-velocity blend

  Forward Signal Formula:
  ┌──────────────────────────────────────────────────────────────────┐
  │  Forward Signal = Current L2 Count × Survival Rate              │
  │                                                                  │
  │  Survival Rate:                                                  │
  │    Theoretical: 10/12 = 0.833 (10 survive out of 12 each week)  │
  │    Actual: adjusted downward if pools have been pausing          │
  │                                                                  │
  │  Meaning: "How many NEW L3 members will exist next week?"        │
  │  This gives Brain 2 a FORWARD-LOOKING view, not just history.    │
  └──────────────────────────────────────────────────────────────────┘
```

---

## SECTION 10 — THE AI SCENARIO MATRIX

Brain 2 + 3 combined produce one of 6 "Scenarios." Each scenario changes the Reserve Multiplier, which controls how aggressively the system creates new pools.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AI SCENARIO DECISION MATRIX                         │
├────────────────────────┬──────────────┬────────────────────────────────────┤
│       SCENARIO         │  MULTIPLIER  │         WHEN IT TRIGGERS           │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 🌊 SUSTAINABLE_WAVE    │    × 0.50    │ Growth > Burn AND RDR < 30%        │
│  (Most Aggressive)     │              │ Real organic growth. Very safe.    │
│                        │              │ Reserve requirement cut by half.   │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 💥 BOOM_GOLDEN_CROSS   │    × 0.75    │ Growth > Burn AND RDR 30–70%       │
│                        │              │ Good growth, mixed traffic.        │
│                        │              │ Slightly relaxed reserves.         │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ ⚡ VELOCITY_CLIFF       │    × 1.00    │ Growth > Burn BUT cliff detected   │
│  (Override)            │              │ Sudden 50%+ drop in 3 days.        │
│                        │              │ System halts optimism, stays safe. │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ ⚠️  FLASH_FLOOD         │    × 1.50    │ Growth > Burn AND RDR > 70%        │
│                        │              │ Referral hype spike. Dangerous.    │
│                        │              │ Extra large reserve held back.     │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 🔴 DRY_PHASE           │    × 2.00    │ Growth < Burn (any RDR)            │
│  (Liquidity Protection)│              │ Paying out MORE than coming in.    │
│                        │              │ Double reserve. No new pools.      │
├────────────────────────┼──────────────┼────────────────────────────────────┤
│ 🆘 REFERRAL_LIFELINE   │    × 2.00    │ Growth < Burn AND RDR > 60%        │
│  (Liquidity Protection)│              │ Organic traffic DEAD. Only bots.   │
│                        │              │ Maximum protection mode.           │
└────────────────────────┴──────────────┴────────────────────────────────────┘

HOW THE MULTIPLIER IS USED:
─────────────────────────────
  Dynamic Reserve Needed = Active Pools × 12 × Multiplier

  Example: 5 pools, SUSTAINABLE_WAVE (×0.50):
    Reserve = 5 × 12 × 0.50 = 30 people must stay in waitlist as buffer

  Remaining waitlist (after reserve subtracted) can form new pools.
  So lower multiplier = more pools can be created = more winners paid out.
```

---

## SECTION 11 — THE WAITLIST REFILL ENGINE (3-Phase System)

After every draw, empty seats need to be filled. This happens in exactly 3 phases, in order.

```
══════════════════════════════════════════════
PHASE 1 — FILL EXISTING POOLS (Double-FIFO)
══════════════════════════════════════════════

  Goal: Bring all under-capacity active pools back to 12 members.

  Pool Priority:  Oldest pool created → filled FIRST (FIFO by creation date)
  Person Priority: Longest waiting person → moved FIRST (FIFO by join date)

  Steps (all done in bulk, not one-by-one — very fast):
    1. Count vacancies in every pool (one database query)
    2. Fetch enough waiting people to fill all vacancies (one query)
    3. Assign people to pools in memory (Python loop)
    4. Update all assignments at once (one update per pool, not 100 updates)
    5. Paused pools that are now full → reactivated to "Active"

  After this phase: every existing pool is either full (12) or still
  short if the waitlist ran out.


══════════════════════════════════════════════
PHASE 2 — CREATE NEW POOLS (Auto-Scale)
══════════════════════════════════════════════

  Goal: If enough extra people are still waiting, create new pools.

  Trigger: After filling all existing pools, if waitlist still has
           enough people for at least one new pool.

  Adaptive Threshold Formula:
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Effective Threshold = MAX(12, 24 × (1 − Pressure Factor))          │
  │                                                                      │
  │  Pressure Factor = MIN(0.50, LPI ÷ 100)                            │
  │                                                                      │
  │  Meaning:                                                            │
  │    LPI 0%  → Need 24 people to trigger new pool (normal)            │
  │    LPI 25% → Need 18 people to trigger new pool (reduced pressure)  │
  │    LPI 50% → Need 12 people to trigger new pool (minimum floor)     │
  │                                                                      │
  │  Also: AI Reserve is subtracted first.                              │
  │    Available for new pools = Waitlist - (Pools × 12 × Multiplier)  │
  └──────────────────────────────────────────────────────────────────────┘

  Steps:
    1. Calculate how many new pools can be made
    2. Create all pools at once (one bulk database insert)
    3. Move 12 people into each new pool (one update per pool)
    4. Rule 39: credit ₹250 to each new member's referrer (if referred)


══════════════════════════════════════════════
PHASE 3 — CONDENSATION (Emergency Merge)
══════════════════════════════════════════════

  Goal: When there's NO waitlist, consolidate half-empty pools.

  Only fires if: Paid waitlist = 0 AND some pools still have < 12 members.

  Algorithm:
    → Take members from the NEWEST full pools ("donors")
    → Move them into the OLDEST under-capacity pools ("receivers")
    → Keep their level, payment status, join date — EXACTLY unchanged
    → The emptied new pool is dissolved
    → SDE-protected pools are IMMUNE (never touched)

  Example:
    Pool A (oldest): 10 members  ← receiver
    Pool Z (newest): 12 members  ← donor
    → Move 2 from Pool Z → Pool A
    → Pool A now has 12 (draws again)
    → Pool Z now has 10 (if further condensation needed, continues)
```

---

## SECTION 12 — THE MONEY FLOW (Financial System)

```
  MONEY IN:
  ─────────
  Every new person pays ₹1,000
  This burns a DEP (Deposit) Token: code SD0000000001
  The ₹1,000 stays in the system as float (working capital)

  LATE FEES:
  ──────────
  ₹50 per day after payment due date
  Maximum cap: ₹500 (no matter how many days late)
  Goes into system as additional float

  GRACE PERIOD FEE:
  ─────────────────
  ₹500 extra to save your seat during the 48-hour grace window
  Paid on top of ₹1,000 weekly installment + any accrued late fees

  MONEY OUT (PAYOUTS):
  ─────────────────────
  Level 1 winner → receives ₹2,000 net  (gross ₹2,500 – fee ₹500)
  Level 2 winner → receives ₹3,000 net  (gross ₹3,500 – fee ₹500)
  Level 3 winner → receives ₹4,000 net  (gross ₹4,500 – fee ₹500)
  Level 4 winner → receives ₹5,500 net  (gross ₹6,000 – fee ₹500)
  Level 5 winner → receives ₹6,500 net  (gross ₹7,000 – fee ₹500)
  Level 6 winner → receives ₹8,000 net  (gross ₹8,500 – fee ₹500)

  Each payout creates a Withdraw Token: WIT-XXXXXX (cryptographically unique)

  REFERRAL PAYOUTS:
  ─────────────────
  ₹250 credited when a referred person ENTERS an active pool
  (NOT when they register — must actually play)
  Accumulates in referrer's account balance
  Redeemable via payout request

  WHAT THE ₹500 FEE COVERS:
  ──────────────────────────
  Operational cost, admin, platform maintenance
  Deducted from every winner's gross payout
```

---

## SECTION 13 — PAYMENT COMPLIANCE SYSTEM (A/B/C Model)

```
  "A" = Elimination Percentage
  ────────────────────────────
  What % of non-payers actually get eliminated.
  Default: 80% (not 100% — some leniency built in)
  Configurable by admin.

  "B" = Late Fee Rate
  ───────────────────
  How much per day: ₹50/day
  Maximum cap: ₹500 total (10 days max accumulation)

  "C" = Grace Saver Percentage
  ─────────────────────────────
  What % of at-risk members successfully save their seat
  during the grace period.
  Default: 15% (most people do lose their seat — this is intentional)

  A, B, and C are CIRCULAR — they affect each other:
    More strict A (higher elimination%) → more pressure on B (late fees rise)
    More lenient C (more grace saves) → reduces effective A
    Higher B (higher late fees) → incentivizes faster payment, reduces need for A

  PAYMENT TIMELINE:
  ─────────────────
  Day 0 (Monday):   Payment window opens. Status = Unpaid.
  Day 4 (Thursday): Due date. Unpaid = Elimination Risk flagged.
  Day 4–6 (Thu-Sat): GRACE PERIOD (48 hours).
                      Pay ₹500 grace fee + accumulated late fee to save seat.
  Day 7 (Saturday 22:00): Grace window closes.
  Day 7 (Sunday 00:00): All still-unpaid + grace-unsaved members → ELIMINATED.
```

---

## SECTION 14 — SECURITY SAFEGUARDS

```
  DRAW LOCK (System Lock):
  ────────────────────────
  • Only ONE draw can run at a time system-wide
  • Lock acquired at Saturday 22:00
  • Lock released at Sunday 00:05 (after cleanup)
  • If lock already exists → error raised, admin notified
  • Total lock window: 2 hours prep + draw + 10 minutes cleanup = 130 minutes

  DOUBLE-DRAW GUARD:
  ──────────────────
  • "draw_completed_this_week" flag on each pool
  • If True → draw refused ("already drew this week")
  • Reset by post_draw_cleanup at 00:05
  • Prevents any pool from drawing twice in one week

  CRYPTOGRAPHIC DRAW RANDOMNESS:
  ────────────────────────────────
  • Winners are picked using os.urandom (hardware random from OS)
  • NOT using Python's standard random (which is predictable)
  • Token codes use same os.urandom source (secrets module)
  • All token codes checked for uniqueness before issuing

  ADMIN PASSWORD REQUIRED FOR:
  ──────────────────────────────
  • Deleting tokens
  • Deleting users
  • Updating elimination settings
  • Confirming grace period seat saves
  • Executing manual elimination

  SAFE-STOP (Pool Pausing):
  ─────────────────────────
  • Pool with < 12 members → draw REFUSED automatically
  • Pool status set to "Paused_Awaiting_Members"
  • No override possible — 12 members is a hard requirement
  • Paused pools get filled first in Phase 1 refill
```

---

## SECTION 15 — COMPLETE END-TO-END FLOW (From Zero to Winner)

```
  ┌───────────────────────────────────────────────────────────────────────┐
  │  PERSON'S JOURNEY: Day 1 to Exit                                     │
  └───────────────────────────────────────────────────────────────────────┘

  DAY 1:
  User registers → pays ₹1,000 → DEP token burned
  Status = WAITLIST, Queue = WL-68
  
  WEEK 1 (if enough people in queue):
  24+ paid waitlist members accumulate
  AI checks: Reserve needed = Pools × 12 × Multiplier
  If remaining waitlist ≥ Adaptive Threshold → New pool created
  Person moves from Waitlist → Pool A at Level 1
  WL-68 → discharged
  If they were referred → their referrer gets ₹250 credited
  
  WEEK 1 DRAW (if in pool, pool has 12):
  LPI calculated: say 5% (healthy)
  Draw type: REGULAR
  Lower tier: L1 people  |  Upper tier: (none yet — new pool)
  Edge case: 2 random winners from L1 pool
  
  IF THEY WIN (Week 1):
    → Level 1 winner → ₹2,000 net payout
    → WIT-XXXXXX token generated
    → Status: Eliminated_Won
    → Exit. Done.
  
  IF THEY SURVIVE (Week 1):
    → Level advances: L1 → L2
    → Weekly payment status reset: Paid → Unpaid for next week
    → Pool refilled: next waitlist person takes the 2 winner spots
  
  WEEK 2 DRAW (if survived):
  They're now L2.
  LPI might be 15% now (more people have survived, getting older)
  Draw type: TYPE A (L1-L2 lower / L3-L4 upper)
  They are in the "lower tier" — random chance to be Winner 1
  
  IF THEY WIN (Week 2):
    → Level 2 winner → ₹3,000 net payout → Exit.
  
  IF THEY SURVIVE (Week 2):
    → Level advances: L2 → L3
  
  WEEK 3 DRAW (if survived):
  They're now L3. LPI might be 26% (getting stressed)
  Draw type: SDE (LPI ≥ 25%)
  → L4 members (if any) are guaranteed upper winners
  → L1/L2 compete for lower tier using AI weights
  
  IF THEY WIN (Week 3 as L3):
    Only possible if LPI > 50% (L3 exception rule activated)
    → ₹4,000 net payout → Exit.
  
  IF THEY SURVIVE (Week 3):
    → Level advances: L3 → L4
    → ⚠️ IMMEDIATE FLAG: sde_required = True (atomically, same DB write)
    → Their pool gets flagged: contains_flagged_l4 = True
  
  WEEK 4 (as L4 person — now in SDE mode):
  Saturday 22:00 T-2H:
    → Brain 5 flags them (catch-up sweep)
    → If their pool has multiple L4 people → some moved to other pools
    → SDE Meta-Pool built — they are the "upper tier" candidate
    → Draw type: SDE
  
  SUNDAY DRAW:
    → L4 (them) = guaranteed upper winner if SDE runs
    → They EXIT at L4 → ₹5,500 net payout
    → WIT-XXXXXX issued
    → Status: Eliminated_Won
    → Journey ends. Total time: ~4 weeks.

  ┌──────────────────────────────────────────────────────────────────────┐
  │  WHAT PREVENTS THEM REACHING L5 or L6?                              │
  │                                                                      │
  │  The SDE hard guarantee: L4 people ALWAYS exit in their FIRST week  │
  │  as L4. They cannot survive to L5 unless SDE completely fails AND   │
  │  no admin override happens AND emergency extension also fails.       │
  │  This triple-safety makes L5/L6 essentially impossible in practice. │
  └──────────────────────────────────────────────────────────────────────┘
```

---

## SECTION 16 — FULL SYSTEM MAP (Everything Connected)

```
  NEW USERS ──────────────────────────────────────────────────────────────────►
                                                                              │
  REGISTRATION                                                                │
  ├── Pay ₹1,000 → DEP Token burned (SD0000000001)                           │
  ├── Status = WAITLIST, Queue position = WL-XX                              │
  └── Referred by someone? → Referrer gets ₹250 when THIS person enters pool │
                                                                              │
  BRAIN 2 monitors join rate:                                                 │
  Blended = (14d-SMA × 50%) + (48h-EMA × 30%) + (Brain5-Forward × 20%)      │
                         │                                                    │
                         ▼                                                    │
  BRAIN 3 checks quality: RDR = referred% of all joins last 7 days           │
                         │                                                    │
                         ▼                                                    │
  SCENARIO DECIDED (one of 6) → MULTIPLIER chosen                            │
                         │                                                    │
                         ▼                                                    │
  PHASE 2 POOL CREATION: Available WL = Total WL − (Pools × 12 × Multiplier)│
       If Available ≥ Adaptive Threshold (12–24) → Create new pool           │
                         │                                                    │
                         ▼                                                    │
  ┌───────────────────────────────────────────────────────────────────────┐  │
  │                        POOL (12 MEMBERS)                              │◄─┘
  │   L1 ─ L1 ─ L1 ─ L1                                                  │
  │   L2 ─ L2 ─ L2                                                        │
  │   L3 ─ L3                                                             │
  │   L4                    ← if ANY L4: SDE fires                        │
  │   L5  ← should not exist. Ext-II fires if it does.                   │
  │   L6  ← should never exist. Ext-III fires if it does.                │
  └───────────────────────────────────────────────────────────────────────┘
                         │
  EVERY SATURDAY 22:00:  │
  BRAIN 5 calculates LPI: (L3+L4+L5+L6) ÷ Total Active × 100
                         │
       ┌─────────────────┼─────────────────────────────┐
       │                 │                             │
    LPI < 14%        LPI 14–24%                  LPI ≥ 25%
       │                 │                        or L4 exists
       ▼                 ▼                             │
   REGULAR          TYPE A DRAW                        ▼
   L1-L3 low        L1-L2 low                       SDE DRAW
   L4-L6 high       L3-L4 high                      L4 high (forced)
                                                     L1-L2 low (AI-weighted)
                         │
  EVERY SUNDAY 00:00     │
  DRAW EXECUTES:         │
  1. SDE Ext-II/III run first (L5/L6 emergency)
  2. Safety check: pool has exactly 12? If not → PAUSE (SafeStop)
  3. Check draw_completed_this_week = True? → SKIP (double-draw guard)
  4. Run Smart Pairing Dual-Draw → 2 winners per pool
  5. Winners get WIT-XXXXXX payout token
  6. Winners exit → Status: Eliminated_Won
  7. Surviving 10 members advance +1 level
  8. L3→L4 advance? → sde_required=True set ATOMICALLY
  9. Pool refill (Phases 1+2+3 as needed from waitlist)
  10. Rule 39: ₹250 credited to referrers of newly active members
                         │
  EVERY SUNDAY 00:05     │
  CLEANUP:               │
  1. draw_completed_this_week → False (all pools)
  2. SDE flags cleared
  3. System LOCK released
  4. Next week begins
```

---

## SECTION 17 — WHAT CAN GO WRONG AND HOW IT'S HANDLED

```
  PROBLEM: Pool has < 12 members at draw time
  SOLUTION: SafeStop — pool automatically PAUSED. No draw. Gets filled
            first in Phase 1 refill next time anyone joins.

  PROBLEM: System lock already held (crash from last week)
  SOLUTION: T-2H preparation detects stale lock → admin notified → 
            auto-clear after timeout. Simulation: lock deleted before retry.

  PROBLEM: Two pools both have the same L4 person (shouldn't happen but...)
  SOLUTION: Multi-L4 redistribution at T-2H moves excess L4 people to
            different pools. Exactly 1 L4 per pool max.

  PROBLEM: Not enough L1/L2 people for SDE lower tier
  SOLUTION: Emergency Waitlist Promotion — pull up to 2 waitlist people
            immediately (mid-week, outside normal refill cycle).

  PROBLEM: Someone reaches L5 (SDE failed somehow)
  SOLUTION: SDE Extension II fires FIRST at Sunday 00:00 (before all other draws)
            Forces L5 exit immediately. Costs ₹13,000 total (L5+L5 dual draw).
            Much cheaper than waiting: L5+L6 = ₹14,500 → saved ₹1,500.

  PROBLEM: Someone reaches L6 (SDE + Ext-II both failed — extreme case)
  SOLUTION: SDE Extension III — L6 forced exit. Costs ₹16,000 total.
            If this happens, something went seriously wrong with administration.

  PROBLEM: Pool becomes 60%+ L4+ (7 of 12 people are old)
  SOLUTION: Accelerated Dissolution — BOTH winners from L4+, not normal split.
            Pool rapidly drained. New relief pool created from waitlist simultaneously.
            Pool dissolved when it drops below 8 members.

  PROBLEM: Waitlist completely empty, some pools still not full
  SOLUTION: Brain 4 Condensation — merge newest pools into oldest pools.
            Fewer but fully-staffed pools is better than many half-empty ones.

  PROBLEM: Join rate suddenly drops 50%+ in 3 days
  SOLUTION: Brain 2 Cliff Detection — scenario forced to VELOCITY_CLIFF (neutral 1.0×).
            System doesn't over-confidently maintain aggressive pool creation.
```

---

## SECTION 18 — THE REFERRAL SYSTEM (Complete)

```
  How referrals work:
  ────────────────────
  1. Person A shares their referral code
  2. Person B registers using Person A's code
  3. Person B's record: referred_by_user_id = Person A's ID

  WHEN IS THE ₹250 PAID? (Rule 39 — Critical)
  ─────────────────────────────────────────────
  NOT at registration (too easy to game — register 100 fake accounts)
  ONLY when Person B actually enters an active pool (pays ₹1,000 and joins)

  Paths that trigger the ₹250 credit:
    ✓ Path 1: Phase 1 refill after a draw (normal waitlist → pool movement)
    ✓ Path 2: Phase 2 auto-scale (new pool created from waitlist)
    ✓ Path 3: Admin vacancy fill (manual admin operation)

  The ₹250 accumulates in Person A's account balance
  Person A requests payout separately via /users/request-referral-payout

  HOW BRAIN 3 USES THIS DATA:
  ────────────────────────────
  RDR = (people who joined via referral ÷ total joins) × 100
  This feeds into the scenario decision:
    High RDR = volatile hype = more conservative AI response
    Low RDR = organic = more aggressive pool creation
```

---

```
══════════════════════════════════════════════════════════════
  SUMMARY: THE 5 RULES THAT GOVERN EVERYTHING

  RULE 1: 12 members exactly — no more, no less, per pool
  RULE 2: 2 winners per pool per week — always, always, always
  RULE 3: L4 ALWAYS exits via SDE — the hard guarantee
  RULE 4: FIFO everywhere — first joined = first served
  RULE 5: ₹250 referral only at pool entry, never at registration
══════════════════════════════════════════════════════════════
```

---

That is the **complete system** — every formula, every rule, every safeguard, every AI brain, every flow — from the moment someone pays ₹1,000 to the moment they receive their payout token. Nothing omitted.