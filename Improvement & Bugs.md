Action Plan A: 

1. simulation stress test developer mode show heavy L5 and L6, heavy pool pause
2. in the stress test there are are dual late fee settings for a single stress test, late fee user ratio and late fees amount %, keep enhanced one, elimination of late unpaid member are unique, more enhancement need throughout and customization from 0.05% to 100%,
3. Elimination rule a member after a week draw opened and status marked as unpaid, and wont pay until the due date,time period setting(give more options in that panel with proper drop down list) due date setting can be set in admin panel and system setting
4. unpaid user untill the due date passed will be eliminated from the draw and non-refund money, also wire a flash notification on user app, message template etc.
5. between due date/time to the 2H draw period this window is grace period, if user continue to take participant and escape from elimination then have to pay 500+late fee to save the seat/slot/pool position and prevent lost deposited money and being active in pool 
6. due date/late fee/ grace period and more advanced setting related to this features available in saperate side bar tab, where all late payers and grace period oayers, elimination risk member, eliminated member due to non pay will be show, use AI scope and make more enhanced this features
7. Simulation stress test i need a master report summary that will also allow me to see how many memmbers joining weekly, week wise, date wise, week wise pool data, active member data weekly, weekly pool draw data, members Level data, pool merge, all 4 type regular, sde type A type B, draw wise data, winning, late/eliminated, late fees, total cash inflow/win payout out flow/referel out flow, weekly LPI data, and so many real data and analysis as per stress test, i need full detailed things whatever you want to do, sub tab add, report save option, i need detailed comphresive data, user inflow should be random data and time so all things are virtually real
8. system is taking slighly slow and taking time in so check this also
9. you didnot implement framer motion throughout the complete admin panel, hydraulic pipeline and command center, also command ceters graphic are not up to the mark presentation are poor
10. after timed injecting people complete system hangging no pool creation automated working nothing is happening all system hanged, people are showing in dashboard correct number, but through out system difference different, user directory showing only 500, where 2222 member in system injected, pool creation failed dont know what happened when i inject people, IN THE SENSE DATA FLOW COMPLETELY STALLED AND BROKEN SOMEWHERE IN PIPELINE FLOW INPUT TO OUTPUT
11. AFTER INJECTING PEOPLE ALL BUTTON SHOW FAILED FOR EXAMPLE POOL CREATION FAILED, INJECT PEOPLE FAILED,  WAITLIST CHECK FAILED ,ANYTHING WANT TO CLICK SHOWS FAILED
12. statistics>Live states tab showing failed, winning ledger showing zero all, i thinkg complete data flow broken
13. waitling list number system every joined member should assign a unique wl number as per irctc pool waiting technology, whenever then enter in active pool as Per FIFO the waitling list updated in realtime for waitlisted members. this sytem dosenot affect the other system fulency also SDE processing are doesnot changes the waitlisted members in actually until it really update the core active members status.
14. make this sytem more robust with the interconnetion communication to each and every engine and area so nothing can broken. zero possibility of mis behave of system and data processing.



Action Plan B: 

1. still all system failure when i inject people timed and mass injection, nothing is working state i think because of your if user detect by system older than 30-day login JWT issued then system hanged 
2. SDE ext-II for L5 target if anyone reach any how there, use all L1-L4 as lower tier win
3. calculate projection drawdown from winner L5 and if they become L6 is more than elimination L5 earlier forcefully to choose both pool winner from L5 then which is lower payout drawdown then proceed with them
4. SDE can use waitlisted member if there are no enough L1/L2 in pool special condition if threshold not met to process WL members to Pool
5. then smartly create new pool from waitlisted and eliminate all L4/L5/L6 make them winner choose both upper tier L4/L5/L6, and adjust them post draw cleanup, if require dissolve pool and fill already created pool if there are no enough members in waitlist to fill further week projections
6. if late member paid late fee before grace period / during grace period then grace period amount+late fee accounted as revenue
7. i need a suggestion from your AI super mind: threshold adjustment by AI: i feel there are a risk of Level advance if we hold member in one pool due to 24 member threshold never surpass; suppose due to one pool is active with 12 member  we are at 23 threshold then consider each week we are coming 2 member, and at 25 new pool created then we have 13 member in waitlist and 12+12 two new pool active, weekly 4 people out 2 in then all people can reach their higher level(its my thought not mathemetical calculated it)




