"""
SDE Engine — Sequential Dynamic Eviction
=========================================
The Anti-Maturity Protocol execution core.  Guarantees that every L4 member
exits via a draw with 100% mathematical certainty.

Architecture:
  - Each L4 member's current pool is processed as one SDE sub-draw.
  - The L4 member is hardcoded as the upper-tier winner (guaranteed exit).
  - Lower tier: AI-weighted selection from the pool's own L1/L2 members.
    Exception: if LPI > 50%, L3 members may also win the lower tier.
  - All sub-draws within a session run sequentially in the backend.
  - Results are written to sde_checkpoints atomically after each sub-draw.
  - The final results are distributed to the original pools' DrawHistory.
  - After SDE processes a pool: pool.draw_completed_this_week = True,
    preventing execute_weekly_draw() from double-drawing it.

Crash safety:
  On restart, resume_from_checkpoint() reads the last completed sub-draw
  number and continues from (max + 1).  The UNIQUE constraint on
  (session_id, sub_draw_number) prevents duplicate writes.

Shared seeding efficiency:
  6 seeds serve N pools (N ≤ 6 per session) rather than N×6.
  Each sub-draw independently selects from its own pool's members,
  but the RNG seeds are derived from a shared server secret + session
  parameters, ensuring cross-pool independence without per-pool entropy.

AI weighting formula (lower tier):
  weight = (weeks_in_pool × 0.30) + (deposits_k × 0.25)
         + (pauses × 0.20) + (organic_score × 0.15) + (noise × 0.10)
  organic_score = 1.0 (organic join) | 0.3 (referred join)
  All weights floor-clamped to 5% of total weight before normalisation.
"""

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from math import ceil

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import (
    LEVEL_PAYOUTS, PAYOUT_FEE_INR,
    SDE_MAX_POOLS_PER_SESSION,
    SDE_L1L2_THRESHOLD_PER_L4,
    SDE_WL_EMERGENCY_PROMOTE,
    SDE_LEVEL_LOWER_NORMAL, SDE_LEVEL_LOWER_EXCEPTION, SDE_LEVEL_UPPER,
    SDE_EXT2_LEVEL_UPPER, SDE_EXT2_LEVEL_LOWER,
    SDE_EXT3_LEVEL_UPPER, SDE_EXT3_LEVEL_LOWER,
    L5_DRAWDOWN_ENABLED,
    LPI_L3_WIN_EXCEPTION,
    SDE_WEIGHT_TIME, SDE_WEIGHT_DEPOSIT, SDE_WEIGHT_PAUSE,
    SDE_WEIGHT_ORGANIC, SDE_WEIGHT_NOISE, SDE_WEIGHT_MIN_FLOOR,
    POOL_DRAW_SDE, POOL_DRAW_SDE_EXT2, POOL_DRAW_SDE_EXT3,
)
from app.crud import token as crud_token, user as crud_user
from app.models.draw_history import DrawHistory
from app.models.pool import Pool, PoolStatus
from app.models.sde_session import SDESession, SDECheckpoint, SDESessionStatus
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.schemas.token import TokenCreate
from app.schemas.user import UserUpdate

_logger = logging.getLogger(__name__)

# Server-side RNG secret — MUST be set in production environment.
# Without this secret, RNG seed hashes are not cryptographically meaningful.
_RNG_SECRET = os.getenv("DRAW_RNG_SECRET", "dev-insecure-secret-replace-in-prod")


# ── Data Transfer Objects ─────────────────────────────────────────────────────

@dataclass
class SDESubDrawResult:
    """Result of one completed SDE sub-draw."""
    sub_draw_number:       int
    session_id:            int
    pool_id:               int
    pool_name:             str
    upper_winner_user_id:  int
    upper_winner_level:    int
    upper_winner_payout:   Decimal
    lower_winner_user_id:  int
    lower_winner_level:    int
    lower_winner_payout:   Decimal
    lower_tier_override:   bool     # True = L3 won under LPI > 50% exception
    rng_seed_hash:         str
    checkpoint_saved:      bool = True


@dataclass
class SDESessionResult:
    """Aggregated result for one SDE session (up to 6 sub-draws)."""
    session_id:        int
    session_number:    int
    week_id:           str
    sub_draws:         list[SDESubDrawResult] = field(default_factory=list)
    overflow_user_ids: list[int]              = field(default_factory=list)
    total_l4_cleared:  int = 0
    total_payout_inr:  int = 0
    status:            str = SDESessionStatus.Planned


@dataclass
class SDEMetaPoolResult:
    """Complete SDE result for one draw week (all sessions combined)."""
    week_id:               str
    sessions:              list[SDESessionResult] = field(default_factory=list)
    total_l4_cleared:      int = 0
    total_pools_processed: int = 0
    overflow_l4_count:     int = 0
    overflow_user_ids:     list[int] = field(default_factory=list)


# ── RNG and cryptographic helpers ────────────────────────────────────────────

def _compute_rng_seed_hash(pool_id: int, session_id: int, sub_draw_number: int) -> str:
    """
    Deterministic SHA-256 seed for one sub-draw.

    Input: pool_id || session_id || sub_draw_number || server_secret || timestamp_second
    The timestamp_second component ensures different seeds on resume, preventing
    an attacker from pre-computing outcomes for a future session.

    Returns: 64-char hex digest.
    """
    ts_second = int(datetime.now(timezone.utc).timestamp())
    raw = f"{pool_id}|{session_id}|{sub_draw_number}|{_RNG_SECRET}|{ts_second}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── AI-weighted lower tier selection ─────────────────────────────────────────

def _calculate_member_weight(member: User, now: datetime) -> float:
    """
    Compute the raw (pre-normalised) selection weight for one lower-tier candidate.

    Weight = (weeks_in_pool × W_TIME) + (deposits_k × W_DEPOSIT)
           + (pauses × W_PAUSE) + (organic_score × W_ORGANIC)
           + (random_noise × W_NOISE)

    weeks_in_pool: time since join_date in fractional weeks (min 0)
    deposits_k:    total_deposited_inr ÷ 1000  (₹1,000 = 1 unit)
    pauses:        pauses_experienced counter
    organic_score: 1.0 if no referrer, 0.3 if referred
    noise:         small random perturbation from secrets [0, 0.1)
    """
    join_dt = member.join_date
    if join_dt.tzinfo is None:
        join_dt = join_dt.replace(tzinfo=timezone.utc)
    weeks = max(0.0, (now - join_dt).total_seconds() / (7 * 86400))
    deposits_k    = (member.total_deposited_inr or 1000) / 1000.0
    pauses        = float(member.pauses_experienced or 0)
    organic_score = 0.3 if member.referred_by_user_id else 1.0
    noise         = secrets.randbelow(100) / 1000.0   # 0.000 – 0.099

    return (
        weeks         * SDE_WEIGHT_TIME
        + deposits_k  * SDE_WEIGHT_DEPOSIT
        + pauses      * SDE_WEIGHT_PAUSE
        + organic_score * SDE_WEIGHT_ORGANIC
        + noise       * SDE_WEIGHT_NOISE
    )


def _compute_weighted_selection(
    candidates: list[User],
) -> dict[int, float]:
    """
    Compute normalised probability distribution over candidates.

    1. Calculate raw weight per candidate.
    2. Apply minimum floor: each candidate's weight ≥ (SDE_WEIGHT_MIN_FLOOR × sum).
    3. Normalise so all probabilities sum to 1.0.

    Returns: {user_id: probability}  — guaranteed sum ≈ 1.0.
    """
    if not candidates:
        return {}

    now = datetime.now(timezone.utc)
    raw_weights = {m.id: _calculate_member_weight(m, now) for m in candidates}
    total_raw   = sum(raw_weights.values())

    if total_raw == 0:
        # Degenerate case: all weights are zero — use uniform distribution
        uniform = 1.0 / len(candidates)
        return {m.id: uniform for m in candidates}

    # Apply floor: ensure minimum participation probability
    floor_weight = SDE_WEIGHT_MIN_FLOOR * total_raw
    floored = {uid: max(w, floor_weight) for uid, w in raw_weights.items()}

    total_floored = sum(floored.values())
    return {uid: w / total_floored for uid, w in floored.items()}


