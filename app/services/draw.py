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

import logging
import random
import string
from dataclasses import dataclass, field
from decimal import Decimal
from sqlalchemy.orm import Session

_logger = logging.getLogger(__name__)

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


@dataclass
class MassDrawResult:
    """Return type of execute_weekly_draw()."""
    pools_drawn:     int
    draw_results:    list[DrawResult]
    total_auto_paid: int
    refill:          dict                    # assign_waitlist_to_pools() summary
    skipped_pools:   list[str] = field(default_factory=list)  # pool names that errored mid-draw
    paused_pools:    list[str] = field(default_factory=list)  # Active pools with < 12 — paused pre-draw


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


def _process_winner(
    db: Session,
    winner: User,
    pool: Pool,
    *,
    pull_replacement: bool = True,
) -> WinnerResult:
    """
    For a single winner:
    1. Look up their level-based payout from LEVEL_PAYOUTS.
    2. Generate a WIT-XXXXXX Withdraw token for the net amount.
    3. Mark them Eliminated_Won and detach from the pool.
    4. Optionally pull the next paid Waitlist member as a replacement (Level 1).
       Set pull_replacement=False when running a mass draw; the caller will do
       a single combined refill via assign_waitlist_to_pools() afterwards.
    """
    gross, net = LEVEL_PAYOUTS.get(winner.current_level, (2500, 2000))
    gross_d = Decimal(str(gross))
    net_d   = Decimal(str(net))
    fee_d   = Decimal(str(PAYOUT_FEE_INR))

    # Generate Withdraw token — stamp pool_id for wallet history traceability
    code = _unique_token_code(db, "WIT-")
    crud_token.create_token(
        db,
        TokenCreate(
            code=code,
            type=TokenType.Withdraw,
            value_inr=net_d,
            user_id=winner.id,
            pool_id=pool.id,
            status=TokenStatus.Active,
        ),
    )

    # Eliminate winner
    crud_user.update_user(
        db,
        winner.id,
        UserUpdate(status=UserStatus.Eliminated_Won, current_pool_id=None),
    )

    # Pull replacement from Waitlist (skipped for mass draws — refill is batched)
    replacement = None
    if pull_replacement:
        replacement = _next_paid_waitlist_member(db)
        if replacement:
            # State machine: entering pool → Level 1, Paid.
            crud_user.update_user(
                db,
                replacement.id,
                UserUpdate(
                    status=UserStatus.Active,
                    current_pool_id=pool.id,
                    current_level=1,
                    weekly_payment_status=WeeklyPaymentStatus.Paid,
                ),
            )
            db.refresh(replacement)
            # Rule 39: credit referral bonus when replacement ENTERS the active pool.
            if replacement.referred_by_user_id:
                _credit_referral_bonus(db, replacement.referred_by_user_id)

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


# ── Single-pool draw ──────────────────────────────────────────────────────────

