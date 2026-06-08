"""
Admin Authentication Router
============================

POST /admin/auth/setup        — one-time: create the first admin account + get TOTP QR
POST /admin/auth/login        — Step 1: password check → temp_token (no external calls)
POST /admin/auth/verify-otp   — Step 2: TOTP code from authenticator app → final JWT
GET  /admin/auth/me           — validate JWT, return admin info

2FA method: TOTP (RFC 6238) — Google Authenticator / Authy / any TOTP app.
No Telegram bot token.  No external API calls.  No secrets in hosting env vars
beyond ADMIN_JWT_SECRET and ADMIN_SETUP_SECRET.
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
    AdminSetupResponse,
)
from app.services.auth import (
    hash_password,
    verify_password,
    generate_totp_secret,
    get_totp_uri,
    verify_totp,
    create_login_session,
    consume_login_session,
    create_jwt,
)
from app.core.security import require_admin_jwt

router = APIRouter(prefix="/admin/auth", tags=["Admin Auth"])


# ── One-time setup ─────────────────────────────────────────────────────────────

@router.post("/setup", response_model=AdminSetupResponse, status_code=201)
def setup_admin(body: AdminSetupRequest, db: Session = Depends(get_db)):
    """
    Create the first Admin account and return the TOTP QR URI.

    Requirements:
    - `setup_secret` must match the ADMIN_SETUP_SECRET environment variable.
    - The `admins` table must be empty (returns 409 otherwise).

    The response includes:
    - `totp_uri`    — scan with Google Authenticator / Authy to add the account
    - `totp_secret` — 32-char base32 string; use "Enter setup key" in your app
                      if QR scanning is not available

    Call this once after first deploy.  Calling it again returns 409 Conflict.
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

    totp_secret = generate_totp_secret()

    admin = Admin(
        username=body.username,
        hashed_password=hash_password(body.password),
        totp_secret=totp_secret,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    return AdminSetupResponse(
        totp_uri=get_totp_uri(totp_secret, body.username),
        totp_secret=totp_secret,
        message=(
            "Admin account created. "
            "Scan the totp_uri with Google Authenticator or Authy, "
            "or add the totp_secret manually via 'Enter a setup key'."
        ),
    )


# ── Step 1: Password → session token ──────────────────────────────────────────

@router.post("/login", response_model=AdminLoginResponse)
def login(body: AdminLoginRequest, db: Session = Depends(get_db)):
    """
    Verify username + password.
    On success, return a short-lived `temp_token` valid for 5 minutes.
    No external calls — the admin will supply the TOTP code from their app.
    """
    admin: Admin | None = (
        db.query(Admin)
        .filter(Admin.username == body.username, Admin.is_active == True)   # noqa: E712
        .first()
    )

    # Constant-time: always call verify_password even on miss
    dummy_hash = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    stored_hash = admin.hashed_password if admin else dummy_hash
    password_ok = verify_password(body.password, stored_hash)

    if not admin or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    temp_token = create_login_session(admin.id, admin.username)

    return AdminLoginResponse(
        temp_token=temp_token,
        message="Password verified. Open your authenticator app and enter the 6-digit code.",
    )


# ── Step 2: TOTP → final JWT ───────────────────────────────────────────────────

@router.post("/verify-otp", response_model=AdminJWTResponse)
def verify_otp(body: AdminOTPRequest, db: Session = Depends(get_db)):
    """
    Validate the `temp_token` + 6-digit TOTP code from the authenticator app.
    On success, return an 8-hour admin JWT.
    """
    try:
        admin_username = consume_login_session(body.temp_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    admin: Admin | None = (
        db.query(Admin)
        .filter(Admin.username == admin_username, Admin.is_active == True)   # noqa: E712
        .first()
    )
    if not admin:
        raise HTTPException(status_code=401, detail="Admin account not found.")

    if not verify_totp(admin.totp_secret, body.otp):
        raise HTTPException(
            status_code=401,
            detail="Invalid authenticator code. Codes refresh every 30 seconds.",
        )

    return AdminJWTResponse(
        access_token=create_jwt(admin.username),
        admin_username=admin.username,
    )


# ── Token introspection ────────────────────────────────────────────────────────

@router.get("/me")
def get_me(admin_username: str = Depends(require_admin_jwt)):
    """Return the currently authenticated admin username. Useful as a heartbeat check."""
    return {"admin_username": admin_username, "authenticated": True}
