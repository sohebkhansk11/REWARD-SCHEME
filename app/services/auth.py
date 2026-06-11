"""
Authentication service
======================
Password hashing      — bcrypt (12 rounds), direct library, no passlib
Admin 2FA             — TOTP (RFC 6238), pyotp, Google Authenticator / Authy
Admin JWT             — python-jose HS256, 8-hour TTL  (ADMIN_JWT_SECRET)
User JWT              — python-jose HS256, 30-day TTL  (USER_JWT_SECRET)

No external API calls.  No bot tokens.  No third-party services.

Login flow:
  Step 1 — verify username + password → create short-lived session → temp_token
  Step 2 — admin opens their authenticator app, submits 6-digit code
            verify code against stored totp_secret → issue final JWT

Setup flow (one-time):
  generate_totp_secret() → base32 string  (store in Admin.totp_secret)
  get_totp_uri()         → otpauth:// URI (admin scans with authenticator app)
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
import pyotp
from jose import jwt, JWTError


# ── Constants ──────────────────────────────────────────────────────────────────

_ALGORITHM         = "HS256"
_JWT_EXPIRE_H      = 8     # admin JWT  — 8 hours
_USER_JWT_EXPIRE_D = 30    # user JWT   — 30 days (mobile app: long session)
_SESSION_EXPIRE_M  = 5     # temp login session between step 1 and step 2


# ── Password helpers (direct bcrypt — no passlib dependency) ───────────────────

def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (12 rounds)."""
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt check. Safe to call even with a dummy hash."""
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── TOTP helpers (no external service required) ────────────────────────────────

def generate_totp_secret() -> str:
    """
    Generate a cryptographically random base32 TOTP secret.
    Store this in Admin.totp_secret at setup time.
    """
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str) -> str:
    """
    Return the otpauth:// URI for QR code generation.
    Admin scans this once with Google Authenticator / Authy.
    """
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name="RewardScheme Admin")


def verify_totp(secret: str, code: str) -> bool:
    """
    Verify a 6-digit TOTP code against the stored secret.
    valid_window=1 allows ±30 seconds of clock drift (industry standard).
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code.strip(), valid_window=1)


# ── Login session (in-process, 5-minute TTL between step 1 and step 2) ────────
# Maps temp_token → {admin_id, admin_username, expires_at}
# No OTP is stored here — the authenticator app holds the secret independently.

_session_store: dict[str, dict] = {}


def create_login_session(admin_id: int, admin_username: str) -> str:
    """
    Called after password is verified (step 1).
    Revokes any prior pending session for this admin, then creates a new one.
    Returns a cryptographically random temp_token.
    """
    for key, val in list(_session_store.items()):
        if val["admin_id"] == admin_id:
            del _session_store[key]

    temp_token = secrets.token_urlsafe(32)
    _session_store[temp_token] = {
        "admin_id":       admin_id,
        "admin_username": admin_username,
        "expires_at":     datetime.now(timezone.utc) + timedelta(minutes=_SESSION_EXPIRE_M),
    }
    return temp_token


def consume_login_session(temp_token: str) -> str:
    """
    Called when the TOTP code is submitted (step 2).
    Validates the session is still within the 5-minute window,
    destroys it (single-use), and returns admin_username.
    Raises ValueError on any failure.
    """
    entry = _session_store.get(temp_token)
    if not entry:
        raise ValueError("Session expired or invalid. Please log in again.")

    if datetime.now(timezone.utc) > entry["expires_at"]:
        del _session_store[temp_token]
        raise ValueError("Session timed out. Please log in again.")

    username = entry["admin_username"]
    del _session_store[temp_token]   # single-use: destroy on success
    return username


# ── Admin JWT (ADMIN_JWT_SECRET, 8-hour TTL) ──────────────────────────────────

def _admin_jwt_secret() -> str:
    s = os.getenv("ADMIN_JWT_SECRET")
    if not s:
        raise RuntimeError("ADMIN_JWT_SECRET is not set in environment variables.")
    return s


def create_jwt(admin_username: str) -> str:
    payload = {
        "sub":  admin_username,
        "type": "admin_access",   # internal type guard — validated in decode_jwt
        "role": "admin",          # spec-compliant field (#149)
        "exp":  datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRE_H),
    }
    return jwt.encode(payload, _admin_jwt_secret(), algorithm=_ALGORITHM)


def decode_jwt(token: str) -> str:
    """Decode and validate an admin JWT. Returns admin_username or raises JWTError."""
    payload = jwt.decode(token, _admin_jwt_secret(), algorithms=[_ALGORITHM])
    sub: str | None = payload.get("sub")
    if not sub or payload.get("type") != "admin_access":
        raise JWTError("Token payload is invalid.")
    return sub


# ── User JWT (USER_JWT_SECRET, 30-day TTL) ────────────────────────────────────

def _user_jwt_secret() -> str:
    s = os.getenv("USER_JWT_SECRET")
    if not s:
        raise RuntimeError("USER_JWT_SECRET is not set in environment variables.")
    return s


def create_user_jwt(user_id: int) -> str:
    payload = {
        "sub":  str(user_id),
        "type": "user_access",
        "exp":  datetime.now(timezone.utc) + timedelta(days=_USER_JWT_EXPIRE_D),
    }
    return jwt.encode(payload, _user_jwt_secret(), algorithm=_ALGORITHM)


def decode_user_jwt(token: str) -> int:
    """Decode a user JWT. Returns user_id (int) or raises JWTError."""
    payload = jwt.decode(token, _user_jwt_secret(), algorithms=[_ALGORITHM])
    sub: str | None = payload.get("sub")
    if not sub or payload.get("type") != "user_access":
        raise JWTError("Token payload is invalid.")
    return int(sub)
