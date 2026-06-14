------
------

Find problematic section in Event flow: SVG observations

You say me than:>>>
T-0H: DRAW EXECUTION

1. Ext-III fires (L6 exits)

2. Ext-II fires (L5 exits)

3. SDE staged winners EXECUTE

L4 exits, WIT tokens issued>>>>>>this happening in prior to winner revealed, that is problem

4. WINNERS REVEALED

5. Regular draws: ALL pools with 12 members, not yet drawn (draw_completed=False) → ALL 12-member pools MUST draw>>>>>>this happening after to winner revealed, that is problem
------
------

every week — no skip CASE E — DEFER>>>>>this is problem in SVG observations

Only 1 L4, zero lower

Cannot dual-L4

admin_override_required=True

SDE deferred to next week>>>>>that is critical

CASE E — Zero Supply + Zero Waitlist (Lower_supply = 0 AND Waitlist = 0)>>>>>>this is share by you before, that is a right approach what do you think?

Extreme scenario. Your new design point: BOTH winners come from L4. This is more expensive (₹5,500 + ₹5,500 = ₹11,000 vs normal ₹5,500 + ₹2,000 = ₹7,500) but it is still cheaper than letting L4 survive to L5 (₹6,500) or L6 (₹8,000). L5 creation is prevented at all costs.

------
------
Suggestions below Approved:

SUGGESTION: Add CASCADE_RISK score to Weekly Report (alongside LPI). Admin sees cascade risk building week-over-week.
SUGGESTION: Weekly Report dashboard widget: "L3→L4 Pressure Forecast" — shows how many current L3 become L4 next week.
SUGGESTION: If Cascade Risk >1.5 for 3+ consecutive weeks → auto-trigger Priority L3 mode permanently until resolved.
BUG TO FIX: sde_engine.py line 806-832 — supply check only counts L1+L2, ignores L3 entirely. Must include L3 when cascade risk > 1.0.
------
------

1. **Meta Pool vacancy distribution order:** 6 remaining meta pool members fill active pool vacancies — go to oldest pools first (FIFO pool age)

2. **Cascade Risk threshold:** agree with 1.0 and 2.0 as breakpoints. 

3. **Configurable System Settings tab:** this Should be a new sidebar section "Draw Calendar" inside the existing System Settings page.

4. **Code fix order:** I have 8 confirmed bugs ready for approval (snapshot metrics, supply check, etc.). Do you want me to present them one by one for approval now
------


**then also reanalyze the previously asked that they are all satisfied or Not, need point to point report on each issue marked before that they are resolved or not, what will be the status after implmentation, each and micro level issues and suggestions you have makred, i have tried to cover for your memory refreshment below**

1. Q1: T-2H ONLY the selection/planning phase (winners stay in pool until T-0H execution)
2. Q2: AI-weighted> Oldest L4 first?>Yes can both winners come from the same pool of there are Zero L3, Zero L2, Zero L1,(if that pool has 2 L4 members), they can be from different pools if other pools have Zero L4
3. Q3: create a partial pool temporarily Later after winner eliminated it will supply the members to pool who have replacement seat vacancy; only take member which can be replaced winner i mean to say suppose there are 3 pool member 6 winner and new Meta pool manager pool 2 winner so total winner 8, so new pool should take 8 members then after winner remaining 6 member placed to older pool and new meta pool has been dissolved(NEED YOUR HIGH LEVEL THINKING ON THIS)
4. Q4: L3 Member and L4 Member are enough to pair suppose per pool 2 winner means L3 = 4  L4=5 in all active pool the there should must 5 winner for L4, then pair with L3, because if we left L3 non winner then it will cause SDE and put pressure on SYSTEM(NEED YOUR HIGH LEVEL THINKING ON THIS)
5. Q5: it is relative to Q1, all winners in database, only eliminated winner at draw time then all thing happened after T-0H and T+05 all resync, refill, pool merging etc all event
6. Q6: When LPI ≥ 25% system-wide and SDE covers all L4 pools, are non-L4 pools, if after successful SDE completion, and there are any pool left without draw and winner then regular draw trigger, its mean after SDE run the any pool untouched then it is eligible for their weekly normal regular draw
7. all active pool with 12 member full capacity must happen draw.
8. winner must reveal only on draw time T-0H
9. there are no time barring for joining of new member 24x7 new members are welcomed in system>system accept joining>DEP token burned>member take their Place in Waiting list until System decide what to do with newly joined Member: this is the simple logic for newly joined member(WL number assignment have its own logics dependent on joining date and time), Deposit amount mandatory check already filled with DEP token must during register 