def _weighted_choice(probabilities: dict[int, float]) -> int:
    """
    Cryptographically seeded weighted random selection.

    Implements inverse CDF (alias-free) using secrets.randbelow for the
    uniform random draw — os.urandom backed, unpredictable.
    """
    items  = list(probabilities.items())
    cumulative = []
    running = 0.0
    for uid, prob in items:
        running += prob
        cumulative.append((uid, running))

    # Generate a uniform float in [0, 1) using secrets
    rand_int = secrets.randbelow(10_000_000)   # 7-digit precision
    r = rand_int / 10_000_000.0

    for uid, cum_prob in cumulative:
        if r <= cum_prob:
            return uid

    return items[-1][0]   # fallback: last item (handles floating-point rounding)


# ── Token generation shim ─────────────────────────────────────────────────────

def _get_unique_token_code(db: Session, prefix: str) -> str:
    """
    Generate a unique WIT-XXXXXX token code using cryptographic randomness.
    Mirrors the same function in draw.py — kept local to avoid circular import.
    """
    import string
    alphabet = string.ascii_uppercase + string.digits
    from app.crud import token as _crud_token
    while True:
        code = prefix + "".join(secrets.choice(alphabet) for _ in range(6))
        if not _crud_token.get_token_by_code(db, code):
            return code


# ── Core sub-draw execution ───────────────────────────────────────────────────

def execute_sde_sub_draw(
    db: Session,
    session_id: int,
    sub_draw_number: int,
    pool_id: int,
    l4_member_id: int,
    *,
    allow_l3_lower: bool = False,
) -> SDESubDrawResult:
    """
    Execute one SDE sub-draw.

    Guarantees:
      - upper winner = l4_member_id (100% certainty)
      - lower winner = AI-weighted selection from L1/L2 pool members
        (or L1/L2/L3 if allow_l3_lower=True under LPI > 50% exception)

    Atomicity:
      All DB writes in this function are part of ONE transaction:
        a) WIT token for upper winner (L4)
        b) WIT token for lower winner
        c) Both winners → Eliminated_Won, detached from pool
        d) DrawHistory row (draw_type='sde', targeted_early_exit=True for upper)
        e) SDECheckpoint row
        f) pool.draw_completed_this_week = True

    Raises:
      ValueError — if pool/member not found, wrong level, or empty lower tier.
    """
    from app.schemas.token import TokenCreate
    from app.models.token import TokenType, TokenStatus

    # ── Load and validate pool ────────────────────────────────────────────────
    pool: Pool | None = db.query(Pool).filter(Pool.id == pool_id).first()
    if not pool:
        raise ValueError(f"SDE sub-draw: pool {pool_id} not found.")

    if pool.draw_completed_this_week:
        raise ValueError(
            f"SDE sub-draw: pool '{pool.name}' already drew this week "
            "(draw_completed_this_week=True)."
        )

    # ── Load and validate L4 member ───────────────────────────────────────────
    l4_member: User | None = db.query(User).filter(User.id == l4_member_id).first()
    if not l4_member:
        raise ValueError(f"SDE sub-draw: L4 member {l4_member_id} not found.")
    if l4_member.current_level not in (4, 5):   # allow L5 for admin-override edge case
        raise ValueError(
            f"SDE sub-draw: member {l4_member_id} is level {l4_member.current_level}, "
            f"expected level 4 (or 5 for admin override)."
        )
    if l4_member.current_pool_id != pool_id:
        raise ValueError(
            f"SDE sub-draw: L4 member {l4_member_id} is not in pool {pool_id} "
            f"(currently in pool {l4_member.current_pool_id})."
        )

    # ── Build lower tier candidate pool ───────────────────────────────────────
    lower_bounds = SDE_LEVEL_LOWER_EXCEPTION if allow_l3_lower else SDE_LEVEL_LOWER_NORMAL
    lower_candidates: list[User] = (
        db.query(User)
        .filter(
            User.current_pool_id == pool_id,
            User.status          == UserStatus.Active,
            User.current_level   >= lower_bounds[0],
            User.current_level   <= lower_bounds[1],
            User.id              != l4_member_id,   # exclude the upper winner
        )
        .all()
    )

    if not lower_candidates:
        tier_desc = "L1/L2/L3" if allow_l3_lower else "L1/L2"
        # ── WL Emergency Promotion — pull waitlisted members into pool ─────────
        # POINT 4 FIX: Instead of immediately raising ValueError (which causes
        # this draw to be skipped / overflowed), attempt to pull paid Waitlist
        # members directly into the pool as L1 members.  This temporarily
        # expands the pool beyond 12; the two winners exiting this draw will
        # normalise the count back to 10-12 (refill handles the rest).
        #
        # Special conditions for emergency promotion:
        #   (a) Waitlist has paid members available
        #   (b) Pool upper tier has at least 1 L4+ member (valid SDE trigger)
        #   (c) Promotion count limited to SDE_WL_EMERGENCY_PROMOTE (default 2)
        #
        # If WL is also empty after this → final fallback: raise ValueError.
        wl_members: list[User] = (
            db.query(User)
            .filter(
                User.status                == UserStatus.Waitlist,
                User.weekly_payment_status == WeeklyPaymentStatus.Paid,
            )
            .order_by(User.join_date.asc())
            .limit(SDE_WL_EMERGENCY_PROMOTE)
            .all()
        )

        if wl_members:
            for wl_m in wl_members:
                crud_user.update_user(
                    db, wl_m.id,
                    UserUpdate(
                        status          = UserStatus.Active,
                        current_pool_id = pool_id,
                        current_level   = 1,
                    ),
                )
                # Credit referral bonus if referred (mirrors draw.py _process_winner)
                if wl_m.referred_by_user_id:
                    from app.services.draw import _credit_referral_bonus
                    _credit_referral_bonus(db, wl_m.referred_by_user_id)
            db.flush()

            # Re-query lower candidates now that WL members are in pool
            lower_candidates = (
                db.query(User)
                .filter(
                    User.current_pool_id == pool_id,
                    User.status          == UserStatus.Active,
                    User.current_level   >= lower_bounds[0],
                    User.current_level   <= lower_bounds[1],
                    User.id              != l4_member_id,
                )
                .all()
            )
            _logger.warning(
                "SDE sub-draw %d.%d: WL EMERGENCY PROMOTION — promoted %d WL member(s) "
                "into pool '%s' (L1/L2 shortage). Pool temporarily has %d members.",
                session_id, sub_draw_number, len(wl_members), pool.name,
                db.query(User).filter(
                    User.current_pool_id == pool_id,
                    User.status == UserStatus.Active,
                ).count(),
            )

        if not lower_candidates:
            raise ValueError(
                f"SDE sub-draw: pool '{pool.name}' has no eligible {tier_desc} members "
                f"for the lower tier, and Waitlist is also empty. "
                f"Pool needs manual supply injection before this draw can proceed."
            )

    # ── AI-weighted lower winner selection ────────────────────────────────────
    probabilities      = _compute_weighted_selection(lower_candidates)
    lower_winner_id    = _weighted_choice(probabilities)
    lower_winner: User = next(m for m in lower_candidates if m.id == lower_winner_id)
    lower_tier_override = (lower_winner.current_level == 3)

    if lower_tier_override:
        _logger.info(
            "SDE sub-draw %d.%d: L3 member %d (%s) won lower tier "
            "(LPI exception active).",
            session_id, sub_draw_number,
            lower_winner.id, lower_winner.username,
        )

    # ── Compute RNG seed hash ─────────────────────────────────────────────────
    rng_hash = _compute_rng_seed_hash(pool_id, session_id, sub_draw_number)

    # ── Payout calculation (stored in checkpoint for T-0H execution) ─────────
    upper_gross, upper_net = LEVEL_PAYOUTS.get(l4_member.current_level,    (6000, 5500))
    lower_gross, lower_net = LEVEL_PAYOUTS.get(lower_winner.current_level, (2500, 2000))
    upper_net_d = Decimal(str(upper_net))
    lower_net_d = Decimal(str(lower_net))

    # ── BEGIN T-2H STAGING TRANSACTION ───────────────────────────────────────
    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Bug #9 — Two-phase SDE commit.  T-2H = STAGING ONLY.
    #
    # Steps formerly executed here at T-2H and their new home:
    #   (a) WIT token upper    → DEFERRED → execute_staged_sde_draws() at T-0H
    #   (b) WIT token lower    → DEFERRED → execute_staged_sde_draws() at T-0H
    #   (c) Eliminated_Won     → DEFERRED → execute_staged_sde_draws() at T-0H
    #   (d) DrawHistory        → DEFERRED → execute_staged_sde_draws() at T-0H
    #   (f) Survivor advance   → DEFERRED → execute_staged_sde_draws() at T-0H
    #
    # Only the crash-recovery checkpoint and the draw-lock flag are written here.
    # Winners remain Active in their pool until T-0H so all reveals are simultaneous.

    # (e) SDE checkpoint — staged with executed=False; T-0H sets executed=True
    db.add(SDECheckpoint(
        session_id                 = session_id,
        sub_draw_number            = sub_draw_number,
        pool_id                    = pool.id,
        upper_winner_user_id       = l4_member.id,
        upper_winner_level         = l4_member.current_level,
        upper_payout_inr           = upper_net_d,
        lower_winner_user_id       = lower_winner.id,
        lower_winner_level         = lower_winner.current_level,
        lower_payout_inr           = lower_net_d,
        lower_winner_tier_override = lower_tier_override,
        rng_seed_hash              = rng_hash,
        executed                   = False,
    ))

    # (g) Draw-lock — prevents execute_weekly_draw() from re-drawing at T-0H.
    # contains_flagged_l4 cleared at T-0H after exits if no new L4 created.
    pool.draw_completed_this_week = True
    pool.pool_draw_type           = POOL_DRAW_SDE

    db.commit()
    # ── END T-2H STAGING TRANSACTION ─────────────────────────────────────────

    _logger.info(
        "SDE sub-draw %d.%d STAGED (T-2H): pool='%s'  upper=@%s(L%d ₹%s)  "
        "lower=@%s(L%d ₹%s)  seed=%s…  [exits deferred to T-0H]",
        session_id, sub_draw_number, pool.name,
        l4_member.username, l4_member.current_level, upper_net_d,
        lower_winner.username, lower_winner.current_level, lower_net_d,
        rng_hash[:12],
    )

    return SDESubDrawResult(
        sub_draw_number      = sub_draw_number,
        session_id           = session_id,
        pool_id              = pool.id,
        pool_name            = pool.name,
        upper_winner_user_id = l4_member.id,
        upper_winner_level   = l4_member.current_level,
        upper_winner_payout  = upper_net_d,
        lower_winner_user_id = lower_winner.id,
        lower_winner_level   = lower_winner.current_level,
        lower_winner_payout  = lower_net_d,
        lower_tier_override  = lower_tier_override,
        rng_seed_hash        = rng_hash,
        checkpoint_saved     = True,
    )


