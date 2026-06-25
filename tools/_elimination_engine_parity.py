# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
Engine parity / field-transition test for `app/services/elimination_engine.py`.

The four production cores are the SINGLE source of truth shared by the live admin
router AND the Time Machine.  This throwaway test pins their documented behaviour
so a future refactor cannot silently drift the real-money lifecycle:

    • mark_at_risk_core      — flags ONLY Active+Unpaid+late-fee'd members (never
                               Paid members or fresh joiners) → elimination_risk.
    • save_seat_core         — settles a seat-save: revenue counters incremented,
                               immutable LFC-/GF- Burned tokens written, all
                               elimination flags cleared, payment marked Paid.
    • run_elimination_cycle_core — the guillotine: expire-grace sweep, eliminate
                               Active+risk+¬grace+¬paid, one immutable
                               EliminationEvent per member (correct reason +
                               forfeiture), survivors untouched; dry_run rolls back.

SAFETY: points DATABASE_URL at a throwaway local SQLite file BEFORE importing the
app and refuses to run against any production marker (Supabase / pooler / postgres).
Run:  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python tools/_elimination_engine_parity.py
"""
import os
import sys
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal

# Ensure the repo root (parent of tools/) is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Isolate BEFORE any app import ────────────────────────────────────────────
_db_path = os.path.join(tempfile.gettempdir(), f"elim_parity_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"]    = f"sqlite:///{_db_path}"
os.environ["ENABLE_DEV_MODE"] = "true"

_url = os.environ["DATABASE_URL"].lower()
assert _url.startswith("sqlite"), f"REFUSE: not sqlite — {_url}"
for forbidden in ("supabase", "pooler", "postgres"):
    assert forbidden not in _url, f"REFUSE: production marker '{forbidden}' in URL"

from app.database import Base, engine, SessionLocal
import app.models  # registers every table on Base.metadata
from app.core import sim_clock
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.elimination_event import EliminationEvent, EliminationReason
from app.models.token import Token, TokenType, TokenStatus
from app.models.system_settings import SystemSettings
from app.services.elimination_engine import (
    _get_all_settings,
    mark_at_risk_core,
    grant_grace_core,
    save_seat_core,
    run_elimination_cycle_core,
)

Base.metadata.create_all(bind=engine)

FAILS = []
def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)

_seq = 0
def mk(db, **kw):
    """Insert a User with unique identity columns; kw overrides any field."""
    global _seq
    _seq += 1
    u = User(name=f"U{_seq}", mobile=f"90000{_seq:06d}", username=f"user{_seq}", **kw)
    db.add(u)
    db.flush()
    return u

def reset(db):
    """Wipe member/financial state between sections so counts are independent."""
    db.query(Token).delete()
    db.query(EliminationEvent).delete()
    db.query(User).delete()
    db.query(SystemSettings).filter(
        SystemSettings.key.in_([
            "revenue_late_fees_collected_inr",
            "revenue_grace_fees_collected_inr",
        ])
    ).delete(synchronize_session=False)
    db.commit()

db = SessionLocal()
try:
    settings = _get_all_settings(db)
    db.commit()
    check("settings carry the documented seat-save fee (₹500)",
          settings["grace_seat_save_fee_inr"] == 500)
    check("settings carry the documented late-fee/day (₹50)",
          settings["late_fee_per_day_inr"] == 50)

    # ─────────────────────────────────────────────────────────────────────────
    print("\n== mark_at_risk_core — flags ONLY genuine Active+Unpaid old members ==")
    reset(db)
    m1 = mk(db, status=UserStatus.Active,   weekly_payment_status=WeeklyPaymentStatus.Unpaid,
            late_fees_inr=Decimal("50"))   # at threshold → MUST flag
    m2 = mk(db, status=UserStatus.Active,   weekly_payment_status=WeeklyPaymentStatus.Unpaid,
            late_fees_inr=Decimal("0"))    # no late fee yet → must NOT flag
    m3 = mk(db, status=UserStatus.Active,   weekly_payment_status=WeeklyPaymentStatus.Paid,
            late_fees_inr=Decimal("120"))  # paid on time → must NOT flag (bug #1)
    m4 = mk(db, status=UserStatus.Waitlist, weekly_payment_status=WeeklyPaymentStatus.Unpaid,
            late_fees_inr=Decimal("120"))  # fresh joiner on waitlist → must NOT flag (bug #1)
    db.commit()

    newly = mark_at_risk_core(db, settings)
    db.commit()
    for u in (m1, m2, m3, m4):
        db.refresh(u)
    check("exactly ONE newly flagged", newly == 1)
    check("Active+Unpaid+late-fee member flagged at-risk", m1.elimination_risk is True)
    check("Active+Unpaid with no late fee NOT flagged",     m2.elimination_risk is False)
    check("Paid-on-time member NOT flagged (bug #1)",       m3.elimination_risk is False)
    check("Waitlist joiner NOT flagged (bug #1)",           m4.elimination_risk is False)

    # ─────────────────────────────────────────────────────────────────────────
    print("\n== save_seat_core — revenue + tokens + flag clearing ==")
    reset(db)
    s = mk(db, status=UserStatus.Active, weekly_payment_status=WeeklyPaymentStatus.Unpaid,
           late_fees_inr=Decimal("300"), elimination_risk=True, grace_active=True,
           grace_expires_at=sim_clock.now() + timedelta(hours=5), grace_fee_paid=False)
    db.commit()

    res = save_seat_core(db, s, settings)
    db.commit()
    db.refresh(s)
    check("save returns grace fee ₹500",        res["grace_fee_paid_inr"] == 500)
    check("save returns late fees cleared ₹300", abs(res["late_fees_cleared"] - 300.0) < 1e-9)
    check("save returns total paid ₹800",        abs(res["total_paid_inr"] - 800.0) < 1e-9)
    check("seat saved → grace_fee_paid True",    s.grace_fee_paid is True)
    check("seat saved → grace_active False",     s.grace_active is False)
    check("seat saved → grace_expires_at None",  s.grace_expires_at is None)
    check("seat saved → elimination_risk False", s.elimination_risk is False)
    check("seat saved → late_fees_inr 0",        float(s.late_fees_inr) == 0.0)
    check("seat saved → weekly_payment_status Paid",
          s.weekly_payment_status == WeeklyPaymentStatus.Paid)

    rev_late  = db.query(SystemSettings).filter(SystemSettings.key == "revenue_late_fees_collected_inr").first()
    rev_grace = db.query(SystemSettings).filter(SystemSettings.key == "revenue_grace_fees_collected_inr").first()
    check("late-fee revenue counter += 300",  rev_late is not None and rev_late.value_int == 300)
    check("grace-fee revenue counter += 500",  rev_grace is not None and rev_grace.value_int == 500)

    toks = db.query(Token).filter(Token.user_id == s.id).all()
    lfc = [t for t in toks if t.code.startswith("LFC-")]
    gf  = [t for t in toks if t.code.startswith("GF-")]
    check("one LFC- Late_Fee token, Burned, ₹300",
          len(lfc) == 1 and lfc[0].type == TokenType.Late_Fee
          and lfc[0].status == TokenStatus.Burned and float(lfc[0].value_inr) == 300.0)
    check("one GF- Grace_Fee token, Burned, ₹500",
          len(gf) == 1 and gf[0].type == TokenType.Grace_Fee
          and gf[0].status == TokenStatus.Burned and float(gf[0].value_inr) == 500.0)

    # ─────────────────────────────────────────────────────────────────────────
    print("\n== run_elimination_cycle_core — dry-run reports + rolls back ==")
    reset(db)
    now = sim_clock.now()
    # A = non_payment   B = grace_expired   C = saved   D = active-grace (pending)   E = paid
    a = mk(db, status=UserStatus.Active, weekly_payment_status=WeeklyPaymentStatus.Unpaid,
           late_fees_inr=Decimal("200"), elimination_risk=True,  grace_active=False, grace_fee_paid=False)
    b = mk(db, status=UserStatus.Active, weekly_payment_status=WeeklyPaymentStatus.Unpaid,
           late_fees_inr=Decimal("150"), elimination_risk=True,  grace_active=True,  grace_fee_paid=False,
           grace_expires_at=now - timedelta(hours=1))           # window lapsed
    c = mk(db, status=UserStatus.Active, weekly_payment_status=WeeklyPaymentStatus.Paid,
           late_fees_inr=Decimal("0"),   elimination_risk=False, grace_active=False, grace_fee_paid=True)
    d = mk(db, status=UserStatus.Active, weekly_payment_status=WeeklyPaymentStatus.Unpaid,
           late_fees_inr=Decimal("100"), elimination_risk=True,  grace_active=True,  grace_fee_paid=False,
           grace_expires_at=now + timedelta(hours=5))           # window still open
    e = mk(db, status=UserStatus.Active, weekly_payment_status=WeeklyPaymentStatus.Paid,
           late_fees_inr=Decimal("0"),   elimination_risk=False, grace_active=False, grace_fee_paid=False)
    db.commit()

    dry = run_elimination_cycle_core(db, settings, dry_run=True)
    check("dry-run would_eliminate == 2 (A + B)",        dry["would_eliminate"] == 2)
    check("dry-run grace_expired_count == 1 (B only)",   dry["grace_expired_count"] == 1)
    check("dry-run reason split 1 non_payment / 1 grace_expired",
          dry["reason_non_payment"] == 1 and dry["reason_grace_expired"] == 1)
    check("dry-run eliminated_count == 0 (report only)", dry["eliminated_count"] == 0)
    check("dry-run wrote NO EliminationEvent rows",
          db.query(EliminationEvent).count() == 0)
    for u in (a, b, c, d, e):
        db.refresh(u)
    check("dry-run left every member untouched (all still Active)",
          all(u.status == UserStatus.Active for u in (a, b, c, d, e)))
    check("dry-run rolled back B's grace sweep (grace_active still True)",
          b.grace_active is True)

    # ─────────────────────────────────────────────────────────────────────────
    print("\n== run_elimination_cycle_core — real guillotine ==")
    real = run_elimination_cycle_core(db, settings, dry_run=False)
    db.commit()
    for u in (a, b, c, d, e):
        db.refresh(u)

    check("eliminated_count == 2 (A + B)",                real["eliminated_count"] == 2)
    check("reason_non_payment == 1 (A)",                  real["reason_non_payment"] == 1)
    check("reason_grace_expired == 1 (B)",                real["reason_grace_expired"] == 1)
    check("grace_expired_count == 1 (B swept, D not)",    real["grace_expired_count"] == 1)
    # A: 1000 + 200 + 0 = 1200   B: 1000 + 150 + 500 = 1650   → 2850
    check("total_forfeited_inr == 2850 (A 1200 + B 1650)",
          abs(real["total_forfeited_inr"] - 2850.0) < 1e-9)
    check("A eliminated (non_payment)",      a.status == UserStatus.Eliminated)
    check("A removed from pool",             a.current_pool_id is None)
    check("B eliminated (grace_expired)",    b.status == UserStatus.Eliminated)
    check("C (seat-saved/Paid) survives Active",  c.status == UserStatus.Active)
    check("D (grace still open) survives Active",  d.status == UserStatus.Active)
    check("E (paid on time) survives Active",      e.status == UserStatus.Active)

    evs = db.query(EliminationEvent).all()
    by_user = {ev.user_id: ev for ev in evs}
    check("exactly 2 immutable EliminationEvent rows", len(evs) == 2)
    check("A event reason non_payment, not in grace, ₹1200",
          a.id in by_user and by_user[a.id].reason == EliminationReason.non_payment
          and by_user[a.id].was_in_grace_period is False
          and float(by_user[a.id].total_forfeited) == 1200.0)
    check("B event reason grace_expired, was in grace, seat_save 500, ₹1650",
          b.id in by_user and by_user[b.id].reason == EliminationReason.grace_expired
          and by_user[b.id].was_in_grace_period is True
          and float(by_user[b.id].seat_save_fee) == 500.0
          and float(by_user[b.id].total_forfeited) == 1650.0)

    # Bug #2 close — after the guillotine, NO member is Active-AND-Unpaid except those
    # still inside an OPEN grace window (D).  A & B (both lapsed/never-grace) are gone.
    active_unpaid_no_grace = db.query(User).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
        User.grace_active == False,   # noqa: E712
    ).count()
    check("bug #2: 0 Active+Unpaid members remain outside an open grace window",
          active_unpaid_no_grace == 0)

finally:
    db.close()
    engine.dispose()
    try:
        os.remove(_db_path)
    except OSError:
        pass

print("\n" + ("ALL GREEN" if not FAILS else f"FAILURES: {FAILS}"))
sys.exit(1 if FAILS else 0)