DRAW DAY, DATE and TIME, DUE DAY, DATE and TIME,, T-02H, T-05M, T-00, T+05M configurable and should be in System setting tab in sider bar



Event flow(THIS IS ONLY EXAMPLE ACTUAL SHOULD BE MORE COMPLXE): Pre Draw Event: Eliminated of non Payer just after Grace Period G+05M>>>T-02H, (Resync, Refill)>T-05M>DRAW>T-00, T+05M Post draw event work Draw happen at T-00, T+05 doing working in T-00 between T+05, Resync, Refill

Understood. Stopping all solution proposals. Grounding from scratch.

Reading the strategy document completely before forming any opinions.

Now let me cross-check the code's SDE implementation against what the strategy actually describes:

Now I have a complete picture from both the strategy and the actual code. Let me now write the strategy in simple English with my honest questions.

---

# REWARD SCHEME — STRATEGY FLOW IN SIMPLE ENGLISH + MY QUESTIONS

---

## THE THREE-LAYER SYSTEM

```
NEW PEOPLE PAY ₹1,000 → WAITLIST (queue, FIFO)
                              │
              When enough people accumulate (min 12–24 depending on LPI)
                              │
                              ▼
        ACTIVE POOLS — 12 people per pool
        Every week: 2 winners exit, 10 survivors advance 1 level
        Empty 2 spots → filled from waitlist
                              │
              When someone wins the draw
                              │
                              ▼
        EXIT — winner gets WIT token (₹2,000–₹8,000 net)
        Status: Eliminated_Won. They are gone permanently.
```

---

## THE WEEKLY 7-DAY CYCLE

### MONDAY — Reset & Join
- New users can join (pay ₹1,000, enter waitlist, get WL number)
- ALL active pool members' payment status → reset to UNPAID
- Late fee clock starts

### TUESDAY–THURSDAY — Payment Window
- Members pay ₹1,000 weekly installment → status becomes Paid
- Late fee: ₹50/day accruing for unpaid members (max cap ₹500)
- Brain 2+3 monitoring join velocity and quality (RDR)

> **Question A:** The simulation injects ALL new users on Monday morning only (`inject_week` at monday_morning). But the strategy describes people joining across Monday through Thursday. Does the strategy require time-distributed injection across the week, or is Monday bulk-injection acceptable for the simulation?

### THURSDAY 23:59 — Due Date
- Unpaid members flagged: Elimination Risk
- Grace period opens: 48 hours remaining

### THURSDAY–SATURDAY 22:00 — Grace Period (48h)
- Unpaid-at-risk members can pay ₹500 grace fee + accumulated late fee to save seat
- If paid: status → Paid, seat saved (Type C in A/B/C model)
- If not paid by Saturday 22:00: seat is forfeited at draw time

---

## SATURDAY 22:00 — T-2H (DRAW PREPARATION — The Heart of the System)

Six things happen in sequence:

**Step 1:** System acquires the DRAW LOCK — only one draw per week, prevents duplicates

**Step 2:** Brain 5 calculates LPI
```
LPI = (L3 + L4 + L5 + L6 active members) ÷ Total Active Members × 100
```

**Step 3:** All L4 members get flagged (`sde_required = True`)

**Step 4:** Multi-L4 redistribution
- If any pool has 2+ L4 members → move excess L4 to pools that have ZERO L4 members
- Goal: maximum 1 L4 per pool

> **Question B:** What happens when ALL pools have L4 members and there are NO zero-L4 pools left to receive excess L4 members? Is this scenario handled differently? The strategy says "moves excess L4 to pools that have zero L4" but doesn't describe total saturation. In the simulation CSV week 17+, we can see 46 L4 members across 14 pools (3+ per pool average). How should redistribution work here?

