"""
SDESession + SDECheckpoint — Sequential Dynamic Eviction persistence layer
==========================================================================

SDESession: one session processes up to 6 L4 members (6 sub-draws).
  Multiple sessions per week are allowed when L4 > 6.
  All sessions for a given week_id belong to the SDE Meta-Pool.

SDECheckpoint: one row per completed sub-draw.
  Written atomically with each sub-draw's winner records.
  Enables crash-safe resume: on restart, query MAX(sub_draw_number) per
  session and continue from (max + 1).

Relationship diagram:
  weekly_draw_state.week_id  ──1:N──► sde_sessions.week_id
  sde_sessions.id            ──1:N──► sde_checkpoints.session_id
  sde_checkpoints            ──────►  pools.id      (soft ref)
  sde_checkpoints            ──────►  users.id × 2  (soft ref)

Soft FK policy: FK constraints are intentionally omitted on checkpoint
  cross-references to avoid table-lock contention during high-throughput
  draw execution.  Referential integrity is enforced at the service layer.
"""
import enum
from sqlalchemy import (
    Boolean, Column, DateTime, Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.sql import func
from app.database import Base


class SDESessionStatus(str, enum.Enum):
    Planned   = "planned"    # created at T-2H, not yet started
    Running   = "running"    # sub-draws in progress
    Completed = "completed"  # all planned sub-draws finished
    Partial   = "partial"    # cleared fewer sub-draws than planned (supply shortage)
    Failed    = "failed"     # unrecoverable error — admin intervention required


class SDESession(Base):
    __tablename__ = "sde_sessions"

    __table_args__ = (
        # One session number per week — prevents duplicate session creation
        # when the preparation job is retried (idempotency).
        UniqueConstraint("week_id", "session_number", name="uq_sde_session_week_number"),
    )

    id             = Column(Integer, primary_key=True, index=True)

    # ISO week key — ties this session to the parent WeeklyDrawState row.
    week_id        = Column(String(10), nullable=False, index=True)

    # 1-based sequence within the week.
    # Session 1 → L4 members 1–6, Session 2 → members 7–12, etc.
    session_number = Column(Integer, nullable=False)

    status = Column(String(20), default=SDESessionStatus.Planned, nullable=False)

    # Planned vs. actually cleared (may differ if supply shortage mid-session)
    l4_count_planned   = Column(Integer, default=0, server_default="0", nullable=False)
    l4_count_completed = Column(Integer, default=0, server_default="0", nullable=False)

    # Running total payout committed across all sub-draws in this session
    total_payout_inr = Column(Numeric(12, 2), default=0, server_default="0", nullable=False)

    started_at   = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SDECheckpoint(Base):
    """
    Immutable record of one completed SDE sub-draw.

    rng_seed_hash  SHA-256(pool_id || session_id || sub_draw_number || DRAW_RNG_SECRET)
      Provides cryptographic auditability — verifiable post-hoc by anyone
      holding the server secret.  The secret itself is never stored here.

    lower_winner_tier_override  TRUE when the lower winner was an L3 member
      selected under the LPI > 50% exception rule.  Preserved for audit trail.
    """
    __tablename__ = "sde_checkpoints"

    __table_args__ = (
        UniqueConstraint(
            "session_id", "sub_draw_number",
            name="uq_sde_checkpoint_session_subdraw",
        ),
    )

    id              = Column(Integer, primary_key=True, index=True)
    session_id      = Column(Integer, nullable=False, index=True)   # soft FK → sde_sessions.id
    sub_draw_number = Column(Integer, nullable=False)                # 1-based within session

    # Source pool this sub-draw belongs to
    pool_id = Column(Integer, nullable=False)   # soft FK → pools.id

    # ── Upper winner — always the L4 member (guaranteed exit) ────────────────
    upper_winner_user_id = Column(Integer, nullable=False)   # soft FK → users.id
    upper_winner_level   = Column(Integer, nullable=False)   # 4 in normal operation; 5 edge case
    upper_payout_inr     = Column(Numeric(12, 2), nullable=False)

    # ── Lower winner — AI-weighted from L1/L2 (or L3 under LPI > 50% rule) ──
    lower_winner_user_id        = Column(Integer, nullable=False)   # soft FK → users.id
    lower_winner_level          = Column(Integer, nullable=False)
    lower_payout_inr            = Column(Numeric(12, 2), nullable=False)
    lower_winner_tier_override  = Column(Boolean, default=False, nullable=False)

    # Cryptographic audit trail — SHA-256 hex digest
    rng_seed_hash = Column(String(64), nullable=False)

    completed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Bug #9 — two-phase SDE commit flag.
    # False (default) = staged at T-2H: winners selected, checkpoint written, pool
    #   locked (draw_completed_this_week=True), but NO WIT tokens, NO status change,
    #   NO DrawHistory, NO survivor advancement yet.
    # True = executed at T-0H: execute_staged_sde_draws() has committed the full
    #   exit (tokens issued, Eliminated_Won, DrawHistory written, survivors advanced).
    # Production migration: ALTER TABLE sde_checkpoints
    #   ADD COLUMN IF NOT EXISTS executed BOOLEAN NOT NULL DEFAULT FALSE;
    executed = Column(Boolean, nullable=False, server_default="false", default=False)
    # SESSION EDIT [Claude Session Jun-14 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Case C — Meta Pool cross-pool supply transfer audit trail.
    # case_c_transfer=True  → lower winner was transferred from a donor pool.
    # case_c_donor_pool_id  → source pool the lower winner came FROM (soft FK → pools.id).
    # Execute_staged_sde_draws() uses case_c_transfer to set draw_type=POOL_DRAW_SDE_CASE_C
    # and edge_case_triggered=True in the DrawHistory row for full financial audit trail.
    # Production migration:
    #   ALTER TABLE sde_checkpoints ADD COLUMN IF NOT EXISTS case_c_transfer BOOLEAN NOT NULL DEFAULT FALSE;
    #   ALTER TABLE sde_checkpoints ADD COLUMN IF NOT EXISTS case_c_donor_pool_id INTEGER;
    case_c_transfer      = Column(Boolean, nullable=False, server_default="false", default=False)
    case_c_donor_pool_id = Column(Integer, nullable=True)
