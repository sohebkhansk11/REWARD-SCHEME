from sqlalchemy import Column, Integer, String, Boolean
from app.database import Base


class Admin(Base):
    """
    Stores admin credentials.  Only one admin account is expected for v1.
    Created via POST /admin/auth/setup (one-time, when the table is empty).

    2FA uses TOTP (RFC 6238 — Google Authenticator / Authy compatible).
    The base32 `totp_secret` is generated once during setup and stored here.
    No external service or API key is required — verification happens entirely
    inside the process using pyotp.
    """
    __tablename__ = "admins"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    totp_secret     = Column(String, nullable=False)   # base32 TOTP secret (RFC 6238)
    is_active       = Column(Boolean, default=True, nullable=False, server_default="true")