**Step 5:** SDE Meta-Pool builds and runs — the core anti-maturity engine

---

## THE SDE META-POOL (CORRECTED UNDERSTANDING — user's correction)

### What SDE Is
SDE = Sequential Dynamic Eviction. It guarantees EVERY L4 member exits in their first week as L4. No L4 person should ever reach L5.

### How the Meta-Pool Works (from user's correction)

**Collect all L4 members system-wide** (they are now in their actual pools, 1 per pool after redistribution):

```
System-wide L4 count = 3 (example)
Upper Tier Pool: [L4_member_A (Pool-1), L4_member_B (Pool-2), L4_member_C (Pool-3)]
```

**Build lower-tier candidate pool.** The rule for how many lower-tier candidates are needed:
- Normal (LPI ≤ 50%): need L1×6 OR L1/L2=6 (2 per L4 member minimum)
- High pressure (LPI > 50%): need L1/L2/L3=6 (L3 also qualifies as lower-tier)
- With L4=3: need 6 lower-tier candidates total (2 per each L4 member)

> **Question C:** Are these 6 lower-tier candidates pulled from EACH L4 MEMBER'S OWN POOL? Or are they pulled system-wide from ANY pool? Example: If L4_member_A is in Pool-1 which has only 1 L1 member, but Pool-2 has 5 L1 members, can Pool-2's L1 members serve as lower-tier candidates for Pool-1's L4 draw?

**Run SDE draws (meta-pool sessions, max 6 L4 per session):**

```
With L4=3: ONE session, THREE sub-draws (one per L4):

  Meta Pool-1:  L4_member_A (upper winner) + 1 lower-tier (AI-weighted) = 2 EXIT
  Meta Pool-2:  L4_member_B (upper winner) + 1 lower-tier (AI-weighted) = 2 EXIT
  Meta Pool-3:  L4_member_C (upper winner) + 1 lower-tier (AI-weighted) = 2 EXIT
  
  Total: 6 people exit (3 L4 + 3 lower-tier)
  3 pools now have 2 vacancies each (10 members left in each)
```

**Redistribute to active pools (vacancies filled from waitlist):**
- 6 vacancies across 3 pools
- 6 waitlist members (FIFO) move into those pools as L1
- The waitlist members are "redistributed to active pools" — THIS is what the user means by redistribution, not the winners being redistributed

> **Question D:** Is this waitlist refill (filling the 6 SDE vacancies) done IMMEDIATELY at T-2H as part of SDE? Or does it happen later at T-0H via Phase 1 refill? Because if refill happens at T-0H, then at draw time (also T-0H), those pools will have 10 members (not 12) and will be paused by the candidate loop. This seems wrong.

**SDE Emergency WL Promotion:**
- If a pool's lower-tier candidates (L1/L2) are too few, pull up to 2 people from waitlist into the pool immediately as emergency lower-tier candidates
- This ensures the L4 exit can always happen even if the pool is depleted of fresh members

> **Question E:** The code's supply check (`run_sde_meta_pool` lines 806–832) only counts L1/L2 members across the batch's pools. When LPI > 50% and L3 IS allowed as lower-tier, the supply check still only counts L1/L2. This means the system marks L4 members as overflow (cannot draw) even when there are plenty of L3 candidates. Is this the intended behavior, or is L3 supposed to count toward the supply threshold when LPI > 50%?

---

## SUNDAY 00:00 — T-0H (THE DRAW)

**Step 1: SDE Extensions (L5/L6 emergency — runs FIRST before everything else)**
- If ANY member reached L5: SDE Ext-II fires immediately
  - Upper winner: the L5 member (forced exit — costs ₹6,500 now vs ₹8,000 if they reach L6)
  - Lower winner: anyone from L1–L4 in that pool
- If ANY member reached L6: SDE Ext-III fires
  - Upper winner: the L6 member (forced exit — extreme case)
  - Lower winner: anyone from L1–L5

