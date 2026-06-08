from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.pool import PoolCreate, PoolUpdate, PoolResponse
from app.crud import pool as crud_pool

router = APIRouter(prefix="/pools", tags=["Pools"])


@router.get("/", response_model=list[PoolResponse])
def list_pools(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud_pool.get_pools(db, skip=skip, limit=limit)


@router.get("/{pool_id}", response_model=PoolResponse)
def get_pool(pool_id: int, db: Session = Depends(get_db)):
    pool = crud_pool.get_pool(db, pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")
    return pool


@router.post("/", response_model=PoolResponse, status_code=201)
def create_pool(pool: PoolCreate, db: Session = Depends(get_db)):
    if crud_pool.get_pool_by_name(db, pool.name):
        raise HTTPException(status_code=400, detail="Pool name already exists")
    return crud_pool.create_pool(db, pool)


@router.patch("/{pool_id}", response_model=PoolResponse)
def update_pool(pool_id: int, pool: PoolUpdate, db: Session = Depends(get_db)):
    updated = crud_pool.update_pool(db, pool_id, pool)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool not found")
    return updated


@router.delete("/{pool_id}", response_model=PoolResponse)
def delete_pool(pool_id: int, db: Session = Depends(get_db)):
    deleted = crud_pool.delete_pool(db, pool_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pool not found")
    return deleted
