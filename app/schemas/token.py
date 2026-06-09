from pydantic import BaseModel
from typing import Optional
from decimal import Decimal
from datetime import datetime
from app.models.token import TokenType, TokenStatus


class TokenBase(BaseModel):
    code:      str
    type:      TokenType
    value_inr: Decimal
    user_id:   Optional[int] = None
    pool_id:   Optional[int] = None    # set for WIT tokens at draw time (for wallet history)
    status:    TokenStatus = TokenStatus.Active


class TokenCreate(TokenBase):
    pass


class TokenUpdate(BaseModel):
    code:                Optional[str]         = None
    type:                Optional[TokenType]   = None
    value_inr:           Optional[Decimal]     = None
    user_id:             Optional[int]         = None
    pool_id:             Optional[int]         = None
    status:              Optional[TokenStatus] = None
    redeemed_at:         Optional[datetime]    = None
    redeemed_by_user_id: Optional[int]         = None


class TokenResponse(TokenBase):
    id:                  int
    pool_id:             Optional[int]      = None
    created_at:          Optional[datetime] = None
    redeemed_at:         Optional[datetime] = None
    redeemed_by_user_id: Optional[int]      = None

    model_config = {"from_attributes": True}
