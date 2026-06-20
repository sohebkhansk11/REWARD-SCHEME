"""
Brain 5 — Level Pressure Index (LPI) Engine
============================================
Master real-time indicator for the Anti-Maturity Protocol.

Responsibilities:
  1. Calculate LPI — the single number that governs pool type routing.
  2. Snapshot the level distribution (L1–L6 active member counts).
  3. Decide pool types for the upcoming draw cycle.
  4. Quantify SDE demand (how many sessions, how many L1/L2 needed).
  5. Compute the forward signal fed into Brain 2 tri-velocity.
  6. Flag L4 members atomically at the start of T-2H preparation.
  7. Redistribute pools where multiple L4 members co-exist (BUG 2 fix).

LPI Formula:
  LPI = (L3 + L4 + L5 + L6) ÷ Total Active Members × 100

LPI thresholds (from config):
  < 14%  → Regular Pool
  14–24% → Execution Pool Type A
  ≥ 25%  → SDE proactive (even without L4)
  Any L4 → SDE HARD OVERRIDE (regardless of LPI value)
  > 50%  → L3 allowed to win SDE lower tier (LPI exception)

All write operations (flag_l4_members, redistribute_multi_l4_pools) are
caller-committed — this module does NOT call db.commit() itself.  The
caller (draw_preparation.py) commits all Phase 0 writes atomically.
"""

import logging
import math
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import (
    LPI_REGULAR_MAX,
    LPI_TYPE_A_MIN,
    LPI_SDE_PROACTIVE,
    LPI_L3_WIN_EXCEPTION,
    SDE_L1L2_THRESHOLD_PER_L4,
    SDE_MAX_POOLS_PER_SESSION,
)
from app.models.user  import User, UserStatus
from app.models.pool  import Pool, PoolStatus
from app.schemas.brain5 import (
    LevelDistribution, PoolTypeDecision, SDEDemand, PoolRedistribution,
)

_logger = logging.getLogger(__name__)


# ── 1. Level distribution snapshot ───────────────────────────────────────────

def get_level_distribution(db: Session) -> LevelDistribution:
    """
    Single GROUP BY query — returns active member counts per level (L1–L6).
    Levels with zero members are represented as 0 (not absent from the dict).
    """
    rows = (
        db.query(User.current_level, func.count(User.id).label("cnt"))
        .filter(User.status == UserStatus.Active)
        .group_by(User.current_level)
        .all()
    )
    counts = {row.current_level: row.cnt for row in rows}
    return LevelDistribution(
        l1=counts.get(1, 0),
        l2=counts.get(2, 0),
        l3=counts.get(3, 0),
        l4=counts.get(4, 0),
        l5=counts.get(5, 0),
        l6=counts.get(6, 0),
    )


# ── 2. LPI calculation ────────────────────────────────────────────────────────

def calculate_lpi(db: Session) -> float:
    """
    LPI = (L3 + L4 + L5 + L6) ÷ Total Active Members × 100

    Returns 0.0 when there are no active members (prevents ZeroDivisionError).
    Result is rounded to 2 decimal places.
    """
    dist = get_level_distribution(db)
    if dist.total == 0:
        return 0.0
    lpi = (dist.pressure_count / dist.total) * 100.0
    return round(lpi, 2)


# ── 3. Pool type decision ────────────────────────────────────────────────────

def decide_pool_types(db: Session) -> PoolTypeDecision:
    """
    Evaluate the current system state and return a PoolTypeDecision that
    tells the draw router how to classify each pool.

    Decision logic (priority order):
      P1 — SDE triggered if:
           (a) ANY L4 member exists AND sde_required=True  → hard override
           (b) LPI ≥ LPI_SDE_PROACTIVE (25%)               → proactive SDE
      P2 — TYPE_A if LPI is in the 14–24% band
      P3 — REGULAR if LPI < 14%
      P4 — TYPE_B if L1/L2 pool is fully exhausted
           (only relevant when P2 / P3 pools exhaust lower tier supply)
    """
    dist = get_level_distribution(db)
    lpi  = calculate_lpi(db)

    # Count flagged L4 members (sde_required=True AND Active)
    l4_flagged = (
        db.query(func.count(User.id))
        .filter(User.status == UserStatus.Active, User.sde_required == True)  # noqa: E712
        .scalar()
    ) or 0

    l1l2_available = dist.l1l2_count

    decision = PoolTypeDecision(lpi=lpi, dist=dist)

    # ── P1: SDE ───────────────────────────────────────────────────────────────
    if l4_flagged > 0:
        decision.p1_sde_active  = True
        decision.p1_sde_reason  = "hard_override_l4"
        decision.l4_flagged_count = l4_flagged
    elif lpi >= LPI_SDE_PROACTIVE:
        decision.p1_sde_active  = True
        decision.p1_sde_reason  = "proactive_lpi"
        decision.l4_flagged_count = l4_flagged

    # SDE supply sufficiency check
    threshold = l4_flagged * SDE_L1L2_THRESHOLD_PER_L4
    decision.sde_threshold_met = (l1l2_available >= threshold) if l4_flagged > 0 else True

    # ── P2: TYPE_A ────────────────────────────────────────────────────────────
    if LPI_TYPE_A_MIN <= lpi < LPI_SDE_PROACTIVE and dist.l3 > 0:
        decision.p2_type_a_active = True

    # ── P3: REGULAR ───────────────────────────────────────────────────────────
    if lpi < LPI_REGULAR_MAX:
        decision.p3_regular_active = True

    # ── P4: TYPE_B ────────────────────────────────────────────────────────────
    decision.l1l2_exhausted    = (l1l2_available == 0)
    decision.p4_type_b_active  = decision.l1l2_exhausted

    _logger.info(
        "Brain5 decide_pool_types: LPI=%.2f%%  L4_flagged=%d  decision=[%s]",
        lpi, l4_flagged, decision.summary(),
    )
    return decision


