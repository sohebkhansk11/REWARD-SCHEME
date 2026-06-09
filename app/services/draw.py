"""
Smart Pairing Dual-Draw Service
================================
Implements the exact algorithm from the V1.0 architecture document.

Normal draw (pool has matured, week 4+):
  Winner 1 — random from Level 1-3
  Winner 2 — random from Level 4-6

Edge case (early weeks 1-3, no L4+ members yet):
  Both winners drawn randomly from the available low-tier pool.
  Two DISTINCT members are selected via random.sample() — never the same person.

Post-draw sequence (always):
  1. Generate level-based Withdraw token for each winner.
  2. Set winner status → Eliminated_Won, detach from pool.
  3. Pull top-2 paid Waitlist members as replacements at Level 1.
  4. Issue ₹250 REF token to any replacement's referrer.
  5. Advance surviving original members by +1 level (hard cap: L6).
  6. Reset weekly_payment_status = Unpaid for ALL pool members.
  7. Sync pool.total_members to actual active count.
"""

import random
import string
from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy.orm import Session

from app.core.config import (
    POOL_CAPACITY, LEVEL_LOW, LEVEL_HIGH,
    LEVEL_PAYOUTS, PAYOUT_FEE_INR, REFERRAL_REWARD_INR,
)
from app.crud import token as crud_token, user as crud_user, pool as crud_pool
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.models.token import TokenType, TokenStatus
from app.schemas.token import TokenCreate
from app.schemas.user import UserUpdate
from app.schemas.pool import PoolUpdate


# ── Referral bonus helper ──────────────────────────────────────────────────────

def _credit_referral_bonus(db: Session, referrer_id: int) -> None:
    """
    Add REFERRAL_REWARD_INR to the referrer's accumulated_referral_bonus_inr
    and increment their total_referrals_count.

    Called when a referred user ENTERS AN ACTIVE POOL (Rule 39) — never at
    registration.  No individual token is generated; the balance accumulates
    in the user's profile and is paid out on request via
    POST /users/request-referral-payout.
    Caller is responsible for db.commit().
    """
    referrer: User | None = db.query(User).filter(User.id == referrer_id).first()
    if not referrer:
        return
    referrer.total_referrals_count          = (referrer.total_referrals_count or 0) + 1
    referrer.accumulated_referral_bonus_inr = (
        Decimal(str(referrer.accumulated_referral_bonus_inr or 0))
        + Decimal(str(REFERRAL_REWARD_INR))
    )
    # Caller is responsible for db.commit()


# ── Data Transfer Objects ──────────────────────────────────────────────────────

@dataclass
class WinnerResult:
    winner_id: int
    winner_username: str
    winner_level: int
    gross_payout_inr: Decimal
    fee_inr: Decimal
    net_payout_inr: Decimal
    withdraw_token_code: str
    replaced_by_user_id: int | None
    replaced_by_username: str | None


@dataclass
class DrawResult:
    pool_id: int
    pool_name: str
    winner_1: WinnerResult          # Low-tier winner (L1-L3), or fallback
    winner_2: WinnerResult          # High-tier winner (L4-L6), or fallback
    edge_case_used: bool = False    # True when pool had no L4+ members (weeks 1-3)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _unique_token_code(db: Session, prefix: str) -> str:
    """Generate a collision-free token code with the given prefix."""
    while True:
        code = prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not crud_token.get_token_by_code(db, code):
            return code


def _next_paid_waitlist_member(db: Session) -> User | None:
    """Return the earliest-joined paid Waitlist member, or None."""
    return (
        db.query(User)
        .filter(
            User.status == UserStatus.Waitlist,
            User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        )
        .order_by(User.join_date)
        .first()
    )


def _issue_referral_token(db: Session, new_active_user: User) -> None:
    """
    Legacy no-op — retained only to avoid import errors in waitlist.py.

    Phase 5 design: referral bonuses are credited as a cumulative balance
    (User.accumulated_referral_bonus_inr) via _credit_referral_bonus() at the
    moment a referred user ENTERS AN ACTIVE POOL (Rule 39), NOT at registration.
    There are three pool-entry paths:
      1. waitlist.py  — bulk auto-scale (24 paid waitlist → new pool)
      2. draw.py      — replacement fill after each winner is drawn
      3. admin.py     — vacancy fill after elimination

    This stub will be removed in a future cleanup pass.
    """
    return  # intentional no-op — see docstring above