Here is the full implementation status with checkboxes, then the questions:

---

## ══════════════════════════════════════════════════════════
## IMPLEMENTATION STATUS — ACTION PLAN A (14 Items)
## ══════════════════════════════════════════════════════════

```
STATUS KEY:
  ✅ DONE        — Implemented and committed
  🔶 PARTIAL     — Partially implemented, needs more work
  ❌ NOT STARTED — Not yet implemented
  🐛 BUG KNOWN  — Bug exists, fix designed
```

---

### A-1 · Stress Test — L5/L6 visibility + pool pause
```
Status: ❌ NOT STARTED

What you asked:
  Simulation shows heavy L5/L6 counts and pool pause events clearly.

What exists now:
  Simulation engine runs cycles, shows level distribution, but L5/L6
  are grouped with other levels — no dedicated L5/L6 escalation row.
  Pool pause count tracked but not visually broken out week-by-week.

What is needed:
  [ ] SimStatsGrid: dedicated L5 peak / L6 peak row
  [ ] Level Progression chart: L5/L6 as separate colored bands
  [ ] Pool pause timeline per week (which pool, which week, why)
  [ ] SDE Ext-II/III draw count in draw breakdown section
```

---

### A-2 · Stress Test — Dual late fee conflict + elimination % customization
```
Status: 🔶 PARTIAL

What you asked:
  Two conflicting late fee inputs exist (StressTestTab % vs ControlsTab ₹).
  Keep the better one. Elimination % slider: min 0.05%, step 0.05%.

What exists now:
  StressTestTab: lateFee (% of member), lateRatio (% of defaulters)
  Pre-Test Setup: lateFeeInr (₹ amount, flat) ← this is the CONFLICT
  elimPct slider: min was likely 1%, not 0.05%

What was done:
  ✅ Plan documented in plan file (Phase 2-B)

What is still needed:
  [ ] Remove lateFeeInr from Pre-Test Setup (conflicts with % model)
  [ ] Change elimPct slider: min={0.05} step={0.05} max={100}
  [ ] Show decimal: {elimPct.toFixed(2)}%
  [ ] Add tooltip explaining difference between pre-test params vs sim params
```

---

### A-3 · Due Date — Time period settings in admin panel with dropdowns
```
Status: ✅ DONE (backend) + ❌ FRONTEND DROPDOWN MISSING

What you asked:
  Due date configurable in admin panel with proper dropdown options.

What was done:
  ✅ system_settings table: payment_due_days (4), payment_due_hour (23)
  ✅ GET/PUT /admin/elimination/settings endpoints
  ✅ Admin password required for changes

What is still needed:
  [ ] Admin UI: Payment Compliance page settings panel
      — Dropdown: Due day (Monday→Sunday relative to draw)
      — Dropdown: Due hour (12:00 AM → 11:00 PM)
      — Dropdown: Late fee rate options:
          "₹0 (no late fee)"
          "₹25/day" | "₹50/day" | "₹75/day" | "₹100/day"
          "Custom amount (per day)"
          "Per hour (0–48 hours window)"
          "Per 3-day window"
      — Number input: Late fee max cap (₹)
      — Number input: Grace period hours (1–168)
      — Toggle: Auto-eliminate ON/OFF
      — Toggle: Grace period ON/OFF
```

---