> **Question F:** If L5 = 34 members exist (as in the simulation week 17+), Ext-II fires 34 times. Each Ext-II draw needs a lower-tier candidate (L1–L4) from that pool. After SDE meta-pool already ran at T-2H and drew from most pools, many pools now have only 10 members (lower-tier depleted). Does Ext-II use the Emergency WL Promotion (pull from waitlist) as a fallback? The strategy says it should. The code does attempt this, BUT only if the waitlist itself is non-empty.

> **Question G:** The user said "i can see there are always members available in waitlist." If this is true, then Ext-II SHOULD succeed every time (waitlist provides emergency lower-tier). Why does the simulation show L5 = 34 members persisting for 30 weeks? Something is preventing Ext-II from executing even though the waitlist has members.

**Step 2: Candidate loop**
- For every Active or Paused pool: count actual active members
- If actual == 12 AND Active → eligible for draw
- If actual == 12 AND Paused → restore to Active → eligible (fix c46feda)
- If actual < 12 AND Active → PAUSE (SafeStop — draw-protection)
- If actual < 12 AND Paused → skip (Phase 1 will fill later)

> **Question H:** If SDE drew a pool at T-2H (pool now has 10 members), and the waitlist refill has NOT yet run (Question D above), the candidate loop sees 10 members → PAUSES the pool → NOT eligible for regular draw. Is this expected? The pool already drew via SDE so it shouldn't draw again anyway (draw_completed_this_week=True). But it gets PAUSED unnecessarily, adding pauses_experienced count and showing the pool as Paused in that week's snapshot. Is pausing these SDE-already-drawn pools intentional?

**Step 3: Draw type for eligible pools**
- LPI < 14% → Regular draw (L1/L2/L3 lower tier, L4/L5/L6 upper tier)
- LPI 14–24% → Type A (L1/L2 lower, L3/L4 upper)
- LPI ≥ 25% or any L4 exists → SDE mode (but L4 pools already drew at T-2H, so only pools with no L4 are here)

> **Question I:** After SDE meta-pool ran at T-2H for ALL pools that had L4, which pools are left for the T-0H regular draw? Only pools that had NO L4 and LPI < 25%? If LPI ≥ 25% system-wide (which it is in weeks 6–47 at 22–62%), does that mean EVERY pool switches to SDE mode, and since SDE already ran for all L4 pools at T-2H, the T-0H draw produces 0 draws for ALL pools? Is 0 regular draws the EXPECTED behavior during high-LPI weeks?

**Step 4: 10 survivors advance +1 level**

> **Question J:** After EVERY draw (both SDE sub-draws at T-2H AND regular draws at T-0H), do all 10 surviving members advance +1 level? The code advances only PAID members. Unpaid survivors do NOT advance. Is this correct per strategy?

> **Question K:** This is the cascade mechanism I see in the CSV. Week 15–17 has 13+10+10 = 33 regular draws. In each draw, survivors advance. L3 survivors become L4. Those new L4 members are then processed by SDE next week. But if 33 draws happen and each creates 10 survivors advancing, many L3 become L4, those L4 create even more next week. Is this expected geometric progression? Or is something wrong with the rate of level advancement?

**Step 5: Phase 1 refill after ALL draws**
- Waitlist members fill vacancies in under-capacity pools (FIFO — oldest pool first, oldest waitlist member first)
- Paused pools that reach 12 → restored to Active

---

## SUNDAY 00:05 — T+5m (CLEANUP)

- `draw_completed_this_week` reset to False on ALL pools
- L4/SDE flags cleared
- System LOCK released
- Next week begins

---

## THE REFILL ENGINE (3 PHASES — run inside assign_waitlist_to_pools)

### Phase 1 — Fill existing under-capacity pools
- All Active + Paused pools checked for vacancies (12 - actual members)
- Oldest pool filled first (FIFO), oldest waitlist member moved first (FIFO)
- Paused pools that reach 12 → Active restored

### Phase 2 — Create new pools (if surplus after Phase 1)
```
Reserve needed = Active_Pools × 12 × AI_Multiplier
Available for new pools = Total_Waitlist − Reserve_Needed
Adaptive threshold = MAX(12, 24 × (1 − MIN(0.5, LPI÷100)))

If Available ≥ Adaptive_Threshold → create new pools
```

