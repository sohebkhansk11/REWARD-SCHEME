"""
Throwaway smoke check for the Manual Event-Timeline Simulator ACTION endpoints
(Phase 3).  Walks a full cycle event-by-event, triggering each per-event action
through the real FastAPI route functions, and asserts the event->action guard
rejects an out-of-window action.

SAFETY: points DATABASE_URL at a throwaway local SQLite file BEFORE importing the
app and asserts the backend is sqlite (never the shared Supabase production DB).
Run:  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python tools/_manual_sim_actions_smoke.py
"""
import os
import sys
import tempfile
import uuid

# Ensure the repo root (parent of tools/) is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Isolate BEFORE any app import ────────────────────────────────────────────
_db_path = os.path.join(tempfile.gettempdir(), f"manualsim_act_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"]    = f"sqlite:///{_db_path}"
os.environ["ENABLE_DEV_MODE"] = "true"

_url = os.environ["DATABASE_URL"].lower()
assert _url.startswith("sqlite"), f"REFUSE: not sqlite — {_url}"
for forbidden in ("supabase", "pooler", "postgres"):
    assert forbidden not in _url, f"REFUSE: production marker '{forbidden}' in URL"

from fastapi import HTTPException

from app.database import Base, engine, SessionLocal
import app.models  # registers every table on Base.metadata
from app.services import manual_sim
from app.routers import dev

Base.metadata.create_all(bind=engine)

FAILS = []
def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)

