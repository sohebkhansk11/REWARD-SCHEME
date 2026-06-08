from pydantic import BaseModel
from typing import Optional
from decimal import Decimal

from app.models.token import TokenType
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
