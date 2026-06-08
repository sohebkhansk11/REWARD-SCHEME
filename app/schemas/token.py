from pydantic import BaseModel
from typing import Optional
from decimal import Decimal
from app.models.token import TokenType, TokenStatus


class TokenBase(BaseModel):
    code: str
    type: TokenType
    value_inr: Decimal
    user_id: Optional[int] = None
    status: TokenStatus = TokenStatus.Active


class TokenCreate(TokenBase):
    pass


class TokenUpdate(BaseModel):
    code: Optional[str] = None
    type: Optional[TokenType] = None
    value_inr: Optional[Decimal] = None
    user_id: Optional[int] = None
    status: Optional[TokenStatus] = None


class TokenResponse(TokenBase):
    id: int

    model_config = {"from_attributes": True}