# ── 4. SDE demand quantification ─────────────────────────────────────────────

def get_sde_demand(db: Session) -> SDEDemand:
    """
    Quantify the full SDE resource requirement for the current draw cycle.

    Returns an SDEDemand object with:
      - How many L4 members need processing
      - How many SDE sessions that requires (ceil(l4_count / 6))
      - Minimum L1/L2 candidates needed (l4_count × 2)
      - How many can actually be cleared given current supply
      - The overflow count (requires admin override if > 0)
    """
    l4_members = get_flagged_l4_members(db)
    l4_count   = len(l4_members)

    dist           = get_level_distribution(db)
    l1l2_available = dist.l1l2_count
    threshold      = l4_count * SDE_L1L2_THRESHOLD_PER_L4

    # How many L4 can we actually clear this cycle?
    # Each L4 draw consumes 1 upper slot + 1 lower slot (from L1/L2).
    # So max clearable = floor(l1l2_available / 2), capped at l4_count.
    clearable = min(l4_count, l1l2_available // 2) if l4_count > 0 else 0
    overflow  = l4_count - clearable

    sessions_needed = math.ceil(l4_count / SDE_MAX_POOLS_PER_SESSION) if l4_count > 0 else 0

    _logger.info(
        "Brain5 SDE demand: L4=%d  sessions=%d  L1L2_needed=%d  L1L2_have=%d  "
        "clearable=%d  overflow=%d",
        l4_count, sessions_needed, threshold, l1l2_available, clearable, overflow,
    )

    return SDEDemand(
        l4_count=l4_count,
        sessions_needed=sessions_needed,
        l1l2_threshold=threshold,
        l4_members=l4_members,
        l1l2_available=l1l2_available,
        clearable_count=clearable,
        overflow_count=overflow,
        overflow_requires_admin=(overflow > 0),
    )


# ── 5. Forward signal (Brain 2 input) ────────────────────────────────────────

def get_forward_signal(db: Session) -> float:
    """
    Brain 5 forward signal: projected new L3 members next week.

    Formula:
      forward_signal = current_L2_count × actual_survival_rate

    actual_survival_rate is computed from the last 4 completed draw weeks:
      survivors_advanced / total_survivors_in_those_weeks

    Falls back to the theoretical rate of 5/6 ≈ 0.8333 when no draw
    history exists or fewer than 4 weeks of data are available.

    This signal feeds into Brain 2 tri-velocity as the 20% "forward"
    component, giving the velocity calculation a forward-looking bias
    rather than being purely backward-looking.
    """
    from app.models.draw_history import DrawHistory

    dist = get_level_distribution(db)
    current_l2 = dist.l2

    # ── Compute actual L2→L3 survival rate from draw history ─────────────────
    # A member "survives" a draw week if they were NOT a winner (i.e. not
    # Eliminated_Won in that week).  In a full pool of 12, 10 survive.
    # Of those 10, 10 advance.  So the survival rate is always 10/12 = 5/6
    # per draw.  However, paused pools and edge cases lower this empirically.
    #
    # We approximate by looking at L3 members who were L2 last week:
    # DrawHistory tells us net payout levels but not survivor advancement.
    # Use structural inference: each draw eliminates 2 of 12 → 10/12 ≈ 0.833.
    # Adjust if we have evidence of pauses (pools not drawing).
    _THEORETICAL_RATE = 5 / 6  # 10 survivors / 12 members

    draws_last_4_weeks = (
        db.query(DrawHistory)
        .order_by(DrawHistory.draw_timestamp.desc())
        .limit(4 * 10)  # approx 4 weeks × up to 10 pools
        .all()
    )

    actual_rate = _THEORETICAL_RATE  # default

    if draws_last_4_weeks:
        # Count pools that drew each week; if significantly fewer than all active
        # pools, adjust survival rate downward to account for paused-pool members
        active_pool_count = (
            db.query(func.count(Pool.id))
            .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
            .scalar()
        ) or 1

        pools_that_drew = len({d.pool_id for d in draws_last_4_weeks})
        draw_participation_rate = min(1.0, pools_that_drew / max(1, active_pool_count))

        # Blend theoretical rate with draw participation as a discount factor
        actual_rate = _THEORETICAL_RATE * draw_participation_rate

    forward_signal = current_l2 * actual_rate

    _logger.debug(
        "Brain5 forward_signal: L2=%d  survival_rate=%.3f  forward_l3=%.1f",
        current_l2, actual_rate, forward_signal,
    )
    return round(forward_signal, 2)


# ── 6. L4 flagging (called at T-2H) ──────────────────────────────────────────

def flag_l4_members(db: Session) -> int:
    """
    Set sde_required=True on ALL active L4 members who are not yet flagged.
    Records the current ISO week key in sde_flagged_week.

    This is called at T-2H preparation time as a belt-and-suspenders sweep.
    The primary flag is set atomically during level advancement in draw.py,
    but this catch-up sweep handles any edge cases where a member was
    promoted to L4 outside the normal draw cycle (e.g., admin override,
    data correction).

    Returns the count of members newly flagged (0 if all already flagged).
    Does NOT call db.commit() — caller owns the transaction.
    """
    now     = datetime.now(timezone.utc)
    iso     = now.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"

    newly_flagged = (
        db.query(User)
        .filter(
            User.status == UserStatus.Active,
            User.current_level == 4,
            User.sde_required == False,   # noqa: E712
        )
        .all()
    )

    for member in newly_flagged:
        member.sde_required     = True
        member.sde_flagged_week = week_id

        # Also set the pool flag so condensation immunity kicks in
        if member.current_pool_id:
            pool = db.query(Pool).filter(Pool.id == member.current_pool_id).first()
            if pool and not pool.contains_flagged_l4:
                pool.contains_flagged_l4 = True

        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Forensic: record each L4 SDE-flag the moment it is set (catch-up sweep).
        try:
            from app.services import forensic as _forensic
            if _forensic.is_on():
                _forensic.sde_event(
                    "l4_flagged", lever="flag_sweep",
                    pool_id=member.current_pool_id,
                    ref=getattr(member, "username", None),
                    severity="notice",
                    payload={"user_id": member.id,
                             "username": getattr(member, "username", None),
                             "sde_flagged_week": week_id},
                    message=f"L4 SDE-flagged: {getattr(member, 'username', member.id)} "
                            f"(pool {member.current_pool_id}) week {week_id}",
                )
        except Exception:
            pass

    count = len(newly_flagged)
    if count:
        _logger.info(
            "Brain5 flag_l4_members: catch-up flagged %d member(s) as SDE-required "
            "for week %s.",
            count, week_id,
        )
    return count


def get_flagged_l4_members(db: Session) -> list:
    """
    Return all active members with sde_required=True.
    Ordered by join_date ASC (FIFO — earliest-joined L4 processed first).

    This ordering ensures fairness: members who have waited longest in L4
    limbo are cleared first.
    """
    return (
        db.query(User)
        .filter(
            User.status    == UserStatus.Active,
            User.sde_required == True,           # noqa: E712
        )
        .order_by(User.join_date.asc())
        .all()
    )


# ── 7. Multi-L4 pool redistribution (BUG 2 fix) ──────────────────────────────

def redistribute_multi_l4_pools(db: Session) -> list[PoolRedistribution]:
    """
    BUG 2 FIX: Detect and resolve pools that contain multiple L4 members.

    SDE architecture constraint: each sub-draw is exactly 1 L4 (upper winner)
    + up to 11 other members.  A pool with 2+ L4 members would require two
    separate sub-draws for the same pool — violating the "max 2 winners per
    pool" rule.

    Resolution: move excess L4 members (second, third, etc.) to pools that
    currently have ZERO L4 members.  Preserve all other member attributes.

    Algorithm:
      1. Find pools with ≥ 2 flagged L4 members.
      2. Find pools with 0 flagged L4 members (candidate receivers).
      3. Move excess L4 members one-by-one to receiver pools (FIFO by join_date).
      4. Update contains_flagged_l4 flags on affected pools.
      5. Return audit trail of all moves.

    Does NOT call db.commit() — caller owns the transaction.
    Returns empty list if no multi-L4 pools exist.
    """
    # Find all pools with their L4-flagged member count
    pool_l4_counts: dict[int, list] = {}
    flagged_members = get_flagged_l4_members(db)

    for member in flagged_members:
        if member.current_pool_id is None:
            continue
        pid = member.current_pool_id
        if pid not in pool_l4_counts:
            pool_l4_counts[pid] = []
        pool_l4_counts[pid].append(member)

    # Identify overflow: pools with > 1 L4 member
    overflow_members: list = []
    for pid, members in pool_l4_counts.items():
        if len(members) > 1:
            # Keep the first (oldest join_date — already FIFO sorted), move the rest
            excess = members[1:]
            overflow_members.extend(excess)
            _logger.warning(
                "Brain5 redistribute: pool %d has %d L4 members — "
                "moving %d excess to single-L4 pools.",
                pid, len(members), len(excess),
            )

    if not overflow_members:
        return []  # no redistribution needed

    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # BUG FIX: original query had no capacity check — a receiver pool already at
    # POOL_CAPACITY members would become capacity+1 after the move.  The candidate
    # loop in execute_weekly_draw then pauses it (actual≠12) and Phase 1 skips it
    # (vacancy=-1), creating a permanent Paused+over-capacity deadlock that stops
    # all draws in that pool forever.
    # Fix: pre-compute live active counts and exclude pools already at capacity.
    from app.core.config import POOL_CAPACITY as _RPOOL_CAP
    occupied_pool_ids = set(pool_l4_counts.keys())
    _all_receivers: list[Pool] = (
        db.query(Pool)
        .filter(
            Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]),
            Pool.contains_flagged_l4 == False,   # noqa: E712
            Pool.id.notin_(occupied_pool_ids),
        )
        .order_by(Pool.id.asc())
        .all()
    )
    _recv_ids = [p.id for p in _all_receivers]
    _recv_counts: dict[int, int] = {}
    if _recv_ids:
        for _row in (
            db.query(User.current_pool_id, func.count(User.id))
            .filter(
                User.current_pool_id.in_(_recv_ids),
                User.status == UserStatus.Active,
            )
            .group_by(User.current_pool_id)
            .all()
        ):
            _recv_counts[_row[0]] = _row[1]
    # Only pools with room for one more member are valid receivers
    receiver_pools: list[Pool] = [
        p for p in _all_receivers if _recv_counts.get(p.id, 0) < _RPOOL_CAP
    ]

    redistributions: list[PoolRedistribution] = []
    receiver_idx = 0

    for member in overflow_members:
        if receiver_idx >= len(receiver_pools):
            _logger.error(
                "Brain5 redistribute: ran out of receiver pools — "
                "%d L4 member(s) could not be redistributed.  "
                "Admin override required.",
                len(overflow_members) - receiver_idx,
            )
            break

        old_pool = db.query(Pool).filter(Pool.id == member.current_pool_id).first()
        new_pool = receiver_pools[receiver_idx]
        receiver_idx += 1

        # Record before mutation
        redistributions.append(PoolRedistribution(
            user_id=member.id,
            username=member.username,
            old_pool_id=old_pool.id if old_pool else 0,
            old_pool_name=old_pool.name if old_pool else "?",
            new_pool_id=new_pool.id,
            new_pool_name=new_pool.name,
            reason="multi_l4_in_pool",
        ))

        # Move member
        member.current_pool_id = new_pool.id

        # Update pool flags
        new_pool.contains_flagged_l4 = True

        # Re-check if old pool still has any L4 members
        if old_pool:
            remaining_l4 = (
                db.query(func.count(User.id))
                .filter(
                    User.current_pool_id == old_pool.id,
                    User.sde_required    == True,         # noqa: E712
                    User.status          == UserStatus.Active,
                    User.id              != member.id,   # exclude the member we just moved
                )
                .scalar()
            ) or 0
            if remaining_l4 == 0:
                old_pool.contains_flagged_l4 = False

        _logger.info(
            "Brain5 redistribute: moved L4 member %d (%s) from pool '%s' → '%s'.",
            member.id, member.username,
            old_pool.name if old_pool else "?",
            new_pool.name,
        )

    return redistributions


# ── 8. Total active count helper ─────────────────────────────────────────────

def get_total_active_count(db: Session) -> int:
    """Count of all Active members — used by draw_preparation snapshot."""
    return (
        db.query(func.count(User.id))
        .filter(User.status == UserStatus.Active)
        .scalar()
    ) or 0


# ── 9. L5/L6 existence check ─────────────────────────────────────────────────

def has_elevated_risk_members(db: Session) -> bool:
    """
    Returns True if any L5 or L6 active members exist.
    In normal operation this should always return False.
    Used by admin dashboard to surface edge-case anomalies.
    """
    count = (
        db.query(func.count(User.id))
        .filter(
            User.status == UserStatus.Active,
            User.current_level >= 5,
        )
        .scalar()
    ) or 0
    return count > 0
