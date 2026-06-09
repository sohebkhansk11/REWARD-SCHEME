import enum
from sqlalchemy import Column, Integer, String, DateTime, Enum
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

    members = relationship("User", back_populates="pool")
