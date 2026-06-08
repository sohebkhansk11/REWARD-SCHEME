"""
Analytics Schemas  —  Phase 4A
================================
Pydantic response models for the Statistics & Analytics control centre.
All monetary values are Decimal to preserve exact precision.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel


# ── 1. Financial & Liability Aggregation ─────────────────────────────────────

class FinancialStats(BaseModel):
    # ── Revenue ──────────────────────────────────────────────────────────────
    total_collected_inr:        Decimal   # SUM of all BURNED DEP tokens
    total_distributed_inr:      Decimal   # SUM of all BURNED WIT tokens (cash actually paid)
    total_referrals_paid_inr:   Decimal   # SUM of all BURNED REF tokens
    total_business_volume_inr:  Decimal   # collected + distributed + referrals_paid (gross flow)

    # ── Liquidity ─────────────────────────────────────────────────────────────
    in_hand_liquidity_inr:      Decimal   # DEP burned − (WIT burned + REF burned)

    # ── Maintenance Fees ──────────────────────────────────────────────────────
    # Each draw winner pays ₹500 fee (gross − ₹500 = net stored in WIT token).
    # Fee is earned at draw time (token creation), not at payout.
    maintenance_fees_count:     int       # count of ALL WIT tokens ever created
    maintenance_fees_total_inr: Decimal   # maintenance_fees_count × ₹500

    # ── Outstanding Liabilities ───────────────────────────────────────────────
    wit_liability_inr:          Decimal   # Active WIT tokens — cash owed to winners
    ref_liability_inr:          Decimal   # Active REF tokens — cash owed to referrers
    total_liability_inr:        Decimal   # wit_liability + ref_liability

    # ── Doomsday Scenario ────────────────────────────────────────────────────
    # If pool cycle stops today and every Active L1-L6 member demands a refund,
    # the liability = sum of all DEP tokens burned by currently Active users
    # (i.e. total capital they have invested so far).
    doomsday_liability_inr:     Decimal
    active_user_count:          int
    waitlist_count:             int
    eliminated_count:           int       # Eliminated + Eliminated_Won combined


# ── 2. Pool-Wise Micro Analytics ──────────────────────────────────────────────

class PoolMemberDetail(BaseModel):
    user_id:               int
    username:              str
    name:                  str
    current_level:         int
    weekly_payment_status: str
    join_date:             datetime


class PoolStatItem(BaseModel):
    pool_id:      int
    pool_name:    str
    pool_status:  str   # Active | Full | Waiting

    current_member_count:           int
    # Total DEP burned by the pool's current members (all weekly payments so far)
    total_deposited_by_members_inr: Decimal
    # Cash collected this week (count of Paid members × ₹1,000)
    weekly_deposits_inr:            Decimal
    # Max cash obligation if every current member won right now (sum of net payouts by level)
    potential_payout_liability_inr: Decimal
    # For active pools: sum of WIT tokens (Burned) for ANY user currently in this pool
    # NOTE: once a member wins they leave, so this captures unpaid WIT for current members.
    wit_pending_inr:                Decimal

    members: list[PoolMemberDetail]


class PoolStatsResponse(BaseModel):
    total_pools:             int
    active_pools_count:      int
    non_active_pools_count:  int

    # Global (system-wide) financials — same source as /admin/stats/financials
    global_collection_inr:   Decimal   # total DEP burned
    global_distribution_inr: Decimal   # total WIT burned
    global_profit_inr:       Decimal   # collection − distribution − referrals paid

    pools: list[PoolStatItem]


# ── 3. Token & Payout Distribution ───────────────────────────────────────────

class TokenTypeStat(BaseModel):
    total_count:       int
    total_value_inr:   Decimal
    burned_count:      int
    burned_value_inr:  Decimal
    active_count:      int
    active_value_inr:  Decimal
    rejected_count:    int       # Admin-voided tokens (fraud / override)
    rejected_value_inr: Decimal


class TokenDistributionResponse(BaseModel):
    deposit:  TokenTypeStat
    withdraw: TokenTypeStat
    referral: TokenTypeStat


class TokenStatusUpdateRequest(BaseModel):
    action: Literal["approve", "reject"]
    note:   Optional[str] = None   # optional admin note (for audit log)


class TokenStatusUpdateResponse(BaseModel):
    token_id:   int
    code:       str
    action:     str
    new_status: str
    message:    str


# ── 4. AI Predictive Forecasting ─────────────────────────────────────────────

class WaitlistVelocityForecast(BaseModel):
    current_paid_waitlist:    int
    needed_to_trigger:        int     # WAITLIST_TRIGGER (24) − current_paid_waitlist
    avg_daily_new_members:    float   # new registrations per day over the lookback window
    estimated_trigger_date:   Optional[date]
    confidence:               str     # "high" | "medium" | "low" | "insufficient_data"
    note:                     str


class LiquidityForecast(BaseModel):
    current_liquidity_inr:   Decimal
    avg_weekly_inflow_inr:   Decimal   # avg DEP burned per week (lookback)
    avg_weekly_outflow_inr:  Decimal   # avg (WIT + REF) burned per week (lookback)
    net_weekly_flow_inr:     Decimal   # inflow − outflow (positive = growing)
    is_self_sustaining:      bool
    runway_weeks:            Optional[float]   # None if self-sustaining
    estimated_deficit_date:  Optional[date]    # None if self-sustaining
    note:                    str


class AIForecastResponse(BaseModel):
    generated_at:       datetime
    lookback_days_used: int
    waitlist_velocity:  WaitlistVelocityForecast
    liquidity_runway:   LiquidityForecast


# ── 5. Growth Chart Time-Series ───────────────────────────────────────────────

class ChartDataPoint(BaseModel):
    period:             str       # "YYYY-MM-DD" (daily) or "YYYY-MM-DD" Monday of week (weekly)
    registrations:      int
    waitlist_additions: int       # = registrations (every registration → 1 new Waitlist slot)
    dep_collected_inr:  Decimal   # DEP tokens burned in this period
    wit_paid_inr:       Decimal   # WIT tokens burned (paid out) in this period
    ref_paid_inr:       Decimal   # REF tokens burned in this period
    net_profit_inr:     Decimal   # dep_collected − wit_paid − ref_paid


class ChartStatsResponse(BaseModel):
    granularity: str              # "day" | "week"
    from_date:   date
    to_date:     date
    data:        list[ChartDataPoint]
