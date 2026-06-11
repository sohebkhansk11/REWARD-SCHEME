"""
WeeklyDrawState — draw-cycle state machine
==========================================
One row per ISO calendar week.  Tracks the complete lifecycle of a draw
cycle from T-2H preparation through post-draw cleanup.

State machine:
  NULL (no row) → preparation_valid=False (prep started, not complete)
               → preparation_valid=True  (prep complete, countdown active)
               → draw_executed=True      (draw fired, cleanup pending)

Two-flag countdown rule (enforced by draw_preparation.get_draw_countdown):
  Frontend MUST receive both countdown_active=True AND preparation_valid=True
  before displaying the countdown timer.  Either flag being False → show
  "Draw being prepared" placeholder instead.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String
from sqlalchemy.sql import func
from app.database import Base


class WeeklyDrawState(Base):
    __tablename__ = "weekly_draw_state"

    id      = Column(Integer, primary_key=True, index=True)

    # ISO week key — uniquely identifies the draw cycle.  Format: "YYYY-Www"
    # e.g. "2026-W24".  Used as idempotency key throughout preparation.
    week_id = Column(String(10), unique=True, nullable=False, index=True)

    # ── Preparation lifecycle ─────────────────────────────────────────────────
    draw_time_utc            = Column(DateTime(timezone=True), nullable=True)
    preparation_started_at   = Column(DateTime(timezone=True), nullable=True)
    preparation_completed_at = Column(DateTime(timezone=True), nullable=True)

    # preparation_valid: TRUE only after ALL preparation steps complete atomically.
    # countdown_active: TRUE iff preparation_valid=True AND draw has not fired.
    preparation_valid = Column(Boolean, default=False, server_default="false", nullable=False)
    countdown_active  = Column(Boolean, default=False, server_default="false", nullable=False)

    # ── Brain 5 snapshot (frozen at T-2H) ────────────────────────────────────
    lpi_snapshot       = Column(Numeric(5, 2), nullable=True)   # 0.00–100.00
    total_l4_count     = Column(Integer, default=0, server_default="0", nullable=False)
    total_l3_count     = Column(Integer, default=0, server_default="0", nullable=False)
    total_active_count = Column(Integer, default=0, server_default="0", nullable=False)

    # ── SDE planning ─────────────────────────────────────────────────────────
    sde_sessions_planned = Column(Integer, default=0, server_default="0", nullable=False)
    sde_sessions_completed = Column(Integer, default=0, server_default="0", nullable=False)
    sde_overflow_count   = Column(Integer, default=0, server_default="0", nullable=False)  # L4 not cleared

    # ── Admin override ────────────────────────────────────────────────────────
    # Raised when SDE demand > available L1/L2 supply for full clearance.
    admin_override_required = Column(Boolean, default=False, server_default="false", nullable=False)
    admin_override_deadline = Column(DateTime(timezone=True), nullable=True)
    # 'option_a' = let overflow L4 draw normally this week (probabilistic L5 risk)
    # 'option_b' = promote overflow L4 to L5 now (certain cost, cleared next week)
    admin_override_choice   = Column(String(10), nullable=True)
    admin_override_applied_at = Column(DateTime(timezone=True), nullable=True)

    # ── Financial snapshot ────────────────────────────────────────────────────
    # Projected maximum payout for this cycle (worst-case sum across all pools).
    float_projection_inr = Column(Integer, default=0, server_default="0", nullable=False)

    # ── Execution state ───────────────────────────────────────────────────────
    draw_executed    = Column(Boolean, default=False, server_default="false", nullable=False)
    draw_executed_at = Column(DateTime(timezone=True), nullable=True)

    # Idempotency token — SHA-256 of (week_id + draw_time_utc).
    # Prevents duplicate execution if the scheduler fires twice.
    idempotency_key = Column(String(64), unique=True, nullable=True)

    # Type B consecutive-week counter snapshot (read at prep time)
    consecutive_type_b_weeks = Column(Integer, default=0, server_default="0", nullable=False)

    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
