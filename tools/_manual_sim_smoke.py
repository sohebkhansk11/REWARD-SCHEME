"""
Throwaway smoke check for the Manual Event-Timeline Simulator backend core.
SAFETY: points DATABASE_URL at a throwaway local SQLite file BEFORE importing the
app and asserts the backend is sqlite (never the shared Supabase production DB).
Run:  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python tools/_manual_sim_smoke.py
"""
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

# Ensure the repo root (parent of tools/) is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Isolate BEFORE any app import ────────────────────────────────────────────
_db_path = os.path.join(tempfile.gettempdir(), f"manualsim_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"]     = f"sqlite:///{_db_path}"
os.environ["ENABLE_DEV_MODE"]  = "true"

_url = os.environ["DATABASE_URL"].lower()
assert _url.startswith("sqlite"), f"REFUSE: not sqlite — {_url}"
for forbidden in ("supabase", "pooler", "postgres"):
    assert forbidden not in _url, f"REFUSE: production marker '{forbidden}' in URL"

from app.database import Base, engine, SessionLocal
import app.models  # registers every table on Base.metadata
from app.services import manual_sim

Base.metadata.create_all(bind=engine)

FAILS = []
def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)

db = SessionLocal()
try:
    print("\n== start_session ==")
    st = manual_sim.start_session(db, link_global=True, ttl_hours=6)
    check("session active", st.get("active") is True)
    check("starts at CYCLE_START", st.get("current_event") == "CYCLE_START")
    check("cycle_num == 1", st.get("cycle_num") == 1)
    check("link_global true", st.get("link_global") is True)
    check("watch has day", bool(st.get("day_of_week")))
    check("timeline has 7 events", len(st.get("events", [])) == 7)
    check("snapshot present", "snapshot" in st)

    print("\n== monotonic jump-next across two full cycles ==")
    seq = [st["current_event"]]
    times = [st["sim_now"]]
    cycles = [st["cycle_num"]]
    for _ in range(13):  # 6 to T_05M, rollover, then 6 more
        st = manual_sim.jump_next(db)
        seq.append(st["current_event"])
        times.append(st["sim_now"])
        cycles.append(st["cycle_num"])

    parsed = [datetime.fromisoformat(t) for t in times]
    monotonic = all(parsed[i] <= parsed[i + 1] for i in range(len(parsed) - 1))
    check("simulated time strictly non-decreasing", monotonic)
    check("cycle 1 walks full spine", seq[:7] == list(manual_sim.EVENT_SPINE))
    check("rollover increments cycle", max(cycles) >= 2)
    check("rollover lands on DUE_DATE", seq[7] == "DUE_DATE")
    print("   event sequence:", " -> ".join(seq))
    print("   cycle numbers  :", cycles)

    print("\n== jump-to forward-only guard ==")
    manual_sim.stop_session(db)
    manual_sim.start_session(db, ttl_hours=6)          # back to CYCLE_START
    st = manual_sim.jump_to(db, "T_02H")
    check("forward jump-to works", st["current_event"] == "T_02H")
    backward_rejected = False
    try:
        manual_sim.jump_to(db, "DUE_DATE")
    except manual_sim.ManualSimError:
        backward_rejected = True
    check("backward jump rejected", backward_rejected)

    print("\n== stop_session ==")
    out = manual_sim.stop_session(db)
    check("stopped", out.get("stopped") is True)
    from app.core import sim_clock
    check("no clock installed after stop", sim_clock.is_simulated() is False)
    st = manual_sim.compute_state(db)
    check("state inactive after stop", st.get("active") is False)

    print("\n== dev-mode gate ==")
    os.environ["ENABLE_DEV_MODE"] = "false"
    refused = False
    try:
        manual_sim.manual_clock(datetime.now(timezone.utc)).__enter__()
    except RuntimeError:
        refused = True
    check("manual_clock refuses without dev mode", refused)
    os.environ["ENABLE_DEV_MODE"] = "true"

finally:
    db.close()
    engine.dispose()
    try:
        os.remove(_db_path)
    except OSError:
        pass

print("\n" + ("ALL GREEN" if not FAILS else f"FAILURES: {FAILS}"))
sys.exit(1 if FAILS else 0)
