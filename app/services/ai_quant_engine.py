"""
Predictive Quantitative AI Engine  (Brain 2 + 3 + 5 integration)
=================================================================
Implements the 4-brain "God Mode" engine described in the architecture document:

  Brain 1 — Hydraulic Engine    : layer-based reserve calculation
  Brain 2 — Momentum Tracker    : Tri-velocity blend + cliff detection (v2)
  Brain 3 — Quality Radar (RDR) : Organic vs referral traffic distinction
  Brain 4 — Condensation Engine : (implemented in waitlist.py Phase 3)
  Brain 5 — LPI Engine          : (brain5_lpi_engine.py) — forward signal
                                    injected here as tri-velocity component C

Brain 2 v2 (Tri-Velocity):
  blended = (slow_14d_sma × 0.50) + (fast_48h × 0.30) + (forward_signal × 0.20)

  Cliff Detection:
    If today's rate < 3-days-ago rate × 0.5 → VELOCITY_CLIFF override.
    VELOCITY_CLIFF forces multiplier to 1.00 (NEUTRAL) regardless of scenario,
    preventing the system from over-optimistically maintaining SUSTAINABLE_WAVE
    during a sudden drop.

This module exposes read-only query functions and a single decision function
`determine_reserve_multiplier(db)` that returns (multiplier, scenario_name).
The multiplier is consumed by Phase 2 of `assign_waitlist_to_pools` to
calculate how much of the waitlist must be held as Dynamic Reserve before
any new pools can be spawned.

Phase 2 formula (with admin-threshold as floor):
  dynamic_reserve_needed  = operational_pools × POOL_CAPACITY × multiplier
  available_for_spawning  = max(0, waitlist_count − dynamic_reserve_needed)
  if available_for_spawning >= admin_threshold:
      pools_to_make = available_for_spawning // POOL_CAPACITY
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.pool import Pool, PoolStatus
from app.models.user import User, UserStatus
from app.core.config import (
    BRAIN2_SLOW_VELOCITY_DAYS,
    BRAIN2_FAST_VELOCITY_HOURS,
    BRAIN2_WEIGHT_SLOW, BRAIN2_WEIGHT_FAST, BRAIN2_WEIGHT_FORWARD,
    BRAIN2_CLIFF_REFERENCE_DAYS, BRAIN2_CLIFF_FACTOR,
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # LEVER 3b — POOL_CAPACITY needed for the gated dynamic-reserve helper below.
    POOL_CAPACITY,
)

_logger = logging.getLogger(__name__)

# ── Tuning constants ───────────────────────────────────────────────────────────
# Read from config — single source of truth for all tunable parameters
_SLOW_VEL_DAYS       = BRAIN2_SLOW_VELOCITY_DAYS   # 14d SMA (was 21)
_FAST_VEL_HOURS      = BRAIN2_FAST_VELOCITY_HOURS  # 48h EMA proxy
_RDR_VOLATILE_THRESH = 70.0   # RDR% above this → volatile referral hype
_RDR_ORGANIC_THRESH  = 30.0   # RDR% below this → genuine organic growth

# Multiplier constants — applied to (operational_pools × POOL_CAPACITY) to size reserve
_M_AGGRESSIVE   = 0.50   # SUSTAINABLE_WAVE: safe to hold minimal reserve
_M_STANDARD     = 1.00   # VELOCITY_CLIFF / NEUTRAL: normal 1:1 reserve ratio
_M_CAUTIOUS     = 1.50   # FLASH_FLOOD: referral-volatile, hold extra cushion
_M_STANDARD_75  = 0.75   # BOOM_GOLDEN_CROSS: mixed traffic, moderate optimism
_M_PROTECTION   = 2.00   # DRY_PHASE / REFERRAL_LIFELINE: double reserve

# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ── Q3 STEADY-RULE SPAWN GATE (Jun-23) ────────────────────────────────────────
# Q2 (Jun-23) removed posture switching from the draw side.  Forensic run
# a4243fd2 ALSO proved that this *spawn* gate — which previously switched between
# a 4/pool healthy floor and a (12 × multiplier)/pool protective ceiling based on
# the brain's scenario — was the SECOND half of the feast-or-famine:
#
#   W5–W19  : DRY_PHASE detected → reserve = pools × 12 × 2.0 → enormous.
#             Waitlist couldn't breach it → 11+ consecutive zero-spawn weeks,
#             waitlist piled up, draws stalled (no fresh L1 supply for refill).
#   W20–W21 : Waitlist FINALLY breached the wall → 60-draw + 80-winner blowout.
#   W22–W27 : Whole pool fabric collapsed; L5 leak began.
#
# Q3 (Jun-23) per user directive: "broken waitlist and pool creation mechanism …
# so many pool".  Collapse to ONE steady rule the way Q2 did for posture.
#
# RULE: reserve = operational_pools × HEALTHY_RESERVE_PER_POOL (4/pool), ALWAYS.
#
#   • 4/pool covers exactly 2 weeks of full-pool 2-winner burn (burn = 2/pool/wk),
#     i.e. one full draw cycle of safety buffer + one in reserve.
#   • Admin threshold (POOL_CAPACITY default) is STILL the floor below this:
#     pools spawn only when (waitlist - reserve) >= admin_threshold.  So spawn
#     never runs ahead of admin intent; the gate just stops over-clamping during
#     a dry phase that mathematically locks the waitlist forever.
#   • multiplier / scenario are still computed by the brain and still emitted in
#     telemetry/forensic events (admin can SEE what the brain detected — Q4
#     reconciliation requires this).  They just no longer GATE the spawn.
HEALTHY_RESERVE_SCENARIOS = frozenset({"SUSTAINABLE_WAVE", "BOOM_GOLDEN_CROSS"})  # retained for legacy callers
HEALTHY_RESERVE_PER_POOL  = 4   # lean reserve floor (members/pool) — now applied universally


def compute_dynamic_reserve(
    operational_pool_count: int,
    multiplier: float,
    scenario: str,
) -> int:
    """Q3 STEADY-RULE: return the lean spawn-reserve floor for EVERY scenario.

    reserve = operational_pools × HEALTHY_RESERVE_PER_POOL (4/pool), unconditionally.

    PURE: ignores ``multiplier`` and ``scenario`` for the math.  The arguments
    are retained for signature stability (the Phase-2 spawn gate in
    waitlist.py and the admin telemetry snapshot below both still pass them,
    and we want the brain's *scenario classification* preserved in telemetry
    even though it no longer SWITCHES the gate — see Q2 / Q3 module banner).

    Single source of truth for both the live Phase-2 spawn gate (waitlist.py)
    and the admin telemetry snapshot (get_system_snapshot below) — they can
    never drift apart because both call THIS function.
    """
    # multiplier + scenario intentionally observed but unused — see Q3 banner.
    _ = (multiplier, scenario)
    return int(operational_pool_count) * HEALTHY_RESERVE_PER_POOL


# ── Query helpers ─────────────────────────────────────────────────────────────

def calculate_burn_rate(db: Session) -> float:
    """
    Weekly payout drain = Active Pools × 2.
    Exactly 2 winners exit per Active pool per draw cycle.
    """
    active_pools: int = (
        db.query(func.count(Pool.id))
        .filter(Pool.status == PoolStatus.Active)
        .scalar()
    ) or 0
    return float(active_pools * 2)


def calculate_slow_velocity(db: Session) -> float:
    """
    Baseline: average new users per week over the last 14 days (2-week SMA).
    Reduced from 21d → 14d for faster responsiveness to trend changes.
    'New user' = any user record whose join_date falls within the window,
    regardless of current status.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_SLOW_VEL_DAYS)
    count: int = (
        db.query(func.count(User.id))
        .filter(User.join_date >= cutoff)
        .scalar()
    ) or 0
    return count / (_SLOW_VEL_DAYS / 7.0)   # convert to per-week rate


