import enum
from sqlalchemy import Column, Integer, String, Enum
from sqlalchemy.orm import relationship
from app.database import Base


class PoolStatus(str, enum.Enum):
    Active = "Active"
    Full = "Full"
    Waiting = "Waiting"


class Pool(Base):
    __tablename__ = "pools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    status = Column(Enum(PoolStatus), default=PoolStatus.Waiting, nullable=False)
    total_members = Column(Integer, default=0, nullable=False)

    members = relationship("User", back_populates="pool")
