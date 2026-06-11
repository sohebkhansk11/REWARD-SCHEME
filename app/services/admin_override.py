"""
Admin Override System — L4 Overflow Resolution
===============================================
Activated when SDE preparation discovers that the L1/L2 supply is insufficient
to clear all flagged L4 members in the upcoming draw cycle.

Override options:
  Option A — Let overflow L4 members draw normally this week.
    Risk: probabilistic L5 advancement (~83.3% chance per member).
    Expected extra cost per member: ~₹1,000 × 0.833 = ~₹833.
    This cost is expected, not certain — depends on draw outcomes.

  Option B — Promote overflow L4 members to L5 now.
    Cost: certain extra payout next week (₹6,500 per member via SDE next cycle).
    Benefit: resolves L4 backlog cleanly; no L5-surprise during this draw.

Auto-select (BUG 4 FIX):
  If the admin does not respond within ADMIN_OVERRIDE_TIMEOUT_HOURS (2 hours),
  the system auto-selects the option with the lower expected cost.
  Typically Option A (probabilistic) has lower expected cost than Option B
  (certain) when L4 count is low.  The auto-select logic compares the two.

Important:
  System NEVER pauses due to L4 overflow.  It only pauses when new member
  inflow drops below SYSTEM_PAUSE_INFLOW_THRESHOLD (2 confirmed DEP burns/week).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import (
    ADMIN_OVERRIDE_TIMEOUT_HOURS,
    LEVEL_PAYOUTS,
    SYSTEM_PAUSE_INFLOW_THRESHOLD,
)
from app.models.user             import User, UserStatus
from app.models.weekly_draw_state import WeeklyDrawState

_logger = logging.getLogger(__name__)

# L4 → L5 advancement probability under normal draw (approx 5/6 = 0.8333)
# A non-L4 upper winner is chosen ~16.7% of the time; the L4 member survives
# and advances to L5 in ~83.3% of normal draws.
_L4_TO_L5_PROBABILITY = 5 / 6


# ── Risk calculations ─────────────────────────────────────────────────────────

def calculate_option_a_risk(overflow_count: int) -> dict:
    """
    Option A: let overflow L4 members draw normally.

    Per member:
      - ~83.3% chance they win their pool → exit at L4 (no extra cost)
      - ~16.7% chance they survive and advance to L5
        → next week's SDE pays out L5 upper (₹6,500) instead of L4 (₹5,500)
        → extra cost = ₹6,500 − ₹5,500 = ₹1,000 per upgraded member

    Expected extra cost = overflow_count × (1 - _L4_TO_L5_PROBABILITY) × 1,000
    """
    l4_net = LEVEL_PAYOUTS[4][1]   # ₹5,500
    l5_net = LEVEL_PAYOUTS[5][1]   # ₹6,500
    payout_diff = l5_net - l4_net  # ₹1,000

    expected_l5_advances    = overflow_count * (1 - _L4_TO_L5_PROBABILITY)
    expected_extra_cost_inr = expected_l5_advances * payout_diff

    return {
        "option":                    "A",
        "description":               "Let overflow L4 members draw normally this week",
        "overflow_count":            overflow_count,
        "l4_win_probability_pct":    round(_L4_TO_L5_PROBABILITY * 100, 1),
        "l4_advance_to_l5_pct":      round((1 - _L4_TO_L5_PROBABILITY) * 100, 1),
        "expected_l5_advances":      round(expected_l5_advances, 2),
        "expected_extra_cost_inr":   round(expected_extra_cost_inr),
        "certain_extra_cost_inr":    overflow_count * payout_diff,  # worst-case
        "note": (
            f"Probabilistic: {round(_L4_TO_L5_PROBABILITY * 100, 1)}% chance each L4 exits "
            f"this week without extra cost.  Expected extra = ₹{round(expected_extra_cost_inr):,}."
        ),
    }


def calculate_option_b_cost(overflow_count: int) -> dict:
    """
    Option B: promote all overflow L4 members to L5 now.

    Each member will draw at L5 next week (via SDE).
    Certain extra payout per member = L5_net − L4_net = ₹1,000.
    No probabilistic uncertainty.
    """
    l4_net = LEVEL_PAYOUTS[4][1]   # ₹5,500
    l5_net = LEVEL_PAYOUTS[5][1]   # ₹6,500
    extra_per_member  = l5_net - l4_net    # ₹1,000
    certain_extra_inr = overflow_count * extra_per_member

    return {
        "option":               "B",
        "description":          "Promote all overflow L4 members to L5 now",
        "overflow_count":       overflow_count,
        "extra_per_member_inr": extra_per_member,
        "certain_extra_cost_inr": certain_extra_inr,
        "l5_cleared_next_week": True,
        "note": (
            f"Certain cost: ₹{certain_extra_inr:,} extra "
            f"({overflow_count} × ₹{extra_per_member:,}).  "
            f"All L5 members cleared next week via SDE."
        ),
    }


# ── Admin override dashboard ──────────────────────────────────────────────────

def get_override_dashboard(db: Session, week_id: str) -> dict | None:
    """
    Return the full override dashboard for admin decision-making.

    Returns None if override is not required for this week.
    Returns a dict with both options, deadline, and recommendation.
    """
    state: WeeklyDrawState | None = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.week_id == week_id)
        .first()
    )

    if not state or not state.admin_override_required:
        return None

    overflow_count = state.sde_overflow_count
    now            = datetime.now(timezone.utc)

    time_remaining_seconds = (
        int((state.admin_override_deadline - now).total_seconds())
        if state.admin_override_deadline
        else 0
    )

    option_a = calculate_option_a_risk(overflow_count)
    option_b = calculate_option_b_cost(overflow_count)

    # Recommendation: lower expected cost wins
    if option_a["expected_extra_cost_inr"] <= option_b["certain_extra_cost_inr"]:
        recommendation = "A"
        reason = (
            f"Option A has lower expected cost "
            f"(₹{option_a['expected_extra_cost_inr']:,} vs ₹{option_b['certain_extra_cost_inr']:,})"
        )
    else:
        recommendation = "B"
        reason = (
            f"Option B has lower total cost "
            f"(₹{option_b['certain_extra_cost_inr']:,} vs ₹{option_a['expected_extra_cost_inr']:,})"
        )

    return {
        "week_id":                 week_id,
        "admin_override_required": True,
        "current_choice":          state.admin_override_choice,
        "deadline_utc":            state.admin_override_deadline.isoformat() if state.admin_override_deadline else None,
        "time_remaining_seconds":  max(0, time_remaining_seconds),
        "overflow_l4_count":       overflow_count,
        "option_a":                option_a,
        "option_b":                option_b,
        "recommendation":          recommendation,
        "recommendation_reason":   reason,
        "auto_select_in_effect":   (time_remaining_seconds <= 0 and state.admin_override_choice is not None),
    }


# ── Apply admin override decision ─────────────────────────────────────────────

def apply_override_decision(
    db: Session,
    week_id: str,
    choice: str,   # 'option_a' or 'option_b'
    applied_by: str = "admin",
) -> dict:
    """
    Apply the admin's override decision.

    Option A: clear sde_required on overflow members so they draw normally.
              They participate in regular/type_a pools this week.
              Risk: ~83.3% chance they advance to L5.

    Option B: promote overflow L4 members to L5.
              They will be flagged sde_required=True at L5 for next week.
              SDE will clear them next week at L5 payout.

    Idempotent: calling twice with the same choice is safe.
    Calling with a different choice after auto-select logs a warning but applies.
    """
    if choice not in ("option_a", "option_b"):
        raise ValueError(f"Invalid override choice '{choice}'. Must be 'option_a' or 'option_b'.")

    state: WeeklyDrawState | None = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.week_id == week_id)
        .first()
    )
    if not state:
        raise ValueError(f"No WeeklyDrawState found for week {week_id}.")
    if not state.admin_override_required:
        raise ValueError(f"Admin override is not required for week {week_id}.")

    # Idempotency: already applied?
    if state.admin_override_choice == choice:
        _logger.info(
            "apply_override_decision: idempotent — choice '%s' already applied for %s.",
            choice, week_id,
        )
        return {"status": "already_applied", "week_id": week_id, "choice": choice}

    # Get overflow L4 members
    overflow_members = _get_overflow_l4_members(db, week_id)

    if not overflow_members:
        _logger.warning(
            "apply_override_decision: no overflow members found for week %s — "
            "state may be stale.",
            week_id,
        )
        state.admin_override_choice    = choice
        state.admin_override_applied_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "applied_no_members", "week_id": week_id, "choice": choice}

    now = datetime.now(timezone.utc)

    if choice == "option_a":
        # Clear SDE flag — these members draw in regular pools this week
        for member in overflow_members:
            member.sde_required     = False
            member.sde_flagged_week = None
        _logger.info(
            "Override Option A applied for %s: %d L4 member(s) will draw normally. "
            "~%.0f%% chance of L5 advancement per member.",
            week_id, len(overflow_members), (1 - _L4_TO_L5_PROBABILITY) * 100,
        )

    elif choice == "option_b":
        # Promote to L5 — they'll be SDE-processed next week
        iso     = now.isocalendar()
        next_week_id = _next_week_id(week_id)
        for member in overflow_members:
            member.current_level     = 5
            member.sde_required      = True
            member.sde_flagged_week  = next_week_id
        _logger.warning(
            "Override Option B applied for %s: %d L4 member(s) promoted to L5. "
            "Will be cleared next week (%s) via SDE at ₹6,500 payout.",
            week_id, len(overflow_members), next_week_id,
        )

    state.admin_override_choice     = choice
    state.admin_override_applied_at = now
    db.commit()

    # If Option B, SDE can now run for the remaining clearable members
    # (the overflow members are now L5 and will be handled next week)
    if choice == "option_b":
        _trigger_deferred_sde(db, week_id)

    return {
        "status":           "applied",
        "week_id":          week_id,
        "choice":           choice,
        "members_affected": len(overflow_members),
        "applied_by":       applied_by,
        "applied_at":       now.isoformat(),
    }


# ── Auto-selection ────────────────────────────────────────────────────────────

def auto_select_on_timeout(db: Session, week_id: str) -> str | None:
    """
    BUG 4 FIX: auto-select override option after deadline expires.

    Called by the scheduler or T-2H preparation follow-up job.
    Returns the chosen option string, or None if no action was taken.

    Auto-select logic:
      Compare expected costs of both options and choose the cheaper one.
      Tie-breaker: Option A (probabilistic) wins ties.
    """
    state: WeeklyDrawState | None = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.week_id == week_id)
        .first()
    )

    if not state:
        return None
    if not state.admin_override_required:
        return None
    if state.admin_override_choice is not None:
        return None   # already decided

    now = datetime.now(timezone.utc)
    if state.admin_override_deadline and state.admin_override_deadline > now:
        return None   # deadline not yet reached

    # Compute expected costs
    overflow_count = state.sde_overflow_count or 0
    option_a_cost  = calculate_option_a_risk(overflow_count)["expected_extra_cost_inr"]
    option_b_cost  = calculate_option_b_cost(overflow_count)["certain_extra_cost_inr"]

    # Option A wins on tie (lower expected cost with uncertainty usually favours A)
    auto_choice = "option_a" if option_a_cost <= option_b_cost else "option_b"

    _logger.warning(
        "auto_select_on_timeout: admin timeout for week %s — "
        "auto-selecting '%s' (A_cost=₹%d  B_cost=₹%d).",
        week_id, auto_choice, option_a_cost, option_b_cost,
    )

    apply_override_decision(db, week_id, auto_choice, applied_by="auto_timeout")
    return auto_choice


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_overflow_l4_members(db: Session, week_id: str) -> list:
    """
    Return the L4 members that were identified as overflow for this week.

    Overflow members are those where sde_required=True AND their pool
    draw_completed_this_week=False (i.e. not yet cleared by SDE).
    """
    from app.models.pool import Pool
    from sqlalchemy import and_

    # Find pools that were NOT SDE-processed (still pending)
    unprocessed_pool_ids = (
        db.query(Pool.id)
        .filter(
            Pool.contains_flagged_l4      == True,   # noqa: E712
            Pool.draw_completed_this_week == False,   # noqa: E712
        )
        .subquery()
    )

    return (
        db.query(User)
        .filter(
            User.status          == UserStatus.Active,
            User.sde_required    == True,             # noqa: E712
            User.current_pool_id.in_(unprocessed_pool_ids),
        )
        .order_by(User.join_date.asc())
        .all()
    )


def _next_week_id(current_week_id: str) -> str:
    """
    Return the ISO week key for the week following current_week_id.
    Format: 'YYYY-Www'
    """
    from datetime import timedelta
    # Parse: '2026-W24' → year=2026, week=24
    parts  = current_week_id.split("-W")
    year   = int(parts[0])
    week   = int(parts[1])
    # Jan 4 is always in week 1 of its year (ISO 8601)
    jan_4  = datetime(year, 1, 4, tzinfo=timezone.utc)
    # Week 1 Monday of this year
    week1_monday = jan_4 - timedelta(days=jan_4.weekday())
    target_monday = week1_monday + timedelta(weeks=week - 1) + timedelta(weeks=1)
    iso = target_monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _trigger_deferred_sde(db: Session, week_id: str) -> None:
    """
    After Option B is applied (overflow L4 promoted to L5), run SDE for the
    remaining clearable L4 members (those that couldn't be cleared due to the
    supply shortage are now out of the way).

    This is a best-effort call — if it fails, the weekly draw will handle
    remaining pools via the standard execute_weekly_draw() path.
    """
    try:
        from app.services.sde_engine import run_sde_meta_pool
        result = run_sde_meta_pool(db, week_id)
        _logger.info(
            "Deferred SDE (post-Option-B) complete: %d L4 cleared  overflow=%d",
            result.total_l4_cleared, result.overflow_l4_count,
        )
    except Exception as exc:
        _logger.error(
            "Deferred SDE failed (non-fatal): %s  — draw will proceed normally.", exc,
        )


# ── Inflow check (system pause trigger) ──────────────────────────────────────

def check_inflow_for_pause_trigger(db: Session, days: int = 7) -> dict:
    """
    System pause is ONLY triggered when confirmed new member inflow drops
    below SYSTEM_PAUSE_INFLOW_THRESHOLD per week.

    'Confirmed' = DEP (Deposit) token has been burned (status=Burned).

    Returns:
      should_pause: bool
      inflow_count: int
      threshold:    int
    """
    from datetime import timedelta
    from app.models.token import Token, TokenType, TokenStatus

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    confirmed_joins = (
        db.query(Token)
        .filter(
            Token.type       == TokenType.Deposit,
            Token.status     == TokenStatus.Burned,
            Token.redeemed_at >= cutoff,
        )
        .count()
    )

    return {
        "should_pause":  confirmed_joins < SYSTEM_PAUSE_INFLOW_THRESHOLD,
        "inflow_count":  confirmed_joins,
        "threshold":     SYSTEM_PAUSE_INFLOW_THRESHOLD,
        "period_days":   days,
    }
