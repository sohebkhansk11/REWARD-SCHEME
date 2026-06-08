from sqlalchemy.orm import Session
from app.models.token import Token
from app.schemas.token import TokenCreate, TokenUpdate


def get_token(db: Session, token_id: int) -> Token | None:
    return db.query(Token).filter(Token.id == token_id).first()


def get_token_by_code(db: Session, code: str) -> Token | None:
    return db.query(Token).filter(Token.code == code).first()


def get_tokens(db: Session, skip: int = 0, limit: int = 100) -> list[Token]:
    return db.query(Token).offset(skip).limit(limit).all()


def get_tokens_by_user(db: Session, user_id: int) -> list[Token]:
    return db.query(Token).filter(Token.user_id == user_id).all()


def create_token(db: Session, token: TokenCreate) -> Token:
    db_token = Token(**token.model_dump())
    db.add(db_token)
    db.commit()
    db.refresh(db_token)
    return db_token


def update_token(db: Session, token_id: int, token: TokenUpdate) -> Token | None:
    db_token = get_token(db, token_id)
    if not db_token:
        return None
    for key, value in token.model_dump(exclude_unset=True).items():
        setattr(db_token, key, value)
    db.commit()
    db.refresh(db_token)
    return db_token


def delete_token(db: Session, token_id: int) -> Token | None:
    db_token = get_token(db, token_id)
    if not db_token:
        return None
    db.delete(db_token)
    db.commit()
    return db_token
