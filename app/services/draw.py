"""
Smart Pairing Dual-Draw Service
================================
Implements the exact algorithm from the V1.0 architecture document,
updated for the SDE anti-maturity architecture (Phase 1+).

Pool-type routing (draw_type parameter):
  'regular'  — L1-3 lower / L4-6 upper  (legacy / low-LPI pools)
  'type_a'   — L1-2 lower / L3-4 upper  (Execution Pool Type A)
  'sde'      — handled by sde_engine.py; run_dual_draw not used
  'type_b'   — L3 lower / L4 upper       (Type B fallback)

Post-draw sequence (always):
  1. Generate level-based Withdraw token for each winner.
  2. Set winner status → Eliminated_Won, detach from pool.
  3. Pull top-2 paid Waitlist members as replacements at Level 1.
  4. Issue ₹250 REF token to any replacement's referrer.
  5. Advance surviving original members by +1 level (hard cap: L6).
     ↳ ATOMIC: if new_level == 4, set sde_required=True + flag the pool.
  6. Set draw_completed_this_week = True on the pool (double-draw guard).
  7. Reset weekly_payment_status = Unpaid for ALL pool members.
  8. Sync pool.total_members to actual active count.
"""

import hashlib
import logging
import os
import random
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session

# _draw_rng: SystemRandom (os.urandom-backed) used ONLY for
# guaranteed-distinct 2-sample draws (no stdlib secrets.sample).
# All single picks use secrets.choice() directly.
_draw_rng = random.SystemRandom()

_logger = logging.getLogger(__name__)

from app.core.config import (
    POOL_CAPACITY,
    LEVEL_LOW, LEVEL_HIGH,              # regular pool tier split
    EXEC_LEVEL_LOW, EXEC_LEVEL_HIGH,    # type_a tier split
    TYPE_B_LEVEL_LOW, TYPE_B_LEVEL_HIGH,# type_b tier split
    POOL_DRAW_REGULAR, POOL_DRAW_TYPE_A, POOL_DRAW_TYPE_B, POOL_DRAW_SDE,
    POOL_DRAW_ACCELERATED,              # accelerated dissolution draw type
    ACCEL_DISS_TRIGGER_RATIO,          # ≥60% L4+ triggers accelerated mode
    ACCEL_DISS_DISSOLVE_BELOW,         # dissolve pool if active count falls below 8
    LEVEL_PAYOUTS, PAYOUT_FEE_INR, REFERRAL_REWARD_INR,
)
from app.crud import token as crud_token, user as crud_user, pool as crud_pool
from app.models.draw_history import DrawHistory
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.models.token import TokenType, TokenStatus
from app.schemas.token import TokenCreate
from app.schemas.user import UserUpdate
from app.schemas.pool import PoolUpdate


# ── Referral bonus helper ──────────────────────────────────────────────────────

