"""
Waitlist Services
=================
fill_pool_vacancies()     — FIFO vacancy fill for existing active pools.
check_and_scale_waitlist() — Create a new pool when ≥24 paid members wait.

Pool-fill ordering rules (Issue 3):
  Priority 1 — oldest pool first (Pool.created_at ASC) so earlier pools
                reach full capacity before newer ones receive members.
  Priority 2 — oldest waitlisted user first (User.join_date ASC — true FIFO).

State machine on pool entry (Issue 2):
  Every path that moves a user from Waitlist → Active Pool must:
    • set current_level  = 1
    • set weekly_payment_status = Paid   (they already deposited to join waitlist)
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import WAITLIST_TRIGGER, NEW_POOL_INTAKE, POOL_CAPACITY
from app.crud import user as crud_user, pool as crud_pool
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.schemas.pool import PoolCreate, PoolUpdate
from app.schemas.user import UserUpdate
from app.services.draw import _issue_referral_token, _credit_referral_bonus

_logger = logging.getLogger(__name__)


def _next_pool_name(db: Session) -> str:
    """Generate Pool A, Pool B, …, Pool Z, Pool AA, … based on existing count."""
    count = db.query(Pool).count()
    letters = ""
    n = count
    while True:
        letters = chr(65 + n % 26) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return f"Pool {letters}"


# ─────────────────────────────────────────────────────────────────────────────
# FIFO Vacancy Fill
# ─────────────────────────────────────────────────────────────────────────────

def fill_pool_vacancies(db: Session) -> list[dict]:
    """
    FIFO vacancy fill — assign paid Waitlist members into any Active pool
    that currently has fewer than POOL_CAPACITY (12) active members.

    Pool ordering  : created_at ASC (oldest pool gets filled first — Issue 3)
    Member ordering: join_date ASC  (longest-waiting user assigned first — Issue 3)

    State machine  : entering members always get current_level=1 + Paid (Issue 2).
    Referral bonus : credited at entry point per Rule 39.

    Returns a list of assignment dicts for audit logging.
    """
    # ── 1. Find active pools ordered oldest-first ─────────────────────────────
    active_pools: list[Pool] = (
        db.query(Pool)
        .filter(Pool.status == PoolStatus.Active)
        .order_by(Pool.created_at.asc())     # oldest pool gets priority (Issue 3)
        .all()
    )

    # Build slot queue: iterate pools in order, adding one entry per vacant slot.
    # This naturally fills pool A fully before moving to pool B.
    slot_queue: list[Pool] = []
    for pool in active_pools:
        actual = (
            db.query(User)
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .count()
        )
        vacancies = POOL_CAPACITY - actual
        if vacancies > 0:
            slot_queue.extend([pool] * vacancies)

    total_vacancies = len(slot_queue)
    if total_vacancies == 0:
        _logger.debug("FIFO fill: no vacancies in any active pool.")
        return []

    _logger.info("FIFO fill: found %d open slot(s) across %d pool(s).",
                 total_vacancies, len(active_pools))

    # ── 2. Pull paid Waitlist members, strictly FIFO by join_date ────────────
    candidates: list[User] = (
        db.query(User)
        .filter(
            User.status == UserStatus.Waitlist,
            User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        )
        .order_by(User.join_date.asc())      # oldest waitlist entry first (Issue 3)
        .limit(total_vacancies)
        .all()
    )

    if not candidates:
        _logger.info("FIFO fill: %d vacancies open but no paid Waitlist members available.",
                     total_vacancies)
        return []

    # ── 3. Assign each candidate to the next available slot ──────────────────
    assignments: list[dict] = []
    for member, pool in zip(candidates, slot_queue):
        # State machine (Issue 2): entering pool → Level 1, Paid
        crud_user.update_user(
            db,
            member.id,
            UserUpdate(
                status=UserStatus.Active,
                current_pool_id=pool.id,
                current_level=1,
                weekly_payment_status=WeeklyPaymentStatus.Paid,
            ),
        )
        db.refresh(member)

        # Rule 39 — credit referral bonus when the referred user enters an active pool
        if member.referred_by_user_id:
            _credit_referral_bonus(db, member.referred_by_user_id)

        assignments.append({
            "user_id":   member.id,
            "username":  member.username,
            "pool_id":   pool.id,
            "pool_name": pool.name,
        })
        _logger.info(
            "FIFO fill: assigned @%s → %s  (%d / %d slots filled)",
            member.username, pool.name, len(assignments), total_vacancies,
        )

    db.commit()   # flush referral bonus updates + final assignment states

    # ── 4. Sync pool.total_members for every affected pool ────────────────────
    affected_pools = {p for p in slot_queue[: len(assignments)]}
    for pool in affected_pools:
        actual = (
            db.query(User)
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .count()
        )
        crud_pool.update_pool(db, pool.id, PoolUpdate(total_members=actual))

    _logger.info(
        "FIFO fill complete: %d assigned, %d slot(s) still unfilled (waitlist exhausted).",
        len(assignments), total_vacancies - len(assignments),
    )
    return assignments


# ─────────────────────────────────────────────────────────────────────────────
# Waitlist Auto-Scale  (new pool creation)
# ─────────────────────────────────────────────────────────────────────────────

def check_and_scale_waitlist(db: Session) -> Pool | None:
    """
    If AUTO_POOL_CREATION_ENABLED is True AND there are at least WAITLIST_TRIGGER
    paid Waitlist members, create a new pool and move the earliest NEW_POOL_INTAKE
    members into it at Level 1 with Paid status.

    Returns the newly created Pool, or None if threshold not met or auto-creation
    is disabled.

    NOTE: This handles NEW pool creation only.  Vacancies in existing pools are
    filled by fill_pool_vacancies().
    """
    from app.core.pool_settings import get_auto_pool_creation

    if not get_auto_pool_creation():
        _logger.info("Auto pool creation is DISABLED — skipping scale check. "
                     "Use POST /admin/pools/manual-create to create pools manually.")
        return None

    paid_waitlist: list[User] = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .order_by(User.join_date.asc())
        .all()
    )

    if len(paid_waitlist) < WAITLIST_TRIGGER:
        return None

    pool_name = _next_pool_name(db)
    new_pool = crud_pool.create_pool(
        db,
        PoolCreate(name=pool_name, status=PoolStatus.Active, total_members=NEW_POOL_INTAKE),
    )

    for member in paid_waitlist[:NEW_POOL_INTAKE]:
        # State machine (Issue 2): entering pool → Level 1, Paid
        crud_user.update_user(
            db,
            member.id,
            UserUpdate(
                status=UserStatus.Active,
                current_pool_id=new_pool.id,
                current_level=1,
                weekly_payment_status=WeeklyPaymentStatus.Paid,
            ),
        )
        db.refresh(member)
        # Rule 39: credit referral bonus at pool entry, not at registration.
        if member.referred_by_user_id:
            _credit_referral_bonus(db, member.referred_by_user_id)
        _issue_referral_token(db, member)   # intentional no-op — kept for compat

    db.commit()
    _logger.info("Waitlist scaled: created %s with %d members.", pool_name, NEW_POOL_INTAKE)
    return new_pool


# ─────────────────────────────────────────────────────────────────────────────
# Manual Pool Creation (admin-triggered, ignores AUTO_POOL_CREATION_ENABLED)
# ─────────────────────────────────────────────────────────────────────────────

def manual_create_pool(db: Session) -> Pool | None:
    """
    Force-create a new Active pool from paid Waitlist members regardless of the
    auto-creation toggle or current waitlist count.

    Returns the new Pool, or None if fewer than NEW_POOL_INTAKE paid members wait.
    Called exclusively from POST /admin/pools/manual-create.
    """
    paid_waitlist: list[User] = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .order_by(User.join_date.asc())
        .all()
    )

    if len(paid_waitlist) < NEW_POOL_INTAKE:
        return None

    pool_name = _next_pool_name(db)
    new_pool = crud_pool.create_pool(
        db,
        PoolCreate(name=pool_name, status=PoolStatus.Active, total_members=NEW_POOL_INTAKE),
    )

    for member in paid_waitlist[:NEW_POOL_INTAKE]:
        crud_user.update_user(
            db,
            member.id,
            UserUpdate(
                status=UserStatus.Active,
                current_pool_id=new_pool.id,
                current_level=1,
                weekly_payment_status=WeeklyPaymentStatus.Paid,
            ),
        )
        db.refresh(member)
        if member.referred_by_user_id:
            _credit_referral_bonus(db, member.referred_by_user_id)
        _issue_referral_token(db, member)

    db.commit()
    _logger.info("Manual pool created: %s with %d members.", pool_name, NEW_POOL_INTAKE)
    return new_pool
