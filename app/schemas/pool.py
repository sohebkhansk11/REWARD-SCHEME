from pydantic import BaseModel
from typing import Optional
from app.models.pool import PoolStatus


class PoolBase(BaseModel):
    name: str
    status: PoolStatus = PoolStatus.Waiting
    total_members: int = 0


class PoolCreate(PoolBase):
    pass


class PoolUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[PoolStatus] = None
    total_members: Optional[int] = None


class PoolResponse(PoolBase):
    id: int

    model_config = {"from_attributes": True}
