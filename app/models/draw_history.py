from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func
from app.database import Base


class DrawHistory(Base):
    __tablename__ = "draw_history"

    id                  = Column(Integer, primary_key=True, index=True)
    pool_id             = Column(Integer, ForeignKey("pools.id"), nullable=False, index=True)
    draw_timestamp      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    edge_case_triggered = Column(Boolean, default=False, nullable=False)

    # Winner 1 — core payout fields
    winner_1_user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner_1_level      = Column(Integer, nullable=False)
    winner_1_net_payout = Column(Numeric(12, 2), nullable=False)

    # Winner 1 — journey provenance (from User.* at time of draw)
    winner_1_total_deposited    = Column(Integer, default=1000, nullable=False)
    winner_1_merges_experienced = Column(Integer, default=0,    nullable=False)
    winner_1_pauses_experienced = Column(Integer, default=0,    nullable=False)
    winner_1_journey_type       = Column(String(20), default="direct", nullable=False)  # 'direct' | 'merged'

    # Winner 2 — core payout fields
    winner_2_user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner_2_level      = Column(Integer, nullable=False)
    winner_2_net_payout = Column(Numeric(12, 2), nullable=False)

    # Winner 2 — journey provenance
    winner_2_total_deposited    = Column(Integer, default=1000, nullable=False)
    winner_2_merges_experienced = Column(Integer, default=0,    nullable=False)
    winner_2_pauses_experienced = Column(Integer, default=0,    nullable=False)
    winner_2_journey_type       = Column(String(20), default="direct", nullable=False)

    # ── Draw classification & SDE provenance ─────────────────────────────────
    # draw_type: routing bucket this pool was processed under.
    #   One of: 'regular' | 'type_a' | 'sde' | 'type_b'
    # targeted_early_exit: TRUE when winner_1 is an L4 member exiting via SDE.
    #   Surfaces the "[TARGETED EARLY EXIT]" badge in the admin draw history view.
    # sde_session_id: FK to sde_sessions.id — populated for SDE draws only.
    #   NULL for regular / Type A / Type B draws.
    draw_type           = Column(String(20), nullable=True)
    targeted_early_exit = Column(Boolean, default=False, nullable=False)
    sde_session_id      = Column(Integer, nullable=True)   # soft FK — no FK constraint (cross-table perf)