def calculate_fast_velocity(db: Session) -> float:
    """
    Momentum proxy: new users per day over last 48 hours, scaled to weekly rate.
    Mimics a 48h EMA by giving the most recent data the highest implicit weight.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_FAST_VEL_HOURS)
    count: int = (
        db.query(func.count(User.id))
        .filter(User.join_date >= cutoff)
        .scalar()
    ) or 0
    daily_rate = count / (_FAST_VEL_HOURS / 24.0)
    return daily_rate * 7.0    # weekly rate for apples-to-apples comparison


def calculate_momentum(db: Session) -> float:
    """
    Momentum = Fast Velocity (48h EMA proxy) − Slow Velocity (14d SMA).
    Positive → growth accelerating (boom signal).
    Negative → growth decelerating (dry signal).
    """
    return calculate_fast_velocity(db) - calculate_slow_velocity(db)


def calculate_cliff_signal(db: Session) -> bool:
    """
    Brain 2 Cliff Detector.

    Compares today's new-user rate against the rate from BRAIN2_CLIFF_REFERENCE_DAYS
    (3) days ago.  If today < 3-days-ago × BRAIN2_CLIFF_FACTOR (0.5), a cliff
    has been detected — growth dropped by more than 50% in 3 days.

    Returns True (cliff) or False (no cliff).

    A velocity cliff overrides SUSTAINABLE_WAVE and BOOM_GOLDEN_CROSS scenarios
    to prevent over-optimistic reserve drawdown during a sudden drop.
    """
    now = datetime.now(timezone.utc)

    # Today's rate: joins in the last 24 hours, scaled to weekly
    today_cutoff = now - timedelta(hours=24)
    today_count: int = (
        db.query(func.count(User.id))
        .filter(User.join_date >= today_cutoff)
        .scalar()
    ) or 0
    today_rate_weekly = today_count * 7.0

    # Reference rate: joins in the 24-hour window ending N days ago
    ref_end   = now - timedelta(days=BRAIN2_CLIFF_REFERENCE_DAYS)
    ref_start = ref_end - timedelta(hours=24)
    ref_count: int = (
        db.query(func.count(User.id))
        .filter(User.join_date >= ref_start, User.join_date < ref_end)
        .scalar()
    ) or 0
    ref_rate_weekly = ref_count * 7.0

    # Cliff condition: today_rate < ref_rate × cliff_factor
    # Guard: if ref_rate is 0 there is no meaningful cliff (system was already dry)
    if ref_rate_weekly == 0:
        return False

    cliff_detected = today_rate_weekly < ref_rate_weekly * BRAIN2_CLIFF_FACTOR

    if cliff_detected:
        _logger.warning(
            "Brain2 CLIFF DETECTED: today_weekly=%.1f  ref_weekly=%.1f  "
            "factor=%.2f  threshold=%.1f",
            today_rate_weekly, ref_rate_weekly,
            BRAIN2_CLIFF_FACTOR, ref_rate_weekly * BRAIN2_CLIFF_FACTOR,
        )
    return cliff_detected


def calculate_blended_velocity(db: Session, forward_signal: float) -> float:
    """
    Brain 2 Tri-Velocity Blend.

    blended = (slow_14d_sma × 0.50) + (fast_48h × 0.30) + (forward_signal × 0.20)

    Components:
      A (50%) — slow_14d_sma: backward-looking baseline (stability)
      B (30%) — fast_48h:     momentum (responsiveness)
      C (20%) — forward_signal from Brain 5: projected new L3 next week
                              (forward-looking, prevents overcautious reserve
                               when a large L2 cohort is about to graduate)

    forward_signal is in "users per week" units (L2_count × survival_rate).
    """
    slow = calculate_slow_velocity(db)
    fast = calculate_fast_velocity(db)
    blended = (
        slow         * BRAIN2_WEIGHT_SLOW     # 0.50
        + fast       * BRAIN2_WEIGHT_FAST     # 0.30
        + forward_signal * BRAIN2_WEIGHT_FORWARD  # 0.20
    )
    _logger.debug(
        "Brain2 tri-velocity: slow=%.2f(×%.2f) fast=%.2f(×%.2f) "
        "forward=%.2f(×%.2f) → blended=%.2f",
        slow, BRAIN2_WEIGHT_SLOW,
        fast, BRAIN2_WEIGHT_FAST,
        forward_signal, BRAIN2_WEIGHT_FORWARD,
        blended,
    )
    return blended


def calculate_rdr(db: Session, days: int = 7) -> float:
    """
    Referral Density Ratio = (users who joined via a referral code / total joins) × 100
    over the last `days` days.  Returns a float in [0.0, 100.0].

    A user is considered "referral" when their referred_by_user_id is not NULL.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    total: int = (
        db.query(func.count(User.id))
        .filter(User.join_date >= cutoff)
        .scalar()
    ) or 0

    if total == 0:
        return 0.0

    referral: int = (
        db.query(func.count(User.id))
        .filter(
            User.join_date >= cutoff,
            User.referred_by_user_id.isnot(None),
        )
        .scalar()
    ) or 0

    return (referral / total) * 100.0


