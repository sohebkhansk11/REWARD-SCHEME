"""
Smoke check for the Manual Event-Timeline Simulator ("Time Machine") ACTION
endpoints — REWRITTEN for the production-faithful payment-state lifecycle.

# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
This walks TWO full cycles through the real FastAPI route functions and asserts the
three reported real-money bugs are fixed end-to-end:

  • Bug #1 — fresh joiners / paid members are NEVER enforced.  At cycle-2 due-date
    we inject NEW members (who join Paid) and prove the set-late cohort is drawn
    ONLY from the genuine carried-forward Active+Unpaid set — never a paid member.
  • Bug #2 — carry-forward + no circular loop + no unpaid-active-after-close.  We
    roll cycle 1 → cycle 2 and prove survivors reset to Unpaid (carry-forward); the
    grace A/B/C split acts ONLY on the real at-risk cohort (A+B+C == at_risk); the
    G_CLOSE guillotine eliminates A (non_payment) + B (grace_expired), C survives,
    and afterwards NO member is left Active-AND-Unpaid.
  • Bug #3 — a member who joins during the draw window stays on the waitlist.  An
    inject at T_02H returns pools_formed == 0 / held_on_waitlist == True and the
    joiners remain Waitlist (roster frozen at G_CLOSE).

The original event→action gating / mutual-exclusion lock / compliance-panel /
task-list / TTL / link-toggle / forensic-audit assertions are preserved.

SAFETY: points DATABASE_URL at a throwaway local SQLite file BEFORE importing the
app and refuses to run against any production marker (Supabase / pooler / postgres).
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
from app.models.user import User, UserStatus, WeeklyPaymentStatus

Base.metadata.create_all(bind=engine)

FAILS = []
def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)

# ── DB-state helpers (read straight from the production tables) ───────────────
def active_unpaid_ids(db):
    return {r[0] for r in db.query(User.id).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
    ).all()}

def active_paid_ids(db):
    return {r[0] for r in db.query(User.id).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Paid,
    ).all()}

def active_at_risk_paid_ids(db):
    """Active + Paid + still flagged at-risk — must ALWAYS be empty (bug #1)."""
    return {r[0] for r in db.query(User.id).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        User.elimination_risk.is_(True),
    ).all()}

def all_user_ids(db):
    return {r[0] for r in db.query(User.id).all()}

def walk_to_rollover(db):
    """Drive the rest of THIS cycle (grace → G_CLOSE → draw → cleanup) doing the
    minimum required action at each event, then jump_next to roll into the next
    cycle's DUE_DATE.  Used to advance cycle 1 into cycle 2.  Each action is run
    AT the event that offers it (the server hard-gates action→event)."""
    manual_sim.jump_to(db, "GRACE_PERIOD_START")
    dev.manual_sim_action_grace_settle(
        dev.ManualSimGraceRequest(late_pct=None, elim_pct_a=0.0, grace_pct_c=0.0), db)
    manual_sim.jump_to(db, "G_CLOSE")
    dev.manual_sim_action_finalize_eliminations(db)
    manual_sim.jump_to(db, "T_02H")
    dev.manual_sim_action_prepare_draw(db)
    manual_sim.jump_to(db, "T_00H")
    dev.manual_sim_action_execute_draw(db)
    manual_sim.jump_to(db, "T_05M")
    dev.manual_sim_action_cleanup(db)
    return manual_sim.jump_next(db)   # T_05M → next cycle DUE_DATE

