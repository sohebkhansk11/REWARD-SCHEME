"""
Production Elimination Engine  —  shared, time-source-agnostic cores
====================================================================

# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
This module is the SINGLE source of truth for the non-payment enforcement
lifecycle.  The four cores below were extracted VERBATIM (field-transition for
field-transition) from `app/routers/admin_elimination.py` so that BOTH callers —

  • the live admin router  (`/admin/elimination/*`, real UTC wall-clock), and
  • the Time Machine        (`/dev/manual-sim/*`,  simulated Chronos clock)

— execute the EXACT same production logic on the EXACT same real member state.
Zero duplication, zero synthetic re-sampling, fully production-code-driven.

The ONLY behavioural difference from the original router code is the time source:
every "now" is read through `sim_clock.now()` instead of `datetime.now(utc)`.
`sim_clock.now()` returns the **simulated** instant when a ChronosEngine is active
(inside `manual_clock()`), and the **real UTC** wall-clock in production — so the
live admin path is byte-for-byte unchanged while the Time Machine drives the same
code at the simulated instant.  (`admin_elimination.py` is intentionally NOT in
`real_simulation._TIME_PATCHED`; routing its time reads through `sim_clock.now()`
here is precisely what lets the simulated clock reach the elimination lifecycle.)

Authoritative lifecycle (app/models/user.py:82-93):
    unpaid past due  →  elimination_risk=True
                     →  grace opens (grace_active=True, grace_expires_at set)
                     →  T-2H grace closes
                     →  eliminate ALL (risk=True AND grace_active=False)

Transaction contract:
    Cores FLUSH (so subsequent same-transaction queries observe the writes) but do
    NOT commit — the CALLER owns the commit.  The single exception is the real
    (non-dry-run) `run_elimination_cycle_core`, whose final `assign_waitlist_to_pools`
    refill commits internally (production waitlist engine) — by then every
    EliminationEvent row + user mutation is already part of that committed unit.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import sim_clock
from app.models.elimination_event import EliminationEvent, EliminationReason
from app.models.pool import Pool
from app.models.system_settings import SystemSettings
from app.models.token import Token, TokenType, TokenStatus
from app.models.user import User, UserStatus, WeeklyPaymentStatus


# ── Default elimination configuration ─────────────────────────────────────────
# Each key is stored as a SystemSettings row so admins can tune them via the API
# without a code change.  (Moved here from admin_elimination.py so there is ONE
# canonical definition; the router re-imports these names.)
_ELIM_DEFAULTS: dict[str, int] = {
    "payment_due_days":        4,     # days from Monday (draw opens) until due date (Thursday)
    "payment_due_hour":        23,    # 23:00 IST on due day (= 17:30 UTC)
    "grace_period_hours":      48,    # hours between due date and draw T-2H
    "grace_seat_save_fee_inr": 500,   # extra ₹ to pay during grace to save seat
    "late_fee_per_day_inr":    50,    # daily late fee accrual
    "late_fee_max_cap_inr":    500,   # maximum total late fee (caps at ₹500)
    "auto_eliminate_enabled":  1,     # 1=True, 0=False — auto-eliminate on due date
    "grace_period_enabled":    1,     # 1=True, 0=False — allow grace period saving
}

_BOOL_KEYS = {"auto_eliminate_enabled", "grace_period_enabled"}


# ── Settings helpers (lazy-init defaults) ─────────────────────────────────────

def _get_setting(db: Session, key: str) -> int:
    """
    Return the integer value of a settings key, creating the row with the
    default value if it does not exist yet.  Lazy-initialises on first read.
    """
    row: SystemSettings | None = (
        db.query(SystemSettings).filter(SystemSettings.key == key).first()
    )
    if row is None:
        default_val = _ELIM_DEFAULTS.get(key, 0)
        row = SystemSettings(key=key, value_int=default_val)
        db.add(row)
        db.flush()
    return row.value_int if row.value_int is not None else _ELIM_DEFAULTS.get(key, 0)


def _get_all_settings(db: Session) -> dict[str, int]:
    """Return all 8 elimination settings as a dict, lazy-creating defaults."""
    return {k: _get_setting(db, k) for k in _ELIM_DEFAULTS}


# ── Collision-safe compliance-token code generator ────────────────────────────

def _unique_compliance_code(db: Session, prefix: str) -> str:
    """
    Collision-safe token code generator for Grace_Fee and Late_Fee settlement tokens.
    Format: "{prefix}{6 uppercase alphanumeric chars}"  e.g. "GF-7MNQ2X"
    Uses os.urandom via secrets — cryptographically random, not MT19937.
    """
    import secrets, string
    from app.crud.token import get_token_by_code
    _alpha = string.ascii_uppercase + string.digits
    while True:
        code = prefix + "".join(secrets.choice(_alpha) for _ in range(6))
        if not get_token_by_code(db, code):
            return code


# ── Core 1 — mark-at-risk ─────────────────────────────────────────────────────

def mark_at_risk_core(db: Session, settings: dict[str, int]) -> int:
    """
    Extracted from `admin_elimination.mark_at_risk` (:434).

    Flag every Active member who is currently Unpaid AND has accumulated late
    fees ≥ one day's late fee (a safe proxy for "payment_due_days have passed")
    AND is not already flagged → set elimination_risk=True.

    FLUSHES (does not commit).  Returns the count of newly-flagged members.
    """
    min_fee = settings.get("late_fee_per_day_inr", 50)

    candidates = (
        db.query(User)
        .filter(
            User.status                == UserStatus.Active,
            User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
            User.late_fees_inr         >= min_fee,
            User.elimination_risk      == False,   # noqa: E712
        )
        .all()
    )

    newly_flagged = 0
    for u in candidates:
        u.elimination_risk = True
        newly_flagged += 1

    if newly_flagged:
        db.flush()

    return newly_flagged


# ── Core 2 — grant grace ──────────────────────────────────────────────────────

def grant_grace_core(
    db:         Session,
    user:       User,
    *,
    hours:      Optional[int]      = None,
    expires_at=None,
    settings:   Optional[dict]     = None,
) -> None:
    """
    Extracted from `admin_elimination.grant_grace_period` (:488), validation
    stripped (the caller is responsible for eligibility checks / responses).

    Opens a grace window on `user`:
      grace_active     = True
      grace_expires_at = expires_at  (explicit instant — used by the Time Machine,
                         which passes the G_CLOSE milestone)
                         OR  sim_clock.now() + hours   (admin router path)
      grace_fee_paid   = False        (must pay grace fee to save seat)
      elimination_risk = True         (remains at-risk until grace fee paid)

    Exactly ONE of `expires_at` / `hours` is required.  When neither is supplied
    the configured grace_period_hours is used.  FLUSHES (does not commit).
    """
    if expires_at is not None:
        grace_expires = expires_at
    else:
        if hours is None:
            cfg = settings if settings is not None else _get_all_settings(db)
            hours = cfg.get("grace_period_hours", 48)
        grace_expires = sim_clock.now() + timedelta(hours=hours)

    user.grace_active     = True
    user.grace_expires_at = grace_expires
    user.grace_fee_paid   = False   # must pay grace fee to save seat
    user.elimination_risk = True    # remains at-risk until grace fee paid

    db.flush()


# ── Core 3 — save seat (confirm grace payment) ────────────────────────────────

def save_seat_core(db: Session, user: User, settings: dict[str, int]) -> dict:
    """
    Extracted from `admin_elimination.confirm_grace_payment` (:550), the part
    AFTER the admin-password check (the caller owns auth).  Records the seat-save
    financial transaction:

      • Increments cumulative revenue counters
        (revenue_late_fees_collected_inr / revenue_grace_fees_collected_inr).
      • Writes immutable Burned compliance tokens (LFC- Late_Fee, GF- Grace_Fee).
      • Clears all elimination flags and settles payment:
            grace_fee_paid=True, grace_active=False, grace_expires_at=None,
            elimination_risk=False, late_fees_inr=0, weekly_payment_status=Paid.

    FLUSHES (does not commit).  Returns the settlement summary dict.
    """
    late_fees_cleared = float(user.late_fees_inr or 0)
    grace_fee_inr     = settings["grace_seat_save_fee_inr"]
    total_paid        = grace_fee_inr + late_fees_cleared

    # ── Track collected revenue BEFORE clearing the fields ────────────────────
    def _increment_revenue(key: str, amount: float) -> None:
        """Atomically add `amount` (rounded to nearest rupee) to a revenue counter."""
        amt_int = int(round(amount))
        if amt_int <= 0:
            return
        row: SystemSettings | None = (
            db.query(SystemSettings).filter(SystemSettings.key == key).first()
        )
        if row is None:
            row = SystemSettings(key=key, value_int=amt_int)
            db.add(row)
        else:
            row.value_int = (row.value_int or 0) + amt_int

    _increment_revenue("revenue_late_fees_collected_inr",  late_fees_cleared)
    _increment_revenue("revenue_grace_fees_collected_inr", grace_fee_inr)

    # ── Create immutable compliance tokens (receipt / audit trail) ────────────
    if late_fees_cleared > 0:
        lf_code = _unique_compliance_code(db, "LFC-")   # LFC = Late Fee Collected
        db.add(Token(
            code      = lf_code,
            type      = TokenType.Late_Fee,
            status    = TokenStatus.Burned,
            value_inr = Decimal(str(int(round(late_fees_cleared)))),
            user_id   = user.id,
            pool_id   = user.current_pool_id,
        ))

    gf_code = _unique_compliance_code(db, "GF-")
    db.add(Token(
        code      = gf_code,
        type      = TokenType.Grace_Fee,
        status    = TokenStatus.Burned,
        value_inr = Decimal(str(grace_fee_inr)),
        user_id   = user.id,
        pool_id   = user.current_pool_id,
    ))

    # ── Clear all elimination flags and settle payment ────────────────────────
    user.grace_fee_paid        = True
    user.grace_active          = False   # grace period fulfilled
    user.grace_expires_at      = None
    user.elimination_risk      = False   # seat is saved — no longer at risk
    user.late_fees_inr         = Decimal("0")
    user.weekly_payment_status = WeeklyPaymentStatus.Paid

    db.flush()

    return {
        "user_id":            user.id,
        "username":           user.username,
        "seat_saved":         True,
        "grace_fee_paid_inr": grace_fee_inr,
        "late_fees_cleared":  late_fees_cleared,
        "total_paid_inr":     total_paid,
    }


# ── Core 4 — run the elimination cycle (the guillotine) ───────────────────────

def run_elimination_cycle_core(
    db:       Session,
    settings: dict[str, int],
    *,
    dry_run:  bool = False,
) -> dict:
    """
    Extracted from `admin_elimination.execute_elimination` (:756), the part AFTER
    the admin-password check (the caller owns auth).

    Step 1 — expire-grace sweep: every Active member whose grace window has
             elapsed unpaid (grace_active=True AND grace_fee_paid=False AND
             grace_expires_at <= sim_clock.now()) has grace_active flipped False;
             their ids are remembered so we can stamp reason=grace_expired below.
    Step 2 — identify the guillotine cohort: Active AND elimination_risk=True AND
             grace_active=False AND grace_fee_paid=False.
    Step 3 — (real run only) write one immutable EliminationEvent per member,
             flip them to Eliminated / current_pool_id=None / flags cleared, then
             REFILL the freed pool seats from the waitlist via the production
             `assign_waitlist_to_pools` engine (same engine the live draw uses).

    `dry_run=True` reports the cohort and ROLLS BACK (no DB changes persist) —
    identical to the production endpoint.

    Time source is `sim_clock.now()` so the cycle runs at the simulated instant
    inside the Time Machine and at real UTC in production.
    """
    now = sim_clock.now()

    # ── Step 1: expire any grace periods that have passed their deadline ──────
    expired_grace = (
        db.query(User)
        .filter(
            User.status           == UserStatus.Active,
            User.grace_active     == True,             # noqa: E712
            User.grace_fee_paid   == False,            # noqa: E712
            User.grace_expires_at <= now,
        )
        .all()
    )
    grace_expired_count = 0
    # After u.grace_active=False is flushed, the field is False for ALL to_eliminate
    # candidates — we cannot use it to distinguish "grace expired" from "never in
    # grace", hence this explicit id set (mirrors the production endpoint exactly).
    grace_expired_ids: set = set()
    for u in expired_grace:
        u.grace_active = False  # grace window closed without payment
        grace_expired_ids.add(u.id)
        grace_expired_count += 1

    if grace_expired_count:
        db.flush()

    # ── Step 2: identify users to eliminate ───────────────────────────────────
    to_eliminate = (
        db.query(User)
        .filter(
            User.status           == UserStatus.Active,
            User.elimination_risk == True,              # noqa: E712
            User.grace_active     == False,             # noqa: E712
            User.grace_fee_paid   == False,             # noqa: E712
        )
        .all()
    )

    if dry_run:
        # Report only — roll back the grace-expire flush so nothing persists.
        users = [
            {
                "id":        u.id,
                "username":  u.username,
                "level":     u.current_level,
                "pool_id":   u.current_pool_id,
                "late_fees": float(u.late_fees_inr or 0),
                "reason":    "grace_expired" if u.id in grace_expired_ids else "non_payment",
            }
            for u in to_eliminate
        ]
        db.rollback()
        return {
            "dry_run":              True,
            "would_eliminate":      len(users),
            "eliminated_count":     0,
            "grace_expired_count":  grace_expired_count,
            "reason_non_payment":   sum(1 for x in users if x["reason"] == "non_payment"),
            "reason_grace_expired": sum(1 for x in users if x["reason"] == "grace_expired"),
            "total_forfeited_inr":  0.0,
            "iso_week":             now.strftime("%G-W%V"),
            "users":                users,
            "refill":               None,
        }

    # ── Step 3: execute eliminations ──────────────────────────────────────────
    eliminated_count     = 0
    reason_non_payment   = 0
    reason_grace_expired = 0
    total_forfeited      = Decimal("0")
    iso_week             = now.strftime("%G-W%V")   # e.g. "2026-W24"
    grace_sv_fee_cfg     = Decimal(str(settings.get("grace_seat_save_fee_inr", 500)))

    for u in to_eliminate:
        was_grace   = u.id in grace_expired_ids
        reason      = EliminationReason.grace_expired if was_grace else EliminationReason.non_payment
        seat_sv_fee = grace_sv_fee_cfg if was_grace else Decimal("0")

        pool_name = None
        if u.current_pool_id:
            pool = db.query(Pool).filter(Pool.id == u.current_pool_id).first()
            pool_name = pool.name if pool else None

        late_fees = Decimal(str(u.late_fees_inr or 0))
        total_ev  = Decimal("1000") + late_fees + seat_sv_fee   # deposit + late + seat-save

        event = EliminationEvent(
            user_id                   = u.id,
            username_snapshot         = u.username,
            user_level_at_elimination = u.current_level,
            pool_id                   = u.current_pool_id,
            pool_name_snapshot        = pool_name,
            draw_week_id              = iso_week,
            reason                    = reason,
            late_fees_forfeited       = late_fees,
            seat_save_fee             = seat_sv_fee,
            deposit_forfeited         = Decimal("1000"),
            total_forfeited           = total_ev,
            was_in_grace_period       = was_grace,
        )
        db.add(event)

        u.status           = UserStatus.Eliminated
        u.current_pool_id  = None
        u.elimination_risk = False
        u.grace_active     = False
        u.grace_expires_at = None
        u.grace_fee_paid   = False
        u.late_fees_inr    = Decimal("0")

        total_forfeited += total_ev
        eliminated_count += 1
        if was_grace:
            reason_grace_expired += 1
        else:
            reason_non_payment += 1

    # ── Step 3b: refill the freed pool seats from the waitlist ────────────────
    # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # The original router endpoint left vacated seats empty; the production-faithful
    # behaviour (same as the live weekly draw) is to backfill from the waitlist via
    # the single-source-of-truth Double-FIFO engine.  This also commits the flushed
    # eliminations as part of its own unit of work.
    refill = None
    if eliminated_count > 0:
        db.flush()
        from app.services.waitlist import assign_waitlist_to_pools
        refill = assign_waitlist_to_pools(db)

    return {
        "dry_run":              False,
        "would_eliminate":      eliminated_count,
        "eliminated_count":     eliminated_count,
        "grace_expired_count":  grace_expired_count,
        "reason_non_payment":   reason_non_payment,
        "reason_grace_expired": reason_grace_expired,
        "total_forfeited_inr":  float(total_forfeited),
        "iso_week":             iso_week,
        "users":                [],
        "refill":               refill,
    }
