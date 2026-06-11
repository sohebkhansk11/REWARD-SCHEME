import enum
from sqlalchemy import Boolean, Column, Index, Integer, String, DateTime, ForeignKey, Enum, CheckConstraint, Numeric
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
    # SPEC NOTE: spec names this column 'waitlist_joined_timestamp'.
    # To align: ALTER TABLE users RENAME COLUMN join_date TO waitlist_joined_timestamp;
    # All ORM attribute references must be updated in the same migration.
    join_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    current_pool_id = Column(Integer, ForeignKey("pools.id"), nullable=True)
    current_level = Column(Integer, default=1, nullable=False)
    status = Column(Enum(UserStatus), default=UserStatus.Waitlist, nullable=False)
    weekly_payment_status = Column(
        Enum(WeeklyPaymentStatus), default=WeeklyPaymentStatus.Unpaid, nullable=False
    )
    late_fees_inr = Column(Numeric(12, 2), default=0, server_default="0", nullable=False)
    referred_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    hashed_password    = Column(String, nullable=True)   # nullable for users created before auth update
    telegram_chat_id   = Column(String, nullable=True)   # numeric Telegram user ID — used for broadcasts

    # Unique referral code — generated on registration, used in invite links.
    # 8-char uppercase alphanumeric; unique constraint enforced at DB level.
    # nullable=True is intentional: legacy users created before this column
    # existed have NULL. All users registered since introduction get a code.
    referral_code = Column(String(8), unique=True, nullable=True, index=True)

    # Cumulative referral tracking — replaces individual REF-token-per-referral model
    total_referrals_count          = Column(Integer,          default=0, server_default="0", nullable=False)
    accumulated_referral_bonus_inr = Column(Numeric(12, 2),   default=0, server_default="0", nullable=False)

    # Journey tracking — incremented by pool operations, never written by users
    # dynamic_merges_experienced: how many times condensation moved this user
    # pauses_experienced:         how many times their pool was SafeStopped
    # total_deposited_inr:        running total of all deposit tokens redeemed
    dynamic_merges_experienced  = Column(Integer, default=0,    server_default="0",    nullable=False)
    pauses_experienced          = Column(Integer, default=0,    server_default="0",    nullable=False)
    total_deposited_inr         = Column(Integer, default=1000, server_default="1000", nullable=False)

    # ── Anti-Maturity Protocol — SDE flags ────────────────────────────────────
    # sde_required: set TRUE (in the same DB transaction as level advancement)
    #   the instant a member's current_level becomes 4.  Cleared when they exit
    #   (status → Eliminated_Won) or admin override resolves their fate.
    # sde_flagged_week: ISO week key ("YYYY-Www") of the draw week in which
    #   the flag was raised.  Prevents cross-week SDE contamination.
    sde_required     = Column(Boolean, default=False, server_default="false", nullable=False)
    sde_flagged_week = Column(String(10), nullable=True)   # e.g. "2026-W24"

    pool   = relationship("Pool", back_populates="members")
    tokens = relationship("Token", foreign_keys="Token.user_id", back_populates="user", cascade="all, delete-orphan")

    @property
    def current_pool_name(self) -> str | None:
        """Returns the name of the pool the user is currently in, or None."""
        return self.pool.name if self.pool else None