def run_dual_draw(
    db: Session,
    pool_id: int,
    *,
    skip_waitlist_fill: bool = False,
) -> DrawResult:
    """
    Execute the Smart Pairing Dual-Draw for the given pool.

    skip_waitlist_fill (default False):
        If False — after the draw, immediately calls assign_waitlist_to_pools()
        to fill the two vacancies and potentially create new pools.
        If True  — inline replacement is also skipped; the pool drops to 10
        members.  The caller (execute_weekly_draw) does a single combined
        refill after ALL pools have been drawn.

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

    # ── Process both winners (token generation + optional replacement) ────────
    _pull = not skip_waitlist_fill   # inline replacement only for single draws
    result_1 = _process_winner(db, winner_1, pool, pull_replacement=_pull)
    db.refresh(pool)
    result_2 = _process_winner(db, winner_2, pool, pull_replacement=_pull)

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

    # NOTE (Issue 2): replacements are NOT reset to Unpaid here.
    # They entered the pool with Paid status (deposit already collected) and their
    # weekly_payment_status only resets to Unpaid in the NEXT draw's level-advance
    # loop — same as every other surviving member.

    # Sync pool.total_members to actual active count (handles missing replacements cleanly)
    actual_count = (
        db.query(User)
        .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
        .count()
    )
    crud_pool.update_pool(db, pool_id, PoolUpdate(total_members=actual_count))

    # After a single draw, immediately run the Double-FIFO refill so vacancies
    # are filled and Phase 2 pool creation is considered.
    # For mass draws (skip_waitlist_fill=True) the caller handles this once
    # after ALL pools have been drawn — pools intentionally sit at 10 members
    # until the combined refill runs.
    if not skip_waitlist_fill:
        from app.services.waitlist import assign_waitlist_to_pools
        assign_waitlist_to_pools(db)

    return DrawResult(
        pool_id=pool.id,
        pool_name=pool.name,
        winner_1=result_1,
        winner_2=result_2,
        edge_case_used=edge_case,
    )


# ── Global Mass Draw ───────────────────────────────────────────────────────────

def execute_weekly_draw(
    db: Session,
    *,
    auto_pay_unpaid: bool = False,
) -> MassDrawResult:
    """
    Global Mass Draw — the production Sunday-draw entry point.

    Algorithm
    ---------
    1. Fetch ALL Active pools whose actual member count == POOL_CAPACITY (12).
       Ordered by pool.id ASC for deterministic processing.
    2. Optionally mark every unpaid member Paid before drawing
       (used by the dev Force-Draw tool to avoid validation failures).
    3. For each eligible pool run run_dual_draw(..., skip_waitlist_fill=True).
       This removes 2 winners and does NOT pull inline replacements, so each
       pool drops from 12 → 10 members.
    4. After ALL pools have been drawn, call assign_waitlist_to_pools() ONCE:
       Phase 1 — fills all 2×N vacancies across all pools (oldest pool first).
       Phase 2 — creates new pools if remaining waitlist >= threshold.

    Raises ValueError if no eligible full pools are found.
    Returns MassDrawResult with per-pool draw traces + combined refill summary.
    """
    from app.services.waitlist import assign_waitlist_to_pools

    # ── 1. Discover eligible pools + apply draw-protection safeguard ─────────
    #
    # Draw protection (spec requirement):
    #   Any Active pool whose actual member count < POOL_CAPACITY is NOT eligible
    #   for the draw.  Running a draw on a partial pool breaks the L1-L3 / L4-L6
    #   payout mathematics.  Such pools are immediately marked
    #   Paused_Awaiting_Members and skipped.  They re-enter Active status
    #   automatically once assign_waitlist_to_pools (Phase 1 or Phase 3) fills
    #   them back to capacity.

    candidate_pools: list[Pool] = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .order_by(Pool.id.asc())
        .all()
    )

    eligible:     list[Pool] = []
    paused_now:   list[str]  = []   # newly paused this run (were Active, < 12)

    for pool in candidate_pools:
        actual: int = (
            db.query(User)
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .count()
        )
        if actual == POOL_CAPACITY:
            eligible.append(pool)
        elif pool.status == PoolStatus.Active:
            # Draw protection: Active pool with < 12 members — pause it
            pool.status = PoolStatus.Paused_Awaiting_Members
            paused_now.append(pool.name)
            _logger.warning(
                "execute_weekly_draw: ⏸  %s has %d/%d members — "
                "marking Paused_Awaiting_Members (DRAW SKIPPED for this pool).",
                pool.name, actual, POOL_CAPACITY,
            )
        # Already Paused_Awaiting_Members → just skip silently

    if paused_now:
        db.commit()
        _logger.info(
            "execute_weekly_draw: draw-protection paused %d pool(s): %s",
            len(paused_now),
            ", ".join(paused_now),
        )

    if not eligible:
        raise ValueError(
            "No active pools with exactly 12 members found. "
            "Run 'Fill Pool Vacancies' (POST /admin/waitlist/check) first, "
            "then retry the draw."
        )

    _logger.info(
        "execute_weekly_draw: %d eligible full pool(s): %s",
        len(eligible),
        ", ".join(p.name for p in eligible),
    )

    # ── 2. Auto-pay unpaid members if requested ───────────────────────────────
    total_auto_paid = 0
    if auto_pay_unpaid:
        for pool in eligible:
            unpaid: list[User] = (
                db.query(User)
                .filter(
                    User.current_pool_id == pool.id,
                    User.status == UserStatus.Active,
                    User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
                )
                .all()
            )
            for member in unpaid:
                member.weekly_payment_status = WeeklyPaymentStatus.Paid
                total_auto_paid += 1
        if total_auto_paid:
            db.commit()
            _logger.info(
                "execute_weekly_draw: auto-paid %d unpaid member(s) across %d pool(s).",
                total_auto_paid, len(eligible),
            )

    # ── 3. Draw every eligible pool — no inline replacement, no intermediate fill
    draw_results: list[DrawResult] = []
    skipped:      list[str]        = []

    for pool in eligible:
        try:
            result = run_dual_draw(db, pool.id, skip_waitlist_fill=True)
            draw_results.append(result)
            _logger.info(
                "execute_weekly_draw: ✓ %s — W1=@%s (L%d %s), W2=@%s (L%d %s)",
                pool.name,
                result.winner_1.winner_username, result.winner_1.winner_level,
                "edge" if result.edge_case_used else "norm",
                result.winner_2.winner_username, result.winner_2.winner_level,
                "edge" if result.edge_case_used else "norm",
            )
        except ValueError as exc:
            _logger.warning("execute_weekly_draw: ✗ %s skipped — %s", pool.name, exc)
            skipped.append(pool.name)

    _logger.info(
        "execute_weekly_draw: %d pool(s) drawn, %d skipped. "
        "Triggering Double-FIFO refill...",
        len(draw_results), len(skipped),
    )

    # ── 4. Single combined FIFO refill after ALL draws ────────────────────────
    refill = assign_waitlist_to_pools(db)

    _logger.info(
        "execute_weekly_draw COMPLETE — "
        "pools_drawn=%d  P1_assigned=%d  P2_created=%s",
        len(draw_results),
        refill["phase1_assigned"],
        refill["phase2_pool_created"] or "none",
    )

    return MassDrawResult(
        pools_drawn=len(draw_results),
        draw_results=draw_results,
        total_auto_paid=total_auto_paid,
        refill=refill,
        skipped_pools=skipped,
        paused_pools=paused_now,
    )