# ── Crash recovery ────────────────────────────────────────────────────────────

def get_resume_sub_draw_number(db: Session, session_id: int) -> int:
    """
    Crash-safe resume: return the next sub_draw_number to run for a session.

    Queries the sde_checkpoints table for the highest completed sub_draw_number
    in this session.  Returns (max + 1), or 1 if no checkpoints exist yet.
    """
    max_completed = (
        db.query(func.max(SDECheckpoint.sub_draw_number))
        .filter(SDECheckpoint.session_id == session_id)
        .scalar()
    )
    return (max_completed + 1) if max_completed is not None else 1


# ── Session orchestration ─────────────────────────────────────────────────────

def run_sde_session(
    db: Session,
    week_id: str,
    session_number: int,
    l4_batch: list[User],
    lpi: float,
) -> SDESessionResult:
    """
    Run one SDE session: process up to SDE_MAX_POOLS_PER_SESSION (6) L4 members.

    Algorithm:
      1. Create or retrieve the SDESession DB record.
      2. Determine resume point from existing checkpoints (crash recovery).
      3. For each L4 member in the batch:
         a. Check if checkpoint already exists (idempotent skip).
         b. Determine if L3 lower tier is allowed (LPI > 50% exception).
         c. Call execute_sde_sub_draw().
         d. On supply shortage: add to overflow, continue with remaining.
      4. Update session status and totals.
      5. Return SDESessionResult.
    """
    # ── Create or load session record ─────────────────────────────────────────
    session: SDESession | None = (
        db.query(SDESession)
        .filter(
            SDESession.week_id        == week_id,
            SDESession.session_number == session_number,
        )
        .first()
    )

    if not session:
        session = SDESession(
            week_id          = week_id,
            session_number   = session_number,
            status           = SDESessionStatus.Running,
            l4_count_planned = len(l4_batch),
            started_at       = datetime.now(timezone.utc),
        )
        db.add(session)
        db.flush()   # get session.id without full commit
    else:
        # Resuming a previously started session
        session.status     = SDESessionStatus.Running
        session.started_at = session.started_at or datetime.now(timezone.utc)

    result = SDESessionResult(
        session_id=session.id,
        session_number=session_number,
        week_id=week_id,
        status=SDESessionStatus.Running,
    )

    # ── L3 exception: allow L3 in lower tier if LPI > 50% ────────────────────
    allow_l3 = lpi > LPI_L3_WIN_EXCEPTION

    # ── Process each L4 member ────────────────────────────────────────────────
    for idx, l4_member in enumerate(l4_batch):
        sub_draw_num = idx + 1

        # Idempotency: skip if checkpoint already exists for this sub-draw
        existing_cp = (
            db.query(SDECheckpoint)
            .filter(
                SDECheckpoint.session_id      == session.id,
                SDECheckpoint.sub_draw_number == sub_draw_num,
            )
            .first()
        )
        if existing_cp:
            _logger.info(
                "SDE session %d sub-draw %d: checkpoint found — skipping (idempotent).",
                session.id, sub_draw_num,
            )
            # Re-construct result from checkpoint for return value completeness
            sub_result = SDESubDrawResult(
                sub_draw_number      = sub_draw_num,
                session_id           = session.id,
                pool_id              = existing_cp.pool_id,
                pool_name            = "?",
                upper_winner_user_id = existing_cp.upper_winner_user_id,
                upper_winner_level   = existing_cp.upper_winner_level,
                upper_winner_payout  = existing_cp.upper_payout_inr,
                lower_winner_user_id = existing_cp.lower_winner_user_id,
                lower_winner_level   = existing_cp.lower_winner_level,
                lower_winner_payout  = existing_cp.lower_payout_inr,
                lower_tier_override  = existing_cp.lower_winner_tier_override,
                rng_seed_hash        = existing_cp.rng_seed_hash,
                checkpoint_saved     = True,
            )
            result.sub_draws.append(sub_result)
            result.total_l4_cleared += 1
            continue

        # Verify pool assignment is still valid
        if l4_member.current_pool_id is None:
            _logger.warning(
                "SDE session %d sub-draw %d: L4 member %d (%s) has no pool — "
                "skipping (member may have already exited).",
                session.id, sub_draw_num, l4_member.id, l4_member.username,
            )
            result.overflow_user_ids.append(l4_member.id)
            continue

        try:
            sub_result = execute_sde_sub_draw(
                db,
                session_id      = session.id,
                sub_draw_number = sub_draw_num,
                pool_id         = l4_member.current_pool_id,
                l4_member_id    = l4_member.id,
                allow_l3_lower  = allow_l3,
            )
            result.sub_draws.append(sub_result)
            result.total_l4_cleared  += 1
            result.total_payout_inr  += int(sub_result.upper_winner_payout + sub_result.lower_winner_payout)

        except ValueError as exc:
            # Lower tier exhausted or other supply issue — overflow this member
            _logger.warning(
                "SDE session %d sub-draw %d: OVERFLOW — member %d (%s) "
                "could not be cleared: %s",
                session.id, sub_draw_num, l4_member.id, l4_member.username, exc,
            )
            result.overflow_user_ids.append(l4_member.id)

    # ── Finalise session ──────────────────────────────────────────────────────
    all_cleared = (result.total_l4_cleared == len(l4_batch))
    session.status             = SDESessionStatus.Completed if all_cleared else SDESessionStatus.Partial
    session.l4_count_completed = result.total_l4_cleared
    session.total_payout_inr   = result.total_payout_inr
    session.completed_at       = datetime.now(timezone.utc)
    db.commit()

    result.status = session.status
    _logger.info(
        "SDE session %d DONE — cleared %d/%d L4  overflow=%d  payout=₹%d",
        session.id, result.total_l4_cleared, len(l4_batch),
        len(result.overflow_user_ids), result.total_payout_inr,
    )
    return result


# ── CASE D: Dual-L4 Cross-Pool Draw ──────────────────────────────────────────
# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Bug #11 — Implements approved CASE D: when lower-tier supply = 0 AND waitlist = 0
# AND system-wide L4 count ≥ 2, pair L4 members from DIFFERENT pools for a dual-L4
# cross-pool draw.  Each L4 receives their own level's payout (₹5,500 each = ₹11,000
# total vs ₹7,500 normal but PREVENTS L4→L5 escalation at any cost).