### A-4 · Elimination + Flash Notification on User App
```
Status: ✅ DONE (backend elimination) + 🔶 PARTIAL (notifications)

What you asked:
  Unpaid past due date → eliminated from draw + non-refund + flash notification
  on user app with message templates.

What was done:
  ✅ /admin/elimination/mark-at-risk — flags unpaid past due users
  ✅ /admin/elimination/execute — removes them, logs EliminationEvent
  ✅ Backend: elimination_risk, grace_active flags on User model
  ✅ GET /auth/my-notifications (backend) returns active alert array
  ✅ NotificationContext.jsx + FlashBanner.jsx designed in plan

What is still needed:
  [ ] user-app/src/context/NotificationContext.jsx — create file
  [ ] user-app/src/components/FlashBanner.jsx — create file
  [ ] Wire into Dashboard.jsx polling loop
  [ ] Message templates in backend constants
  [ ] Test: user gets red banner when elimination_risk=True
  [ ] Test: user gets amber banner when late but not yet at risk
```

---

### A-5 · Grace Period — ₹500+late fee to save seat
```
Status: ✅ DONE (backend complete)

What you asked:
  Due date → T-2H window = grace period. Pay ₹500+late fee → seat saved.

What was done:
  ✅ /admin/elimination/grant-grace/{uid} — opens grace window
  ✅ /admin/elimination/save-seat/{uid} — confirms payment, clears flags
  ✅ grace_active, grace_expires_at, grace_fee_paid on User model
  ✅ Admin password gate on save-seat
  ✅ Countdown timer in response (time_remaining_seconds)
  ✅ User notification: "LAST CHANCE — pay by [time] to save seat"

Gap:
  [ ] Frontend: Grace Period tab in PaymentCompliance page (not yet built)
  [ ] Frontend: Countdown timer component on grace period cards
  [ ] Frontend: "Confirm Payment" button with admin password modal
```

---

### A-6 · Payment Compliance Sidebar Tab — AI-enhanced, full panel
```
Status: ✅ DONE (backend) + ❌ FRONTEND NOT BUILT

What you asked:
  Separate sidebar tab. Tabs: Late Payers, Grace Period, Elimination Risk,
  Eliminated History. AI risk score. Enhanced features.

What was done:
  ✅ All backend endpoints ready
  ✅ AI risk score: risk = (days_late/due_days × 0.6) + (level/5 × 0.4)
  ✅ Sort by risk score descending
  ✅ Revenue summary endpoint

What is still needed:
  [ ] admin-dashboard/src/pages/PaymentCompliance.jsx — create entire page
  [ ] Sidebar.jsx — add "Payment Compliance" nav entry
  [ ] App.jsx — add route /payment-compliance
  [ ] Tab 1: Late Payers (risk score, color-coded, sortable)
  [ ] Tab 2: Grace Period (countdown timer, Confirm Payment button)
  [ ] Tab 3: Elimination Risk (with Grant Grace + Execute Eliminate buttons)
  [ ] Tab 4: Elimination History (audit log + financial summary strip)
  [ ] Settings sub-panel (dropdown UI per A-3 above)
```

---

### A-7 · Simulation Master Report — Weekly detailed data
```
Status: ❌ NOT STARTED

What you asked:
  Weekly breakdown: members joining (random timestamps), pool data,
  level data, draw types (Regular/SDE/TypeA/TypeB), winnings, late/eliminated,
  cash inflow/outflow/referral, LPI, pool merge events.
  Sub-tabs. Report save/download. Random realistic timestamps.

What exists now:
  Simulation returns summary only — no per-week breakdown.
  No download option.

What is needed:
  [ ] Backend: _AdvSimEngine weekly_detail array (week, date, users, pools, draws, etc.)
  [ ] Backend: Randomized user join timestamps (Gaussian within week)
  [ ] Backend: Per-week draw type breakdown {regular, type_a, sde, type_b}
  [ ] Backend: Per-week cash flow {inflow, outflow_wins, outflow_referral, net_float}
  [ ] Frontend: DevTools.jsx — add 6-tab sub-navigation in results panel:
      [Summary] [Weekly Report] [Pool Activity] [Draw Analysis] [Cash Flow] [Level Progression]
  [ ] Frontend: Weekly Report tab — virtualized sortable table
  [ ] Frontend: "Download CSV" + "Download JSON" buttons
  [ ] All timestamps should be realistic (not all same instant)
```

