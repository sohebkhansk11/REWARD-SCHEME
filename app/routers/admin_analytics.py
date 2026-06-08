"""
Admin Analytics & Statistics Router  —  Phase 4A
==================================================
GET  /admin/stats/financials     Financial & liability aggregation
GET  /admin/stats/pools          Pool-wise micro analytics
GET  /admin/stats/tokens         Token & payout distribution
PUT  /admin/tokens/{id}/status   Approve / Reject withdrawal queue
GET  /admin/stats/ai-forecast    Predictive algorithmic forecasting
GET  /admin/stats/charts         Growth chart time-series data

All endpoints require a valid Admin JWT.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import LEVEL_PAYOUTS, PAYOUT_FEE_INR, WAITLIST_TRIGGER
from app.core.security import require_admin_jwt
from app.database import get_db
from app.models.pool import Pool, PoolStatus
from app.models.token import Token, TokenType, TokenStatus
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.schemas.analytics import (
    AIForecastResponse,
    ChartDataPoint,
    ChartStatsResponse,
    FinancialStats,
    LiquidityForecast,
    PoolMemberDetail,
    PoolStatItem,
    PoolStatsResponse,
    TokenDistributionResponse,
    TokenStatusUpdateRequest,
    TokenStatusUpdateResponse,
    TokenTypeStat,
    WaitlistVelocityForecast,
)

router = APIRouter(tags=["Admin · Analytics"], dependencies=[Depends(require_admin_jwt)])

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_ZERO = Decimal("0")


def _d(val) -> Decimal:
    """Safely coerce a DB aggregate result (may be None) to Decimal."""
    return Decimal(str(val)) if val is not None else _ZERO


def _scalar_sum(db: Session, token_type: TokenType, status: TokenStatus) -> Decimal:
    return _d(
        db.query(func.sum(Token.value_inr))
        .filter(Token.type == token_type, Token.status == status)
        .scalar()
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1.  GET /admin/stats/financials
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/financials", response_model=FinancialStats)
def get_financials(db: Session = Depends(get_db)):
    """
    Complete financial & liability snapshot.

    Key metrics:
    - total_collected_inr       — cash actually deposited (DEP burned)
    - total_distributed_inr     — cash actually paid out (WIT burned)
    - in_hand_liquidity_inr     — what's available in the bank right now
    - maintenance_fees_total    — ₹500 × every draw winner ever
    - total_liability_inr       — outstanding WIT + REF promises (un-burned)
    - doomsday_liability_inr    — worst-case refund if all Active users exit today
    """
    # ── Deposit (DEP) ─────────────────────────────────────────────────────────
    dep_burned = _scalar_sum(db, TokenType.Deposit, TokenStatus.Burned)

    # ── Withdraw / Winning (WIT) ──────────────────────────────────────────────
    wit_burned = _scalar_sum(db, TokenType.Withdraw, TokenStatus.Burned)
    wit_active = _scalar_sum(db, TokenType.Withdraw, TokenStatus.Active)

    # Fee count = every WIT ever created (fee earned at draw time, not payout time)
    wit_all_count: int = (
        db.query(func.count(Token.id))
        .filter(Token.type == TokenType.Withdraw)
        .scalar() or 0
    )

    # ── Referral (REF) ────────────────────────────────────────────────────────
    ref_burned = _scalar_sum(db, TokenType.Referral, TokenStatus.Burned)
    ref_active = _scalar_sum(db, TokenType.Referral, TokenStatus.Active)

    # ── Derived figures ───────────────────────────────────────────────────────
    business_volume   = dep_burned + wit_burned + ref_burned   # gross money flow
    liquidity         = dep_burned - wit_burned - ref_burned
    maintenance_total = Decimal(str(wit_all_count * PAYOUT_FEE_INR))

    # ── Doomsday: SUM of DEP burned by ALL currently Active users (via subquery)
    active_sq = db.query(User.id).filter(User.status == UserStatus.Active).subquery()
    doomsday  = _d(
        db.query(func.sum(Token.value_inr))
        .filter(
            Token.type   == TokenType.Deposit,
            Token.status == TokenStatus.Burned,
            Token.user_id.in_(active_sq),
        )
        .scalar()
    )

    # ── User counts ───────────────────────────────────────────────────────────
    active_count = (
        db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar() or 0
    )
    waitlist_count = (
        db.query(func.count(User.id)).filter(User.status == UserStatus.Waitlist).scalar() or 0
    )
    eliminated_count = (
        db.query(func.count(User.id))
        .filter(User.status.in_([UserStatus.Eliminated, UserStatus.Eliminated_Won]))
        .scalar() or 0
    )

    return FinancialStats(
        total_collected_inr        = dep_burned,
        total_distributed_inr      = wit_burned,
        total_referrals_paid_inr   = ref_burned,
        total_business_volume_inr  = business_volume,
        in_hand_liquidity_inr      = liquidity,
        maintenance_fees_count     = wit_all_count,
        maintenance_fees_total_inr = maintenance_total,
        wit_liability_inr          = wit_active,
        ref_liability_inr          = ref_active,
        total_liability_inr        = wit_active + ref_active,
        doomsday_liability_inr     = doomsday,
        active_user_count          = active_count,
        waitlist_count             = waitlist_count,
        eliminated_count           = eliminated_count,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2.  GET /admin/stats/pools
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/pools", response_model=PoolStatsResponse)
def get_pool_stats(db: Session = Depends(get_db)):
    """
    Pool-wise micro analytics.

    Global figures come from system-wide token aggregates.
    Per-pool figures are computed from current pool members because the Token
    model does not carry a pool_id column.  Specifically:
      total_deposited_by_members_inr  — SUM of all DEP burned by current members
      weekly_deposits_inr             — this week's paid-in amount (Paid members × ₹1,000)
      potential_payout_liability_inr  — hypothetical total if every member won today
      wit_pending_inr                 — Active WIT tokens belonging to current members
    """
    pools   = db.query(Pool).order_by(Pool.id).all()
    members = (
        db.query(User)
        .filter(User.current_pool_id.isnot(None), User.status == UserStatus.Active)
        .all()
    )

    # Group members by pool_id
    pool_members: dict[int, list[User]] = defaultdict(list)
    for m in members:
        pool_members[m.current_pool_id].append(m)

    all_member_ids = [m.id for m in members]

    # ── Bulk-query DEP contributions for ALL pool members in ONE query ─────────
    dep_by_user: dict[int, Decimal] = {}
    wit_active_by_user: dict[int, Decimal] = {}
    if all_member_ids:
        for uid, total in (
            db.query(Token.user_id, func.sum(Token.value_inr))
            .filter(
                Token.type   == TokenType.Deposit,
                Token.status == TokenStatus.Burned,
                Token.user_id.in_(all_member_ids),
            )
            .group_by(Token.user_id)
            .all()
        ):
            dep_by_user[uid] = _d(total)

        for uid, total in (
            db.query(Token.user_id, func.sum(Token.value_inr))
            .filter(
                Token.type   == TokenType.Withdraw,
                Token.status == TokenStatus.Active,
                Token.user_id.in_(all_member_ids),
            )
            .group_by(Token.user_id)
            .all()
        ):
            wit_active_by_user[uid] = _d(total)

    # ── Global aggregates ─────────────────────────────────────────────────────
    global_col  = _scalar_sum(db, TokenType.Deposit,  TokenStatus.Burned)
    global_dist = _scalar_sum(db, TokenType.Withdraw, TokenStatus.Burned)
    global_ref  = _scalar_sum(db, TokenType.Referral, TokenStatus.Burned)

    # ── Build per-pool items ──────────────────────────────────────────────────
    pool_items: list[PoolStatItem] = []
    active_count     = 0
    non_active_count = 0

    for pool in pools:
        if pool.status == PoolStatus.Active:
            active_count += 1
        else:
            non_active_count += 1

        cur_members = sorted(
            pool_members.get(pool.id, []),
            key=lambda u: u.current_level,
            reverse=True,
        )

        total_deposited  = sum((dep_by_user.get(m.id, _ZERO) for m in cur_members), _ZERO)
        weekly_deposits  = Decimal(
            str(sum(1 for m in cur_members if m.weekly_payment_status == WeeklyPaymentStatus.Paid) * 1_000)
        )
        potential_payout = sum(
            Decimal(str(LEVEL_PAYOUTS.get(m.current_level, (0, 0))[1]))
            for m in cur_members
        )
        wit_pending = sum((wit_active_by_user.get(m.id, _ZERO) for m in cur_members), _ZERO)

        member_details = [
            PoolMemberDetail(
                user_id               = m.id,
                username              = m.username,
                name                  = m.name,
                current_level         = m.current_level,
                weekly_payment_status = m.weekly_payment_status.value,
                join_date             = m.join_date,
            )
            for m in cur_members
        ]

        pool_items.append(
            PoolStatItem(
                pool_id                         = pool.id,
                pool_name                       = pool.name,
                pool_status                     = pool.status.value,
                current_member_count            = len(cur_members),
                total_deposited_by_members_inr  = total_deposited,
                weekly_deposits_inr             = weekly_deposits,
                potential_payout_liability_inr  = potential_payout,
                wit_pending_inr                 = wit_pending,
                members                         = member_details,
            )
        )

    return PoolStatsResponse(
        total_pools             = len(pools),
        active_pools_count      = active_count,
        non_active_pools_count  = non_active_count,
        global_collection_inr   = global_col,
        global_distribution_inr = global_dist,
        global_profit_inr       = global_col - global_dist - global_ref,
        pools                   = pool_items,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3a.  GET /admin/stats/tokens
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/tokens", response_model=TokenDistributionResponse)
def get_token_stats(db: Session = Depends(get_db)):
    """
    Token & payout distribution — counts and values broken down by type
    (Deposit / Withdraw / Referral) and status (Active / Burned / Rejected).
    """

    def _build_stat(token_type: TokenType) -> TokenTypeStat:
        rows = (
            db.query(Token.status, func.count(Token.id), func.sum(Token.value_inr))
            .filter(Token.type == token_type)
            .group_by(Token.status)
            .all()
        )
        s = TokenTypeStat(
            total_count=0, total_value_inr=_ZERO,
            burned_count=0, burned_value_inr=_ZERO,
            active_count=0, active_value_inr=_ZERO,
            rejected_count=0, rejected_value_inr=_ZERO,
        )
        for status, cnt, val in rows:
            cnt = cnt or 0
            val = _d(val)
            s.total_count     += cnt
            s.total_value_inr += val
            if status == TokenStatus.Burned:
                s.burned_count,   s.burned_value_inr   = cnt, val
            elif status == TokenStatus.Active:
                s.active_count,   s.active_value_inr   = cnt, val
            elif status == TokenStatus.Rejected:
                s.rejected_count, s.rejected_value_inr = cnt, val
        return s

    return TokenDistributionResponse(
        deposit  = _build_stat(TokenType.Deposit),
        withdraw = _build_stat(TokenType.Withdraw),
        referral = _build_stat(TokenType.Referral),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3b.  PUT /admin/tokens/{token_id}/status  —  Approve / Reject queue
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/admin/tokens/{token_id}/status", response_model=TokenStatusUpdateResponse)
def update_token_status(
    token_id: int,
    body:     TokenStatusUpdateRequest,
    db:       Session = Depends(get_db),
):
    """
    Approve or Reject a pending Withdraw (WIT-) token.

    **approve** → marks status as `Burned` — cash has been physically paid to the user.
    **reject**  → marks status as `Rejected` — fraud / admin override; win is voided.
                  The user retains `Eliminated_Won` status (already exited the pool)
                  but forfeits the payout.

    Only `Active` WIT tokens may be actioned.  Attempting to action an already
    Burned or Rejected token returns 409 Conflict.

    ⚠️  `reject` requires the DB migration:
        `ALTER TYPE tokenstatus ADD VALUE 'Rejected';`
    """
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail=f"Token ID {token_id} not found.")

    if token.type != TokenType.Withdraw:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only Withdraw (WIT-) tokens can be approved or rejected. "
                f"Token {token.code} is of type '{token.type.value}'."
            ),
        )

    if token.status != TokenStatus.Active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Token {token.code} is already '{token.status.value}'. "
                "Only Active tokens may be approved or rejected."
            ),
        )

    now = datetime.now(timezone.utc)

    if body.action == "approve":
        token.status      = TokenStatus.Burned
        token.redeemed_at = now
        new_status = TokenStatus.Burned.value
        message = (
            f"✅  {token.code} approved — status set to Burned. "
            "Cash payment is confirmed."
        )

    elif body.action == "reject":
        token.status      = TokenStatus.Rejected
        token.redeemed_at = now
        new_status = TokenStatus.Rejected.value
        message = (
            f"🚫  {token.code} rejected — status set to Rejected. "
            "Payout voided (fraud / admin override). "
            "User retains Eliminated_Won status but will not receive funds."
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{body.action}'. Must be 'approve' or 'reject'.",
        )

    try:
        db.commit()
        db.refresh(token)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                f"Database error — if you are using 'reject' for the first time, "
                f"run the migration: ALTER TYPE tokenstatus ADD VALUE 'Rejected'; "
                f"({type(exc).__name__}: {exc})"
            ),
        )

    return TokenStatusUpdateResponse(
        token_id   = token.id,
        code       = token.code,
        action     = body.action,
        new_status = new_status,
        message    = message,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4.  GET /admin/stats/ai-forecast
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/ai-forecast", response_model=AIForecastResponse)
def get_ai_forecast(
    lookback_days: int = Query(
        30, ge=7, le=365,
        description="Days of history to base the forecast on (7–365). Default: 30.",
    ),
    db: Session = Depends(get_db),
):
    """
    Algorithmic predictive forecasting — two independent models.

    **Waitlist Velocity**
    Measures how many new members join per day over the lookback window.
    Because every registration burns a DEP token, each registration = one
    new paid-waitlist member.  The model then divides the remaining slots
    needed to hit the 24-member trigger by that daily rate.

    Confidence bands:
    - ≥ 1.5 members/day → "high"
    - ≥ 0.5 members/day → "medium"
    - < 0.5 members/day → "low"
    - no history        → "insufficient_data"

    **Liquidity Runway**
    Computes average weekly DEP inflow and (WIT + REF) outflow over the
    lookback window.  If net weekly flow is negative, calculates how many
    weeks before in-hand cash hits zero.
    """
    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)

    # ── Waitlist Velocity ─────────────────────────────────────────────────────
    new_joiners: int = (
        db.query(func.count(User.id))
        .filter(User.join_date >= start)
        .scalar() or 0
    )
    avg_daily = round(new_joiners / lookback_days, 4)

    current_paid_waitlist: int = (
        db.query(func.count(User.id))
        .filter(
            User.status                 == UserStatus.Waitlist,
            User.weekly_payment_status  == WeeklyPaymentStatus.Paid,
        )
        .scalar() or 0
    )
    needed = max(0, WAITLIST_TRIGGER - current_paid_waitlist)

    if needed == 0:
        trigger_date = now.date()
        confidence   = "high"
        wv_note = (
            f"Paid waitlist already has {current_paid_waitlist} members — "
            f"pool trigger threshold ({WAITLIST_TRIGGER}) is ALREADY MET. "
            "A new pool can be created immediately."
        )
    elif avg_daily > 0:
        days_needed  = math.ceil(needed / avg_daily)
        trigger_date = (now + timedelta(days=days_needed)).date()
        if avg_daily >= 1.5:
            confidence = "high"
        elif avg_daily >= 0.5:
            confidence = "medium"
        else:
            confidence = "low"
        wv_note = (
            f"Based on {new_joiners} registrations over the last {lookback_days} days "
            f"({avg_daily:.2f}/day), the {needed} remaining slot(s) will fill in "
            f"~{days_needed} day(s) — estimated pool trigger: {trigger_date}."
        )
    else:
        trigger_date = None
        confidence   = "insufficient_data"
        wv_note = (
            f"No new registrations in the last {lookback_days} days. "
            "Cannot project a pool trigger date."
        )

    waitlist_forecast = WaitlistVelocityForecast(
        current_paid_waitlist  = current_paid_waitlist,
        needed_to_trigger      = needed,
        avg_daily_new_members  = avg_daily,
        estimated_trigger_date = trigger_date,
        confidence             = confidence,
        note                   = wv_note,
    )

    # ── Liquidity Runway ──────────────────────────────────────────────────────
    # Use whole-week averages to smooth out noise
    weeks_back = max(1, lookback_days // 7)

    dep_in  = _d(
        db.query(func.sum(Token.value_inr))
        .filter(Token.type == TokenType.Deposit, Token.status == TokenStatus.Burned,
                Token.redeemed_at >= start, Token.redeemed_at.isnot(None))
        .scalar()
    )
    wit_out = _d(
        db.query(func.sum(Token.value_inr))
        .filter(Token.type == TokenType.Withdraw, Token.status == TokenStatus.Burned,
                Token.redeemed_at >= start, Token.redeemed_at.isnot(None))
        .scalar()
    )
    ref_out = _d(
        db.query(func.sum(Token.value_inr))
        .filter(Token.type == TokenType.Referral, Token.status == TokenStatus.Burned,
                Token.redeemed_at >= start, Token.redeemed_at.isnot(None))
        .scalar()
    )

    weeks_d          = Decimal(str(weeks_back))
    avg_weekly_in    = dep_in  / weeks_d
    avg_weekly_out   = (wit_out + ref_out) / weeks_d
    net_weekly       = avg_weekly_in - avg_weekly_out

    # Current total in-hand cash
    total_dep  = _scalar_sum(db, TokenType.Deposit,  TokenStatus.Burned)
    total_wit  = _scalar_sum(db, TokenType.Withdraw, TokenStatus.Burned)
    total_ref  = _scalar_sum(db, TokenType.Referral, TokenStatus.Burned)
    liquidity  = total_dep - total_wit - total_ref

    if net_weekly >= _ZERO:
        is_sustaining  = True
        runway_weeks   = None
        deficit_date   = None
        liq_note = (
            f"The system is cash-flow POSITIVE with a net inflow of "
            f"+₹{float(avg_weekly_in - avg_weekly_out):,.2f}/week "
            f"(in ₹{float(avg_weekly_in):,.2f} | out ₹{float(avg_weekly_out):,.2f}). "
            "No liquidity deficit is forecast."
        )
    else:
        is_sustaining = False
        drain_rate = -net_weekly    # how much liquidity shrinks per week
        if drain_rate > _ZERO:
            weeks_f      = float(liquidity) / float(drain_rate)
            runway_weeks = round(max(0.0, weeks_f), 2)
            deficit_date = (now + timedelta(weeks=runway_weeks)).date()
            liq_note = (
                f"Net weekly cash flow is -₹{float(drain_rate):,.2f}/week. "
                f"At the current rate, in-hand liquidity of ₹{float(liquidity):,.2f} "
                f"will be exhausted in ~{runway_weeks:.1f} week(s) "
                f"(estimated deficit: {deficit_date}). "
                "Consider slowing payouts or accelerating registrations."
            )
        else:
            runway_weeks = None
            deficit_date = None
            liq_note     = "Outflow data is zero; cannot compute runway."

    liquidity_forecast = LiquidityForecast(
        current_liquidity_inr  = liquidity,
        avg_weekly_inflow_inr  = avg_weekly_in,
        avg_weekly_outflow_inr = avg_weekly_out,
        net_weekly_flow_inr    = net_weekly,
        is_self_sustaining     = is_sustaining,
        runway_weeks           = runway_weeks,
        estimated_deficit_date = deficit_date,
        note                   = liq_note,
    )

    return AIForecastResponse(
        generated_at       = now,
        lookback_days_used = lookback_days,
        waitlist_velocity  = waitlist_forecast,
        liquidity_runway   = liquidity_forecast,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5.  GET /admin/stats/charts
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/charts", response_model=ChartStatsResponse)
def get_chart_data(
    days: int = Query(
        30, ge=7, le=365,
        description="Lookback window in days (7–365). Default: 30.",
    ),
    granularity: str = Query(
        "auto",
        description="'day', 'week', or 'auto' (auto picks day for ≤60d, week for >60d).",
    ),
    db: Session = Depends(get_db),
):
    """
    Time-series chart data formatted for Recharts / Chart.js.

    Each data point contains:
    - **period**             — date string key  (``"YYYY-MM-DD"``)
    - **registrations**      — new users joined
    - **waitlist_additions** — same as registrations (every registration = 1 waitlist entry)
    - **dep_collected_inr**  — DEP tokens burned in the period
    - **wit_paid_inr**       — WIT tokens burned (payouts made) in the period
    - **ref_paid_inr**       — REF tokens burned in the period
    - **net_profit_inr**     — dep − wit − ref for the period

    Daily periods are zero-filled so the chart has a continuous x-axis.
    Weekly periods only include weeks with at least one data event.
    """
    if granularity not in ("day", "week", "auto"):
        raise HTTPException(
            status_code=400,
            detail="granularity must be 'day', 'week', or 'auto'.",
        )

    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    trunc = ("day" if days <= 60 else "week") if granularity == "auto" else granularity

    # ── Period label helpers ──────────────────────────────────────────────────
    def _to_label(dt_or_d) -> str:
        """Convert a datetime / date (possibly timezone-aware) to a period label string."""
        d = dt_or_d.date() if hasattr(dt_or_d, "date") else dt_or_d
        if trunc == "week":
            # Use the Monday of the ISO week so Recharts gets a clean date axis
            monday: date = d - timedelta(days=d.weekday())
            return monday.strftime("%Y-%m-%d")
        return d.strftime("%Y-%m-%d")

    # ── DB queries ────────────────────────────────────────────────────────────
    # Registrations
    reg_rows = (
        db.query(
            func.date_trunc(trunc, User.join_date).label("period"),
            func.count(User.id).label("cnt"),
        )
        .filter(User.join_date >= start)
        .group_by("period")
        .order_by("period")
        .all()
    )

    def _flow_rows(token_type: TokenType):
        """Return (period, sum) rows for burned tokens of a given type."""
        return (
            db.query(
                func.date_trunc(trunc, Token.redeemed_at).label("period"),
                func.sum(Token.value_inr).label("total"),
            )
            .filter(
                Token.type   == token_type,
                Token.status == TokenStatus.Burned,
                Token.redeemed_at >= start,
                Token.redeemed_at.isnot(None),
            )
            .group_by("period")
            .order_by("period")
            .all()
        )

    dep_rows = _flow_rows(TokenType.Deposit)
    wit_rows = _flow_rows(TokenType.Withdraw)
    ref_rows = _flow_rows(TokenType.Referral)

    # ── Build a dict keyed by period label ────────────────────────────────────
    data: dict[str, dict] = {}

    def _ensure(key: str) -> dict:
        if key not in data:
            data[key] = {
                "period":             key,
                "registrations":      0,
                "waitlist_additions": 0,
                "dep_collected_inr":  _ZERO,
                "wit_paid_inr":       _ZERO,
                "ref_paid_inr":       _ZERO,
            }
        return data[key]

    for row in reg_rows:
        k = _to_label(row.period)
        _ensure(k)["registrations"]      = row.cnt
        _ensure(k)["waitlist_additions"] = row.cnt

    for row in dep_rows:
        k = _to_label(row.period)
        _ensure(k)["dep_collected_inr"] = _d(row.total)

    for row in wit_rows:
        k = _to_label(row.period)
        _ensure(k)["wit_paid_inr"] = _d(row.total)

    for row in ref_rows:
        k = _to_label(row.period)
        _ensure(k)["ref_paid_inr"] = _d(row.total)

    # ── Zero-fill every day in the range (for daily view) ────────────────────
    if trunc == "day":
        cursor = start.date()
        end    = now.date()
        while cursor <= end:
            _ensure(cursor.strftime("%Y-%m-%d"))
            cursor += timedelta(days=1)

    # ── Assemble final sorted list with computed net_profit ───────────────────
    points: list[ChartDataPoint] = []
    for key in sorted(data.keys()):
        d   = data[key]
        dep = d["dep_collected_inr"]
        wit = d["wit_paid_inr"]
        ref = d["ref_paid_inr"]
        points.append(
            ChartDataPoint(
                period             = key,
                registrations      = d["registrations"],
                waitlist_additions = d["waitlist_additions"],
                dep_collected_inr  = dep,
                wit_paid_inr       = wit,
                ref_paid_inr       = ref,
                net_profit_inr     = dep - wit - ref,
            )
        )

    return ChartStatsResponse(
        granularity = trunc,
        from_date   = start.date(),
        to_date     = now.date(),
        data        = points,
    )
