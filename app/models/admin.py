from sqlalchemy import Column, Integer, String, Boolean
from app.database import Base


class Admin(Base):
    """
    Stores admin credentials.  Only one admin account is expected for v1.
    Created via POST /admin/auth/setup (one-time, when the table is empty).
    """
    __tablename__ = "admins"

    id               = Column(Integer, primary_key=True, index=True)
    username         = Column(String, unique=True, nullable=False, index=True)
    hashed_password  = Column(String, nullable=False)
    telegram_chat_id = Column(String, nullable=False)   # e.g. "123456789"
    is_active        = Column(Boolean, default=True, nullable=False, server_default="true")
