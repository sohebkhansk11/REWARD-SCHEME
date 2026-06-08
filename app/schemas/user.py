from pydantic import BaseModel, field_validator
from typing import Optional
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

    @field_validator("current_level")
    @classmethod
    def validate_level(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 6):
            raise ValueError("current_level must be between 1 and 6")
        return v


class UserResponse(UserBase):
    id: int
    username: str
    join_date: datetime

    model_config = {"from_attributes": True}