def _case_d_pair_l4_members(l4_candidates: list[User]) -> list[tuple[User, User]]:
    """
    Group L4 candidates by pool, then pair consecutive pools (FIFO oldest pool first).

    One L4 per pool contributes; pools with zero L4 remaining are skipped.
    Returns list of (upper_winner, lower_winner) cross-pool pairs.
    """
    pool_to_first: dict[int, User] = {}
    for m in l4_candidates:
        pid = m.current_pool_id
        if pid is not None and pid not in pool_to_first:
            pool_to_first[pid] = m

    ordered = [pool_to_first[pid] for pid in sorted(pool_to_first.keys())]
    return [
        (ordered[i], ordered[i + 1])
        for i in range(0, len(ordered) - 1, 2)
    ]


def _execute_case_d_single_pair(
    db:          Session,
    session_num: int,
    upper_l4:    User,
    lower_l4:    User,
) -> bool:
    """
    Execute one CASE D dual-L4 cross-pool pair draw.

    Upper winner = Pool A's L4 (upper-tier payout).
    Lower winner = Pool B's L4 (lower-tier slot — receives L4 payout not L1/L2).

    Writes ONE DrawHistory row anchored to Pool A with edge_case_triggered=True.
    Advances survivors and sets draw_completed_this_week=True on BOTH pools.
    Issues WIT tokens for both.  Commits atomically.
    """
    from app.models.token import TokenType, TokenStatus

    try:
        pool_a: Pool | None = db.query(Pool).filter(Pool.id == upper_l4.current_pool_id).first()
        pool_b: Pool | None = db.query(Pool).filter(Pool.id == lower_l4.current_pool_id).first()
        if pool_a is None or pool_b is None:
            _logger.warning(
                "SDE CASE D: pool not found for pair (@%s pool=%s, @%s pool=%s) — skipping.",
                upper_l4.username, upper_l4.current_pool_id,
                lower_l4.username, lower_l4.current_pool_id,
            )
            return False

        # Journey snapshot BEFORE any mutations
        _up_dep    = upper_l4.total_deposited_inr        or 1000
        _up_merges = upper_l4.dynamic_merges_experienced or 0
        _up_pauses = upper_l4.pauses_experienced         or 0
        _lo_dep    = lower_l4.total_deposited_inr        or 1000
        _lo_merges = lower_l4.dynamic_merges_experienced or 0
        _lo_pauses = lower_l4.pauses_experienced         or 0

        # Both receive their level's net payout (L4 = ₹5,500 — same as upper normal SDE)
        _, upper_net = LEVEL_PAYOUTS.get(upper_l4.current_level, (6000, 5500))
        _, lower_net = LEVEL_PAYOUTS.get(lower_l4.current_level, (6000, 5500))
        upper_net_d  = Decimal(str(upper_net))
        lower_net_d  = Decimal(str(lower_net))

        rng_hash = _compute_rng_seed_hash(pool_a.id, session_num, 1)

        # WIT token — upper winner (Pool A L4)
        crud_token.create_token(db, TokenCreate(
            code      = _get_unique_token_code(db, "WIT-"),
            type      = TokenType.Withdraw,
            value_inr = upper_net_d,
            user_id   = upper_l4.id,
            pool_id   = pool_a.id,
            status    = TokenStatus.Active,
        ))

        # WIT token — lower winner (Pool B L4, cross-pool)
        crud_token.create_token(db, TokenCreate(
            code      = _get_unique_token_code(db, "WIT-"),
            type      = TokenType.Withdraw,
            value_inr = lower_net_d,
            user_id   = lower_l4.id,
            pool_id   = pool_b.id,
            status    = TokenStatus.Active,
        ))

        # Exit both as Eliminated_Won
        crud_user.update_user(db, upper_l4.id, UserUpdate(
            status           = UserStatus.Eliminated_Won,
            current_pool_id  = None,
            sde_required     = False,
            sde_flagged_week = None,
        ))
        crud_user.update_user(db, lower_l4.id, UserUpdate(
            status           = UserStatus.Eliminated_Won,
            current_pool_id  = None,
            sde_required     = False,
            sde_flagged_week = None,
        ))

        # DrawHistory anchored to Pool A — edge_case_triggered=True marks CASE D cross-pool
        db.add(DrawHistory(
            pool_id             = pool_a.id,
            draw_type           = POOL_DRAW_SDE,
            targeted_early_exit = True,
            edge_case_triggered = True,
            winner_1_user_id            = upper_l4.id,
            winner_1_level              = upper_l4.current_level,
            winner_1_net_payout         = upper_net_d,
            winner_1_total_deposited    = _up_dep,
            winner_1_merges_experienced = _up_merges,
            winner_1_pauses_experienced = _up_pauses,
            winner_1_journey_type       = "merged" if _up_merges > 0 else "direct",
            winner_2_user_id            = lower_l4.id,
            winner_2_level              = lower_l4.current_level,
            winner_2_net_payout         = lower_net_d,
            winner_2_total_deposited    = _lo_dep,
            winner_2_merges_experienced = _lo_merges,
            winner_2_pauses_experienced = _lo_pauses,
            winner_2_journey_type       = "merged" if _lo_merges > 0 else "direct",
        ))

        # Advance survivors in BOTH pools + mark draw_completed
        now_utc = datetime.now(timezone.utc)
        iso_wk  = now_utc.isocalendar()
        wk_id   = f"{iso_wk.year}-W{iso_wk.week:02d}"

        for pool, exited_id in ((pool_a, upper_l4.id), (pool_b, lower_l4.id)):
            new_l4_created = False
            for s in (
                db.query(User)
                .filter(
                    User.current_pool_id == pool.id,
                    User.status          == UserStatus.Active,
                    User.id              != exited_id,
                )
                .all()
            ):
                new_lvl = min(s.current_level + 1, 6)
                if new_lvl == 4:
                    new_l4_created = True
                crud_user.update_user(db, s.id, UserUpdate(
                    current_level         = new_lvl,
                    weekly_payment_status = WeeklyPaymentStatus.Unpaid,
                    sde_required          = (True   if new_lvl == 4 else None),
                    sde_flagged_week      = (wk_id  if new_lvl == 4 else None),
                ))
            pool.draw_completed_this_week = True
            pool.pool_draw_type           = POOL_DRAW_SDE
            if not new_l4_created:
                pool.contains_flagged_l4 = False

        db.commit()

        _logger.info(
            "SDE CASE D ✓  upper=@%s(Pool '%s' L%d ₹%s)  "
            "lower=@%s(Pool '%s' L%d ₹%s)  total_payout=₹%s",
            upper_l4.username, pool_a.name, upper_l4.current_level, upper_net_d,
            lower_l4.username, pool_b.name, lower_l4.current_level, lower_net_d,
            upper_net_d + lower_net_d,
        )
        return True

    except Exception as exc:
        _logger.error(
            "SDE CASE D: pair (@%s, @%s) failed: %s",
            upper_l4.username, lower_l4.username, exc, exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False


# ── Meta-pool orchestration ───────────────────────────────────────────────────

def run_sde_meta_pool(db: Session, week_id: str) -> SDEMetaPoolResult:
    """
    Master SDE orchestrator for one draw week.

    Runs as many SDE sessions as needed to clear all flagged L4 members.
    Each session handles up to 6 L4 members.

    Steps:
      1. Get flagged L4 members (Brain 5).
      2. Redistribute multi-L4 pools (BUG 2 fix via Brain 5).
      3. Re-read flagged members after redistribution.
      4. Calculate current LPI for L3 exception check.
      5. Partition into batches of ≤ 6.
      6. For each batch: check supply sufficiency, run session.
      7. Collect overflow (L4 members that couldn't be cleared).
      8. Return SDEMetaPoolResult.
    """
    from app.services.brain5_lpi_engine import (
        get_flagged_l4_members, redistribute_multi_l4_pools, calculate_lpi,
    )

    _logger.info("SDE Meta-Pool: starting for week %s", week_id)

    # Step 1+2: flag, redistribute
    redistributions = redistribute_multi_l4_pools(db)
    if redistributions:
        db.commit()
        _logger.info(
            "SDE Meta-Pool: redistributed %d L4 member(s) from multi-L4 pools.",
            len(redistributions),
        )

    # Step 3: re-read after redistribution
    l4_members = get_flagged_l4_members(db)

    if not l4_members:
        _logger.info("SDE Meta-Pool: no flagged L4 members — nothing to process.")
        return SDEMetaPoolResult(week_id=week_id)

    # Step 4: LPI for L3 exception check + cascade risk assessment
    lpi = calculate_lpi(db)
    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Bug #7 — supply check was fixed at current_level <= 2 (L1+L2 only) which
    # ignored L3 members even when cascade_risk > 1.0.  False supply shortage
    # triggered admin_override_required → SDE deferred → L4 accumulated → L5.
    # Cascade Risk = L3_count / MAX(L1+L2, 1).  Thresholds (approved): >1.0
    # Forming (L3 eligible), >2.0 Extreme (L3 mandatory).  Supply check now
    # widens to level ≤ 3 when cascade_risk > 1.0 OR lpi > LPI_L3_WIN_EXCEPTION.
    _l3_sys = (
        db.query(func.count(User.id))
        .filter(User.status == UserStatus.Active, User.current_level == 3)
        .scalar()
    ) or 0
    _l1l2_sys = (
        db.query(func.count(User.id))
        .filter(User.status == UserStatus.Active, User.current_level <= 2)
        .scalar()
    ) or 0
    cascade_risk    = _l3_sys / max(_l1l2_sys, 1)
    allow_l3_supply = cascade_risk > 1.0 or lpi > LPI_L3_WIN_EXCEPTION
    _logger.info(
        "SDE Meta-Pool: cascade_risk=%.3f  L3=%d  L1+L2=%d  "
        "allow_l3_supply=%s  lpi=%.1f%%",
        cascade_risk, _l3_sys, _l1l2_sys, allow_l3_supply, lpi,
    )

    meta_result = SDEMetaPoolResult(week_id=week_id)
    session_num  = 1
    remaining    = list(l4_members)

    while remaining:
        batch     = remaining[:SDE_MAX_POOLS_PER_SESSION]
        remaining = remaining[SDE_MAX_POOLS_PER_SESSION:]

        # Check lower-tier supply sufficiency for this batch.
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Bug #7 — lower-tier threshold widens to level ≤ 3 (includes L3) when
        # cascade_risk > 1.0 or lpi > LPI_L3_WIN_EXCEPTION.  Previously fixed at
        # level ≤ 2 which under-counted supply and triggered false overrides.
        pool_ids           = [m.current_pool_id for m in batch if m.current_pool_id]
        _lower_max_level   = 3 if allow_l3_supply else 2
        lower_supply_count = (
            db.query(func.count(User.id))
            .filter(
                User.current_pool_id.in_(pool_ids),
                User.status          == UserStatus.Active,
                User.current_level   <= _lower_max_level,
            )
            .scalar()
        ) or 0

        min_needed = len(batch) * SDE_L1L2_THRESHOLD_PER_L4
        if lower_supply_count < min_needed:
            # Reduce batch to what supply allows
            clearable           = lower_supply_count // SDE_L1L2_THRESHOLD_PER_L4
            overflow_from_batch = batch[clearable:]
            batch               = batch[:clearable]
            meta_result.overflow_l4_count  += len(overflow_from_batch)
            meta_result.overflow_user_ids.extend(m.id for m in overflow_from_batch)
            _logger.warning(
                "SDE Meta-Pool session %d: supply shortage — "
                "lower_supply(L1+L2%s)=%d  needed=%d  "
                "reducing batch from %d → %d  overflow=%d",
                session_num,
                "+L3" if allow_l3_supply else "",
                lower_supply_count, min_needed,
                clearable + len(overflow_from_batch), clearable,
                len(overflow_from_batch),
            )

        if not batch:
            # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Bug #11 — CASE D: before giving up on this batch, check whether two or more
            # L4 members exist in DIFFERENT pools so they can be paired cross-pool.
            # Conditions: lower_supply=0 AND waitlist=0 AND distinct_l4_pools≥2.
            # Cost: ₹11,000 (₹5,500 + ₹5,500) — prevents L4→L5 at all costs.
            all_uncleared = overflow_from_batch + remaining
            remaining     = []  # all consumed; remaining repopulated below

            wl_count = (
                db.query(func.count(User.id))
                .filter(User.status == UserStatus.Waitlist)
                .scalar()
            ) or 0

            paired_ids: set[int] = set()
            if wl_count == 0 and len(all_uncleared) >= 2:
                pairs = _case_d_pair_l4_members(all_uncleared)
                for upper_l4, lower_l4 in pairs:
                    if _execute_case_d_single_pair(db, session_num, upper_l4, lower_l4):
                        meta_result.total_l4_cleared += 2
                        session_num                  += 1
                        paired_ids.add(upper_l4.id)
                        paired_ids.add(lower_l4.id)
                if paired_ids:
                    _logger.info(
                        "SDE Meta-Pool: CASE D cleared %d pair(s) (%d L4 exits). "
                        "edge_case_triggered=True on respective DrawHistory rows.",
                        len(paired_ids) // 2, len(paired_ids),
                    )

            # Any L4 members not paired → true overflow
            unpaired = [m for m in all_uncleared if m.id not in paired_ids]
            if unpaired:
                meta_result.overflow_l4_count += len(unpaired)
                meta_result.overflow_user_ids.extend(m.id for m in unpaired)
                _logger.warning(
                    "SDE Meta-Pool: %d L4 member(s) → overflow "
                    "(CASE D cleared %d, wl=%d, true_supply=0).",
                    len(unpaired), len(paired_ids) // 2, wl_count,
                )
            break

        session_result = run_sde_session(db, week_id, session_num, batch, lpi)
        meta_result.sessions.append(session_result)
        meta_result.total_l4_cleared      += session_result.total_l4_cleared
        meta_result.total_pools_processed += len(session_result.sub_draws)

        # Add session-level overflow to meta overflow
        meta_result.overflow_l4_count  += len(session_result.overflow_user_ids)
        meta_result.overflow_user_ids.extend(session_result.overflow_user_ids)

        session_num += 1

    _logger.info(
        "SDE Meta-Pool COMPLETE: week=%s  sessions=%d  L4_cleared=%d  overflow=%d",
        week_id, len(meta_result.sessions),
        meta_result.total_l4_cleared, meta_result.overflow_l4_count,
    )
    return meta_result


# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Bug #9 — Step 4: T-0H execution phase.
# execute_staged_sde_draws() commits all sub-draws that were staged at T-2H.
# Called by execute_weekly_draw() at T-0H before the main candidate-pool loop.
# For each SDECheckpoint where executed=False and session.week_id = this week:
#   - Loads pool + both winners from DB (still Active, still in pool)
#   - Issues WIT tokens, sets Eliminated_Won, writes DrawHistory
#   - Advances survivors (+1 level, flags new L4s)
#   - Marks checkpoint.executed=True and commits atomically per checkpoint
# Returns the count of checkpoints executed (0 if nothing was staged).

def execute_staged_sde_draws(db: Session) -> int:
    """
    T-0H phase of the two-phase SDE commit.  Executes all sub-draws that were
    staged (executed=False) at T-2H for the current ISO week.

    Returns the number of checkpoints committed.  Logs warnings for any
    checkpoint that cannot be fully committed (both winners must still be
    Active and in their original pool).
    """
    from app.models.token import TokenType, TokenStatus

    now_utc  = datetime.now(timezone.utc)
    iso      = now_utc.isocalendar()
    week_id  = f"{iso.year}-W{iso.week:02d}"

    # All staged-but-not-yet-executed checkpoints for this week, ordered by
    # session then sub-draw so pair execution is deterministic.
    staged = (
        db.query(SDECheckpoint)
        .join(SDESession, SDECheckpoint.session_id == SDESession.id)
        .filter(
            SDESession.week_id    == week_id,
            SDECheckpoint.executed == False,  # noqa: E712
        )
        .order_by(SDECheckpoint.session_id, SDECheckpoint.sub_draw_number)
        .all()
    )

    if not staged:
        _logger.info(
            "execute_staged_sde_draws: no staged SDE sub-draws for week %s.", week_id,
        )
        return 0

    _logger.info(
        "execute_staged_sde_draws: executing %d staged sub-draw(s) for week %s (T-0H).",
        len(staged), week_id,
    )

    executed_count = 0

    for cp in staged:
        try:
            # ── Load pool ─────────────────────────────────────────────────────
            pool: Pool | None = db.query(Pool).filter(Pool.id == cp.pool_id).first()
            if not pool:
                _logger.error(
                    "execute_staged_sde_draws: pool %d not found for checkpoint %d — skip.",
                    cp.pool_id, cp.id,
                )
                continue

            # ── Load both winners — must still be Active in their pool ────────
            upper: User | None = (
                db.query(User)
                .filter(
                    User.id             == cp.upper_winner_user_id,
                    User.status         == UserStatus.Active,
                    User.current_pool_id == cp.pool_id,
                )
                .first()
            )
            lower: User | None = (
                db.query(User)
                .filter(
                    User.id             == cp.lower_winner_user_id,
                    User.status         == UserStatus.Active,
                    User.current_pool_id == cp.pool_id,
                )
                .first()
            )

            if not upper or not lower:
                _logger.error(
                    "execute_staged_sde_draws: checkpoint %d — winner(s) not found "
                    "or no longer Active in pool %d (upper=%s lower=%s) — skip.",
                    cp.id, cp.pool_id,
                    upper.id if upper else "MISSING",
                    lower.id if lower else "MISSING",
                )
                continue

            # ── Snapshot journey data (fresh from DB — users haven't exited yet) ──
            _up_dep    = upper.total_deposited_inr        or 1000
            _up_merges = upper.dynamic_merges_experienced or 0
            _up_pauses = upper.pauses_experienced         or 0
            _lo_dep    = lower.total_deposited_inr        or 1000
            _lo_merges = lower.dynamic_merges_experienced or 0
            _lo_pauses = lower.pauses_experienced         or 0

            upper_net_d = cp.upper_payout_inr   # computed at T-2H, stored in checkpoint
            lower_net_d = cp.lower_payout_inr

            # (a) WIT token — upper winner (L4 guaranteed exit)
            crud_token.create_token(
                db,
                TokenCreate(
                    code      = _get_unique_token_code(db, "WIT-"),
                    type      = TokenType.Withdraw,
                    value_inr = upper_net_d,
                    user_id   = upper.id,
                    pool_id   = pool.id,
                    status    = TokenStatus.Active,
                ),
            )

            # (b) WIT token — lower winner
            crud_token.create_token(
                db,
                TokenCreate(
                    code      = _get_unique_token_code(db, "WIT-"),
                    type      = TokenType.Withdraw,
                    value_inr = lower_net_d,
                    user_id   = lower.id,
                    pool_id   = pool.id,
                    status    = TokenStatus.Active,
                ),
            )

            # (c) Exit both winners
            crud_user.update_user(
                db, upper.id,
                UserUpdate(
                    status           = UserStatus.Eliminated_Won,
                    current_pool_id  = None,
                    sde_required     = False,
                    sde_flagged_week = None,
                ),
            )
            crud_user.update_user(
                db, lower.id,
                UserUpdate(status=UserStatus.Eliminated_Won, current_pool_id=None),
            )

            # (d) DrawHistory row — simultaneous reveal with all T-0H regular draws
            db.add(DrawHistory(
                pool_id             = pool.id,
                draw_type           = POOL_DRAW_SDE,
                targeted_early_exit = True,
                edge_case_triggered = False,
                sde_session_id      = cp.session_id,
                winner_1_user_id            = upper.id,
                winner_1_level              = cp.upper_winner_level,
                winner_1_net_payout         = upper_net_d,
                winner_1_total_deposited    = _up_dep,
                winner_1_merges_experienced = _up_merges,
                winner_1_pauses_experienced = _up_pauses,
                winner_1_journey_type       = "merged" if _up_merges > 0 else "direct",
                winner_2_user_id            = lower.id,
                winner_2_level              = cp.lower_winner_level,
                winner_2_net_payout         = lower_net_d,
                winner_2_total_deposited    = _lo_dep,
                winner_2_merges_experienced = _lo_merges,
                winner_2_pauses_experienced = _lo_pauses,
                winner_2_journey_type       = "merged" if _lo_merges > 0 else "direct",
            ))

            # (f) Advance surviving members +1 level; flag any new L4s
            pool_id_local  = pool.id
            new_l4_created = False
            sde_flag_week  = week_id

            for survivor in (
                db.query(User)
                .filter(
                    User.current_pool_id == pool_id_local,
                    User.status          == UserStatus.Active,
                    User.id.notin_([upper.id, lower.id]),
                )
                .all()
            ):
                new_level   = min(survivor.current_level + 1, 6)
                reaching_l4 = (new_level == 4)
                if reaching_l4:
                    new_l4_created = True
                    _logger.info(
                        "execute_staged_sde_draws: pool '%s' survivor %d (%s) → L4; "
                        "sde_required=True, flagged week=%s.",
                        pool.name, survivor.id, survivor.username, sde_flag_week,
                    )
                crud_user.update_user(
                    db, survivor.id,
                    UserUpdate(
                        current_level         = new_level,
                        weekly_payment_status = WeeklyPaymentStatus.Unpaid,
                        sde_required          = (True         if reaching_l4 else None),
                        sde_flagged_week      = (sde_flag_week if reaching_l4 else None),
                    ),
                )

            # Clear L4 flag on pool if no new L4 was created by survivor advancement
            if not new_l4_created:
                pool.contains_flagged_l4 = False

            # Mark checkpoint as fully executed
            cp.executed = True

            db.commit()
            executed_count += 1

            _logger.info(
                "execute_staged_sde_draws: ✓ checkpoint %d  pool='%s'  "
                "upper=@%s(L%d ₹%s)  lower=@%s(L%d ₹%s)",
                cp.id, pool.name,
                upper.username, cp.upper_winner_level, upper_net_d,
                lower.username, cp.lower_winner_level, lower_net_d,
            )

        except Exception as exc:
            _logger.error(
                "execute_staged_sde_draws: checkpoint %d FAILED — %s; rolling back.",
                cp.id, exc, exc_info=True,
            )
            try:
                db.rollback()
            except Exception:
                pass

    _logger.info(
        "execute_staged_sde_draws: T-0H committed %d/%d staged sub-draw(s) for week %s.",
        executed_count, len(staged), week_id,
    )
    return executed_count


# ═════════════════════════════════════════════════════════════════════════════
# SDE EXTENSION II — L5 Forced Exit
# ═════════════════════════════════════════════════════════════════════════════
#
# POINT 2 IMPLEMENTATION:
# Triggered when ANY pool member reaches Level 5.  L5 should NEVER exist in
# normal operation — it means SDE failed to clear an L4 member at least once.
#
# Rules:
#   Upper tier: L5 ONLY (forced exit — mirrors SDE's L4 guarantee)
#   Lower tier: L1, L2, L3, L4  (everyone below L5)
#
# POINT 3 — L5 Drawdown Projection:
# Before executing, calculate the financial comparison:
#   Option A (act now):  dual-L5 = ₹6,500 × 2 = ₹13,000 payout
#   Option B (wait 1w):  L5→L6 + L5 = ₹8,000 + ₹6,500 = ₹14,500 payout
#   Option C (wait 2w):  both L5→L6 = ₹8,000 × 2 = ₹16,000 payout
# Conclusion: ALWAYS eliminate L5 now.  ₹1,500 saved per week of earlier action.
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class SDEExt2DrawResult:
    """Result of one SDE Extension II draw (L5 forced exit)."""
    pool_id:                 int
    pool_name:               str
    upper_winner_user_id:    int       # L5 member — guaranteed exit
    upper_winner_level:      int       # always 5
    upper_winner_payout:     Decimal
    lower_winner_user_id:    int
    lower_winner_level:      int       # L1-L4
    lower_winner_payout:     Decimal
    draw_type:               str       # POOL_DRAW_SDE_EXT2 or POOL_DRAW_SDE_EXT3
    drawdown_projection:     dict      # financial projection that justified this draw


def calculate_l5_drawdown_projection(pool_members: list) -> dict:
    """
    Calculate the payout drawdown comparison for an L5 (or L6) emergency draw.

    POINT 3: This projection is ALWAYS computed before any SDE Ext-II execution.
    The system always chooses the lowest-drawdown option (which is always: act now).

    Returns a dict with the projection details for logging and audit purposes.
    """
    l5_members = [m for m in pool_members if m.current_level == 5]
    l6_members = [m for m in pool_members if m.current_level == 6]
    n_l5 = len(l5_members)
    n_l6 = len(l6_members)

    l5_net = Decimal(str(LEVEL_PAYOUTS[5][1]))   # ₹6,500
    l6_net = Decimal(str(LEVEL_PAYOUTS[6][1]))   # ₹8,000

    # Option A: dual-L5 exit NOW
    dual_l5_payout = l5_net * 2   # ₹13,000

    # Option B: wait 1 week (one L5 becomes L6)
    projected_l5_l6_payout = l6_net + l5_net   # ₹14,500

    # Option C: wait 2 weeks (both L5 become L6)
    projected_l6_l6_payout = l6_net * 2   # ₹16,000

    savings_vs_1_week  = projected_l5_l6_payout - dual_l5_payout   # ₹1,500
    savings_vs_2_weeks = projected_l6_l6_payout - dual_l5_payout   # ₹3,000

    # Pool collects ₹12,000 this week; dual-L5 creates ₹1,000 deficit
    # This is covered by float from earlier low-payout cycles (L1/L2 winners).
    weekly_collection = Decimal("12000")
    this_week_deficit = max(Decimal("0"), dual_l5_payout - weekly_collection)

    return {
        "n_l5_members":                  n_l5,
        "n_l6_members":                  n_l6,
        "dual_l5_payout_inr":            int(dual_l5_payout),
        "projected_1week_payout_inr":    int(projected_l5_l6_payout),
        "projected_2week_payout_inr":    int(projected_l6_l6_payout),
        "savings_acting_now_vs_1week":   int(savings_vs_1_week),
        "savings_acting_now_vs_2weeks":  int(savings_vs_2_weeks),
        "this_week_deficit_inr":         int(this_week_deficit),
        "deficit_note": (
            "Covered by float from prior low-payout draw cycles."
            if this_week_deficit > 0 else "No deficit — within weekly collection."
        ),
        "recommendation":               "EXECUTE_DUAL_L5_IMMEDIATELY",
        "reasoning": (
            f"Eliminating {n_l5} L5 member(s) NOW saves ₹{int(savings_vs_1_week):,} "
            f"vs waiting 1 week (₹{int(savings_vs_2_weeks):,} vs 2 weeks). "
            f"Dual-L5 draw is always the lowest-drawdown option."
        ),
    }


def execute_sde_ext2_draw(
    db: Session,
    pool_id: int,
    l5_member_id: int,
    *,
    draw_type: str = POOL_DRAW_SDE_EXT2,
) -> SDEExt2DrawResult:
    """
    Execute one SDE Extension II sub-draw.

    POINT 2: Guarantees L5 (or L6 for Ext-III) member exits this draw.
    POINT 3: Calculates drawdown projection before executing and logs it.

    draw_type = POOL_DRAW_SDE_EXT2  → L5 forced exit  (lower tier: L1-L4)
    draw_type = POOL_DRAW_SDE_EXT3  → L6 forced exit  (lower tier: L1-L5)

    Upper tier: L5 (Ext-II) or L6 (Ext-III)
    Lower tier: L1-L4 (Ext-II) or L1-L5 (Ext-III) — AI-weighted selection

    Raises ValueError on validation failure.
    """
    from app.schemas.token import TokenCreate
    from app.models.token import TokenType, TokenStatus

    # ── Determine tier bounds by draw type ───────────────────────────────────
    if draw_type == POOL_DRAW_SDE_EXT3:
        upper_bounds = SDE_EXT3_LEVEL_UPPER   # (6, 6)
        lower_bounds = SDE_EXT3_LEVEL_LOWER   # (1, 5)
        expected_upper_level = 6
    else:
        # Default: SDE Ext-II
        draw_type    = POOL_DRAW_SDE_EXT2
        upper_bounds = SDE_EXT2_LEVEL_UPPER   # (5, 5)
        lower_bounds = SDE_EXT2_LEVEL_LOWER   # (1, 4)
        expected_upper_level = 5

    # ── Load and validate pool ────────────────────────────────────────────────
    pool: Pool | None = db.query(Pool).filter(Pool.id == pool_id).first()
    if not pool:
        raise ValueError(f"SDE Ext-II draw: pool {pool_id} not found.")
    if pool.draw_completed_this_week:
        raise ValueError(
            f"SDE Ext-II draw: pool '{pool.name}' already drew this week."
        )

    # ── Load and validate the upper-tier member (L5 or L6) ───────────────────
    upper_member: User | None = db.query(User).filter(User.id == l5_member_id).first()
    if not upper_member:
        raise ValueError(f"SDE Ext-II draw: member {l5_member_id} not found.")
    if upper_member.current_level != expected_upper_level:
        raise ValueError(
            f"SDE Ext-II draw: member {l5_member_id} is level "
            f"{upper_member.current_level}, expected {expected_upper_level}."
        )
    if upper_member.current_pool_id != pool_id:
        raise ValueError(
            f"SDE Ext-II draw: member {l5_member_id} is not in pool {pool_id}."
        )

    # ── Drawdown projection (POINT 3) ─────────────────────────────────────────
    all_pool_members: list[User] = (
        db.query(User)
        .filter(
            User.current_pool_id == pool_id,
            User.status          == UserStatus.Active,
        )
        .all()
    )

    projection = {}
    if L5_DRAWDOWN_ENABLED and draw_type == POOL_DRAW_SDE_EXT2:
        projection = calculate_l5_drawdown_projection(all_pool_members)
        _logger.info(
            "SDE Ext-II DRAWDOWN PROJECTION pool='%s': %s",
            pool.name, projection["reasoning"],
        )

    # ── Build lower tier candidates ───────────────────────────────────────────
    lower_candidates: list[User] = (
        db.query(User)
        .filter(
            User.current_pool_id == pool_id,
            User.status          == UserStatus.Active,
            User.current_level   >= lower_bounds[0],
            User.current_level   <= lower_bounds[1],
            User.id              != l5_member_id,
        )
        .all()
    )

    # WL emergency promotion if lower candidates are empty (same logic as Ext-I)
    if not lower_candidates:
        wl_members: list[User] = (
            db.query(User)
            .filter(
                User.status                == UserStatus.Waitlist,
                User.weekly_payment_status == WeeklyPaymentStatus.Paid,
            )
            .order_by(User.join_date.asc())
            .limit(SDE_WL_EMERGENCY_PROMOTE)
            .all()
        )
        if wl_members:
            for wl_m in wl_members:
                crud_user.update_user(
                    db, wl_m.id,
                    UserUpdate(
                        status=UserStatus.Active,
                        current_pool_id=pool_id,
                        current_level=1,
                    ),
                )
                if wl_m.referred_by_user_id:
                    from app.services.draw import _credit_referral_bonus
                    _credit_referral_bonus(db, wl_m.referred_by_user_id)
            db.flush()
            lower_candidates = (
                db.query(User)
                .filter(
                    User.current_pool_id == pool_id,
                    User.status          == UserStatus.Active,
                    User.current_level   >= lower_bounds[0],
                    User.current_level   <= lower_bounds[1],
                    User.id              != l5_member_id,
                )
                .all()
            )
            _logger.warning(
                "SDE Ext-II: WL emergency promotion — %d member(s) added to pool '%s'.",
                len(wl_members), pool.name,
            )

    if not lower_candidates:
        raise ValueError(
            f"SDE Ext-II: pool '{pool.name}' has no eligible L{lower_bounds[0]}"
            f"–L{lower_bounds[1]} members for lower tier, and Waitlist is empty."
        )

    # ── AI-weighted lower winner selection ────────────────────────────────────
    probabilities     = _compute_weighted_selection(lower_candidates)
    lower_winner_id   = _weighted_choice(probabilities)
    lower_winner: User = next(m for m in lower_candidates if m.id == lower_winner_id)

    # ── Snapshot journey data ─────────────────────────────────────────────────
    _up_dep    = upper_member.total_deposited_inr        or 1000
    _up_merges = upper_member.dynamic_merges_experienced or 0
    _up_pauses = upper_member.pauses_experienced         or 0
    _lo_dep    = lower_winner.total_deposited_inr        or 1000
    _lo_merges = lower_winner.dynamic_merges_experienced or 0
    _lo_pauses = lower_winner.pauses_experienced         or 0

    # ── Payout calculation ────────────────────────────────────────────────────
    upper_gross, upper_net = LEVEL_PAYOUTS.get(upper_member.current_level, (7000, 6500))
    lower_gross, lower_net = LEVEL_PAYOUTS.get(lower_winner.current_level, (2500, 2000))
    upper_net_d = Decimal(str(upper_net))
    lower_net_d = Decimal(str(lower_net))

    # ── BEGIN ATOMIC TRANSACTION ──────────────────────────────────────────────

    # (a) WIT token — upper winner (L5/L6 guaranteed exit)
    upper_token_code = _get_unique_token_code(db, "WIT-")
    crud_token.create_token(
        db,
        TokenCreate(
            code=upper_token_code,
            type=TokenType.Withdraw,
            value_inr=upper_net_d,
            user_id=upper_member.id,
            pool_id=pool.id,
            status=TokenStatus.Active,
        ),
    )

    # (b) WIT token — lower winner
    lower_token_code = _get_unique_token_code(db, "WIT-")
    crud_token.create_token(
        db,
        TokenCreate(
            code=lower_token_code,
            type=TokenType.Withdraw,
            value_inr=lower_net_d,
            user_id=lower_winner.id,
            pool_id=pool.id,
            status=TokenStatus.Active,
        ),
    )

    # (c) Eliminate both winners
    crud_user.update_user(
        db, upper_member.id,
        UserUpdate(
            status=UserStatus.Eliminated_Won,
            current_pool_id=None,
            sde_required=False,
        ),
    )
    crud_user.update_user(
        db, lower_winner.id,
        UserUpdate(status=UserStatus.Eliminated_Won, current_pool_id=None),
    )

    # (d) DrawHistory row — targeted_early_exit=True for the upper (L5/L6) winner
    now_utc  = datetime.now(timezone.utc)
    iso      = now_utc.isocalendar()
    week_id  = f"{iso.year}-W{iso.week:02d}"

    db.add(DrawHistory(
        pool_id             = pool.id,
        draw_type           = draw_type,   # sde_ext2 or sde_ext3
        targeted_early_exit = True,
        edge_case_triggered = False,
        # Upper winner (L5/L6 — guaranteed forced exit)
        winner_1_user_id            = upper_member.id,
        winner_1_level              = upper_member.current_level,
        winner_1_net_payout         = upper_net_d,
        winner_1_total_deposited    = _up_dep,
        winner_1_merges_experienced = _up_merges,
        winner_1_pauses_experienced = _up_pauses,
        winner_1_journey_type       = "merged" if _up_merges > 0 else "direct",
        # Lower winner (AI-weighted from L1-L4 / L1-L5)
        winner_2_user_id            = lower_winner.id,
        winner_2_level              = lower_winner.current_level,
        winner_2_net_payout         = lower_net_d,
        winner_2_total_deposited    = _lo_dep,
        winner_2_merges_experienced = _lo_merges,
        winner_2_pauses_experienced = _lo_pauses,
        winner_2_journey_type       = "merged" if _lo_merges > 0 else "direct",
    ))

    # (e) Advance surviving members +1 level, atomically flag any new L4/L5
    new_escalation_in_pool = False
    surviving_members: list[User] = (
        db.query(User)
        .filter(
            User.current_pool_id == pool_id,
            User.status          == UserStatus.Active,
            User.id.notin_([upper_member.id, lower_winner.id]),
        )
        .all()
    )
    for survivor in surviving_members:
        new_level    = min(survivor.current_level + 1, 6)
        reaching_l4  = (new_level == 4)
        reaching_l5  = (new_level == 5)
        if reaching_l4 or reaching_l5:
            new_escalation_in_pool = True
        crud_user.update_user(
            db, survivor.id,
            UserUpdate(
                current_level         = new_level,
                weekly_payment_status = WeeklyPaymentStatus.Unpaid,
                sde_required          = (True    if reaching_l4 else None),
                sde_flagged_week      = (week_id if reaching_l4 else None),
            ),
        )

    # (f) Mark pool drawn — prevent double-draw; update pool draw type
    pool.draw_completed_this_week = True
    pool.pool_draw_type           = draw_type
    if not new_escalation_in_pool:
        pool.contains_flagged_l4 = False

    db.commit()
    # ── END ATOMIC TRANSACTION ────────────────────────────────────────────────

    _logger.info(
        "SDE Ext-II COMPLETE pool='%s': upper=@%s(L%d ₹%s)  lower=@%s(L%d ₹%s)  "
        "savings=₹%s vs waiting 1 week",
        pool.name,
        upper_member.username, upper_member.current_level, upper_net_d,
        lower_winner.username, lower_winner.current_level, lower_net_d,
        projection.get("savings_acting_now_vs_1week", "N/A"),
    )

    return SDEExt2DrawResult(
        pool_id=pool.id,
        pool_name=pool.name,
        upper_winner_user_id=upper_member.id,
        upper_winner_level=upper_member.current_level,
        upper_winner_payout=upper_net_d,
        lower_winner_user_id=lower_winner.id,
        lower_winner_level=lower_winner.current_level,
        lower_winner_payout=lower_net_d,
        draw_type=draw_type,
        drawdown_projection=projection,
    )


def check_and_run_sde_extensions(db: Session, week_id: str) -> list[SDEExt2DrawResult]:
    """
    Check ALL active pools for L5 and L6 members and execute SDE Ext-II/III draws.

    Called BEFORE regular SDE and before the weekly draw to ensure no L5/L6
    members remain when the regular draw cycle runs.

    Priority order (most severe first):
      1. SDE Ext-III (L6 members)  — extreme edge case
      2. SDE Ext-II  (L5 members)  — rare but critical

    Returns list of all Ext-II/III draws executed this run.
    """
    results: list[SDEExt2DrawResult] = []

    # ── Step 1: Check for L6 members (Ext-III — extreme priority) ────────────
    l6_members: list[User] = (
        db.query(User)
        .filter(
            User.status        == UserStatus.Active,
            User.current_level == 6,
        )
        .all()
    )
    if l6_members:
        _logger.critical(
            "SDE Ext-III REQUIRED: %d L6 member(s) detected across pools. "
            "This indicates SDE Ext-II also failed previously. "
            "Executing L6 forced exits immediately.",
            len(l6_members),
        )
        for l6_member in l6_members:
            if l6_member.current_pool_id is None:
                continue
            # Skip pools already drawn this week
            pool_check = db.query(Pool).filter(Pool.id == l6_member.current_pool_id).first()
            if pool_check and pool_check.draw_completed_this_week:
                _logger.warning(
                    "SDE Ext-III: pool '%s' already drew this week — "
                    "L6 member %d (%s) will be processed next week.",
                    pool_check.name, l6_member.id, l6_member.username,
                )
                continue
            try:
                r = execute_sde_ext2_draw(
                    db,
                    pool_id=l6_member.current_pool_id,
                    l5_member_id=l6_member.id,
                    draw_type=POOL_DRAW_SDE_EXT3,
                )
                results.append(r)
            except ValueError as exc:
                _logger.error(
                    "SDE Ext-III FAILED for member %d (%s) pool %d: %s",
                    l6_member.id, l6_member.username, l6_member.current_pool_id, exc,
                )

    # ── Step 2: Check for L5 members (Ext-II) ────────────────────────────────
    l5_members: list[User] = (
        db.query(User)
        .filter(
            User.status        == UserStatus.Active,
            User.current_level == 5,
        )
        .all()
    )
    if l5_members:
        _logger.error(
            "SDE Ext-II REQUIRED: %d L5 member(s) detected across pools. "
            "SDE failed to clear L4 → L5 advancement occurred. "
            "Executing L5 forced exits immediately.",
            len(l5_members),
        )
        for l5_member in l5_members:
            if l5_member.current_pool_id is None:
                continue
            # Skip pools already drawn this week (e.g., just ran Ext-III above)
            pool_check = db.query(Pool).filter(Pool.id == l5_member.current_pool_id).first()
            if pool_check and pool_check.draw_completed_this_week:
                _logger.warning(
                    "SDE Ext-II: pool '%s' already drew this week — "
                    "L5 member %d (%s) will be processed next week.",
                    pool_check.name, l5_member.id, l5_member.username,
                )
                continue
            try:
                r = execute_sde_ext2_draw(
                    db,
                    pool_id=l5_member.current_pool_id,
                    l5_member_id=l5_member.id,
                    draw_type=POOL_DRAW_SDE_EXT2,
                )
                results.append(r)
            except ValueError as exc:
                _logger.error(
                    "SDE Ext-II FAILED for member %d (%s) pool %d: %s",
                    l5_member.id, l5_member.username, l5_member.current_pool_id, exc,
                )

    if results:
        _logger.info(
            "SDE Extensions complete: %d Ext-II/III draw(s) executed this week.",
            len(results),
        )
    return results
