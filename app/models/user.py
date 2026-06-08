import enum
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, CheckConstraint, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class UserStatus(str, enum.Enum):
    Active = "Active"
    Waitlist = "Waitlist"
    Eliminated = "Eliminated"
    Eliminated_Won = "Eliminated_Won"


class WeeklyPaymentStatus(str, enum.Enum):
    Paid = "Paid"
    Unpaid = "Unpaid"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("current_level >= 1 AND current_level <= 6", name="ck_user_level_range"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    mobile = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    join_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    current_pool_id = Column(Integer, ForeignKey("pools.id"), nullable=True)
    current_level = Column(Integer, default=1, nullable=False)
    status = Column(Enum(UserStatus), default=UserStatus.Waitlist, nullable=False)
    weekly_payment_status = Column(
        Enum(WeeklyPaymentStatus), default=WeeklyPaymentStatus.Unpaid, nullable=False
    )
    late_fees_inr = Column(Numeric(12, 2), default=0, server_default="0", nullable=False)
    referred_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    hashed_password = Column(String, nullable=True)   # nullable for users created before auth update

    pool = relationship("Pool", back_populates="members")
    tokens = relationship("Token", back_populates="user")