def _process_winner(db: Session, winner: User, pool: Pool) -> WinnerResult:
    """
    For a single winner:
    1. Look up their level-based payout from LEVEL_PAYOUTS.
    2. Generate a WIT-XXXXXX Withdraw token for the net amount.
    3. Mark them Eliminated_Won and detach from the pool.
    4. Pull the next paid Waitlist member as their replacement at Level 1.
    5. Issue a referral token if the replacement was referred.
    """
    gross, net = LEVEL_PAYOUTS.get(winner.current_level, (2500, 2000))
    gross_d = Decimal(str(gross))
    net_d   = Decimal(str(net))
    fee_d   = Decimal(str(PAYOUT_FEE_INR))

    # Generate Withdraw token
    code = _unique_token_code(db, "WIT-")
    crud_token.create_token(
        db,
        TokenCreate(
            code=code,
            type=TokenType.Withdraw,
            value_inr=net_d,
            user_id=winner.id,
            status=TokenStatus.Active,
        ),
    )

    # Eliminate winner
    crud_user.update_user(
        db,
        winner.id,
        UserUpdate(status=UserStatus.Eliminated_Won, current_pool_id=None),
    )

    # Pull replacement from Waitlist
    replacement = _next_paid_waitlist_member(db)
    if replacement:
        crud_user.update_user(
            db,
            replacement.id,
            UserUpdate(status=UserStatus.Active, current_pool_id=pool.id, current_level=1),
        )
        db.refresh(replacement)
        # Rule 39: credit referral bonus when replacement ENTERS the active pool.
        if replacement.referred_by_user_id:
            _credit_referral_bonus(db, replacement.referred_by_user_id)
    # If no replacement is available, pool.total_members is synced at the end of
    # run_dual_draw — no partial update needed here.

    return WinnerResult(
        winner_id=winner.id,
        winner_username=winner.username,
        winner_level=winner.current_level,
        gross_payout_inr=gross_d,
        fee_inr=fee_d,
        net_payout_inr=net_d,
        withdraw_token_code=code,
        replaced_by_user_id=replacement.id if replacement else None,
        replaced_by_username=replacement.username if replacement else None,
    )


# ── Public draw entry-point ────────────────────────────────────────────────────

def run_dual_draw(db: Session, pool_id: int) -> DrawResult:
    """
    Execute the Smart Pairing Dual-Draw for the given pool.

    Raises ValueError with a human-readable message on any validation failure.
    """
    # ── Validate pool ──────────────────────────────────────────────────────────
    pool: Pool | None = crud_pool.get_pool(db, pool_id)
    if not pool:
        raise ValueError(f"Pool {pool_id} not found.")
    if pool.status != PoolStatus.Active:
        raise ValueError(
            f"Pool '{pool.name}' is not Active (current status: {pool.status.value})."
        )

    members: list[User] = (
        db.query(User)
        .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
        .all()
    )

    if len(members) != POOL_CAPACITY:
        raise ValueError(
            f"Pool '{pool.name}' has {len(members)} active member(s); "
            f"exactly {POOL_CAPACITY} are required to run the draw."
        )

    # ── Split by tier ──────────────────────────────────────────────────────────
    low_pool  = [m for m in members if LEVEL_LOW[0]  <= m.current_level <= LEVEL_LOW[1]]
    high_pool = [m for m in members if LEVEL_HIGH[0] <= m.current_level <= LEVEL_HIGH[1]]

    edge_case = (len(high_pool) == 0)

    if edge_case:
        # ── Edge case: weeks 1–3, pool has not yet matured to L4 ──────────────
        # Per spec: "simply select 2 random winners from the available lower
        # levels until the pool matures."
        # We need at least 2 distinct members in the low pool.
        if len(low_pool) < 2:
            raise ValueError(
                f"Pool '{pool.name}' has fewer than 2 eligible members for the "
                f"early-pool edge-case draw (low_pool size: {len(low_pool)})."
            )
        winner_1, winner_2 = random.sample(low_pool, 2)  # guaranteed distinct
    else:
        # ── Normal draw: one winner from each tier ─────────────────────────────
        if not low_pool:
            raise ValueError(
                f"Pool '{pool.name}' has no members at Level "
                f"{LEVEL_LOW[0]}–{LEVEL_LOW[1]} for the low-tier draw."
            )
        winner_1 = random.choice(low_pool)
        winner_2 = random.choice(high_pool)

    # ── Snapshot IDs before any mutations ─────────────────────────────────────
    original_ids = {m.id for m in members}
    winner_ids   = {winner_1.id, winner_2.id}

    # ── Process both winners (token generation + replacement) ─────────────────
    result_1 = _process_winner(db, winner_1, pool)
    db.refresh(pool)
    result_2 = _process_winner(db, winner_2, pool)

    # ── Post-draw maintenance ──────────────────────────────────────────────────
    surviving_ids = original_ids - winner_ids

    for member_id in surviving_ids:
        member = crud_user.get_user(db, member_id)
        if member and member.status == UserStatus.Active and member.current_pool_id == pool_id:
            # Advance level — hard cap at L6 (per spec: L7 is mathematically impossible)
            crud_user.update_user(
                db,
                member_id,
                UserUpdate(
                    current_level=min(member.current_level + 1, 6),
                    weekly_payment_status=WeeklyPaymentStatus.Unpaid,
                ),
            )

    # Reset payment status for replacement members — new week begins after the draw
    for rep_id in filter(None, [result_1.replaced_by_user_id, result_2.replaced_by_user_id]):
        member = crud_user.get_user(db, rep_id)
        if member and member.status == UserStatus.Active:
            crud_user.update_user(
                db, rep_id,
                UserUpdate(weekly_payment_status=WeeklyPaymentStatus.Unpaid),
            )

    # Sync pool.total_members to actual active count (handles missing replacements cleanly)
    actual_count = (
        db.query(User)
        .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
        .count()
    )
    crud_pool.update_pool(db, pool_id, PoolUpdate(total_members=actual_count))

    return DrawResult(
        pool_id=pool.id,
        pool_name=pool.name,
        winner_1=result_1,
        winner_2=result_2,
        edge_case_used=edge_case,
    )
