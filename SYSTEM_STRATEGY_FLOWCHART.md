# Reward Scheme — Core Strategy Flowchart
**Full System Architecture & Upgraded Feature Map**
*Generated after 14-item enhancement plan — June 2026*

---

## 1. System Architecture Overview

```mermaid
graph TB
    subgraph FRONTEND["Frontend Layer"]
        UA["User App<br/>React + Vite<br/>reward-scheme-user.vercel.app"]
        AD["Admin Dashboard<br/>React + Vite<br/>reward-scheme.vercel.app"]
    end

    subgraph BACKEND["Backend Layer (FastAPI on Render)"]
        direction TB
        API["FastAPI App<br/>app/main.py"]
        POOL_SIZE["DB Pool<br/>size=20 max=20<br/>pre_ping recycled 30min"]

        subgraph ROUTERS["Routers"]
            R1["/auth/*<br/>User Auth"]
            R2["/admin/*<br/>Admin Ops"]
            R3["/admin/elimination/*<br/>Payment Compliance"]
            R4["/admin/users|tokens<br/>Data Engine"]
            R5["/dev/*<br/>Dev Mode Only"]
            R6["/users/me/*<br/>User Profile"]
        end

        subgraph SCHEDULER["APScheduler Jobs"]
            J1["Sunday 5 PM IST<br/>draw_preparation()"]
            J2["Sunday 7 PM IST<br/>execute_weekly_draw()"]
            J3["Sunday 7:05 PM IST<br/>post_draw_cleanup()"]
            J4["Every 5min<br/>admin_override_watchdog()"]
            J5["Every 6h<br/>data_integrity_check()"]
        end
    end

    subgraph DB["Database Layer (Supabase PostgreSQL)"]
        T1[("users")]
        T2[("pools")]
        T3[("tokens")]
        T4[("draw_history")]
        T5[("elimination_events ★NEW")]
        T6[("system_settings")]
        T7[("weekly_draw_state")]
        T8[("sde_session / checkpoint")]
    end

    UA <-->|JWT + REST| API
    AD <-->|Admin JWT + REST| API
    API --> ROUTERS
    API --> SCHEDULER
    API --> POOL_SIZE
    POOL_SIZE <-->|QueuePool| DB
```

---

## 2. User Registration & Entry Flow

```mermaid
flowchart TD
    START([User wants to join]) --> BUY["Buy Deposit Token<br/>DEP-XXXXXX from Admin<br/>Value = ₹1,000"]
    BUY --> REG["POST /auth/register<br/>Name + Mobile + Username<br/>+ Password + DEP token"]
    REG --> VAL{Token valid?<br/>Active DEP = ₹1000?}
    VAL -- No --> ERR1["400 Error<br/>Invalid/Used Token"]
    VAL -- Yes --> CREATE["Create User<br/>status = Waitlist<br/>level = 1<br/>payment = Paid"]
    CREATE --> BURN["Burn DEP token<br/>stamped with user_id<br/>+ redeemed_at"]
    BURN --> REFCODE["Generate referral code<br/>8-char uppercase<br/>alphanumeric"]
    REFCODE --> JWT["Issue 30-day User JWT"]
    JWT --> BGFIFO["Background: assign_waitlist_to_pools()<br/>Double-FIFO vacancy fill"]

    BGFIFO --> CHECK{Waitlist count ≥<br/>pool threshold?}
    CHECK -- Yes --> NEWPOOL["Create new pool<br/>12 members capacity<br/>FIFO by join_date"]
    CHECK -- No --> QUEUE["User stays on Waitlist<br/>WL-XX position assigned<br/>via ROW_NUMBER() window fn"]
    NEWPOOL --> ACTIVE["User status = Active<br/>current_pool_id set<br/>weekly_payment = Paid"]
    ACTIVE --> DASH["User App Dashboard<br/>Shows pool + level"]
    QUEUE --> DASH2["User App Dashboard<br/>Shows WL-XX position<br/>★ IRCTC-style numbering"]
```

---

## 3. WL Queue Numbering System ★NEW