# ── Core decision function ────────────────────────────────────────────────────

def determine_reserve_multiplier(
    db: Session,
    *,
    forward_signal: float | None = None,
) -> tuple[float, str]:
    """
    Primary AI decision function.  Returns (multiplier, scenario_name).

    Uses Brain 2 tri-velocity blend when forward_signal is provided.
    Falls back to fast_velocity alone for backward compatibility when
    forward_signal is not injected (legacy callers).

    Decision Matrix (v2 with cliff detection)
    ─────────────────────────────────────────────────────────────────────────
    VELOCITY_CLIFF detected (any scenario)     →  VELOCITY_CLIFF   →  1.00
      Analysis: Growth dropped >50% in 3 days.  Override optimistic scenarios.
      Action:   Standard reserve.  Do not draw down to SUSTAINABLE_WAVE levels.

    Velocity > Burn Rate AND RDR < 30%          →  SUSTAINABLE_WAVE  →  0.50
      Analysis: Organic growth exceeds drain. Hype is durable.
      Action:   Aggressive spawning. Cut reserve requirement to 50%.

    Velocity > Burn Rate AND RDR > 70%          →  FLASH_FLOOD       →  1.50
      Analysis: High velocity but driven by volatile referral networks.
      Action:   Cautious reserve (1.5×). Spawn but hold extra cushion.

    Velocity > Burn Rate (30–70% RDR)           →  BOOM_GOLDEN_CROSS →  0.75
      Analysis: Healthy growth with mixed traffic — moderate optimism.
      Action:   Slightly relaxed reserve.

    Velocity < Burn Rate AND RDR > 60%          →  REFERRAL_LIFELINE →  2.00
      Analysis: Organic traffic dead; only referral bonus hunters remain.
      Action:   Liquidity Protection. Double reserve. Halt new pools.

    Velocity < Burn Rate (any RDR)              →  DRY_PHASE         →  2.00
      Analysis: Paying out more than acquiring.  System drying up.
      Action:   Liquidity Protection. Double reserve. Halt new pools.

    No active pools or no data                  →  NEUTRAL           →  1.00
      Action:   Standard — use admin threshold as-is.
    ─────────────────────────────────────────────────────────────────────────
    """
    slow_vel   = calculate_slow_velocity(db)
    burn_rate  = calculate_burn_rate(db)
    fast_vel   = calculate_fast_velocity(db)
    rdr        = calculate_rdr(db, days=7)

    # No meaningful data yet (fresh deployment)
    if slow_vel == 0.0 and fast_vel == 0.0:
        return _M_STANDARD, "NEUTRAL"

    # Use tri-velocity blend when Brain 5 forward signal is available
    if forward_signal is not None:
        effective_vel = calculate_blended_velocity(db, forward_signal)
    else:
        effective_vel = fast_vel   # legacy fallback — single velocity

    # ── Cliff detection override ──────────────────────────────────────────────
    cliff = calculate_cliff_signal(db)
    if cliff and effective_vel > burn_rate:
        # Cliff overrides optimistic scenarios (SUSTAINABLE_WAVE / BOOM_GOLDEN_CROSS)
        # but does NOT override protective scenarios (DRY / LIFELINE) — those are
        # already conservative.
        _logger.info(
            "Brain2 VELOCITY_CLIFF override: blended=%.2f > burn=%.2f "
            "but cliff detected → forcing NEUTRAL (1.00)",
            effective_vel, burn_rate,
        )
        return _M_STANDARD, "VELOCITY_CLIFF"

    if effective_vel > burn_rate:
        # Growth outpacing drain — system is healthy
        if rdr < _RDR_ORGANIC_THRESH:
            return _M_AGGRESSIVE, "SUSTAINABLE_WAVE"
        elif rdr > _RDR_VOLATILE_THRESH:
            return _M_CAUTIOUS, "FLASH_FLOOD"   # 1.5 — cautious, referral hype volatile
        else:
            return _M_STANDARD_75, "BOOM_GOLDEN_CROSS"
    else:
        # Drain outpacing growth — protect liquidity
        if rdr > 60.0:
            return _M_PROTECTION, "REFERRAL_LIFELINE"
        return _M_PROTECTION, "DRY_PHASE"


