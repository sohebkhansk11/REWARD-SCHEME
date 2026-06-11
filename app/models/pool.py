import enum
from sqlalchemy import Boolean, Column, Integer, String, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class PoolStatus(str, enum.Enum):
    Active = "Active"
    Full = "Full"
    Waiting = "Waiting"
    Paused_Awaiting_Members = "Paused_Awaiting_Members"
    Merged_Dissolved = "Merged_Dissolved"


class Pool(Base):
    __tablename__ = "pools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    status = Column(Enum(PoolStatus), default=PoolStatus.Waiting, nullable=False)
    total_members = Column(Integer, default=0, nullable=False)
    # Timestamp used for FIFO pool-fill ordering (oldest pool gets vacancies filled first)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ── Draw-cycle tracking ───────────────────────────────────────────────────
    # draw_completed_this_week: TRUE after this pool's winners have been selected
    #   this cycle (SDE pre-draw or live draw).  Prevents double-draw.
    #   Reset to FALSE by post_draw_cleanup() at T+0H:05.
    # pool_draw_type: the routing decision made at T-2H preparation.
    #   One of: 'regular' | 'type_a' | 'sde' | 'type_b' | NULL (not yet decided)
    # contains_flagged_l4: TRUE when ≥1 member in this pool has sde_required=TRUE.
    #   Set synchronously alongside the member's sde_required flag.
    #   Drives condensation immunity and SDE routing.
    draw_completed_this_week = Column(Boolean, default=False, server_default="false", nullable=False)
    pool_draw_type           = Column(String(20), nullable=True)
    contains_flagged_l4      = Column(Boolean, default=False, server_default="false", nullable=False)

    members = relationship("User", back_populates="pool")