```mermaid
flowchart LR
    subgraph QUEUE["Live Waitlist Queue (FIFO by join_date)"]
        direction TB
        W1["WL-01 — oldest joiner"]
        W2["WL-02"]
        W3["WL-03"]
        WN["..."]
        W60["WL-60 — current user"]
        WZ["WL-1077 — newest joiner"]
    end

    POOL_FORM["Pool forms (threshold reached)<br/>WL-01 → WL-08 enter active pool"]
    POOL_FORM --> PROMOTE["All remaining members<br/>auto-promote positions"]
    PROMOTE --> W60B["WL-60 → WL-52<br/>Promotion toast in user app 🎉"]

    BACKEND["Backend: ROW_NUMBER() OVER<br/>(ORDER BY join_date ASC)<br/>Always live, never stale"]
    BACKEND --> FORMAT["Format: WL-{rank:02d}<br/>WL-01, WL-68, WL-142"]

    POLL["User App polls every 30s<br/>GET /users/me/waitlist-rank"]
    POLL --> DETECT["prevRank vs newRank<br/>newRank < prevRank = Promoted!"]
```

---

## 4. Pool Formation & FIFO Algorithm

```mermaid
flowchart TD
    TRIG(["Trigger: new user joins<br/>OR deposit redeemed<br/>OR admin force-fill"])
    TRIG --> FIFO["assign_waitlist_to_pools()<br/>Double-FIFO engine"]

    FIFO --> VAC{Any pool has<br/>vacancies?}
    VAC -- Yes --> FILL["Fill vacancies FIFO<br/>oldest waitlist users first<br/>level=1, payment=Paid"]
    VAC -- No --> THRESH

    THRESH{Paid waitlist count<br/>≥ threshold (default 8)?}
    THRESH -- Yes --> NEWPOOL["Create new 12-member pool<br/>pool_draw_type assigned<br/>contains_flagged_l4 = False"]
    THRESH -- No --> DONE([Wait for more users])

    FILL --> ACTIVE["User: Waitlist → Active<br/>current_pool_id assigned"]
    NEWPOOL --> FILL2["Fill pool with FIFO members"]
    FILL2 --> ACTIVE

    ACTIVE --> PAYCHECK{All 12 members<br/>weekly_payment = Paid?}
    PAYCHECK -- Yes --> ELIGIBLE["Pool eligible for draw"]
    PAYCHECK -- No --> UNPAID["Unpaid members accrued<br/>late_fees += ₹50/day<br/>POST /admin/penalty/apply-daily"]
```

---

## 5. Weekly Draw Lifecycle (Sunday Automated)

```mermaid
flowchart TD
    subgraph PREP["T-2H: Draw Preparation (5 PM IST)"]
        P1["LPI snapshot computed<br/>LPI = L4 members / total active"]
        P2["SDE pre-processing<br/>Flag L4 members: sde_required=True"]
        P3["Acquire system lock<br/>Prevents concurrent draws"]
        P4["WeeklyDrawState created<br/>ISO week key YYYY-Www"]
    end

    subgraph DRAW["T+0: Execute Draw (7 PM IST)"]
        D1{LPI > 25%?}
        D1 -- Yes, High LPI --> SDE["SDE Draw<br/>L4 members targeted<br/>Early exit from pool"]
        D1 -- No --> NORMAL

        NORMAL{Pool member levels?}
        NORMAL -- No L4+ --> TYPEA["Type A Draw<br/>Edge case — early weeks<br/>Two L1-L3 winners"]
        NORMAL -- Has L4+ --> REG["Regular Draw<br/>Winner 1: L1-L3<br/>Winner 2: L4-L6"]
        NORMAL -- L6 present --> TYPEB["Type B Draw<br/>L6 special payout"]

        SDE --> WIN["2 Winners selected<br/>per pool"]
        TYPEA --> WIN
        REG --> WIN
        TYPEB --> WIN

        WIN --> PAYOUT["Calculate payouts<br/>Gross = pool deposits<br/>Fee = 10%<br/>Net = Gross - Fee"]
        PAYOUT --> WIT["Issue WIT-XXXXXX token<br/>Withdraw token to each winner"]
        WIT --> ADVANCE["Surviving members advance<br/>current_level += 1 (max 6)<br/>status = Active (new pool)"]
        ADVANCE --> REPLACE["Refill vacancies from waitlist<br/>FIFO backfill"]
    end

    subgraph CLEANUP["T+5m: Post Draw Cleanup"]
        C1["Release system lock"]
        C2["Reset weekly_payment = Unpaid<br/>all active members"]
        C3["Clear SDE flags<br/>sde_required = False"]
        C4["Record to draw_history"]
        C5["Update WeeklyDrawState = complete"]
    end

    PREP --> DRAW --> CLEANUP
```

---

## 6. Payment, Late Fee & Elimination Engine ★NEW

