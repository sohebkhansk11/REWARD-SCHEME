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

    out = dev.manual_sim_action_inject(dev.ManualSimInjectRequest(count=24), db)
    check("inject ran", out["action"] == "inject_users")
    check("24 users injected", out["result"]["injected"] == 24)
    check("pools formed from injection", out["result"]["pools_formed"] >= 1)
    print("   inject result:", out["result"])

    print("\n== event->action guard (pay-all before DUE_DATE) ==")
    guard_409 = False
    try:
        dev.manual_sim_action_pay_all(db)
    except HTTPException as exc:
        guard_409 = (exc.status_code == 409)
    check("pay-all rejected at CYCLE_START (409)", guard_409)

    print("\n== DUE_DATE: set-late / pay-all / pay-remaining ==")
    manual_sim.jump_to(db, "DUE_DATE")
    out = dev.manual_sim_action_set_late(dev.ManualSimSetLateRequest(late_pct=20.0), db)
    check("set-late stored ratio 0.2", abs(out["result"]["late_ratio"] - 0.2) < 1e-9)
    out = dev.manual_sim_action_pay_all(db)
    check("pay-all ran", "installments_paid" in out["result"])
    out = dev.manual_sim_action_pay_remaining(db)
    check("pay-remaining ran", "remaining_paid" in out["result"])

    print("\n== GRACE_PERIOD_START: A/B/C settlement ==")
    manual_sim.jump_to(db, "GRACE_PERIOD_START")
    out = dev.manual_sim_action_grace_settle(
        dev.ManualSimGraceRequest(late_pct=30.0, elim_pct_a=50.0, grace_pct_c=40.0), db)
    r = out["result"]
    check("grace settlement ran", "late_payers" in r)
    check("B + grace-no-fee accounts for all late",
          r["paid_late_fee_B"] + r["entered_grace_no_fee"] == r["late_payers"])
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

    print("\n== rollover then stop ==")
    st = manual_sim.jump_next(db)            # T_05M -> next cycle DUE_DATE
    check("rolled into cycle 2", st["cycle_num"] == 2 and st["current_event"] == "DUE_DATE")
    manual_sim.stop_session(db)
    from app.core import sim_clock
    check("no clock installed after stop", sim_clock.is_simulated() is False)

finally:
    db.close()
    engine.dispose()
    try:
        os.remove(_db_path)
    except OSError:
        pass

print("\n" + ("ALL GREEN" if not FAILS else f"FAILURES: {FAILS}"))
sys.exit(1 if FAILS else 0)
