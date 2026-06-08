import enum
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.database import Base


class TokenType(str, enum.Enum):
    Deposit = "Deposit"
    Withdraw = "Withdraw"
    Referral = "Referral"


class TokenStatus(str, enum.Enum):
    Active = "Active"
    Burned = "Burned"


class Token(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False, index=True)
    type = Column(Enum(TokenType), nullable=False)
    value_inr = Column(Numeric(12, 2), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(Enum(TokenStatus), default=TokenStatus.Active, nullable=False)

    user = relationship("User", back_populates="tokens")