db = SessionLocal()
try:
    print("\n== CYCLE 1 — start + inject at CYCLE_START ==")
    st = manual_sim.start_session(db, ttl_hours=6)
    check("starts at CYCLE_START", st["current_event"] == "CYCLE_START")

    inj = dev.manual_sim_action_inject(dev.ManualSimInjectRequest(count=36), db)
    check("inject ran", inj["action"] == "inject_users")
    check("36 users injected", inj["result"]["injected"] == 36)
    check("pools_formed is a non-negative int (production-gated, no override)",
          isinstance(inj["result"]["pools_formed"], int) and inj["result"]["pools_formed"] >= 0)
    check("inject window surfaced (date never overridden)",
          bool(inj["result"].get("window_start")) and bool(inj["result"].get("window_end")))
    check("inject held_on_waitlist False before draw window",
          inj["result"].get("held_on_waitlist") is False)

    comp0 = manual_sim.compute_state(db)["compliance"]
    check("#6: every injected user accounted for (active + waitlist == 36, no loss)",
          comp0["active"] + comp0["waitlist"] == 36)
    check("#6: pools form only as full 12-member batches (production gate, no instant-drain)",
          comp0["active"] == 12 * inj["result"]["pools_formed"])
    check("cycle-1 pools actually formed (need Active members to drive the lifecycle)",
          comp0["active"] >= 12)
    print(f"   cycle-1: active={comp0['active']}  waitlist={comp0['waitlist']}  "
          f"pools_formed={inj['result']['pools_formed']}")

    print("\n== event->action guard (pay-all before DUE_DATE) ==")
    guard_409 = False
    try:
        dev.manual_sim_action_pay_all(db)
    except HTTPException as exc:
        guard_409 = (exc.status_code == 409)
    check("pay-all rejected at CYCLE_START (409)", guard_409)

    print("\n== CYCLE 1 DUE_DATE — pay-all (members just joined Paid) + lock ==")
    manual_sim.jump_to(db, "DUE_DATE")
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

    dev.manual_sim_action_pay_all(db)
    state_paid = manual_sim.compute_state(db)
    check("can advance after pay-all (gate open)", state_paid["can_advance"] is True)
    check("pay-all dims set_late_pct + pay_remaining (locked, no overwrite)",
          "set_late_pct" in state_paid["disabled_actions"]
          and "pay_remaining" in state_paid["disabled_actions"])

    print("\n== CYCLE 1 → CYCLE 2 rollover (carry-forward reset) ==")
    active_c1 = manual_sim.compute_state(db)["compliance"]["active"]
    st2 = walk_to_rollover(db)
    check("rolled into cycle 2 at DUE_DATE",
          st2["cycle_num"] == 2 and st2["current_event"] == "DUE_DATE")
    comp_due2 = manual_sim.compute_state(db)["compliance"]
    carried = comp_due2["active"]
    check("survivors carried forward (>=3 Active members to settle)", carried >= 3)
    check("bug #2 carry-forward: EVERY surviving Active member reset to Unpaid",
          comp_due2["unpaid"] == carried and comp_due2["paid_on_time"] == 0)
    check("bug #2 carry-forward: no stale at-risk / grace flags survive the reset",
          comp_due2["at_risk"] == 0 and comp_due2["grace_active"] == 0)
    print(f"   cycle-2 due-date: carried Active(Unpaid)={carried}")

    print("\n== CYCLE 2 DUE_DATE — inject fresh joiners, then set-late (bug #1) ==")
    unpaid_before = active_unpaid_ids(db)            # the carried cohort
    ids_before_inj2 = all_user_ids(db)
    # Inject a batch large enough to clear the AI-reserve gate so some joiners are
    # placed into REAL pools as Active+Paid — the genuine bug-#1 test population
    # ("new member paid their fees" must NEVER be enforced at due date).
    inj2 = dev.manual_sim_action_inject(dev.ManualSimInjectRequest(count=48), db)
    check("cycle-2 mid-window inject ran (before draw window)",
          inj2["result"].get("held_on_waitlist") is False)
    pools_formed2 = inj2["result"]["pools_formed"]
    fresh_ids = all_user_ids(db) - ids_before_inj2
    check("all 48 fresh joiners materialised", len(fresh_ids) == 48)
    check("bug #1 precondition: every fresh joiner joined PAID (not Unpaid)",
          {r[0] for r in db.query(User.id).filter(
              User.id.in_(fresh_ids),
              User.weekly_payment_status == WeeklyPaymentStatus.Paid).all()} == fresh_ids)
    fresh_active_paid = active_paid_ids(db) & fresh_ids
    fresh_waitlist = {r[0] for r in db.query(User.id).filter(
        User.id.in_(fresh_ids), User.status == UserStatus.Waitlist).all()}
    check("every fresh joiner accounted for as Active+Paid (pooled/vacancy-filled) "
          "or Waitlist+Paid (held) — none lost, none Unpaid",
          len(fresh_active_paid) + len(fresh_waitlist) == 48)
    check("production gate placed ≥ 12 × newly-formed pools of fresh joiners (no override)",
          len(fresh_active_paid) >= 12 * pools_formed2)
    check("real Active+Paid joiners exist to exercise the strong bug-#1 path",
          len(fresh_active_paid) >= 1)
    print(f"   cycle-2 inject: pools_formed={pools_formed2}  "
          f"fresh_active_paid={len(fresh_active_paid)}  fresh_waitlist={len(fresh_waitlist)}")

    out = dev.manual_sim_action_set_late(dev.ManualSimSetLateRequest(late_pct=40.0), db)
    r = out["result"]
    expect_late = int(round(carried * 0.40))
    late_ids = set(r["late_cohort_ids"])
    check("set-late counted ONLY the carried Active+Unpaid members (fresh Paid excluded)",
          r["unpaid_members"] == carried)
    check("set-late selected exactly round(carried × 40%)", r["late_selected"] == expect_late)
    check("set-late flagged exactly the late cohort at-risk",
          r["newly_at_risk"] == expect_late)
    check("bug #1: late cohort is a subset of the carried Unpaid members",
          late_ids.issubset(unpaid_before))
    check("bug #1: NOT ONE fresh joiner (pooled or waitlisted) is in the late cohort",
          late_ids.isdisjoint(fresh_ids))
    check("bug #1: NO Active+Paid member is ever flagged at-risk (incl. fresh pooled joiners)",
          len(active_at_risk_paid_ids(db)) == 0)
    print(f"   set-late: unpaid={r['unpaid_members']}  late_selected={r['late_selected']}  "
          f"accrued=₹{r['late_fee_accrued_inr']}")

    # Lock: set-late dims pay-all (a cycle with a late cohort cannot be "everyone paid").
    state_late = manual_sim.compute_state(db)
    check("set-late dims pay_all_installments (no overwrite)",
          "pay_all_installments" in state_late["disabled_actions"])
    check("still cannot advance — stragglers must pay (can_advance False)",
          state_late["can_advance"] is False)

    print("\n== CYCLE 2 DUE_DATE — pay-remaining (late cohort carries forward) ==")
    out = dev.manual_sim_action_pay_remaining(db)
    pr = out["result"]
    check("pay-remaining settled the NON-late stragglers",
          pr["remaining_paid"] == (carried - expect_late))
    check("pay-remaining HELD the late cohort (carry-forward)",
          pr["late_cohort_held"] == expect_late)
    comp_after_pr = manual_sim.compute_state(db)["compliance"]
    check("only the late cohort remains Unpaid + at-risk",
          comp_after_pr["unpaid"] == expect_late and comp_after_pr["at_risk"] == expect_late)
    check("can advance after the due-date is fully settled",
          manual_sim.compute_state(db)["can_advance"] is True)

    print("\n== CYCLE 2 GRACE — A/B/C settlement on the REAL at-risk cohort ==")
    manual_sim.jump_to(db, "GRACE_PERIOD_START")
    paid_active_before_grace = active_paid_ids(db)
    out = dev.manual_sim_action_grace_settle(
        dev.ManualSimGraceRequest(late_pct=None, elim_pct_a=50.0, grace_pct_c=25.0), db)
    g = out["result"]
    at_risk = g["at_risk"]
    n_a = min(at_risk, int(at_risk * 50.0 / 100.0))
    n_c = min(at_risk - n_a, int(at_risk * 25.0 / 100.0))
    n_b = at_risk - n_a - n_c
    check("grace settlement acted on the carried at-risk cohort", at_risk == expect_late)
    check("A/B/C buckets match the deterministic clamping split",
          g["eliminate_pending_A"] == n_a and g["grace_saved_C"] == n_c
          and g["grace_pending_B"] == n_b)
    check("ABC invariant A+B+C == at_risk",
          g["eliminate_pending_A"] + g["grace_saved_C"] + g["grace_pending_B"] == at_risk)
    check("buckets_reconcile flag is True", g["buckets_reconcile"] is True)
    check("misleading entered_grace_no_fee field removed", "entered_grace_no_fee" not in g)
    check("bug #2: members who already paid are untouched by the A/B/C split",
          active_paid_ids(db).issuperset(paid_active_before_grace))
    print(f"   grace: at_risk={at_risk}  A={g['eliminate_pending_A']}  "
          f"C={g['grace_saved_C']}  B={g['grace_pending_B']}  "
          f"revenue=₹{g['total_compliance_revenue_inr']}")

    print("\n== CYCLE 2 G_CLOSE — the REAL guillotine (mutating, no longer read-only) ==")
    manual_sim.jump_to(db, "G_CLOSE")
    out = dev.manual_sim_action_finalize_eliminations(db)
    f = out["result"]
    check("finalize is NOT read-only (real guillotine)", f["read_only"] is False)
    check("eliminated A (non_payment) + B (grace_expired)",
          f["eliminated_this_cycle"] == n_a + n_b)
    check("reason split: A → non_payment", f["reason_non_payment"] == n_a)
    check("reason split: B → grace_expired", f["reason_grace_expired"] == n_b)
    check("seats_refilled surfaced as an int", isinstance(f["seats_refilled"], int))
    # Bug #2 CLOSE — after the guillotine NO member is left Active-AND-Unpaid.
    comp_close = manual_sim.compute_state(db)["compliance"]
    check("bug #2 close: 0 Active+Unpaid members remain after grace window closes",
          comp_close["unpaid"] == 0)
    check("bug #2 close: 0 members left at-risk / in grace",
          comp_close["at_risk"] == 0 and comp_close["grace_active"] == 0)
    print(f"   finalize: eliminated={f['eliminated_this_cycle']}  "
          f"non_payment={f['reason_non_payment']}  grace_expired={f['reason_grace_expired']}  "
          f"forfeited=₹{f['total_forfeited_inr']}  refilled={f['seats_refilled']}")

    print("\n== CYCLE 2 T_02H — draw-window inject stays on waitlist (bug #3) ==")
    manual_sim.jump_to(db, "T_02H")
    wl_before = manual_sim.compute_state(db)["compliance"]["waitlist"]
    inj3 = dev.manual_sim_action_inject(dev.ManualSimInjectRequest(count=8), db)
    i3 = inj3["result"]
    check("bug #3: draw-window inject forms NO pool", i3["pools_formed"] == 0)
    check("bug #3: draw-window joiners are held on the waitlist", i3["held_on_waitlist"] is True)
    check("bug #3: a held-on-waitlist note is surfaced", bool(i3.get("note")))
    wl_after = manual_sim.compute_state(db)["compliance"]["waitlist"]
    check("bug #3: all 8 joiners landed on the waitlist (none drawn into a pool)",
          wl_after - wl_before == 8)
    print(f"   draw-window inject: injected={i3['injected']}  pools_formed={i3['pools_formed']}  "
          f"waitlist {wl_before}→{wl_after}")

    # Satisfy T_02H so the timeline stays consistent (prepare the draw).
    dev.manual_sim_action_prepare_draw(db)

    print("\n== Phase 4 — TTL / link toggle / forensic audit ==")
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

    print("\n== stop ==")
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