```mermaid
flowchart TD
    SUNDAY["Sunday 7 PM IST<br/>Draw executed<br/>payment reset → Unpaid"]
    SUNDAY --> MONDAY["Monday: Payment window OPENS<br/>Members must pay weekly ₹1,000"]

    MONDAY --> PAY{Member pays<br/>this week?}
    PAY -- Yes: DEP token redeemed --> PAID["weekly_payment = Paid<br/>late_fees_inr stays 0<br/>elimination_risk = False"]
    PAY -- No --> DAY1["Daily late fee accrual<br/>late_fees_inr += ₹50/day<br/>Max cap: ₹500<br/>POST /admin/penalty/apply-daily"]

    DAY1 --> DUEDATE["Thursday 23:59 IST<br/>payment_due_days=4 hit<br/>late_fees ≥ ₹50"]
    DUEDATE --> RISKFLAG["elimination_risk = True<br/>Member appears in<br/>Payment Compliance → At Risk tab"]

    RISKFLAG --> GRACE{grace_period_enabled<br/>= True?}

    GRACE -- Yes --> GRACEWIN["Grace Window Opens<br/>grace_active = True<br/>grace_expires_at = Sunday T-2H<br/>grace_expires_at set"]
    GRACEWIN --> GRACEPAY{Member pays<br/>₹1000 + ₹500 grace fee<br/>+ accumulated late fees?}

    GRACEPAY -- Yes: Admin confirms via save-seat --> SEAT["grace_fee_paid = True<br/>elimination_risk = False<br/>grace_active = False<br/>late_fees_inr = 0<br/>weekly_payment = Paid<br/>SEAT SAVED ✅"]

    GRACEPAY -- No, time expires --> EXPIRE["grace_active = False<br/>grace_expired_ids tracked<br/>reason = grace_expired"]

    GRACE -- No --> DIRECTELIM

    EXPIRE --> EXECUTE["POST /admin/elimination/execute<br/>Admin password required"]
    DIRECTELIM["elimination_risk=True<br/>grace_active=False"] --> EXECUTE

    EXECUTE --> DRYRUN{dry_run = True?}
    DRYRUN -- Yes --> REPORT["Preview: who WOULD be eliminated<br/>Correct reason per user<br/>No DB changes"]
    DRYRUN -- No --> ELIMINATE["status = Eliminated<br/>current_pool_id = None<br/>All flags cleared"]

    ELIMINATE --> AUDIT["EliminationEvent audit record<br/>reason: non_payment | grace_expired<br/>seat_save_fee: ₹500 if grace_expired<br/>deposit_forfeited: ₹1,000<br/>total_forfeited: deposit + late_fees + grace_fee<br/>was_in_grace_period: True/False<br/>Numeric(12,2) — exact accounting"]
```

---

## 7. AI Risk Score & Payment Compliance Admin

```mermaid
flowchart LR
    subgraph SCORE["AI Risk Score (0.0 → 1.0)"]
        FORMULA["risk = (days_late_factor × 0.6)<br/>     + (level_factor × 0.4)<br/><br/>days_late_factor = min(1.0, days_late / due_days)<br/>level_factor = (level - 1) / 5"]
    end

    subgraph TABS["PaymentCompliance Admin Page"]
        T1["Tab 1: Late Payers<br/>All Unpaid active members<br/>sorted by risk_score DESC"]
        T2["Tab 2: Grace Period<br/>grace_active=True members<br/>Live countdown timer"]
        T3["Tab 3: At Risk<br/>elimination_risk=True<br/>grace_active=False"]
        T4["Tab 4: Elimination History<br/>EliminationEvent audit log<br/>Financial summary strip"]
    end

    subgraph COLORS["Risk Color Band"]
        GREEN["0.0 – 0.4<br/>🟢 Green — Safe"]
        AMBER["0.4 – 0.7<br/>🟡 Amber — Warning"]
        RED["0.7 – 1.0<br/>🔴 Red — Critical"]
    end

    SCORE --> TABS
    SCORE --> COLORS
```

---

## 8. Data Integrity Auto-Repair Job ★NEW

```mermaid
flowchart TD
    CRON["APScheduler: Every 6 hours<br/>job_data_integrity_check()"]

    CRON --> R1["Repair 1: Pool member counts<br/>Sync pool.total_members<br/>vs actual active user count"]
    CRON --> R2["Repair 2: Orphaned SDE flags<br/>Clear sde_required=True<br/>on non-Active users"]
    CRON --> R3["Repair 3: Expired grace periods<br/>Clear grace_active=True<br/>past grace_expires_at"]
    CRON --> R4["Repair 4: L4 flag sync<br/>Recompute contains_flagged_l4<br/>for all pools"]

    R1 & R2 & R3 & R4 --> LOG["Log all corrections<br/>to admin.log<br/>Count reported to pipeline-health"]
```

