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
    SDE_LEVEL_LOWER_NORMAL, SDE_LEVEL_LOWER_EXCEPTION, SDE_LEVEL_UPPER,
    LPI_L3_WIN_EXCEPTION,
    SDE_WEIGHT_TIME, SDE_WEIGHT_DEPOSIT, SDE_WEIGHT_PAUSE,
    SDE_WEIGHT_ORGANIC, SDE_WEIGHT_NOISE, SDE_WEIGHT_MIN_FLOOR,
    POOL_DRAW_SDE,
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
        raise ValueError(
            f"SDE sub-draw: pool '{pool.name}' has no eligible {tier_desc} members "
            f"for the lower tier.  Pool may need supply injection."
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

    # ── Snapshot journey data BEFORE mutations ────────────────────────────────
    _up_dep    = l4_member.total_deposited_inr        or 1000
    _up_merges = l4_member.dynamic_merges_experienced or 0
    _up_pauses = l4_member.pauses_experienced         or 0
    _lo_dep    = lower_winner.total_deposited_inr        or 1000
    _lo_merges = lower_winner.dynamic_merges_experienced or 0
    _lo_pauses = lower_winner.pauses_experienced         or 0

    # ── Payout calculation ────────────────────────────────────────────────────
    upper_gross, upper_net = LEVEL_PAYOUTS.get(l4_member.current_level,    (6000, 5500))
    lower_gross, lower_net = LEVEL_PAYOUTS.get(lower_winner.current_level, (2500, 2000))
    upper_net_d = Decimal(str(upper_net))
    lower_net_d = Decimal(str(lower_net))

    # ── BEGIN ATOMIC TRANSACTION ──────────────────────────────────────────────
    # All writes below are committed together.  Any exception triggers rollback.

    # (a) WIT token — upper winner (L4 guaranteed exit)
    upper_token_code = _get_unique_token_code(db, "WIT-")
    from app.models.token import TokenType, TokenStatus
    crud_token.create_token(
        db,
        TokenCreate(
            code=upper_token_code,
            type=TokenType.Withdraw,
            value_inr=upper_net_d,
            user_id=l4_member.id,
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
        db, l4_member.id,
        UserUpdate(
            status=UserStatus.Eliminated_Won,
            current_pool_id=None,
            sde_required=False,
            sde_flagged_week=None,
        ),
    )
    crud_user.update_user(
        db, lower_winner.id,
        UserUpdate(status=UserStatus.Eliminated_Won, current_pool_id=None),
    )

    # (d) DrawHistory row — targeted_early_exit=True for SDE upper winner
    db.add(DrawHistory(
        pool_id             = pool.id,
        draw_type           = POOL_DRAW_SDE,
        targeted_early_exit = True,            # [TARGETED EARLY EXIT] badge
        edge_case_triggered = False,
        sde_session_id      = session_id,
        # Upper winner (L4 — guaranteed exit)
        winner_1_user_id            = l4_member.id,
        winner_1_level              = l4_member.current_level,
        winner_1_net_payout         = upper_net_d,
        winner_1_total_deposited    = _up_dep,
        winner_1_merges_experienced = _up_merges,
        winner_1_pauses_experienced = _up_pauses,
        winner_1_journey_type       = "merged" if _up_merges > 0 else "direct",
        # Lower winner (AI-weighted L1/L2 or L3)
        winner_2_user_id            = lower_winner.id,
        winner_2_level              = lower_winner.current_level,
        winner_2_net_payout         = lower_net_d,
        winner_2_total_deposited    = _lo_dep,
        winner_2_merges_experienced = _lo_merges,
        winner_2_pauses_experienced = _lo_pauses,
        winner_2_journey_type       = "merged" if _lo_merges > 0 else "direct",
    ))

    # (e) SDE checkpoint — crash recovery anchor
    db.add(SDECheckpoint(
        session_id               = session_id,
        sub_draw_number          = sub_draw_number,
        pool_id                  = pool.id,
        upper_winner_user_id     = l4_member.id,
        upper_winner_level       = l4_member.current_level,
        upper_payout_inr         = upper_net_d,
        lower_winner_user_id     = lower_winner.id,
        lower_winner_level       = lower_winner.current_level,
        lower_payout_inr         = lower_net_d,
        lower_winner_tier_override = lower_tier_override,
        rng_seed_hash            = rng_hash,
    ))

    # (f) Advance surviving members by +1 level — mirrors run_dual_draw behaviour.
    #
    # CRITICAL: execute_weekly_draw() skips SDE-processed pools via
    # draw_completed_this_week=True.  Without level advancement here, the 10
    # survivors never progress that week — violating the weekly cycle contract.
    # This block is part of the same atomic transaction as the exits above.
    #
    # New L4 edge case: if an L3 survivor advances to L4 in THIS same pool,
    # it is flagged immediately and pool.contains_flagged_l4 stays True.
    # The pool will be SDE-processed NEXT week.
    now_utc  = datetime.now(timezone.utc)
    iso      = now_utc.isocalendar()
    week_id  = f"{iso.year}-W{iso.week:02d}"
    new_l4_created_in_pool = False

    # Load all survivors before mutations (excludes the two winners who just exited)
    surviving_members: list[User] = (
        db.query(User)
        .filter(
            User.current_pool_id == pool_id,
            User.status          == UserStatus.Active,
            User.id.notin_([l4_member.id, lower_winner.id]),
        )
        .all()
    )

    for survivor in surviving_members:
        new_level   = min(survivor.current_level + 1, 6)
        reaching_l4 = (new_level == 4)
        if reaching_l4:
            new_l4_created_in_pool = True
            _logger.info(
                "SDE pool '%s' survivor %d (%s) advanced to L4 — "
                "sde_required=True, flagged for next week (%s).",
                pool.name, survivor.id, survivor.username, week_id,
            )
        crud_user.update_user(
            db, survivor.id,
            UserUpdate(
                current_level         = new_level,
                weekly_payment_status = WeeklyPaymentStatus.Unpaid,
                sde_required          = (True    if reaching_l4 else None),
                sde_flagged_week      = (week_id if reaching_l4 else None),
            ),
        )

    # (g) Mark pool as drawn this week — prevents double-draw
    pool.draw_completed_this_week = True
    pool.pool_draw_type           = POOL_DRAW_SDE
    # contains_flagged_l4: clear if no survivor just advanced to L4;
    # leave True if a new L4 was created (pool needs SDE next week)
    if not new_l4_created_in_pool:
        pool.contains_flagged_l4 = False

    db.commit()
    # ── END ATOMIC TRANSACTION ────────────────────────────────────────────────

    _logger.info(
        "SDE sub-draw %d.%d COMPLETE: pool='%s'  upper=@%s(L%d ₹%s)  "
        "lower=@%s(L%d ₹%s)  seed=%s…",
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

    # Step 4: LPI for L3 exception check
    lpi = calculate_lpi(db)

    meta_result = SDEMetaPoolResult(week_id=week_id)
    session_num  = 1
    remaining    = list(l4_members)

    while remaining:
        batch    = remaining[:SDE_MAX_POOLS_PER_SESSION]
        remaining = remaining[SDE_MAX_POOLS_PER_SESSION:]

        # Check L1/L2 supply sufficiency for this batch
        pool_ids = [m.current_pool_id for m in batch if m.current_pool_id]
        l1l2_count = (
            db.query(func.count(User.id))
            .filter(
                User.current_pool_id.in_(pool_ids),
                User.status          == UserStatus.Active,
                User.current_level   <= 2,
            )
            .scalar()
        ) or 0

        min_needed = len(batch) * SDE_L1L2_THRESHOLD_PER_L4
        if l1l2_count < min_needed:
            # Reduce batch to what supply allows
            clearable = l1l2_count // SDE_L1L2_THRESHOLD_PER_L4
            overflow_from_batch = batch[clearable:]
            batch                = batch[:clearable]
            meta_result.overflow_l4_count  += len(overflow_from_batch)
            meta_result.overflow_user_ids.extend(m.id for m in overflow_from_batch)
            _logger.warning(
                "SDE Meta-Pool session %d: supply shortage — "
                "L1L2_available=%d  needed=%d  "
                "reducing batch from %d → %d  overflow=%d",
                session_num, l1l2_count, min_needed,
                clearable + len(overflow_from_batch), clearable,
                len(overflow_from_batch),
            )

        if not batch:
            _logger.warning(
                "SDE Meta-Pool session %d: empty batch after supply check — skipping.",
                session_num,
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
