"""
EliminationEvent Model
======================
Immutable audit trail for every non-payment elimination that occurs in the system.

One row is written per eliminated user per elimination cycle.  Records are
NEVER updated after creation — this is a financial audit log.

Columns:
  id                    — auto-increment PK
  user_id               — FK to users (nullable: kept even if user row is deleted)
  pool_id               — FK to pools at the time of elimination (nullable)
  username_snapshot     — username at the time of elimination (denormalised)
  pool_name_snapshot    — pool name at time of elimination (denormalised)
  draw_week_id          — ISO week string "YYYY-Www" of the draw cycle (informational)
  reason                — enum: 'non_payment' | 'grace_expired'
  late_fees_forfeited   — total late fees (₹) forfeited (Numeric for exact accounting)
  seat_save_fee         — ₹500 grace fee if they entered grace but didn't pay it
                          (0 if they never entered grace, 500 if they entered but expired)
  deposit_forfeited     — original ₹1,000 deposit forfeited (always 1000 for non-pay)
  created_at            — UTC timestamp of the elimination event
"""

import enum

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum,
    ForeignKey, Integer, Numeric, String,
)
from sqlalchemy.sql import func

from app.database import Base


class EliminationReason(str, enum.Enum):
    non_payment   = "non_payment"    # eliminated because weekly payment was never made
    grace_expired = "grace_expired"  # entered grace period but grace fee not paid by deadline


class EliminationEvent(Base):
    """
    Financial audit record for every non-payment elimination.

    Immutable after creation — never UPDATE or DELETE rows in this table.
    All monetary columns use Numeric(12, 2) for exact decimal arithmetic.
    """
    __tablename__ = "elimination_events"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)

    # ── User reference (nullable FK — preserved even if user row is later deleted) ──
    user_id           = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username_snapshot = Column(String, nullable=False)   # denormalised for audit durability
    user_level_at_elimination = Column(Integer, nullable=False, default=1)

    # ── Pool reference (nullable FK — preserved if pool is dissolved) ────────────
    pool_id           = Column(Integer, ForeignKey("pools.id", ondelete="SET NULL"), nullable=True)
    pool_name_snapshot = Column(String, nullable=True)   # denormalised

    # ── Draw cycle identification ─────────────────────────────────────────────────
    draw_week_id = Column(String(10), nullable=True)   # "YYYY-Www", e.g. "2026-W24"

    # ── Elimination metadata ──────────────────────────────────────────────────────
    reason = Column(
        Enum(EliminationReason),
        nullable=False,
        default=EliminationReason.non_payment,
    )

    # ── Financial impact (exact Numeric for accounting integrity) ─────────────────
    # late_fees_forfeited: total accumulated late fees at time of elimination
    late_fees_forfeited   = Column(Numeric(12, 2), default=0, nullable=False)
    # seat_save_fee:        ₹500 grace fee (0 if grace never activated; 500 if entered grace but expired)
    seat_save_fee         = Column(Numeric(12, 2), default=0, nullable=False)
    # deposit_forfeited:    ₹1,000 initial deposit lost (always 1000 for non-payment eliminations)
    deposit_forfeited     = Column(Numeric(12, 2), default=1000, nullable=False)
    # total_forfeited:      sum of all above — pre-computed for reporting efficiency
    total_forfeited       = Column(Numeric(12, 2), default=1000, nullable=False)

    # ── Flags ─────────────────────────────────────────────────────────────────────
    was_in_grace_period = Column(Boolean, default=False, nullable=False)

    # ── Timestamp ────────────────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