---

## 9. Simulation Engine (_AdvSimEngine) ★UPGRADED

```mermaid
flowchart TD
    subgraph ENGINE["In-Memory Simulation"]
        INIT["Initialize:<br/>total_cycles, late_fee_pct<br/>late_users_ratio_pct<br/>volatility_mode, avg_rdr_pct"]
        
        CYCLE["Per-cycle run_cycle():<br/>1. Poisson inflow of new users<br/>2. FIFO pool assignment<br/>3. Payment scenario applied<br/>4. Late fee accrual<br/>5. Draw execution<br/>6. Level advancement<br/>7. SDE check if LPI > 25%"]

        WEEKLY["weekly_detail[] per cycle:<br/>• users_joined, active, waitlist<br/>• pools_formed, merges, LPI<br/>• draw_type_breakdown<br/>• winners list with payouts<br/>• cash_inflow, outflow, net_float<br/>• level_distribution L1-L6<br/>• scenario + momentum + velocity"]

        TRACKING["Peak tracking:<br/>_max_l5, _max_l6<br/>_high_lpi_streak<br/>high_pressure_mode (LPI > 40% for 3+ weeks)"]
    end

    subgraph REPORT["6-Tab Report Panel"]
        TAB1["Summary<br/>KPI grid + system health<br/>level matrix"]
        TAB2["Weekly Report<br/>Sortable virtualized table<br/>CSV export"]
        TAB3["Pool Activity<br/>pools_active + formed + merged<br/>timeline chart"]
        TAB4["Draw Analysis<br/>Stacked bar: Regular/Type A/SDE/Type B<br/>win distribution"]
        TAB5["Cash Flow<br/>Area chart: inflow/outflow/net_float<br/>per week"]
        TAB6["Level Progression<br/>Stacked area L1-L6 distribution<br/>LPI overlay"]
    end

    ENGINE --> REPORT
```

---

## 10. Full Token Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Active : Admin creates token<br/>(DEP or WIT or REF)

    Active --> Burned : User redeems<br/>POST /auth/register<br/>or /auth/deposit/redeem
    Active --> Deleted : Admin deletes<br/>(admin password required)

    Burned --> [*] : Immutable audit trail<br/>user_id, redeemed_at<br/>redeemed_by_user_id stamped

    note right of Burned
        DEP token burn:
        → User created on Waitlist (first)
        → OR weekly_payment = Paid (rejoin)
        
        WIT token = winnings withdrawal
        → Issued on draw win
        → Redeemed by user for cash
        
        REF token = referral bonus
        → accumulated_referral_bonus_inr
        → Admin approves payout
    end note
```

---

## 11. Admin Password 2FA Gate ★NEW

```mermaid
flowchart LR
    subgraph PROTECTED["Password-Gated Endpoints"]
        A["PUT /admin/elimination/settings"]
        B["POST /admin/elimination/save-seat/{uid}"]
        C["POST /admin/elimination/execute"]
        D["DELETE /admin/tokens/{id}"]
        E["DELETE /admin/users/{id}"]
        F["PUT /admin/settings/threshold"]
    end

    REQ["Request hits protected endpoint<br/>body.admin_password required"]
    REQ --> VERIFY["verify_admin_password(db, username, password)<br/>app/core/security.py"]
    VERIFY --> BCRYPT["bcrypt.checkpw(password, stored_hash)<br/>ALWAYS runs dummy hash if admin not found<br/>→ Prevents username enumeration (timing attack)"]
    BCRYPT --> MATCH{Password<br/>matches?}
    MATCH -- No --> HTTP403["HTTP 403 Forbidden<br/>Invalid admin password"]
    MATCH -- Yes --> EXEC["Execute destructive operation<br/>Full audit trail recorded"]
