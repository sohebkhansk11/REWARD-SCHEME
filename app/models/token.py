import enum
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class TokenType(str, enum.Enum):
    Deposit  = "Deposit"
    Withdraw = "Withdraw"
    Referral = "Referral"


class TokenStatus(str, enum.Enum):
    Active = "Active"
    Burned = "Burned"


class Token(Base):
    __tablename__ = "tokens"

    id          = Column(Integer, primary_key=True, index=True)
    code        = Column(String, unique=True, nullable=False, index=True)
    type        = Column(Enum(TokenType), nullable=False)
    value_inr   = Column(Numeric(12, 2), nullable=False)
    status      = Column(Enum(TokenStatus), default=TokenStatus.Active, nullable=False)

    # Ownership — which user this token belongs to / was issued for
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Audit trail
    created_at          = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    redeemed_at         = Column(DateTime(timezone=True), nullable=True)   # set when status → Burned
    redeemed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # who initiated the burn

    user = relationship("User", foreign_keys=[user_id], back_populates="tokens")
