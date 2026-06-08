from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.token import TokenCreate, TokenUpdate, TokenResponse
from app.crud import token as crud_token

router = APIRouter(prefix="/tokens", tags=["Tokens"])


@router.get("/", response_model=list[TokenResponse])
def list_tokens(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud_token.get_tokens(db, skip=skip, limit=limit)


@router.get("/user/{user_id}", response_model=list[TokenResponse])
def get_tokens_by_user(user_id: int, db: Session = Depends(get_db)):
    return crud_token.get_tokens_by_user(db, user_id)


@router.get("/{token_id}", response_model=TokenResponse)
def get_token(token_id: int, db: Session = Depends(get_db)):
    token = crud_token.get_token(db, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    return token


@router.post("/", response_model=TokenResponse, status_code=201)
def create_token(token: TokenCreate, db: Session = Depends(get_db)):
    if crud_token.get_token_by_code(db, token.code):
        raise HTTPException(status_code=400, detail="Token code already exists")
    return crud_token.create_token(db, token)


@router.patch("/{token_id}", response_model=TokenResponse)
def update_token(token_id: int, token: TokenUpdate, db: Session = Depends(get_db)):
    updated = crud_token.update_token(db, token_id, token)
    if not updated:
        raise HTTPException(status_code=404, detail="Token not found")
    return updated


@router.delete("/{token_id}", response_model=TokenResponse)
def delete_token(token_id: int, db: Session = Depends(get_db)):
    deleted = crud_token.delete_token(db, token_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Token not found")
    return deleted