db = SessionLocal()
try:
    print("\n== start + inject at CYCLE_START ==")
    st = manual_sim.start_session(db, ttl_hours=6)
    check("starts at CYCLE_START", st["current_event"] == "CYCLE_START")

    inj = dev.manual_sim_action_inject(dev.ManualSimInjectRequest(count=24), db)
    check("inject ran", inj["action"] == "inject_users")
    check("24 users injected", inj["result"]["injected"] == 24)
    # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Pool formation is now PURELY production-gated (the manual_create_pool force-drain
    # override was REMOVED).  pools_formed may legitimately be 0 (the AI-reserve gate
    # held) — assert the production-gated shape, not the old >=1 override behaviour.
    check("pools_formed is a non-negative int (production-gated, no override)",
          isinstance(inj["result"]["pools_formed"], int) and inj["result"]["pools_formed"] >= 0)
    check("inject window surfaced (date never overridden)",
          bool(inj["result"].get("window_start")) and bool(inj["result"].get("window_end")))
    print("   inject result:", inj["result"])

    # ── Requirement #6: confirm NO instant-drain override ─────────────────────
    # Fresh DB: every injected user is either Active (in a full 12-member pool the
    # production gate decided to form) or still on the waitlist.  None are lost, and
    # pools only ever appear in full-12 batches — exactly assign_waitlist_to_pools.
    comp0 = manual_sim.compute_state(db)["compliance"]
    check("#6: every injected user accounted for (active + waitlist == 24, no loss)",
          comp0["active"] + comp0["waitlist"] == 24)
    check("#6: pools form only as full 12-member batches (production gate, no instant-drain)",
          comp0["active"] == 12 * inj["result"]["pools_formed"])
    print(f"   #6 compliance: active={comp0['active']}  waitlist={comp0['waitlist']}  "
          f"pools_formed={inj['result']['pools_formed']}")

    print("\n== event->action guard (pay-all before DUE_DATE) ==")
    guard_409 = False
    try:
        dev.manual_sim_action_pay_all(db)
    except HTTPException as exc:
        guard_409 = (exc.status_code == 409)
    check("pay-all rejected at CYCLE_START (409)", guard_409)

    print("\n== DUE_DATE: gating + compliance + set-late / pay-all / pay-remaining ==")
    manual_sim.jump_to(db, "DUE_DATE")

    # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Event-driven gating (req #2): cannot advance until a pay action is done.
    # Compliance panel + per-event task list must be present (req #3).
    state_due = manual_sim.compute_state(db)
    check("DUE_DATE requires a pay action", "pay_all_installments" in state_due["required_action"])
    check("cannot advance before paying (can_advance False)", state_due["can_advance"] is False)
    check("compliance panel present", isinstance(state_due.get("compliance"), dict)
          and "late_payers" in state_due["compliance"])
    check("task_list present + non-empty", isinstance(state_due.get("task_list"), list)
          and len(state_due["task_list"]) > 0)
    blocked = False
    try:
        manual_sim.jump_next(db)
    except manual_sim.ManualSimError:
        blocked = True
    check("jump-next hard-blocked until required action done (no override)", blocked)

    out = dev.manual_sim_action_set_late(dev.ManualSimSetLateRequest(late_pct=20.0), db)
    check("set-late stored ratio 0.2", abs(out["result"]["late_ratio"] - 0.2) < 1e-9)
    out = dev.manual_sim_action_pay_all(db)
    check("pay-all ran", "installments_paid" in out["result"])

    # SESSION EDIT [Jun-24]: after pay-all the gate opens and the mutually-exclusive
    # pay actions are dimmed (req #2 + #3 — no override / overwrite).
    state_paid = manual_sim.compute_state(db)
    check("can advance after pay-all (gate open)", state_paid["can_advance"] is True)
    check("pay-all dims set_late_pct + pay_remaining (locked, no overwrite)",
          "set_late_pct" in state_paid["disabled_actions"]
          and "pay_remaining" in state_paid["disabled_actions"])

    out = dev.manual_sim_action_pay_remaining(db)
    check("pay-remaining ran", "remaining_paid" in out["result"])

    print("\n== GRACE_PERIOD_START: A/B/C settlement ==")
    manual_sim.jump_to(db, "GRACE_PERIOD_START")
    out = dev.manual_sim_action_grace_settle(
        dev.ManualSimGraceRequest(late_pct=30.0, elim_pct_a=50.0, grace_pct_c=40.0), db)
    r = out["result"]
    check("grace settlement ran", "late_payers" in r)
    # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Truthful A/B/C buckets must reconcile to the late cohort (req #3).  The old
    # misleading entered_grace_no_fee field has been removed.
    check("ABC invariant A+B+C == late_payers",
          r["eliminated_A"] + r["paid_late_fee_B"] + r["grace_survivors_C"] == r["late_payers"])
    check("buckets_reconcile flag is True", r["buckets_reconcile"] is True)
    check("misleading entered_grace_no_fee field removed", "entered_grace_no_fee" not in r)
    print("   grace result:", r)

    print("\n== G_CLOSE: guillotine confirm (read-only) ==")
    manual_sim.jump_to(db, "G_CLOSE")
    out = dev.manual_sim_action_finalize_eliminations(db)
    check("finalize read-only", out["result"]["read_only"] is True)
    check("eliminations counted", "eliminations_this_cycle" in out["result"])
    print("   finalize result:", out["result"])

    print("\n== T_02H: draw preparation ==")
    manual_sim.jump_to(db, "T_02H")
    out = dev.manual_sim_action_prepare_draw(db)
    check("prepare-draw produced a week_id", bool(out["result"].get("week_id")))
    print("   prepare result:", out["result"])

    print("\n== T_00H: execute draw ==")
    manual_sim.jump_to(db, "T_00H")
    out = dev.manual_sim_action_execute_draw(db)
    check("execute-draw returned pools_drawn", isinstance(out["result"]["pools_drawn"], int))
    print("   execute result:", out["result"])

    print("\n== T_05M: cleanup ==")
    manual_sim.jump_to(db, "T_05M")
    out = dev.manual_sim_action_cleanup(db)
    check("cleanup ran", "cleanup" in out["result"])
    print("   cleanup result:", out["result"])

    print("\n== Phase 4: link toggle / TTL / forensic audit ==")
    state_now = manual_sim.compute_state(db)
    check("ttl_remaining surfaced", isinstance(state_now.get("ttl_remaining_seconds"), int)
          and state_now["ttl_remaining_seconds"] > 0)
    check("ttl_hours surfaced", state_now.get("ttl_hours") == 6)

    out = dev.manual_sim_link(dev.ManualSimLinkRequest(link_global=True), db)
    check("link toggled ON", out["link_global"] is True)
    out = dev.manual_sim_link(dev.ManualSimLinkRequest(link_global=False), db)
    check("link toggled OFF", out["link_global"] is False)

    from app.models.forensic_event import ForensicEvent
    audit_n = db.query(ForensicEvent).filter(ForensicEvent.run_id == "manual_sim").count()
    action_n = db.query(ForensicEvent).filter(
        ForensicEvent.run_id == "manual_sim",
        ForensicEvent.event_type.like("action:%"),
    ).count()
    check("forensic audit rows written", audit_n > 0)
    check("per-action audit rows written", action_n >= 5)
    print(f"   audit rows: total={audit_n}  action={action_n}")

    print("\n== rollover then stop ==")
    st = manual_sim.jump_next(db)            # T_05M -> next cycle DUE_DATE
    check("rolled into cycle 2", st["cycle_num"] == 2 and st["current_event"] == "DUE_DATE")
    manual_sim.stop_session(db)
    from app.core import sim_clock
    check("no clock installed after stop", sim_clock.is_simulated() is False)
    stop_audit = db.query(ForensicEvent).filter(
        ForensicEvent.run_id == "manual_sim",
        ForensicEvent.event_type == "session_stopped",
    ).count()
    check("stop audited", stop_audit == 1)

finally:
    db.close()
    engine.dispose()
    try:
        os.remove(_db_path)
    except OSError:
        pass

print("\n" + ("ALL GREEN" if not FAILS else f"FAILURES: {FAILS}"))
sys.exit(1 if FAILS else 0)
