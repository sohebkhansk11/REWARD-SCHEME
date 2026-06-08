from sqlalchemy.orm import Session
from app.models.pool import Pool
from app.schemas.pool import PoolCreate, PoolUpdate


def get_pool(db: Session, pool_id: int) -> Pool | None:
    return db.query(Pool).filter(Pool.id == pool_id).first()


def get_pool_by_name(db: Session, name: str) -> Pool | None:
    return db.query(Pool).filter(Pool.name == name).first()


def get_pools(db: Session, skip: int = 0, limit: int = 100) -> list[Pool]:
    return db.query(Pool).offset(skip).limit(limit).all()


def create_pool(db: Session, pool: PoolCreate) -> Pool:
    db_pool = Pool(**pool.model_dump())
    db.add(db_pool)
    db.commit()
    db.refresh(db_pool)
    return db_pool


def update_pool(db: Session, pool_id: int, pool: PoolUpdate) -> Pool | None:
    db_pool = get_pool(db, pool_id)
    if not db_pool:
        return None
    for key, value in pool.model_dump(exclude_unset=True).items():
        setattr(db_pool, key, value)
    db.commit()
    db.refresh(db_pool)
    return db_pool


def delete_pool(db: Session, pool_id: int) -> Pool | None:
    db_pool = get_pool(db, pool_id)
    if not db_pool:
        return None
    db.delete(db_pool)
    db.commit()
    return db_pool
