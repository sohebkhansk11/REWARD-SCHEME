"""
Authentication service
======================
- Password hashing via passlib / bcrypt
- Temporary OTP generation + in-memory storage (single-use, 5-minute TTL)
- Telegram OTP delivery via Bot API (async httpx)
- Final Admin JWT creation + decoding (python-jose, HS256, 8-hour TTL)

NOTE: The OTP store is in-process memory.  If the Render free tier restarts
the worker between Step-1 and Step-2, the admin simply retries the login.
A Redis store is the production-grade upgrade path.
"""

import os
import secrets
import random
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
import httpx
from jose import jwt, JWTError


# ── Constants ──────────────────────────────────────────────────────────────────

_ALGORITHM       = "HS256"
_JWT_EXPIRE_H    = 8        # hours until the final JWT expires
_OTP_EXPIRE_MIN  = 5        # minutes until the temp OTP expires

# temp_token → {otp, admin_id, admin_username, expires_at}
_otp_store: dict[str, dict] = {}


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


# ── JWT helpers ────────────────────────────────────────────────────────────────

def _jwt_secret() -> str:
    s = os.getenv("ADMIN_JWT_SECRET")
    if not s:
        raise RuntimeError("ADMIN_JWT_SECRET is not set in environment variables.")
    return s


def create_jwt(admin_username: str) -> str:
    payload = {
        "sub":  admin_username,
        "type": "admin_access",
        "exp":  datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRE_H),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_ALGORITHM)


def decode_jwt(token: str) -> str:
    """Decode and validate an admin JWT. Returns admin_username or raises JWTError."""
    payload = jwt.decode(token, _jwt_secret(), algorithms=[_ALGORITHM])
    sub: str | None = payload.get("sub")
    if not sub or payload.get("type") != "admin_access":
        raise JWTError("Token payload is invalid.")
    return sub


# ── OTP helpers ────────────────────────────────────────────────────────────────

def generate_otp(admin_id: int, admin_username: str) -> tuple[str, str]:
    """
    Create a random 6-digit OTP and a cryptographically random temp_token.
    Stores them in the in-memory OTP store.
    Returns (temp_token, otp).
    """
    # Revoke any previous pending OTP for this admin (prevents flooding)
    for key, val in list(_otp_store.items()):
        if val["admin_id"] == admin_id:
            del _otp_store[key]

    temp_token = secrets.token_urlsafe(32)
    otp        = str(random.randint(100_000, 999_999))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_OTP_EXPIRE_MIN)

    _otp_store[temp_token] = {
        "otp":            otp,
        "admin_id":       admin_id,
        "admin_username": admin_username,
        "expires_at":     expires_at,
    }
    return temp_token, otp


def consume_otp(temp_token: str, otp: str) -> str:
    """
    Validate the OTP for the given temp_token.
    Deletes the entry on success (single-use) or expiry.
    Returns admin_username on success; raises ValueError on failure.
    """
    entry = _otp_store.get(temp_token)
    if not entry:
        raise ValueError("Invalid or expired session token. Please log in again.")

    if datetime.now(timezone.utc) > entry["expires_at"]:
        del _otp_store[temp_token]
        raise ValueError(f"OTP expired. Please log in again.")

    if entry["otp"] != otp.strip():
        raise ValueError("Incorrect OTP. Please try again.")

    username = entry["admin_username"]
    del _otp_store[temp_token]   # single-use: destroy after successful verification
    return username


# ── Telegram delivery ──────────────────────────────────────────────────────────

async def send_telegram_otp(chat_id: str, otp: str, admin_username: str) -> None:
    """
    Send the 6-digit OTP to the admin's Telegram chat via the Bot API.
    Raises RuntimeError on any failure.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment variables.")

    message = (
        f"🔐 *Reward Scheme Admin*\n\n"
        f"Login attempt detected for account `{admin_username}`.\n\n"
        f"Your one-time OTP is:\n\n"
        f"*{otp}*\n\n"
        f"⏰ Expires in {_OTP_EXPIRE_MIN} minutes.\n"
        f"🚫 Do *not* share this code with anyone."
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "Markdown",
        })

    if resp.status_code != 200:
        raise RuntimeError(
            f"Telegram API returned {resp.status_code}: {resp.text}"
        )