# ── System snapshot (used by /admin/stats/ai-snapshot endpoint) ───────────────

def get_system_snapshot(db: Session) -> dict:
    """
    Return all AI metrics in one call — consumed by the admin API endpoint
    and the DevTools AI status indicator.

    v2: Includes Brain 5 LPI + forward signal + cliff signal.
    Brain 5 import is deferred to avoid circular dependency at module load.
    """
    # ── Brain 2 + 3 metrics ───────────────────────────────────────────────────
    slow_vel   = calculate_slow_velocity(db)
    fast_vel   = calculate_fast_velocity(db)
    burn_rate  = calculate_burn_rate(db)
    momentum   = fast_vel - slow_vel
    rdr        = calculate_rdr(db, days=7)
    cliff      = calculate_cliff_signal(db)

    # ── Brain 5 metrics (deferred import) ────────────────────────────────────
    try:
        from app.services.brain5_lpi_engine import (
            calculate_lpi, get_level_distribution, get_forward_signal,
            has_elevated_risk_members,
        )
        lpi              = calculate_lpi(db)
        dist             = get_level_distribution(db)
        forward_signal   = get_forward_signal(db)
        elevated_risk    = has_elevated_risk_members(db)
        blended_vel      = calculate_blended_velocity(db, forward_signal)
    except Exception as exc:
        _logger.warning("get_system_snapshot: Brain 5 unavailable — %s", exc)
        lpi            = 0.0
        dist           = None
        forward_signal = 0.0
        elevated_risk  = False
        blended_vel    = fast_vel  # graceful fallback

    # ── Full decision with tri-velocity ──────────────────────────────────────
    multiplier, scenario = determine_reserve_multiplier(db, forward_signal=forward_signal)

    # ── Pool counts ───────────────────────────────────────────────────────────
    active_pools: int = (
        db.query(func.count(Pool.id))
        .filter(Pool.status == PoolStatus.Active)
        .scalar()
    ) or 0
    operational_pools: int = (
        db.query(func.count(Pool.id))
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .scalar()
    ) or 0
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # LEVER 3b — mirror the gated reserve in admin telemetry so the displayed
    # "dynamic_reserve_needed" can never diverge from the live Phase-2 spawn gate.
    dynamic_reserve_needed = compute_dynamic_reserve(operational_pools, multiplier, scenario)

    phase = (
        "BOOM"    if blended_vel > burn_rate and momentum > 0 else
        "DRY"     if blended_vel < burn_rate else
        "NEUTRAL"
    )

    snapshot = {
        # ── Brain 2 legacy fields (unchanged names — backward compat) ─────────
        "slow_velocity_weekly":    round(slow_vel, 2),
        "fast_velocity_weekly":    round(fast_vel, 2),
        "burn_rate_weekly":        burn_rate,
        "momentum":                round(momentum, 3),
        "rdr_percent":             round(rdr, 1),
        "multiplier":              multiplier,
        "scenario":                scenario,
        "phase":                   phase,
        "active_pools":            active_pools,
        "operational_pools":       operational_pools,
        "dynamic_reserve_needed":  dynamic_reserve_needed,
        # ── Brain 2 v2 new fields ─────────────────────────────────────────────
        "blended_velocity_weekly": round(blended_vel, 2),
        "cliff_signal":            cliff,
        # ── Brain 5 fields ────────────────────────────────────────────────────
        "lpi":                     round(lpi, 2),
        "forward_signal_l3":       round(forward_signal, 2),
        "elevated_risk_members":   elevated_risk,
    }

    if dist is not None:
        snapshot["level_distribution"] = dist.as_dict()

    return snapshot
