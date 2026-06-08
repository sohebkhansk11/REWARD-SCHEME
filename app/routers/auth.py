"""
Admin Authentication Router
============================

POST /admin/auth/setup        — one-time: create the first admin account
POST /admin/auth/login        — Step 1: password check → Telegram OTP
POST /admin/auth/verify-otp   — Step 2: OTP check → final JWT
GET  /admin/auth/me           — validate JWT, return admin info
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.schemas.auth import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminOTPRequest,
    AdminJWTResponse,
    AdminSetupRequest,
)
from app.services.auth import (
    hash_password,
    verify_password,
    generate_otp,
    consume_otp,
    create_jwt,
    send_telegram_otp,
)
from app.core.security import require_admin_jwt

router = APIRouter(prefix="/admin/auth", tags=["Admin Auth"])


# ── One-time setup ─────────────────────────────────────────────────────────────

@router.post("/setup", response_model=AdminJWTResponse, status_code=201)
async def setup_admin(body: AdminSetupRequest, db: Session = Depends(get_db)):
    """
    Create the first (and only) Admin account.

    Requirements:
    - `setup_secret` must match the ADMIN_SETUP_SECRET environment variable.
    - The `admins` table must be empty (returns 409 otherwise).

    Call this once after first deploy, then remove/guard the endpoint.
    """
    expected_secret = os.getenv("ADMIN_SETUP_SECRET", "")
    if not expected_secret:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_SETUP_SECRET is not configured on the server.",
        )
    if body.setup_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid setup secret.")

    if db.query(Admin).count() > 0:
        raise HTTPException(
            status_code=409,
            detail="An admin account already exists. Use POST /admin/auth/login.",
        )

    admin = Admin(
        username=body.username,
        hashed_password=hash_password(body.password),
        telegram_chat_id=body.telegram_chat_id,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    return AdminJWTResponse(
        access_token=create_jwt(admin.username),
        admin_username=admin.username,
    )


# ── Step 1: Password → OTP ─────────────────────────────────────────────────────

@router.post("/login", response_model=AdminLoginResponse)
async def login(body: AdminLoginRequest, db: Session = Depends(get_db)):
    """
    Verify username + password.  If correct, generate a 6-digit OTP,
    send it to the admin's registered Telegram chat, and return a
    short-lived `temp_token` for Step 2.
    """
    admin: Admin | None = (
        db.query(Admin)
        .filter(Admin.username == body.username, Admin.is_active == True)   # noqa: E712
        .first()
    )

    # Constant-time-safe: always call verify_password even on miss
    dummy_hash = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    stored_hash = admin.hashed_password if admin else dummy_hash
    password_ok = verify_password(body.password, stored_hash)

    if not admin or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    temp_token, otp = generate_otp(admin.id, admin.username)

    try:
        await send_telegram_otp(admin.telegram_chat_id, otp, admin.username)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not deliver OTP via Telegram: {exc}",
        )

    return AdminLoginResponse(
        temp_token=temp_token,
        message="OTP sent to your registered Telegram. It expires in 5 minutes.",
    )


# ── Step 2: OTP → final JWT ────────────────────────────────────────────────────

@router.post("/verify-otp", response_model=AdminJWTResponse)
def verify_otp(body: AdminOTPRequest):
    """
    Validate the `temp_token` + 6-digit `otp`.
    On success, return an 8-hour admin JWT.
    """
    try:
        admin_username = consume_otp(body.temp_token, body.otp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    return AdminJWTResponse(
        access_token=create_jwt(admin_username),
        admin_username=admin_username,
    )


# ── Token introspection ────────────────────────────────────────────────────────

@router.get("/me")
def get_me(admin_username: str = Depends(require_admin_jwt)):
    """Return the currently authenticated admin username. Useful as a heartbeat check."""
    return {"admin_username": admin_username, "authenticated": True}