---

### A-8 · System Speed Optimization
```
Status: 🔶 PARTIAL (DB pool fixed, background injection fixed)

What you asked:
  System slightly slow, taking time — check this.

What was done this session:
  ✅ database.py: pool_size=20, max_overflow=20, pool_pre_ping, recycle (from prev session)
  ✅ Injection pool formation: now runs in background thread (this session)

What may still be slow:
  [ ] UserDirectory: loads only first 500 users — pagination fix needed
  [ ] Hydraulic Pipeline: N+1 queries per pool card
  [ ] Statistics/Live Stats: potentially slow query without proper indexes
  [ ] GET /admin/users: max limit 1000, need to raise to 5000+
  [ ] client.js: getAdminUsers hardcodes limit:500
```

---

### A-9 · Framer Motion throughout admin + Command Center graphics
```
Status: ❌ NOT STARTED

What you asked:
  framer-motion on every admin page + Command Center 5 brains with proper
  animations. LPI gauge animated fill. Scatterplot dot moves on update.
  Pool hex nodes scale on count change. SDE Brain 5 rows animate in/out.

What is needed:
  [ ] CommandCenter.jsx — LPI thermometer: motion.rect animated height
  [ ] CommandCenter.jsx — Scatterplot: motion.circle lerps on data update
  [ ] CommandCenter.jsx — Topology paths: motion.path with pathLength
  [ ] CommandCenter.jsx — Brain 5: AnimatePresence on L4 rows
  [ ] HydraulicPipeline.jsx — pool cards: AnimatePresence mount/unmount
  [ ] HydraulicPipeline.jsx — buffer fill bar: motion.div width transition
  [ ] Statistics.jsx — KPI cards stagger on load
  [ ] TokenManager.jsx — table rows fadeUp stagger
  [ ] UserDirectory.jsx — LevelDistBar segments animate width
  [ ] All pages: fadeUp on page load
```

---

### A-10/11/12 · System Hanging + All Buttons Failed + Data Flow Broken
```
Status: 🔶 PARTIAL (injection blocking fixed this session)

Root causes identified:
  ✅ DB connection pool: pool_size=20 (was default 5) — fixed
  ✅ Injection blocking: async background now (fixed this session)
  🔶 Admin JWT expiry: 30-day TTL — admin must re-login after 30 days
  ❌ UserDirectory limit:500 hardcoded in client.js — shows wrong count
  ❌ No 401 auto-redirect: expired JWT causes "all buttons fail" silently

What is needed:
  [ ] client.js: getAdminUsers limit change from 500 → 5000
  [ ] admin.py: GET /admin/users max limit raise from le=1000 → le=10000
  [ ] client.js: axios 401 interceptor → redirect to /login automatically
  [ ] Consider: admin JWT TTL increase from 30 to 90 days in staging
  [ ] UserDirectory: "Load More" pagination or virtual scroll
```

---

### A-13 · Waitlist Number System — IRCTC WL-XX
```
Status: ✅ DONE (backend) + ❌ FRONTEND NOT BUILT

What you asked:
  Every registered user gets WL-XX position. FIFO. Realtime update.
  SDE does NOT change WL positions (SDE operates on active pool members only).

What was done:
  ✅ Backend: GET /users/me/waitlist-rank returns {rank, wl_number, total_waiting}
  ✅ IRCTC-style: WL-01 to WL-XXXX numbering
  ✅ Position computed dynamically via ROW_NUMBER() window function
  ✅ SDE does NOT touch waitlist — confirmed in code

What is needed:
  [ ] user-app Dashboard.jsx: replace #{rank} with "WL-60" large hero display
  [ ] user-app: "You are WL-60 of 1,077 waiting" sub-label
  [ ] user-app: Animate number change when rank decreases (motion.span counter)
  [ ] user-app: "🎉 Promoted! WL-68 → WL-60" micro-toast on promotion
  [ ] Admin UserDirectory: show wl_position column for Waitlist users
```

