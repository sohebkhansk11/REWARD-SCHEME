from pydantic import BaseModel, field_validator
from typing import Optional
from decimal import Decimal
from datetime import datetime
from app.models.user import UserStatus, WeeklyPaymentStatus


class UserBase(BaseModel):
    name: str
    mobile: str
    username: Optional[str] = None
    current_pool_id: Optional[int] = None
    current_level: int = 1
    status: UserStatus = UserStatus.Waitlist
    weekly_payment_status: WeeklyPaymentStatus = WeeklyPaymentStatus.Unpaid
    late_fees_inr: Decimal = Decimal("0")
    referred_by_user_id: Optional[int] = None

    @field_validator("current_level")
    @classmethod
    def validate_level(cls, v: int) -> int:
        if not (1 <= v <= 6):
            raise ValueError("current_level must be between 1 and 6")
        return v


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    name: Optional[str] = None
    mobile: Optional[str] = None
    username: Optional[str] = None
    current_pool_id: Optional[int] = None
    current_level: Optional[int] = None
    status: Optional[UserStatus] = None
    weekly_payment_status: Optional[WeeklyPaymentStatus] = None
    late_fees_inr: Optional[Decimal] = None
    referred_by_user_id: Optional[int] = None
    telegram_chat_id: Optional[str] = None

    @field_validator("current_level")
    @classmethod
    def validate_level(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 6):
            raise ValueError("current_level must be between 1 and 6")
        return v


class UserResponse(UserBase):
    id:       int
    username: str
    join_date: datetime
    # Human-readable pool name populated via the User.current_pool_name property
    current_pool_name: Optional[str] = None
    # Cumulative referral fields (read-only — set by system)
    total_referrals_count:          int     = 0
    accumulated_referral_bonus_inr: Decimal = Decimal("0")

    model_config = {"from_attributes": True}
