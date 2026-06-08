from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal
from datetime import datetime

from app.models.token import TokenType, TokenStatus
from app.schemas.token import TokenResponse
from app.schemas.user import UserResponse
from app.schemas.pool import PoolResponse
from app.models.user import UserStatus


# --- Token endpoints ---

class TokenGenerateRequest(BaseModel):
    type: TokenType
    value_inr: Decimal
    user_id: Optional[int] = None


class TokenRedeemRequest(BaseModel):
    user_id: int


class RedeemResponse(BaseModel):
    token: TokenResponse
    user: UserResponse
    new_pool: Optional[PoolResponse] = None
    message: str


# --- Draw endpoint ---

class WinnerResultResponse(BaseModel):
    winner_id: int
    winner_username: str
    winner_level: int
    gross_payout_inr: Decimal
    fee_inr: Decimal
    net_payout_inr: Decimal
    withdraw_token_code: str
    replaced_by_user_id: Optional[int] = None
    replaced_by_username: Optional[str] = None


class DrawResultResponse(BaseModel):
    pool_id: int
    pool_name: str
    winner_1: WinnerResultResponse          # Low-tier winner (L1-L3) or edge-case fallback
    winner_2: WinnerResultResponse          # High-tier winner (L4-L6) or edge-case fallback
    edge_case_used: bool = False            # True when pool had no L4+ members (early weeks)


# --- Waitlist check endpoint ---

class WaitlistCheckResponse(BaseModel):
    paid_waitlist_count: int
    pool_created: Optional[PoolResponse] = None
    message: str


# ── Admin User Management ──────────────────────────────────────────────────────

class AdminUserListItem(BaseModel):
    """One row in GET /admin/users — includes computed payment timestamp."""
    id:                     int
    name:                   str
    mobile:                 str
    username:               str
    status:                 str
    current_level:          int
    current_pool_id:        Optional[int]
    weekly_payment_status:  str
    late_fees_inr:          Decimal
    join_date:              datetime
    first_payment_at:       Optional[datetime]   # earliest burned DEP token
    referred_by_user_id:    Optional[int]

    model_config = {"from_attributes": True}


class AdminTokenSummary(BaseModel):
    """Token summary embedded inside AdminUserDetail."""
    id:                  int
    code:                str
    type:                str
    value_inr:           Decimal
    status:              str
    created_at:          Optional[datetime]
    redeemed_at:         Optional[datetime]

    model_config = {"from_attributes": True}


class AdminUserDetail(AdminUserListItem):
    """GET /admin/users/{id} — comprehensive profile."""
    total_wins:       int              # count of WIT tokens
    total_won_inr:    Decimal          # sum of WIT token values
    tokens:           list[AdminTokenSummary]


# ── Admin Token Audit ──────────────────────────────────────────────────────────

class AdminTokenAudit(BaseModel):
    """One row in GET /admin/tokens — enriched with owner + redeemer usernames."""
    id:                  int
    code:                str
    type:                str
    value_inr:           Decimal
    status:              str
    created_at:          Optional[datetime]
    redeemed_at:         Optional[datetime]
    user_id:             Optional[int]
    user_username:       Optional[str]
    user_name:           Optional[str]
    redeemed_by_user_id: Optional[int]
    redeemed_by_username: Optional[str]


# ── CSV Import ─────────────────────────────────────────────────────────────────

class ImportError(BaseModel):
    row:    int
    mobile: str
    reason: str


class ImportSummaryResponse(BaseModel):
    total_rows:    int
    created_count: int
    skipped_count: int
    errors:        list[ImportError]


# ── Broadcast ─────────────────────────────────────────────────────────────────

from typing import Literal

class BroadcastRequest(BaseModel):
    message:       str = Field(min_length=1, max_length=1000)
    audience_type: Literal["all", "active", "waitlist", "winners", "pool"] = "all"
    pool_id:       Optional[int] = Field(
        None,
        description="Required when audience_type='pool'. The target pool's ID.",
    )
    channels:      list[Literal["whatsapp", "telegram"]] = Field(
        default=["whatsapp"],
        description="One or more: whatsapp, telegram",
    )


class BroadcastChannelResult(BaseModel):
    sent:    int
    failed:  int
    skipped: int
    errors:  list[str] = []


class BroadcastResponse(BaseModel):
    audience_type:   str
    total_targeted:  int
    channels:        dict[str, BroadcastChannelResult]