def _credit_referral_bonus(db: Session, referrer_id: int) -> None:
    """
    Add the admin-configured referral reward to the referrer's
    accumulated_referral_bonus_inr and increment their total_referrals_count.

    The reward amount is read from the system_settings DB table via
    get_referral_reward(db) — default ₹250 (REFERRAL_REWARD_INR).
    An admin can change it live via PUT /admin/settings/referral-reward.
    A value of 0 means rewards are temporarily disabled; the count is still
    incremented so referral statistics remain accurate.

    Called when a referred user ENTERS AN ACTIVE POOL (Rule 39) — never at
    registration.  No individual token is generated; the balance accumulates
    in the user's profile and is paid out on request via
    POST /users/request-referral-payout.
    Caller is responsible for db.commit().
    """
    # Deferred import — avoids a module-level circular dependency chain.
    from app.services.settings import get_referral_reward

    referrer: User | None = db.query(User).filter(User.id == referrer_id).first()
    if not referrer:
        return

    reward = get_referral_reward(db)   # live DB value, 60-second cache

    referrer.total_referrals_count = (referrer.total_referrals_count or 0) + 1
    if reward > 0:
        referrer.accumulated_referral_bonus_inr = (
            Decimal(str(referrer.accumulated_referral_bonus_inr or 0))
            + Decimal(str(reward))
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
    winner_1: WinnerResult          # Low-tier winner, or fallback
    winner_2: WinnerResult          # High-tier winner, or fallback
    edge_case_used: bool = False    # True when pool had no upper-tier members
    draw_type: str = POOL_DRAW_REGULAR  # routing bucket used


@dataclass
class MassDrawResult:
    """Return type of execute_weekly_draw()."""
    pools_drawn:     int
    draw_results:    list[DrawResult]
    total_auto_paid: int
    refill:          dict                     # assign_waitlist_to_pools() summary
    skipped_pools:   list[str] = field(default_factory=list)   # errored mid-draw
    paused_pools:    list[str] = field(default_factory=list)   # Active pools with < 12 — paused
    sde_pre_drawn:   list[str] = field(default_factory=list)   # pools drawn by SDE pre-draw
    # U-02: EngineEvent trace — one immutable record per draw sub-step.
    # Callers can inspect this to verify LPI monotonicity (CON-2 proof) and
    # diagnose why each pool was routed to a specific draw type.
    event_trace:     list = field(default_factory=list)        # list[EngineEvent]


# ── Internal helpers ───────────────────────────────────────────────────────────

def _current_week_id() -> str:
    """Return the ISO week key for the current UTC date.  Format: 'YYYY-Www'."""
    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _unique_token_code(db: Session, prefix: str) -> str:
    """
    Generate a collision-free token code using cryptographic randomness.

    Uses secrets.choice() (backed by os.urandom) — replaces the former
    random.choices() call which used the MT19937 PRNG (predictable after
    sufficient observation).
    """
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = prefix + "".join(secrets.choice(alphabet) for _ in range(6))
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

def _resolve_tier_bounds(draw_type: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """
    Return (low_bounds, high_bounds) for the given draw_type.

    BUG 1 FIX: tier rules are now pool-type-specific.
      regular → L1-3 lower / L4-6 upper (legacy behaviour)
      type_a  → L1-2 lower / L3-4 upper (Execution Pool)
      type_b  → L3   lower / L4   upper (Type B Fallback)
      sde     → not handled here (sde_engine.py owns SDE tier logic)
    """
    if draw_type == POOL_DRAW_TYPE_A:
        return EXEC_LEVEL_LOW, EXEC_LEVEL_HIGH
    if draw_type == POOL_DRAW_TYPE_B:
        return TYPE_B_LEVEL_LOW, TYPE_B_LEVEL_HIGH
    # default / 'regular'
    return LEVEL_LOW, LEVEL_HIGH


def run_dual_draw(
    db: Session,
    pool_id: int,
    *,
    skip_waitlist_fill: bool = False,
    draw_type: str = POOL_DRAW_REGULAR,
) -> DrawResult:
    """
    Execute the Smart Pairing Dual-Draw for the given pool.

    draw_type controls tier bounds (BUG 1 FIX):
      'regular' (default) — L1-3 lower / L4-6 upper
      'type_a'            — L1-2 lower / L3-4 upper
      'type_b'            — L3   lower / L4   upper
      'sde'               — never routed here; use sde_engine.run_sde_sub_draw()

    skip_waitlist_fill (default False):
        If True — no inline replacement; pool drops to 10 members.
        Caller (execute_weekly_draw) does one combined refill after all draws.

    Raises ValueError with a human-readable message on any validation failure.
    """
    if draw_type == POOL_DRAW_SDE:
        raise ValueError(
            "draw_type='sde' must not be routed through run_dual_draw(). "
            "Use sde_engine.run_sde_sub_draw() instead."
        )

    # ── Validate pool ──────────────────────────────────────────────────────────
    pool: Pool | None = crud_pool.get_pool(db, pool_id)
    if not pool:
        raise ValueError(f"Pool {pool_id} not found.")
    if pool.status != PoolStatus.Active:
        raise ValueError(
            f"Pool '{pool.name}' is not Active (current status: {pool.status.value})."
        )

    # BUG 7 FIX: double-draw guard — refuse if this pool already drew this week
    if pool.draw_completed_this_week:
        raise ValueError(
            f"Pool '{pool.name}' already completed its draw this week "
            f"(draw_completed_this_week=True).  Prevent duplicate execution."
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

    # ── Split by tier (pool-type-specific bounds) ─────────────────────────────
    low_bounds, high_bounds = _resolve_tier_bounds(draw_type)
    low_pool  = [m for m in members if low_bounds[0]  <= m.current_level <= low_bounds[1]]
    high_pool = [m for m in members if high_bounds[0] <= m.current_level <= high_bounds[1]]

    edge_case = (len(high_pool) == 0)

    if edge_case:
        # ── Edge case: pool has not yet matured — no upper-tier members ────────
        # Per spec: "select 2 random winners from the available lower tier
        # until the pool matures."  Requires ≥ 2 distinct candidates.
        if len(low_pool) < 2:
            raise ValueError(
                f"Pool '{pool.name}' has fewer than 2 eligible members for the "
                f"early-pool edge-case draw (low_pool size: {len(low_pool)})."
            )
        winner_1, winner_2 = _draw_rng.sample(low_pool, 2)  # guaranteed distinct
    else:
        # ── Normal draw: one winner from each tier ─────────────────────────────
        if not low_pool:
            raise ValueError(
                f"Pool '{pool.name}' has no members at Level "
                f"{low_bounds[0]}–{low_bounds[1]} for the low-tier draw."
            )
        winner_1 = secrets.choice(low_pool)
        winner_2 = secrets.choice(high_pool)

    # ── Snapshot IDs before any mutations ─────────────────────────────────────
    original_ids = {m.id for m in members}
    winner_ids   = {winner_1.id, winner_2.id}

    # Snapshot winner journey fields BEFORE _process_winner mutates their status
    _w1_dep    = winner_1.total_deposited_inr        or 1000
    _w1_merges = winner_1.dynamic_merges_experienced or 0
    _w1_pauses = winner_1.pauses_experienced         or 0
    _w2_dep    = winner_2.total_deposited_inr        or 1000
    _w2_merges = winner_2.dynamic_merges_experienced or 0
    _w2_pauses = winner_2.pauses_experienced         or 0

    # ── Process both winners (token generation + optional replacement) ────────
    _pull = not skip_waitlist_fill   # inline replacement only for single draws
    result_1 = _process_winner(db, winner_1, pool, pull_replacement=_pull)
    db.refresh(pool)
    result_2 = _process_winner(db, winner_2, pool, pull_replacement=_pull)

    # ── Post-draw maintenance ──────────────────────────────────────────────────
    surviving_ids = original_ids - winner_ids
    week_id = _current_week_id()
    new_l4_flagged = False  # tracks whether any survivor just became L4

    for member_id in surviving_ids:
        member = crud_user.get_user(db, member_id)
        if member and member.status == UserStatus.Active and member.current_pool_id == pool_id:
            new_level = min(member.current_level + 1, 6)

            # ANTI-MATURITY PROTOCOL — ATOMIC L4 FLAG (BUG 1 / REAL-TIME FLAGGING):
            # If this member just advanced to L4, set sde_required=True in the
            # SAME database write as the level change.  This is a hard guarantee —
            # there is no window between "member is L4" and "member is flagged".
            reaching_l4 = (new_level == 4)
            if reaching_l4:
                new_l4_flagged = True
                _logger.info(
                    "Anti-Maturity: member %d (%s) advanced to L4 — "
                    "sde_required=True flagged atomically (week %s).",
                    member.id, member.username, week_id,
                )

            crud_user.update_user(
                db,
                member_id,
                UserUpdate(
                    current_level=new_level,
                    weekly_payment_status=WeeklyPaymentStatus.Unpaid,
                    # Atomically set SDE flag if this member just hit L4
                    sde_required=(True if reaching_l4 else None),
                    sde_flagged_week=(week_id if reaching_l4 else None),
                ),
            )

    # If any survivor reached L4, mark the pool as containing a flagged L4 member.
    # This sets contains_flagged_l4=True in the SAME transaction as the flag itself.
    if new_l4_flagged:
        pool.contains_flagged_l4 = True

    # NOTE (Issue 2): replacements are NOT reset to Unpaid here.
    # They entered the pool with Paid status (deposit already collected) and their
    # weekly_payment_status only resets to Unpaid in the NEXT draw's level-advance
    # loop — same as every other surviving member.

    # BUG 7 FIX: mark pool as drawn this week — prevents double-draw in same cycle
    pool.draw_completed_this_week = True
    pool.pool_draw_type           = draw_type

    # Sync pool.total_members to actual active count
    actual_count = (
        db.query(User)
        .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
        .count()
    )
    crud_pool.update_pool(db, pool_id, PoolUpdate(total_members=actual_count))

    # Immutable draw audit record — one row per completed draw, never updated
    db.add(DrawHistory(
        pool_id             = pool.id,
        edge_case_triggered = edge_case,
        draw_type           = draw_type,           # NEW: draw classification
        targeted_early_exit = False,               # only SDE upper winners get True
        # Winner 1
        winner_1_user_id            = result_1.winner_id,
        winner_1_level              = result_1.winner_level,
        winner_1_net_payout         = result_1.net_payout_inr,
        winner_1_total_deposited    = _w1_dep,
        winner_1_merges_experienced = _w1_merges,
        winner_1_pauses_experienced = _w1_pauses,
        winner_1_journey_type       = "merged" if _w1_merges > 0 else "direct",
        # Winner 2
        winner_2_user_id            = result_2.winner_id,
        winner_2_level              = result_2.winner_level,
        winner_2_net_payout         = result_2.net_payout_inr,
        winner_2_total_deposited    = _w2_dep,
        winner_2_merges_experienced = _w2_merges,
        winner_2_pauses_experienced = _w2_pauses,
        winner_2_journey_type       = "merged" if _w2_merges > 0 else "direct",
    ))
    db.commit()

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

    Algorithm (Circular Engine Update — U-02/U-03/U-04 integrated)
    ---------------------------------------------------------------
    0. SDE Extension II/III pre-pass — clear any L5/L6 members first.
    1. Read an ATOMIC system snapshot via get_system_snapshot_atomic(db).
       This establishes the baseline LPI and draw-type routing for the cycle.
    2. Fetch ALL Active pools whose actual member count == POOL_CAPACITY (12).
    3. Optionally mark every unpaid member Paid.
    4. For each eligible pool:
       a. Re-evaluation gate (U-03): re-read LPI snapshot after each draw.
          If LPI shifted ≥ MIN_LPI_DELTA from the previous snapshot, re-decide
          the next pool's draw_type.  Cap at MAX_REEVALS to prevent thrashing.
       b. Convergence guard (U-04): LPI is monotonically non-increasing within
          a single cycle (proof: only L4 exits and fills occur → both reduce LPI).
          Belt-and-suspenders: MIN_LPI_DELTA=0.5, MAX_REEVALS=3.
       c. Record an EngineEvent for every sub-step (U-02).
    5. Single combined FIFO refill after ALL draws.

    Raises ValueError if no eligible full pools are found.
    Returns MassDrawResult with per-pool draw traces, event_trace, and refill summary.
    """
    from app.services.waitlist import assign_waitlist_to_pools
    from app.services.engine_snapshot import (
        get_system_snapshot_atomic, MIN_LPI_DELTA, MAX_REEVALS,
        _evt,
    )

    # ── 0. SDE Extension II/III pre-pass — clear any L5/L6 members FIRST ───────
    #
    # POINT 2+3 FIX: Before regular draws, run SDE Ext-II/III to eliminate any
    # L5 or L6 members.  These should never exist in normal operation.  If they
    # do, it means SDE failed at some point and level advancement went unchecked.
    #
    # SDE Ext-II (L5) and Ext-III (L6) run here as a safety net BEFORE the
    # regular draw loop, so that normal pools don't accidentally try to run a
    # regular draw on a pool containing an L5/L6 member.
    #
    # The drawdown projection is calculated and logged inside the Ext-II function
    # to confirm we're choosing the cheaper option (always: eliminate now).
    try:
        from app.services.sde_engine import check_and_run_sde_extensions
        from app.services.waitlist import assign_waitlist_to_pools as _wl_refill
        week_id_str = _current_week_id()
        ext_results = check_and_run_sde_extensions(db, week_id_str)
        if ext_results:
            # Run a quick partial refill so ext-II/III pools get replacements
            # before the main draw checks pool capacity.
            _wl_refill(db)
            _logger.info(
                "execute_weekly_draw: SDE Ext-II/III ran %d draw(s) before main loop.",
                len(ext_results),
            )
    except Exception as _ext_exc:
        _logger.error(
            "execute_weekly_draw: SDE Extension check failed (non-fatal): %s",
            _ext_exc, exc_info=True,
        )

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
            # Record the pause in every active member's journey counter
            db.query(User).filter(
                User.current_pool_id == pool.id,
                User.status == UserStatus.Active,
            ).update(
                {"pauses_experienced": User.pauses_experienced + 1},
                synchronize_session=False,
            )
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

    # ── U-01: Establish atomic LPI baseline before any draws ─────────────────
    # Read all brain metrics in one transaction-consistent snapshot.
    # This prevents stale cross-reads between Brain 2 velocity and Brain 5 LPI.
    try:
        lpi_snapshot = get_system_snapshot_atomic(db)
        prev_lpi     = lpi_snapshot.lpi
        reeval_count = 0
        _logger.info(
            "execute_weekly_draw: ⚡ Atomic snapshot — LPI=%.2f%% L4=%d scenario=%s",
            prev_lpi, lpi_snapshot.l4, lpi_snapshot.scenario,
        )
    except Exception as snap_exc:
        _logger.warning("execute_weekly_draw: snapshot failed, using fallback — %s", snap_exc)
        prev_lpi     = 0.0
        reeval_count = 0

    # ── 3. Draw every eligible pool — no inline replacement, no intermediate fill
    draw_results: list[DrawResult] = []
    skipped:      list[str]        = []
    sde_skipped:  list[str]        = []   # pools already handled by SDE pre-draw
    event_trace:  list             = []   # U-02: EngineEvent list

    for pool in eligible:
        # BUG 7 FIX: skip any pool that SDE (or a previous draw attempt) already
        # processed this week.  draw_completed_this_week=True is the authoritative
        # single source of truth for "already drawn".
        if pool.draw_completed_this_week:
            sde_skipped.append(pool.name)
            _logger.info(
                "execute_weekly_draw: ⟳ %s already drawn this week (SDE or prior run) — skipping.",
                pool.name,
            )
            continue

        # U-03: Re-evaluation gate — re-read LPI before assigning draw type
        # This ensures each pool uses a current (not stale) LPI reading.
        # Gate fires if LPI shifted ≥ MIN_LPI_DELTA since last measurement.
        try:
            if reeval_count < MAX_REEVALS:
                fresh_snap = get_system_snapshot_atomic(db)
                lpi_delta  = abs(fresh_snap.lpi - prev_lpi)
                if lpi_delta >= MIN_LPI_DELTA:
                    # LPI shifted meaningfully — re-decide draw type for this pool
                    reeval_count += 1
                    new_draw_type = fresh_snap.pool_type_decision
                    event_trace.append(_evt(
                        event_type     = "lpi_reeval",
                        pool_id        = pool.id,
                        pool_name      = pool.name,
                        draw_type_used = new_draw_type,
                        lpi_before     = prev_lpi,
                        lpi_after      = fresh_snap.lpi,
                        reeval_count   = reeval_count,
                        note           = (
                            f"LPI shifted {lpi_delta:.2f}pp — re-routed to {new_draw_type}. "
                            f"Re-eval #{reeval_count}/{MAX_REEVALS}."
                        ),
                    ))
                    _logger.info(
                        "execute_weekly_draw: ⟲ LPI re-eval #%d for %s — "
                        "%.2f%%→%.2f%% (Δ%.2f) — new draw_type=%s",
                        reeval_count, pool.name, prev_lpi, fresh_snap.lpi,
                        lpi_delta, new_draw_type,
                    )
                    # Update the pool's draw type so it takes effect now
                    pool.pool_draw_type = new_draw_type
                    db.flush()
                    prev_lpi = fresh_snap.lpi
                # U-04: Convergence guard — LPI should only decrease or stay flat.
                # Log a warning if it somehow increased (should be mathematically impossible).
                elif fresh_snap.lpi > prev_lpi + MIN_LPI_DELTA:
                    _logger.warning(
                        "execute_weekly_draw: ⚠ Convergence anomaly — LPI INCREASED "
                        "%.2f%% → %.2f%% (Δ+%.2f). This is unexpected within a single cycle. "
                        "Possible cause: concurrent pool modification by another request.",
                        prev_lpi, fresh_snap.lpi, fresh_snap.lpi - prev_lpi,
                    )
                    event_trace.append(_evt(
                        event_type  = "convergence_guard",
                        pool_id     = pool.id,
                        pool_name   = pool.name,
                        lpi_before  = prev_lpi,
                        lpi_after   = fresh_snap.lpi,
                        note        = "LPI increased — convergence anomaly logged (non-fatal).",
                    ))
        except Exception as reeval_exc:
            _logger.debug("execute_weekly_draw: re-eval gate skipped: %s", reeval_exc)

        try:
            # Route to correct draw type based on pool_draw_type set at T-2H prep.
            # If prep hasn't run (pool_draw_type is None), default to 'regular'.
            effective_draw_type = pool.pool_draw_type or POOL_DRAW_REGULAR

            # Record draw-start event (U-02)
            event_trace.append(_evt(
                event_type     = "draw_start",
                pool_id        = pool.id,
                pool_name      = pool.name,
                draw_type_used = effective_draw_type,
                lpi_before     = prev_lpi,
                reeval_count   = reeval_count,
            ))

            result = run_dual_draw(
                db, pool.id,
                skip_waitlist_fill=True,
                draw_type=effective_draw_type,
            )
            draw_results.append(result)

            # Record draw-complete event (U-02)
            _dc_evt = _evt(
                event_type     = "draw_complete",
                pool_id        = pool.id,
                pool_name      = pool.name,
                draw_type_used = effective_draw_type,
                lpi_before     = prev_lpi,
                reeval_count   = reeval_count,
                note           = (
                    f"W1={result.winner_1.winner_username}(L{result.winner_1.winner_level}) "
                    f"W2={result.winner_2.winner_username}(L{result.winner_2.winner_level})"
                ),
            )
            event_trace.append(_dc_evt)

            # U-05: Push to SSE live-stream queue (non-blocking — never affects draw)
            try:
                from app.routers.admin_analytics import post_draw_event
                import dataclasses
                post_draw_event(dataclasses.asdict(_dc_evt))
            except Exception:
                pass   # SSE is reporting only — draw continues regardless

            _logger.info(
                "execute_weekly_draw: ✓ %s [%s] — W1=@%s (L%d %s), W2=@%s (L%d %s)",
                pool.name, effective_draw_type,
                result.winner_1.winner_username, result.winner_1.winner_level,
                "edge" if result.edge_case_used else "norm",
                result.winner_2.winner_username, result.winner_2.winner_level,
                "edge" if result.edge_case_used else "norm",
            )
        except ValueError as exc:
            db.rollback()
            _logger.warning("execute_weekly_draw: ✗ %s skipped — %s", pool.name, exc)
            skipped.append(pool.name)
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # DIAGNOSIS: Non-ValueError exceptions from run_dual_draw() (e.g. IntegrityError,
        # AttributeError) were bypassing the except ValueError handler and aborting the
        # ENTIRE execute_weekly_draw() call silently — simulation logged only a one-line
        # warning with no traceback, making root cause invisible.
        # FIX: Catch all exceptions here so one bad pool doesn't kill the draw cycle.
        # Each pool failure is now logged with full traceback (exc_info=True).
        except Exception as exc:
            db.rollback()
            _logger.error(
                "execute_weekly_draw: ✗ %s UNEXPECTED ERROR (non-ValueError) — %s",
                pool.name, exc, exc_info=True,
            )
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
        sde_pre_drawn=sde_skipped,
        event_trace=event_trace,   # U-02: full EngineEvent trace
    )


# ── Post-draw cleanup (T+0H:05) ────────────────────────────────────────────────

def post_draw_cleanup(db: Session) -> dict:
    """
    Post-draw cleanup job.  Run at T+0H:05 after all draws complete.

    Actions:
      1. Reset draw_completed_this_week=False on all non-dissolved pools.
         (Enables next week's draw.)
      2. Reset pool_draw_type=None on all non-dissolved pools.
         (Next week's prep will re-assign types at T-2H.)
      3. Clear contains_flagged_l4=False on pools whose L4 members exited.
      4. Clear sde_required=False on any Eliminated_Won member who still
         has the flag set (defensive cleanup — SDE should have cleared it,
         but this catches any edge-case survivors).
      5. Release the draw engine system lock.

    Returns a summary dict for logging / admin API response.
    """
    non_dissolved = [
        PoolStatus.Active,
        PoolStatus.Waiting,
        PoolStatus.Paused_Awaiting_Members,
        PoolStatus.Full,
    ]

    # 1+2: reset weekly draw flags
    pools_reset: int = (
        db.query(Pool)
        .filter(Pool.status.in_(non_dissolved))
        .update(
            {"draw_completed_this_week": False, "pool_draw_type": None},
            synchronize_session=False,
        )
    )

    # 3: clear L4 flag on pools that no longer have any sde_required members
    #    (sub-query: pool IDs that still have at least one sde_required=True active member)
    pools_still_flagged = (
        db.query(User.current_pool_id)
        .filter(User.sde_required == True, User.status == UserStatus.Active)  # noqa: E712
        .distinct()
        .subquery()
    )
    pools_cleared: int = (
        db.query(Pool)
        .filter(
            Pool.contains_flagged_l4 == True,  # noqa: E712
            ~Pool.id.in_(pools_still_flagged),
        )
        .update({"contains_flagged_l4": False}, synchronize_session=False)
    )

    # 4: defensive sde_required cleanup for exited members
    orphan_flags_cleared: int = (
        db.query(User)
        .filter(
            User.sde_required == True,   # noqa: E712
            User.status.in_([UserStatus.Eliminated_Won, UserStatus.Eliminated]),
        )
        .update(
            {"sde_required": False, "sde_flagged_week": None},
            synchronize_session=False,
        )
    )

    # 5: release draw engine lock
    from app.models.system_lock import SystemLock
    db.query(SystemLock).filter(SystemLock.lock_name == "draw_engine").delete()

    db.commit()

    summary = {
        "pools_draw_flag_reset": pools_reset,
        "pools_l4_flag_cleared": pools_cleared,
        "orphan_sde_flags_cleared": orphan_flags_cleared,
        "draw_lock_released": True,
    }
    _logger.info("post_draw_cleanup complete: %s", summary)
    return summary


# ═════════════════════════════════════════════════════════════════════════════
# ACCELERATED DISSOLUTION — POINT 5
# ═════════════════════════════════════════════════════════════════════════════
#
# Trigger: a pool's L4+ ratio exceeds ACCEL_DISS_TRIGGER_RATIO (60%).
#   Example: 8 of 12 members are L4+ → upper tier crowded → normal draws
#   take 4+ weeks to clear them.
#
# Action:
#   1. BOTH winners drawn from L4+ tier (not the normal lower/upper split).
#      This removes 2 upper-tier members per week instead of 1.
#   2. A new "relief pool" is created from waitlist simultaneously, injecting
#      fresh L1 members into the system.
#   3. If after accelerated draws the pool falls below ACCEL_DISS_DISSOLVE_BELOW
#      (8) active members, it is dissolved — remaining members are condensed
#      into other pools via Phase 3 of assign_waitlist_to_pools().
#
# Both winners come from the same tier (L4+).
# The "lower winner" = smallest L4 member by AI weight (more time to recoup).
# The "upper winner" = highest L4 member by AI weight (longest overstayed).
# ═════════════════════════════════════════════════════════════════════════════


def check_accelerated_dissolution(db: Session, pool: Pool) -> bool:
    """
    Check if a pool qualifies for Accelerated Dissolution mode.

    Returns True if ≥ ACCEL_DISS_TRIGGER_RATIO (60%) of active members are L4+.
    Called after each draw's level advancement to detect newly-triggered pools.
    """
    members: list[User] = (
        db.query(User)
        .filter(
            User.current_pool_id == pool.id,
            User.status          == UserStatus.Active,
        )
        .all()
    )
    if not members:
        return False

    l4plus_count = sum(1 for m in members if m.current_level >= 4)
    ratio        = l4plus_count / len(members)
    return ratio >= ACCEL_DISS_TRIGGER_RATIO


@dataclass
class AccelDissolutionResult:
    """Result of one accelerated dissolution draw."""
    pool_id:         int
    pool_name:       str
    winner_1:        WinnerResult   # "lower" L4+ winner (by AI weight — lower ranked)
    winner_2:        WinnerResult   # "upper" L4+ winner (by AI weight — higher ranked)
    relief_pool_id:  int | None     # newly created relief pool from WL (if any)
    pool_dissolved:  bool           # True if pool fell below ACCEL_DISS_DISSOLVE_BELOW
    l4plus_ratio:    float          # L4+ ratio at time of draw (for audit)
    draw_type:       str = POOL_DRAW_ACCELERATED


def run_accelerated_dissolution_draw(
    db: Session,
    pool_id: int,
    *,
    create_relief_pool: bool = True,
) -> AccelDissolutionResult:
    """
    Execute one Accelerated Dissolution draw for the given pool.

    POINT 5: Both winners are drawn from the L4+ tier (≥ Level 4).
    The pool is expected to have ≥60% L4+ members when this is called.

    If create_relief_pool=True (default):
      - Attempt to create a new pool from paid WL members if WL >= POOL_CAPACITY.
      - The relief pool restores L1 member supply to the system.

    After the draw:
      - If pool.active_count falls below ACCEL_DISS_DISSOLVE_BELOW (8):
        → Pool condensed into other pools via Phase 3 (pool dissolved).
      - Otherwise: survivors advance, pool continues with accelerated mode
        for subsequent weeks until L4+ ratio normalises.

    Raises ValueError on validation failure.
    """
    from app.services.waitlist import assign_waitlist_to_pools, manual_create_pool

    pool: Pool | None = crud_pool.get_pool(db, pool_id)
    if not pool:
        raise ValueError(f"Accelerated dissolution: pool {pool_id} not found.")
    if pool.status != PoolStatus.Active:
        raise ValueError(
            f"Accelerated dissolution: pool '{pool.name}' is not Active."
        )
    if pool.draw_completed_this_week:
        raise ValueError(
            f"Accelerated dissolution: pool '{pool.name}' already drew this week."
        )

    # ── Get all active members ────────────────────────────────────────────────
    members: list[User] = (
        db.query(User)
        .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
        .all()
    )

    l4plus = [m for m in members if m.current_level >= 4]
    l4plus_ratio = len(l4plus) / max(1, len(members))

    if len(l4plus) < 2:
        raise ValueError(
            f"Accelerated dissolution: pool '{pool.name}' needs ≥ 2 L4+ members "
            f"(has {len(l4plus)})."
        )

    # ── Select both winners from L4+ using AI weights ─────────────────────────
    # "Lower winner"  = lower AI weight (less urgency — gives pool cleanup time)
    # "Upper winner"  = higher AI weight (most urgent exit per SDE score)
    from app.services.sde_engine import _compute_weighted_selection, _weighted_choice

    probabilities = _compute_weighted_selection(l4plus)
    upper_winner_id   = _weighted_choice(probabilities)
    upper_winner: User = next(m for m in l4plus if m.id == upper_winner_id)

    # Exclude upper winner for lower selection
    remaining_l4plus = [m for m in l4plus if m.id != upper_winner_id]
    lower_winner: User
    if remaining_l4plus:
        lower_probabilities = _compute_weighted_selection(remaining_l4plus)
        lower_winner_id = _weighted_choice(lower_probabilities)
        lower_winner = next(m for m in remaining_l4plus if m.id == lower_winner_id)
    else:
        raise ValueError(
            f"Accelerated dissolution: pool '{pool.name}' needs at least 2 distinct "
            f"L4+ members to draw two winners."
        )

    # ── Process both winners ──────────────────────────────────────────────────
    # skip_waitlist_fill=True here; we handle refill via assign_waitlist_to_pools later
    result_1 = _process_winner(db, upper_winner, pool, pull_replacement=False)
    db.refresh(pool)
    result_2 = _process_winner(db, lower_winner, pool, pull_replacement=False)

    # ── Advance surviving members ─────────────────────────────────────────────
    surviving_ids   = {m.id for m in members} - {upper_winner.id, lower_winner.id}
    week_id         = _current_week_id()
    new_l4_flagged  = False

    for member_id in surviving_ids:
        member = crud_user.get_user(db, member_id)
        if member and member.status == UserStatus.Active and member.current_pool_id == pool_id:
            new_level    = min(member.current_level + 1, 6)
            reaching_l4  = (new_level == 4)
            if reaching_l4:
                new_l4_flagged = True
            crud_user.update_user(
                db, member_id,
                UserUpdate(
                    current_level         = new_level,
                    weekly_payment_status = WeeklyPaymentStatus.Unpaid,
                    sde_required          = (True    if reaching_l4 else None),
                    sde_flagged_week      = (week_id if reaching_l4 else None),
                ),
            )

    if new_l4_flagged:
        pool.contains_flagged_l4 = True

    pool.draw_completed_this_week = True
    pool.pool_draw_type           = POOL_DRAW_ACCELERATED

    # ── DrawHistory record ────────────────────────────────────────────────────
    db.add(DrawHistory(
        pool_id             = pool.id,
        draw_type           = POOL_DRAW_ACCELERATED,
        targeted_early_exit = True,   # both winners are upper-tier forced exits
        edge_case_triggered = False,
        winner_1_user_id            = result_1.winner_id,
        winner_1_level              = result_1.winner_level,
        winner_1_net_payout         = result_1.net_payout_inr,
        winner_1_total_deposited    = upper_winner.total_deposited_inr or 1000,
        winner_1_merges_experienced = upper_winner.dynamic_merges_experienced or 0,
        winner_1_pauses_experienced = upper_winner.pauses_experienced or 0,
        winner_1_journey_type       = "merged" if (upper_winner.dynamic_merges_experienced or 0) > 0 else "direct",
        winner_2_user_id            = result_2.winner_id,
        winner_2_level              = result_2.winner_level,
        winner_2_net_payout         = result_2.net_payout_inr,
        winner_2_total_deposited    = lower_winner.total_deposited_inr or 1000,
        winner_2_merges_experienced = lower_winner.dynamic_merges_experienced or 0,
        winner_2_pauses_experienced = lower_winner.pauses_experienced or 0,
        winner_2_journey_type       = "merged" if (lower_winner.dynamic_merges_experienced or 0) > 0 else "direct",
    ))
    db.commit()

    # ── Create relief pool from waitlist ──────────────────────────────────────
    relief_pool_id: int | None = None
    if create_relief_pool:
        relief_pool = manual_create_pool(db)
        if relief_pool:
            relief_pool_id = relief_pool.id
            _logger.info(
                "Accelerated dissolution: relief pool '%s' (id=%d) created from WL.",
                relief_pool.name, relief_pool.id,
            )

    # ── Check dissolution threshold ───────────────────────────────────────────
    pool_dissolved = False
    remaining_active: int = (
        db.query(User)
        .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
        .count()
    )

    if remaining_active < ACCEL_DISS_DISSOLVE_BELOW:
        _logger.warning(
            "Accelerated dissolution: pool '%s' has only %d active members "
            "(< threshold %d) — triggering condensation / dissolution.",
            pool.name, remaining_active, ACCEL_DISS_DISSOLVE_BELOW,
        )
        # Demote remaining members back to Waitlist so Phase 3 condensation
        # can redistribute them into other pools (fills under-capacity pools).
        db.query(User).filter(
            User.current_pool_id == pool_id,
            User.status          == UserStatus.Active,
        ).update(
            {
                "status":          UserStatus.Waitlist,
                "current_pool_id": None,
            },
            synchronize_session=False,
        )
        pool.status = PoolStatus.Dissolved
        db.commit()
        pool_dissolved = True
        _logger.info(
            "Accelerated dissolution: pool '%s' DISSOLVED — %d member(s) returned "
            "to Waitlist for Phase 3 condensation.",
            pool.name, remaining_active,
        )
        # Run condensation to redistribute the returned members
        assign_waitlist_to_pools(db)
    else:
        # Run normal refill — fills the 2 vacancies from waitlist
        assign_waitlist_to_pools(db)

    _logger.info(
        "Accelerated dissolution COMPLETE: pool='%s'  L4+_ratio=%.0f%%  "
        "upper=@%s(L%d)  lower=@%s(L%d)  dissolved=%s  relief_pool=%s",
        pool.name, l4plus_ratio * 100,
        upper_winner.username, upper_winner.current_level,
        lower_winner.username, lower_winner.current_level,
        pool_dissolved, relief_pool_id,
    )

    return AccelDissolutionResult(
        pool_id=pool_id,
        pool_name=pool.name,
        winner_1=result_1,
        winner_2=result_2,
        relief_pool_id=relief_pool_id,
        pool_dissolved=pool_dissolved,
        l4plus_ratio=l4plus_ratio,
    )
