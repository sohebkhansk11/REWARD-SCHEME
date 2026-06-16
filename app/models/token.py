import enum
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Python-side default that yields the SIMULATED instant during a Chronos run and
# real UTC in production, so a token's created_at follows the simulated week
# instead of the real PostgreSQL clock.  Governs every ORM db.add(Token(...)) path
# (RW / LF / GF / LFC / grace-WK tokens); the 5 bulk sa_insert(Token) sites set
# created_at explicitly because core bulk inserts bypass this default.
from app.core.sim_clock import now as _sim_now


class TokenType(str, enum.Enum):
    Deposit           = "Deposit"
    Withdraw          = "Withdraw"
    Referral          = "Referral"           # legacy — individual REF tokens (phase 1-3)
    Referral_Withdraw = "Referral_Withdraw"  # cumulative payout request (phase 5+) — requires DB migration
    # ── Compliance Revenue Tokens ──────────────────────────────────────────────
    # Late_Fee:   Immutable receipt created each time POST /admin/penalty/apply-daily
    #             accrues ₹50 on an unpaid member.  One token per member per day.
    #             Also created as a settlement receipt in confirm_grace_payment() when
    #             the user finally pays their accumulated late fees.
    #             Value = daily accrual amount (LATE_FEE_DAILY_INR, default ₹50),
    #             or the full accumulated amount when created as settlement.
    #             Code prefix: "LF-"
    #             DB MIGRATION: ALTER TYPE tokentype ADD VALUE 'Late_Fee';
    #
    # Grace_Fee:  Immutable receipt created in confirm_grace_payment() when the admin
    #             confirms a user has paid the ₹500 seat-save fee.
    #             Value = grace_seat_save_fee_inr from system_settings (default ₹500).
    #             Code prefix: "GF-"
    #             DB MIGRATION: ALTER TYPE tokentype ADD VALUE 'Grace_Fee';
    Late_Fee          = "Late_Fee"           # daily late-fee accrual receipt — requires DB migration
    Grace_Fee         = "Grace_Fee"          # grace seat-save fee receipt (₹500) — requires DB migration


class TokenStatus(str, enum.Enum):
    Active           = "Active"
    Burned           = "Burned"
    Rejected         = "Rejected"         # admin-voided (fraud / admin override)      — requires DB migration
    Pending_Approval = "Pending_Approval" # awaiting admin review (Referral_Withdraw)  — requires DB migration


class Token(Base):
    __tablename__ = "tokens"

    id          = Column(Integer, primary_key=True, index=True)
    code        = Column(String, unique=True, nullable=False, index=True)
    type        = Column(Enum(TokenType), nullable=False)
    value_inr   = Column(Numeric(12, 2), nullable=False)
    status      = Column(Enum(TokenStatus), default=TokenStatus.Active, nullable=False)

    # Ownership — which user this token belongs to / was issued for
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Pool this token is associated with (set for WIT/Withdraw tokens at draw time)
    pool_id = Column(Integer, ForeignKey("pools.id"), nullable=True)

    # Audit trail
    created_at          = Column(DateTime(timezone=True), default=_sim_now, server_default=func.now(), nullable=False)
    redeemed_at         = Column(DateTime(timezone=True), nullable=True)   # set when status → Burned
    redeemed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # who initiated the burn

    user = relationship("User", foreign_keys=[user_id], back_populates="tokens")
    pool = relationship("Pool", foreign_keys=[pool_id])