```

---

## 12. User App Notification System ★NEW

```mermaid
flowchart TD
    POLL["User App polls every 60s<br/>GET /auth/my-notifications<br/>Bearer JWT"]

    POLL --> BACKEND["Backend checks user flags:<br/>elimination_risk, grace_active<br/>draw countdown, payment status"]

    BACKEND --> N1["🔴 grace_period_active<br/>type: danger, persistent<br/>Pay ₹X + ₹Y by [time] or lose seat"]
    BACKEND --> N2["⚠️ elimination_risk<br/>type: warning, persistent<br/>Payment overdue"]
    BACKEND --> N3["⏰ payment_overdue<br/>type: warning, 8s auto-dismiss"]
    BACKEND --> N4["🎯 draw_approaching<br/>type: info, 8s auto-dismiss<br/>Draw in 2 hours"]

    N1 & N2 & N3 & N4 --> CONTEXT["NotificationContext<br/>manages queue + auto-dismiss"]
    CONTEXT --> BANNER["FlashBanner.jsx<br/>Stacked banners with AnimatePresence<br/>slide-in / slide-out"]
```

---

## 13. Deployment Architecture

```mermaid
graph TB
    subgraph VERCEL["Vercel (Frontend CDN)"]
        ADMIN_FRONT["Admin Dashboard<br/>reward-scheme.vercel.app<br/>VITE_API_URL → Render<br/>VITE_ENABLE_DEV_MODE=true (staging)"]
        USER_FRONT["User App<br/>reward-scheme-user.vercel.app<br/>VITE_API_URL → Render"]
    end

    subgraph RENDER["Render (Backend)"]
        FASTAPI["FastAPI + Uvicorn<br/>YOUR_BACKEND.onrender.com<br/>SCHEDULER_ENABLED=true<br/>ENABLE_DEV_MODE=true (staging)"]
    end

    subgraph SUPABASE["Supabase (Database)"]
        PG["PostgreSQL<br/>aws-1-ap-south-1 (pooler port 6543)<br/>Connection pool: 40 max concurrent"]

        subgraph TABLES["Tables"]
            direction LR
            users_t["users ★+4 cols"]
            pools_t["pools"]
            tokens_t["tokens"]
            elim_t["elimination_events ★NEW"]
            settings_t["system_settings<br/>★+8 elimination keys"]
            draw_t["draw_history"]
        end
    end

    ADMIN_FRONT -->|HTTPS + Admin JWT| FASTAPI
    USER_FRONT -->|HTTPS + User JWT| FASTAPI
    FASTAPI -->|QueuePool size=20 max=20| PG

    ALLOWED_ORIGINS["ALLOWED_ORIGINS =<br/>reward-scheme.vercel.app,<br/>reward-scheme-user.vercel.app"]
    FASTAPI --- ALLOWED_ORIGINS
```

---

## 14. What Was Upgraded — Session Summary

| Phase | What Changed | Impact |
|---|---|---|
| **Phase 0** | DB pool size=20/max=20, inject-timed background tasks, UserDirectory pagination, health endpoints | Fixes all buttons failing after large injections |
| **Phase 1** | Full elimination engine, grace period flow, EliminationEvent audit table, 10 API endpoints, PaymentCompliance page, user-app flash notifications | Real payment enforcement with full financial audit trail |
| **Phase 2** | _AdvSimEngine L5/L6 tracking, 6-tab simulation report, consolidated late fee settings | Rich per-week simulation analytics with CSV export |
| **Phase 3** | Framer-motion animations across all 5 admin pages, LevelDistBar animation, WL promotion micro-toast | Smooth, professional UI feel |
| **Phase 4** | IRCTC-style WL-XX numbering via ROW_NUMBER() window fn, promotion detection in Dashboard | Clear real-time queue position for users |
| **Phase 5** | 6h data integrity APScheduler job, pipeline-health endpoint | Self-healing system, ops visibility |
| **Cross-Verification** | was_grace audit bug fixed (EliminationReason + seat_save_fee now correct), WinningLedger case-insensitive color, DevTools 479-line dead code removal | Accurate financial audit records |

---

## 15. One-Thing-You-Still-Need

```
⚠️  VITE_API_URL is still set to placeholder in both frontend .env files:
       admin-dashboard/.env  →  VITE_API_URL=https://YOUR_RENDER_BACKEND.onrender.com
       user-app/.env         →  VITE_API_URL=https://YOUR_RENDER_BACKEND.onrender.com

    Also fill in before going live:
       .env  →  USER_JWT_SECRET=<your 64-char hex>
       .env  →  ADMIN_JWT_SECRET=<your 64-char hex>
       .env  →  ADMIN_SETUP_SECRET=<your chosen secret>
    
    Generate secrets:
       python -c "import secrets; print(secrets.token_hex(32))"
```