> **Question L:** In DRY_PHASE (multiplier = ×2) with 14 pools and even modest waitlist — e.g., waitlist = 200:
> ```
> Reserve = 14 × 12 × 2 = 336 people must stay as reserve
> Available = 200 − 336 = −136 (negative)
> Result: NO new pools created, ALL waitlist held as reserve
> ```
> Is this correct? Does DRY_PHASE intentionally BLOCK Phase 2 pool creation entirely, keeping all waitlist members as a liquidity buffer? The user said the waitlist always has members. If the reserve formula consumes all of them, Phase 2 never fires in DRY_PHASE. Is this the designed behavior — the system "holds" the waitlist as reserve and only uses Phase 1 to refill existing pools?

### Phase 3 — Condensation (only when waitlist = 0)
- Only fires when paid waitlist = 0 entirely
- Takes members from NEWEST full pools, moves into OLDEST under-capacity pools
- Dissolved: the source pool after it's emptied
- SDE-protected pools are immune

---

## THE DRAW METRICS (WHERE THE REPORTING IS CURRENTLY WRONG)

The simulation currently records:
```python
draws_this_week = mass_result.pools_drawn  # ← only T-0H regular draws
winners_this_week = draws_this_week × 2    # ← derived from wrong source
```

But the actual draws that HAPPEN are:
1. T-2H: SDE meta-pool sub-draws (`draw_type = POOL_DRAW_SDE`) — NOT counted
2. T-0H: SDE Ext-II/III pre-pass (`draw_type = POOL_DRAW_SDE_EXT2/EXT3`) — NOT counted
3. T-0H: Regular/Type-A draws (`draw_type = POOL_DRAW_REGULAR/TYPE_A`) — COUNTED (but often 0 during high-LPI weeks)

> **Question M:** The user confirmed "i can see there are always members available in waitlist" and the active_users declining ~4/week during the "0 draws" period proves SDE draws ARE happening. But the metric shows 0. Should draws_this_week count ALL draws from ALL draw types for that week? Or should the metric show them broken down: sde_draws_this_week + regular_draws_this_week + ext2_draws_this_week?

---

## MISSING WEEKLY REPORT FIELDS (confirmed gaps vs strategy design)

Strategy requires per-week financial visibility. Currently missing from simulation report:

| Field | Strategy Requires | Currently in Report |
|---|---|---|
| cash_outflow_inr | Yes — winner payouts per week | MISSING |
| net_cash_flow_inr | Yes — inflow minus outflow | MISSING |
| members_joined_this_week | Yes — how many entered pools | MISSING |
| members_exited_this_week | Yes — winners + eliminated | MISSING |
| sde_draws_this_week | Yes — separate SDE draw count | MISSING |
| regular_draws_this_week | Yes — separate regular draw count | MISSING |
| draws_this_week (ALL types combined) | Yes | WRONG (only regular) |
| winners_this_week (actual count) | Yes | WRONG (derived from wrong counter) |
| pools_formed (Phase 1 + Phase 2) | Yes | WRONG (Phase 2 only) |
| pools_paused (instantaneous at snapshot time) | Yes | ALWAYS 0 (snapshot runs after refill) |
| ext2_exits_this_week (per-week) | Yes | CUMULATIVE total (wrong) |

---

These are my 13 questions and the complete strategy as I now understand it. Please correct any remaining misunderstandings before I propose any code changes. I will not touch any code until you confirm my understanding is correct on all points.




NOW GIVE ME YOUR SYSTEMATIC REVIEW AND FRAMWORK IN WIRE DIAGRAM IF THIS IS ACCEPTABLE, IF THERE ARE QUESTION THEN ASK ME, ALSO GIVE ME SUGGESTION WHERE I NEED AND ASKED FROM YOU.



-------
-----------------
-------

I need a deep AI thinking from you for below point:
also adopt same structure for SDE II/SDE III; just one rule is different if there are Case E then in case of SDE II a single winner of L5/L6 can be possible winner, For L5 pool criteria for draw is minimum 6 member, forced winner of L5 level all member, for SDE III no minimum pool criteria for L6 all L6  L5/L6 must Exit winner eliminated from system 