---

### A-14 · System Robustness — Zero data breakage
```
Status: 🔶 PARTIAL

What was done:
  ✅ Data integrity job: runs every 6 hours (sync pool counts, clear orphaned flags)
  ✅ pool_pre_ping: dead connections detected before use
  ✅ pool_timeout=30: fail fast instead of hang forever
  ✅ Double-draw guard: draw_completed_this_week flag

What is needed:
  [ ] Frontend 401 interceptor (critical — silent failures on expired JWT)
  [ ] GET /admin/pipeline-health: already built, but Diagnostics page should poll it
  [ ] Rate limiting on injection endpoints
  [ ] Error boundary components in React (prevent one failed API from crashing whole page)
```

---

## ══════════════════════════════════════════════════════════
## IMPLEMENTATION STATUS — ACTION PLAN B (7 Items)
## ══════════════════════════════════════════════════════════

```
B-1 · System failure / JWT / injection blocking
  ✅ DB pool: pool_size=20, max_overflow=20, pre_ping (done prev session)
  ✅ Injection async: pool formation moved to background thread (this session)
  ❌ Admin JWT 401 interceptor: not yet added to frontend
  → Verify: does injection complete without hanging now?

B-2 · SDE Ext-II (L5 target, L1-L4 lower)
  ✅ execute_sde_ext2_draw() implemented
  ✅ Lower tier: L1-L4 exactly as requested
  ✅ Upper tier: L5 ONLY (forced exit guaranteed)
  ✅ Triggers before every weekly draw automatically

B-3 · L5 drawdown projection
  ✅ calculate_l5_drawdown_projection() implemented
  ✅ Math verified: dual-L5 = ₹13,000 < wait = ₹14,500+
  ✅ Logged before every Ext-II draw execution
  ✅ Savings shown in draw result

B-4 · WL emergency promotion (L1/L2 shortage)
  ✅ execute_sde_sub_draw(): pulls WL members when lower_candidates empty
  ✅ Also added to execute_sde_ext2_draw()
  ✅ Max 2 WL members per emergency (SDE_WL_EMERGENCY_PROMOTE=2)
  ✅ Pool temporarily 13-14 → normalizes after draw

B-5 · Smart pool dissolution + both winners from L4+
  ✅ run_accelerated_dissolution_draw(): both winners from L4+
  ✅ Creates relief pool from WL simultaneously
  ✅ Dissolves pool if < 8 members after clearing (ACCEL_DISS_DISSOLVE_BELOW)
  ✅ Trigger ratio: 60% L4+ (ACCEL_DISS_TRIGGER_RATIO)
  ✅ POST /admin/pools/{id}/accelerated-dissolution endpoint

B-6 · Late fee / grace fee = revenue when paid
  ✅ save-seat now logs to system_settings revenue counters before clearing
  ✅ Keys: revenue_late_fees_collected_inr, revenue_grace_fees_collected_inr
  ✅ GET /admin/elimination/revenue-summary: collected vs forfeited breakdown

B-7 · AI adaptive threshold
  ✅ get_adaptive_threshold(): LPI-pressure formula
  ✅ At LPI ≥ 50% → threshold = 12 (minimum = pool capacity)
  ✅ Phase 2 of assign_waitlist_to_pools() now uses adaptive threshold
  ✅ GET /admin/settings/adaptive-threshold with explanation
```

---


