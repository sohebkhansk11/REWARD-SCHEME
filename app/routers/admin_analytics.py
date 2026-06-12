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
from sqlalchemy import case, func
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

    Legacy metrics:
    - total_collected_inr         — DEP burned (cash received)
    - total_distributed_inr       — WIT burned (cash paid out)
    - in_hand_liquidity_inr       — bank balance right now
    - maintenance_fees_total_inr  — ₹500 × draw count
    - total_liability_inr         — outstanding WIT + REF obligations
    - doomsday_liability_inr      — total DEP invested by active users

    New — Liability-Adjusted Profit:
    - total_cash_inflow_inr          — same as total_collected_inr; canonical name
    - total_cash_outflow_inr         — WIT burned + Referral_Withdraw burned
    - current_active_liability_inr   — level-based principal owed to active/waitlist
                                       Active Paid L  → L × ₹1,000
                                       Active Unpaid L → (L−1) × ₹1,000
                                       Waitlist       → ₹1,000
    - pure_realized_profit_inr       — inflow − outflow − active_liability

    New — Weekly Rolling Surplus (ISO week Mon 00:00 UTC → now):
    - week_start_date
    - weekly_collections_inr
    - weekly_payouts_inr
    - weekly_rolling_surplus_inr
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

    # ── Referral (REF — legacy individual tokens) ─────────────────────────────
    ref_burned = _scalar_sum(db, TokenType.Referral, TokenStatus.Burned)
    ref_active = _scalar_sum(db, TokenType.Referral, TokenStatus.Active)

    # ── Referral_Withdraw (cumulative payout requests, Phase 5+) ─────────────
    ref_withdraw_burned = _d(
        db.query(func.sum(Token.value_inr))
        .filter(
            Token.type   == TokenType.Referral_Withdraw,
            Token.status == TokenStatus.Burned,
        )
        .scalar()
    )

    # ── Derived legacy figures ────────────────────────────────────────────────
    business_volume   = dep_burned + wit_burned + ref_burned
    liquidity         = dep_burned - wit_burned - ref_burned
    maintenance_total = Decimal(str(wit_all_count * PAYOUT_FEE_INR))

    # ── Doomsday: SUM of DEP burned by ALL currently Active users ─────────────
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

    # ─────────────────────────────────────────────────────────────────────────
    # NEW ①  total_cash_outflow — WIT Burned + Referral_Withdraw Burned
    # ─────────────────────────────────────────────────────────────────────────
    # Note: legacy Referral (REF) tokens are intentionally excluded because they
    # are micro-bonuses tracked separately; the spec explicitly calls out only
    # Withdraw and Referral_Withdraw as "cash effectively paid out".
    cash_outflow: Decimal = wit_burned + ref_withdraw_burned

    # ─────────────────────────────────────────────────────────────────────────
    # NEW ②  current_active_liability — level-based principal owed to current
    #         participants.  Computed as a single SQL aggregation:
    #
    #   Active Paid   Level L  →  L × 1000  (paid L instalments incl. this week)
    #   Active Unpaid Level L  →  (L-1) × 1000  (paid L-1 instalments)
    #   Waitlist               →  1000  (initial deposit only)
    #
    # This differs from doomsday_liability (which sums actual DEP tokens burned
    # per user from the tokens table).  Here we derive the liability from game
    # state so it works even when token records are sparse.
    # ─────────────────────────────────────────────────────────────────────────
    liability_expr = case(
        (User.status == UserStatus.Waitlist, 1000),
        (
            (User.status == UserStatus.Active)
            & (User.weekly_payment_status == WeeklyPaymentStatus.Paid),
            User.current_level * 1000,
        ),
        (
            (User.status == UserStatus.Active)
            & (User.weekly_payment_status == WeeklyPaymentStatus.Unpaid),
            (User.current_level - 1) * 1000,
        ),
        else_=0,
    )
    active_liability: Decimal = _d(
        db.query(func.sum(liability_expr))
        .filter(User.status.in_([UserStatus.Active, UserStatus.Waitlist]))
        .scalar()
    )

    # ─────────────────────────────────────────────────────────────────────────
    # NEW ③  pure_realized_profit
    # ─────────────────────────────────────────────────────────────────────────
    pure_profit: Decimal = dep_burned - cash_outflow - active_liability

    # ─────────────────────────────────────────────────────────────────────────
    # NEW ④  weekly rolling surplus
    #         Window: Monday 00:00:00 UTC of the current ISO week → now
    # ─────────────────────────────────────────────────────────────────────────
    now_utc   = datetime.now(timezone.utc)
    week_start_dt = (
        now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=now_utc.weekday())   # roll back to Monday
    )
    week_start_date = week_start_dt.date()

    weekly_collections: Decimal = _d(
        db.query(func.sum(Token.value_inr))
        .filter(
            Token.type       == TokenType.Deposit,
            Token.status     == TokenStatus.Burned,
            Token.redeemed_at >= week_start_dt,
            Token.redeemed_at.isnot(None),
        )
        .scalar()
    )
    weekly_payouts: Decimal = _d(
        db.query(func.sum(Token.value_inr))
        .filter(
            Token.type       == TokenType.Withdraw,
            Token.status     == TokenStatus.Burned,
            Token.redeemed_at >= week_start_dt,
            Token.redeemed_at.isnot(None),
        )
        .scalar()
    )
    weekly_surplus: Decimal = weekly_collections - weekly_payouts

    return FinancialStats(
        # ── Legacy fields (unchanged) ─────────────────────────────────────────
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
        # ── New: Liability-Adjusted Profit ────────────────────────────────────
        total_cash_inflow_inr          = dep_burned,      # canonical alias
        total_cash_outflow_inr         = cash_outflow,
        current_active_liability_inr   = active_liability,
        pure_realized_profit_inr       = pure_profit,
        # ── New: Weekly Rolling Surplus ───────────────────────────────────────
        week_start_date              = week_start_date,
        weekly_collections_inr       = weekly_collections,
        weekly_payouts_inr           = weekly_payouts,
        weekly_rolling_surplus_inr   = weekly_surplus,
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


# ─────────────────────────────────────────────────────────────────────────────
# 6.  GET /admin/winners/history  — Winning Ledger
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/winners/history")
def get_winners_history(
    level:        Optional[int] = Query(None, ge=1, le=6, description="Filter by winning level"),
    journey_type: Optional[str] = Query(None, description="Filter by journey type: 'direct' or 'merged'"),
    limit:        int           = Query(100, ge=1, le=500),
    offset:       int           = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Paginated winner history for the Winning Ledger tab.

    Each draw produces two winner records (winner_1 and winner_2) which are
    returned as individual rows. Includes full journey provenance: level won,
    pool exited from, total deposited, merges + pauses experienced, and
    whether the journey was direct or went through dynamic condensation.
    """
    from app.models.draw_history import DrawHistory
    from app.models.pool import Pool

    # Pull draw history with pool names — no ORM relationship needed
    raw = (
        db.query(DrawHistory, Pool.name.label("pool_name"))
        .outerjoin(Pool, DrawHistory.pool_id == Pool.id)
        .order_by(DrawHistory.draw_timestamp.desc())
        .all()
    )

    rows = []
    for dh, pool_name in raw:
        for slot in (1, 2):
            uid    = dh.winner_1_user_id            if slot == 1 else dh.winner_2_user_id
            lvl    = dh.winner_1_level              if slot == 1 else dh.winner_2_level
            net    = dh.winner_1_net_payout         if slot == 1 else dh.winner_2_net_payout
            dep    = dh.winner_1_total_deposited    if slot == 1 else dh.winner_2_total_deposited
            merges = dh.winner_1_merges_experienced if slot == 1 else dh.winner_2_merges_experienced
            pauses = dh.winner_1_pauses_experienced if slot == 1 else dh.winner_2_pauses_experienced
            jtype  = dh.winner_1_journey_type       if slot == 1 else dh.winner_2_journey_type

            # Apply filters before any DB lookup
            if level        is not None and lvl   != level:        continue
            if journey_type is not None and jtype != journey_type: continue

            user: User | None = (
                db.query(User).filter(User.id == uid).first() if uid else None
            )
            net_f  = float(net or 0)
            dep_i  = dep or 1000
            gross  = net_f + 500   # net = gross − ₹500 platform fee

            rows.append({
                "draw_id":              dh.id,
                "pool_id":              dh.pool_id,
                "pool_name":            pool_name or f"Pool #{dh.pool_id}",
                "draw_timestamp":       dh.draw_timestamp.isoformat() if dh.draw_timestamp else None,
                "edge_case":            dh.edge_case_triggered,
                "user_id":              uid,
                "username":             user.username  if user else None,
                "user_name":            user.name      if user else None,
                "level_won":            lvl,
                "gross_payout_inr":     round(gross, 2),
                "net_payout_inr":       round(net_f, 2),
                "total_deposited_inr":  dep_i,
                "net_profit_inr":       round(net_f - dep_i, 2),
                "merges_experienced":   merges or 0,
                "pauses_experienced":   pauses or 0,
                "journey_type":         jtype  or "direct",
                "is_referred":          bool(user.referred_by_user_id) if user else False,
            })

    total = len(rows)
    return {
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "items":  rows[offset : offset + limit],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7.  GET /admin/stats/level-breakdown  — Winner stats aggregated by level
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/level-breakdown")
def get_level_breakdown(db: Session = Depends(get_db)):
    """
    Aggregate draw_history winner records by winning level (L1–L6).

    Returns collected (total deposited by winners) and distributed (net payout)
    for each level so the Statistics tab can render a side-by-side BarChart.
    Counts both winner_1 and winner_2 slots per draw record.
    """
    from app.models.draw_history import DrawHistory

    all_draws = db.query(DrawHistory).all()

    stats: dict[int, dict] = {
        l: {"winners": 0, "collected": 0, "distributed": 0.0}
        for l in range(1, 7)
    }

    for dh in all_draws:
        for lvl, dep, pay in (
            (dh.winner_1_level, dh.winner_1_total_deposited, dh.winner_1_net_payout),
            (dh.winner_2_level, dh.winner_2_total_deposited, dh.winner_2_net_payout),
        ):
            if lvl and 1 <= lvl <= 6:
                stats[lvl]["winners"]     += 1
                stats[lvl]["collected"]   += dep or 1000
                stats[lvl]["distributed"] += float(pay or 0)

    levels = []
    for l in range(1, 7):
        s = stats[l]
        levels.append({
            "level":                 l,
            "winners_count":         s["winners"],
            "total_collected_inr":   s["collected"],
            "total_distributed_inr": round(s["distributed"], 2),
            "avg_payout_inr":        round(s["distributed"] / s["winners"], 2)
                                     if s["winners"] else 0.0,
        })

    return {"levels": levels}


# ─────────────────────────────────────────────────────────────────────────────
# 8.  GET /admin/stats/ai-snapshot  — Quant Engine live state
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/ai-snapshot")
def get_ai_snapshot(db: Session = Depends(get_db)):
    """
    Live snapshot of all AI Quant Engine signals: velocity, momentum, RDR,
    active scenario, and dynamic reserve calculation.  Used by the admin
    dashboard header and DevTools AI status indicator.

    v2: now includes Brain 5 LPI, forward signal, cliff signal,
    blended velocity, and level distribution.
    """
    from app.services.ai_quant_engine import get_system_snapshot
    return get_system_snapshot(db)


# ─────────────────────────────────────────────────────────────────────────────
# 9.  GET /admin/stats/brain5-lpi  — Brain 5 LPI live state
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/brain5-lpi")
def get_brain5_lpi(db: Session = Depends(get_db)):
    """
    Brain 5 Level Pressure Index — live snapshot.

    Returns:
      lpi:               float (0–100)
      level_distribution: counts per level (L1–L6)
      pool_type_decision: routing decision for the upcoming draw cycle
      sde_demand:        SDE resource requirements
      forward_signal_l3: projected new L3 members next week
      elevated_risk:     True if any L5/L6 members exist (should be False normally)
    """
    from app.services.brain5_lpi_engine import (
        calculate_lpi, get_level_distribution, decide_pool_types,
        get_sde_demand, get_forward_signal, has_elevated_risk_members,
    )

    lpi      = calculate_lpi(db)
    dist     = get_level_distribution(db)
    decision = decide_pool_types(db)
    demand   = get_sde_demand(db)
    fwd      = get_forward_signal(db)
    elev     = has_elevated_risk_members(db)

    return {
        "lpi":                round(lpi, 2),
        "level_distribution": dist.as_dict(),
        "total_active":       dist.total,
        "pool_type_decision": {
            "p1_sde_active":      decision.p1_sde_active,
            "p1_sde_reason":      decision.p1_sde_reason,
            "p2_type_a_active":   decision.p2_type_a_active,
            "p3_regular_active":  decision.p3_regular_active,
            "p4_type_b_active":   decision.p4_type_b_active,
            "l4_flagged_count":   decision.l4_flagged_count,
            "sde_threshold_met":  decision.sde_threshold_met,
            "l1l2_exhausted":     decision.l1l2_exhausted,
            "summary":            decision.summary(),
        },
        "sde_demand": {
            "l4_count":               demand.l4_count,
            "sessions_needed":        demand.sessions_needed,
            "l1l2_threshold":         demand.l1l2_threshold,
            "l1l2_available":         demand.l1l2_available,
            "clearable_count":        demand.clearable_count,
            "overflow_count":         demand.overflow_count,
            "overflow_requires_admin": demand.overflow_requires_admin,
        },
        "forward_signal_l3":  round(fwd, 2),
        "elevated_risk":      elev,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 10.  GET /draw/countdown  — Two-flag countdown (public endpoint)
# ─────────────────────────────────────────────────────────────────────────────

# Note: this is intentionally NOT under /admin/ — it is shown to users too.
# The router is `admin_analytics` but we register a public path here.
# FastAPI does not restrict path prefixes per router; the auth dependency
# is only on the router-level for /admin/* paths.  This endpoint has NO
# auth so users can poll it freely.
from fastapi import APIRouter as _APIRouter
_public_router = _APIRouter(tags=["Draw Schedule"])

@_public_router.get("/draw/countdown")
def get_draw_countdown_public(db: Session = Depends(get_db)):
    """
    Two-flag countdown endpoint.

    Returns countdown data ONLY when preparation_valid=True AND
    countdown_active=True.  Otherwise returns a placeholder message.

    Clients MUST check `countdown_active` before displaying the timer.
    """
    from app.services.draw_preparation import get_draw_countdown
    return get_draw_countdown(db)


# ─────────────────────────────────────────────────────────────────────────────
# 10B.  GET /admin/stats/weekly-pool-reports  — Weekly Pool & Draw Activity Report
#        Feeds the Statistics → "Weekly Pool Reports" sub-tab.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/weekly-pool-reports")
def get_weekly_pool_reports(
    weeks: int = Query(24, ge=1, le=104, description="Number of recent weeks to return (max 104 = 2 years)"),
    db: Session = Depends(get_db),
):
    """
    Per-week draw and pool activity report.

    Groups DrawHistory rows by ISO calendar week.  For each week returns:
      week_id              — ISO week key "YYYY-WXX"
      week_start           — Monday date of that week "YYYY-MM-DD"
      draw_count           — total draws that week
      pool_count           — unique pools that drew that week
      winner_count         — total winners that week  (2 per draw)
      total_payout_inr     — sum of all winner payouts
      avg_payout_inr       — average payout per winner
      draw_types           — {regular, type_a, type_b, sde} counts
      winner_levels        — {L1…L6} winner counts
      total_sde_exits      — draws with targeted_early_exit = True
      total_deposits_inr   — sum of all winner deposits (1000 × winner_count as proxy)

    Also returns a snapshot of current system state for context.
    """
    from app.models.draw_history import DrawHistory
    from app.models.pool import Pool, PoolStatus
    from app.models.user import User, UserStatus
    from datetime import datetime, timezone

    all_draws = (
        db.query(DrawHistory)
        .order_by(DrawHistory.draw_timestamp.asc())
        .all()
    )

    if not all_draws:
        return {"weeks": [], "total_weeks": 0, "snapshot": {}}

    # ── Group by ISO calendar week ─────────────────────────────────────────────
    weekly: dict[str, list] = {}
    for dh in all_draws:
        dt = dh.draw_timestamp
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        iso = dt.isocalendar()
        wk  = f"{iso.year}-W{iso.week:02d}"
        weekly.setdefault(wk, []).append(dh)

    sorted_keys = sorted(weekly.keys())
    # Return most recent N weeks only
    if len(sorted_keys) > weeks:
        sorted_keys = sorted_keys[-weeks:]

    # ── Build per-week rows ────────────────────────────────────────────────────
    result_weeks = []
    for wk in sorted_keys:
        draws = weekly[wk]

        # Week start date from first draw's ISO info
        dt0 = draws[0].draw_timestamp
        if dt0.tzinfo is None:
            dt0 = dt0.replace(tzinfo=timezone.utc)
        iso0 = dt0.isocalendar()
        try:
            week_start_dt = datetime.fromisocalendar(iso0.year, iso0.week, 1)
            week_start    = week_start_dt.strftime("%Y-%m-%d")
        except Exception:
            week_start = str(draws[0].draw_timestamp)[:10]

        # Draw-type counts
        type_counts: dict[str, int] = {"regular": 0, "type_a": 0, "type_b": 0, "sde": 0}
        sde_exits = 0
        for dh in draws:
            raw_type = (dh.draw_type or "regular").lower().replace("-", "_")
            mapped   = raw_type if raw_type in type_counts else "regular"
            type_counts[mapped] += 1
            if dh.targeted_early_exit:
                sde_exits += 1

        # Winner aggregates
        level_dist: dict[int, int] = {l: 0 for l in range(1, 7)}
        total_payout = 0.0
        winner_count = 0
        total_deposits = 0

        for dh in draws:
            for lvl, pay, dep in (
                (dh.winner_1_level, dh.winner_1_net_payout, dh.winner_1_total_deposited),
                (dh.winner_2_level, dh.winner_2_net_payout, dh.winner_2_total_deposited),
            ):
                if lvl and 1 <= lvl <= 6:
                    level_dist[lvl] += 1
                    total_payout    += float(pay or 0)
                    total_deposits  += int(dep or 1000)
                    winner_count    += 1

        pool_ids = {dh.pool_id for dh in draws}

        result_weeks.append({
            "week_id":          wk,
            "week_start":       week_start,
            "draw_count":       len(draws),
            "pool_count":       len(pool_ids),
            "winner_count":     winner_count,
            "total_payout_inr": round(total_payout, 2),
            "avg_payout_inr":   round(total_payout / winner_count, 2) if winner_count else 0.0,
            "total_deposits_inr": total_deposits,
            "draw_types":       type_counts,
            "winner_levels":    {f"L{l}": level_dist[l] for l in range(1, 7)},
            "total_sde_exits":  sde_exits,
        })

    # ── Current system snapshot ────────────────────────────────────────────────
    try:
        active_users    = db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar() or 0
        waitlist_count  = db.query(func.count(User.id)).filter(User.status == UserStatus.Waitlist).scalar() or 0
        active_pools    = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Active).scalar() or 0
        total_draws_all = len(all_draws)
    except Exception:
        active_users = waitlist_count = active_pools = total_draws_all = 0

    return {
        "weeks":       result_weeks,
        "total_weeks": len(result_weeks),
        "snapshot": {
            "active_users":   active_users,
            "waitlist_count": waitlist_count,
            "active_pools":   active_pools,
            "total_draws":    total_draws_all,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11.  GET  /admin/draw/state            — Current WeeklyDrawState
#      POST /admin/draw/prepare          — Trigger T-2H preparation (manual)
#      POST /admin/draw/cleanup          — Trigger post-draw cleanup (manual)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/draw/state")
def get_draw_state(db: Session = Depends(get_db)):
    """
    Return the current WeeklyDrawState for admin monitoring.
    Shows preparation status, SDE sessions, float projection, etc.
    """
    from datetime import datetime, timezone
    from app.models.weekly_draw_state import WeeklyDrawState

    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"

    state = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.week_id == week_id)
        .first()
    )

    if not state:
        return {
            "week_id":            week_id,
            "status":             "not_prepared",
            "preparation_valid":  False,
            "countdown_active":   False,
            "draw_executed":      False,
            "message":            "No preparation state found for this week.",
        }

    return {
        "week_id":                   state.week_id,
        "preparation_valid":         state.preparation_valid,
        "countdown_active":          state.countdown_active,
        "draw_time_utc":             state.draw_time_utc.isoformat() if state.draw_time_utc else None,
        "preparation_started_at":    state.preparation_started_at.isoformat() if state.preparation_started_at else None,
        "preparation_completed_at":  state.preparation_completed_at.isoformat() if state.preparation_completed_at else None,
        "lpi_snapshot":              float(state.lpi_snapshot or 0),
        "total_l4_count":            state.total_l4_count,
        "total_l3_count":            state.total_l3_count,
        "sde_sessions_planned":      state.sde_sessions_planned,
        "sde_sessions_completed":    state.sde_sessions_completed,
        "sde_overflow_count":        state.sde_overflow_count,
        "admin_override_required":   state.admin_override_required,
        "admin_override_deadline":   state.admin_override_deadline.isoformat() if state.admin_override_deadline else None,
        "admin_override_choice":     state.admin_override_choice,
        "float_projection_inr":      state.float_projection_inr,
        "draw_executed":             state.draw_executed,
        "consecutive_type_b_weeks":  state.consecutive_type_b_weeks,
    }


@router.post("/admin/draw/prepare")
def trigger_draw_preparation(
    draw_time_utc_iso: str,
    db: Session = Depends(get_db),
):
    """
    Manually trigger T-2H draw preparation.

    draw_time_utc_iso: ISO 8601 UTC datetime of the draw.
    Example: "2026-06-14T13:30:00Z"

    Idempotent: safe to call multiple times.  Returns existing state
    if preparation is already complete for this week.
    """
    from datetime import datetime, timezone
    from app.services.draw_preparation import start_draw_preparation

    try:
        dt = datetime.fromisoformat(draw_time_utc_iso.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ISO datetime: '{draw_time_utc_iso}'. "
                   "Use format: '2026-06-14T13:30:00Z'",
        )

    try:
        state = start_draw_preparation(db, dt)
        return {
            "status":             "prepared",
            "week_id":            state.week_id,
            "preparation_valid":  state.preparation_valid,
            "countdown_active":   state.countdown_active,
            "sde_sessions":       state.sde_sessions_planned,
            "admin_override_req": state.admin_override_required,
            "float_projection":   state.float_projection_inr,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/admin/draw/cleanup")
def trigger_post_draw_cleanup(db: Session = Depends(get_db)):
    """
    Manually trigger post-draw cleanup (T+0H:05).

    Resets draw_completed_this_week flags, clears SDE flags on exited members,
    releases the draw engine lock.  Idempotent.
    """
    from app.services.draw import post_draw_cleanup
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"

    result = post_draw_cleanup(db)
    return {"status": "cleanup_complete", "week_id": week_id, **result}


# ─────────────────────────────────────────────────────────────────────────────
# 12.  GET  /admin/draw/override-dashboard
#      POST /admin/draw/override-decision
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/draw/override-dashboard")
def get_override_dashboard(
    week_id: Optional[str] = Query(
        None, description="ISO week key (e.g. '2026-W24'). Defaults to current week."
    ),
    db: Session = Depends(get_db),
):
    """
    Admin override dashboard for L4 overflow resolution.

    Shows financial risk comparison for both options with real-time expected costs.
    Returns null if no override is required for the specified week.
    """
    from app.services.admin_override import get_override_dashboard as _get_dashboard
    from datetime import datetime, timezone

    if not week_id:
        now = datetime.now(timezone.utc)
        iso = now.isocalendar()
        week_id = f"{iso.year}-W{iso.week:02d}"

    dashboard = _get_dashboard(db, week_id)
    if dashboard is None:
        return {
            "admin_override_required": False,
            "week_id": week_id,
            "message": "No admin override required for this week.",
        }
    return dashboard


@router.post("/admin/draw/override-decision")
def submit_override_decision(
    choice: str,
    week_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Submit admin override decision: 'option_a' or 'option_b'.

    option_a: Let overflow L4 members draw normally (probabilistic L5 risk).
    option_b: Promote overflow L4 → L5, clear them next week via SDE.
    """
    from app.services.admin_override import apply_override_decision
    from datetime import datetime, timezone

    if not week_id:
        now = datetime.now(timezone.utc)
        iso = now.isocalendar()
        week_id = f"{iso.year}-W{iso.week:02d}"

    try:
        result = apply_override_decision(db, week_id, choice, applied_by="admin_api")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 13.  GET  /admin/draw/scheduler-status  — APScheduler live state
#      POST /admin/draw/execute           — Manual draw trigger (dev / recovery)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/draw/scheduler-status")
def get_scheduler_status():
    """
    Return APScheduler running state and next-run times for all 4 draw jobs.

    Fields:
      running   — True if the scheduler process is alive
      enabled   — True if SCHEDULER_ENABLED=true was set at startup
      jobs      — list of { id, name, next_run } for each registered job
      schedule  — configured UTC trigger times for draw / prep / cleanup

    Use this to verify:
      • The scheduler started correctly on Render / production.
      • Next Sunday's jobs are queued at the expected times.
      • No jobs are silently missing (e.g. after a crash + restart).
    """
    from app.services.scheduler import get_scheduler_status as _get_status
    return _get_status()


@router.post("/admin/draw/execute")
def manual_execute_draw(db: Session = Depends(get_db)):
    """
    Manually execute the weekly draw.

    Intended for:
      • Recovery draws when SCHEDULER_ENABLED=false (local dev, staging).
      • Emergency re-run if the scheduler missed the Sunday trigger.

    Sequence mirrors the scheduler job exactly:
      1. Auto-select override if deadline has passed.
      2. execute_weekly_draw() — draws all eligible full pools.
      3. Marks WeeklyDrawState.draw_executed=True + countdown_active=False.

    Returns full draw result including per-pool outcomes and waitlist refill.

    Note: This is NOT idempotent by itself — use only after confirming no draw
    has already run this week (check GET /admin/draw/state first).
    """
    from app.services.draw             import execute_weekly_draw
    from app.services.admin_override   import auto_select_on_timeout
    from app.models.weekly_draw_state  import WeeklyDrawState
    from datetime import datetime, timezone
    from dataclasses import asdict

    now     = datetime.now(timezone.utc)
    iso     = now.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"

    # Belt-and-suspenders: resolve any pending override before drawing
    late_choice = auto_select_on_timeout(db, week_id)

    try:
        result = execute_weekly_draw(db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Mark WeeklyDrawState.draw_executed
    state = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.week_id == week_id)
        .first()
    )
    if state:
        state.draw_executed    = True
        state.draw_executed_at = now
        state.countdown_active = False
        db.commit()

    return {
        "status":              "draw_complete",
        "week_id":             week_id,
        "pools_drawn":         result.pools_drawn,
        "sde_pre_drawn":       result.sde_pre_drawn,
        "skipped_pools":       result.skipped_pools,
        "paused_pools":        result.paused_pools,
        "total_auto_paid":     result.total_auto_paid,
        "refill":              result.refill,
        "late_override_choice": late_choice,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 14.  GET /admin/stats/pause-calendar  — System Pause Heatmap (rolling 90 d)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/stats/pause-calendar")
def get_pause_calendar(db: Session = Depends(get_db)):
    """
    Rolling 90-day pause-activity calendar.

    Because the schema stores no explicit pause-event timestamps, data comes
    from two proxy sources and the frontend labels each source accordingly:

    source = "current"
      Pools whose status is currently Paused_Awaiting_Members are placed under
      today's date.  This is the most reliable signal.

    source = "draw_history"
      DrawHistory rows in the last 90 days where either winner carried a
      non-zero pauses_experienced count.  The draw_timestamp date is used as a
      proxy — it shows that the winning pool had experienced at least one pause
      during its lifetime, even if the exact pause date is unknown.

    The response is a sparse list: only dates with ≥1 pause event are included.
    The frontend fills the remaining calendar cells with "no data" styling.
    """
    from app.models.draw_history import DrawHistory

    today     = datetime.now(timezone.utc).date()
    date_from = today - timedelta(days=90)
    since_dt  = datetime(date_from.year, date_from.month, date_from.day,
                         tzinfo=timezone.utc)

    # ── Source 1: currently paused pools → today ──────────────────────────────
    paused_now: list[Pool] = (
        db.query(Pool)
        .filter(Pool.status == PoolStatus.Paused_Awaiting_Members)
        .order_by(Pool.id)
        .all()
    )

    # ── Source 2: draw dates where winners had pause history ──────────────────
    history_rows = (
        db.query(DrawHistory, Pool.name.label("pool_name"))
        .outerjoin(Pool, DrawHistory.pool_id == Pool.id)
        .filter(
            DrawHistory.draw_timestamp >= since_dt,
            (
                (DrawHistory.winner_1_pauses_experienced > 0)
                | (DrawHistory.winner_2_pauses_experienced > 0)
            ),
        )
        .order_by(DrawHistory.draw_timestamp)
        .all()
    )

    # ── Build sparse calendar dict keyed by ISO date ──────────────────────────
    cal: dict[str, dict] = {}

    def _ensure(d: date, source: str) -> dict:
        key = d.isoformat()
        if key not in cal:
            cal[key] = {"date": key, "paused_count": 0, "source": source, "pools": []}
        return cal[key]

    for pool in paused_now:
        entry = _ensure(today, "current")
        entry["pools"].append({"id": pool.id, "name": pool.name})
        entry["paused_count"] += 1

    seen: set[tuple[int, str]] = set()
    for dh, pool_name in history_rows:
        draw_date  = dh.draw_timestamp.date()
        dedup_key  = (dh.pool_id, draw_date.isoformat())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        entry = _ensure(draw_date, "draw_history")
        entry["pools"].append({
            "id":   dh.pool_id,
            "name": pool_name or f"Pool #{dh.pool_id}",
        })
        entry["paused_count"] += 1

    calendar_days = sorted(cal.values(), key=lambda x: x["date"])

    return {
        "date_from":            date_from.isoformat(),
        "date_to":              today.isoformat(),
        "calendar":             calendar_days,
        "current_paused_count": len(paused_now),
        "total_pause_events":   sum(d["paused_count"] for d in calendar_days),
    }
