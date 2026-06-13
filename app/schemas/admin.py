from pydantic import BaseModel, Field
from typing import Optional, Literal
from decimal import Decimal
from datetime import datetime

from app.models.token import TokenType, TokenStatus
from app.models.user import UserStatus, WeeklyPaymentStatus
from app.schemas.token import TokenResponse
from app.schemas.user import UserResponse
from app.schemas.pool import PoolResponse


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
    id:                             int
    name:                           str
    mobile:                         str
    username:                       str
    status:                         str
    current_level:                  int
    current_pool_id:                Optional[int]
    weekly_payment_status:          str
    late_fees_inr:                  Decimal
    join_date:                      datetime
    first_payment_at:               Optional[datetime]   # earliest burned DEP token
    referred_by_user_id:            Optional[int]
    total_referrals_count:          int     = 0
    accumulated_referral_bonus_inr: Decimal = Decimal("0")
    # Phase 4: IRCTC-style dynamic waitlist position
    # Null for Active/Eliminated users; "WL-60" string for Waitlist users.
    # Computed via ROW_NUMBER() window function — always live, never stale.
    wl_position:                    Optional[str] = None   # e.g. "WL-60" | null
    # Compliance flags (Phase 1)
    sde_required:                   bool    = False
    elimination_risk:               bool    = False
    grace_active:                   bool    = False

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


# ── Admin Deep User Management (Phase 5) ──────────────────────────────────────

class AdminFullUpdateRequest(BaseModel):
    """PUT /admin/users/{id}/full-update — any field may be patched. All optional."""
    name:                           Optional[str]                 = None
    mobile:                         Optional[str]                 = None
    username:                       Optional[str]                 = None
    new_password:                   Optional[str]                 = Field(None, min_length=6,
                                                                          description="Plain-text; hashed before saving.")
    status:                         Optional[UserStatus]          = None
    current_level:                  Optional[int]                 = Field(None, ge=1, le=6)
    weekly_payment_status:          Optional[WeeklyPaymentStatus] = None
    current_pool_id:                Optional[int]                 = None
    late_fees_inr:                  Optional[Decimal]             = Field(None, ge=0)
    referred_by_user_id:            Optional[int]                 = None
    total_referrals_count:          Optional[int]                 = Field(None, ge=0)
    accumulated_referral_bonus_inr: Optional[Decimal]             = Field(None, ge=0)
    telegram_chat_id:               Optional[str]                 = None


class AdminDeleteTokenRequest(BaseModel):
    """DELETE /admin/tokens/{id} — admin password required as a second-factor safety gate."""
    admin_password: str = Field(..., description="Current admin account password (verified before deletion).")


class DeleteUserRequest(BaseModel):
    """DELETE /admin/users/{id} — admin password required before permanent deletion."""
    admin_password: str = Field(..., description="Current admin account password (verified before deletion).")


class UpdateThresholdRequest(BaseModel):
    """PUT /admin/settings/threshold — change the pool-creation waitlist threshold."""
    new_threshold: int = Field(..., ge=1, le=1000,
                               description="Minimum paid Waitlist members needed to auto-trigger a new pool (1–1000).")
    admin_password: str = Field(..., description="Admin account password — required to authorise this change.")


class ThresholdResponse(BaseModel):
    """Response body for GET / PUT /admin/settings/threshold."""
    pool_creation_threshold: int
    message:                 str


class UpdateReferralRewardRequest(BaseModel):
    """PUT /admin/settings/referral-reward — change the per-referral reward amount."""
    new_amount_inr: int = Field(
        ..., ge=0, le=10000,
        description=(
            "Per-referral reward credited in INR when a referred user enters an active pool "
            "(Rule 39).  Range: 0 (disabled) – ₹10,000.  Default: ₹250."
        ),
    )
    admin_password: str = Field(
        ...,
        description="Current admin account password — required to authorise this financial change.",
    )


class ReferralRewardResponse(BaseModel):
    """Response body for GET / PUT /admin/settings/referral-reward."""
    referral_reward_inr: int
    message:             str


class DeleteUserResponse(BaseModel):
    deleted_user_id:        int
    deleted_username:       str
    tokens_deleted:         int
    was_in_active_pool:     bool
    pool_id:                Optional[int]
    pool_members_remaining: Optional[int]
    message:                str


class DeleteTokenResponse(BaseModel):
    deleted_token_id:   int
    deleted_token_code: str
    token_type:         str
    token_value_inr:    Decimal
    message:            str


# ── Admin Referral Queue (Phase 5) ─────────────────────────────────────────────

class PendingReferralItem(BaseModel):
    """One row in GET /admin/referrals/pending."""
    token_id:                       int
    token_code:                     str
    token_value_inr:                Decimal
    created_at:                     Optional[datetime]
    user_id:                        Optional[int]
    username:                       Optional[str]
    user_name:                      Optional[str]
    total_referrals_count:          int
    accumulated_bonus_inr:          Decimal


class ReferralStatusUpdateRequest(BaseModel):
    """PUT /admin/referrals/{id}/status — approve or reject a pending payout."""
    action: Literal["approve", "reject"]
    note:   Optional[str] = None


# ── Broadcast ─────────────────────────────────────────────────────────────────

class BroadcastRequest(BaseModel):
    message:       str  = Field(min_length=1, max_length=1000)
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
