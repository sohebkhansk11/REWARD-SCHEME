from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.crud import user as crud_user

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=list[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    mobile: Optional[str] = None,
    username: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if mobile:
        user = crud_user.get_user_by_mobile(db, mobile)
        return [user] if user else []
    if username:
        user = crud_user.get_user_by_username(db, username)
        return [user] if user else []
    return crud_user.get_users(db, skip=skip, limit=limit)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    if crud_user.get_user_by_mobile(db, user.mobile):
        raise HTTPException(status_code=400, detail="Mobile number already registered")
    if user.username and crud_user.get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    return crud_user.create_user(db, user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, user: UserUpdate, db: Session = Depends(get_db)):
    if user.username:
        existing = crud_user.get_user_by_username(db, user.username)
        if existing and existing.id != user_id:
            raise HTTPException(status_code=400, detail="Username already taken")
    updated = crud_user.update_user(db, user_id, user)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.delete("/{user_id}", response_model=UserResponse)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    deleted = crud_user.delete_user(db, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return deleted
