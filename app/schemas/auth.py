from pydantic import BaseModel, Field
from typing import Optional


# ── User registration & login ──────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    name:              str
    mobile:            str
    username:          str
    password:          str = Field(min_length=6)
    deposit_token:     str = Field(description="Active DEP-XXXXXX token code")
    referred_by_username: Optional[str] = None


class UserLoginRequest(BaseModel):
    username: str
    password: str


class UserJWTResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         dict                   # full UserResponse serialised as dict


# ── Step 1: Admin password login ───────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    temp_token: str
    message: str


# ── Step 2: OTP verification ───────────────────────────────────────────────────

class AdminOTPRequest(BaseModel):
    temp_token: str
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class AdminJWTResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin_username: str


# ── One-time setup ─────────────────────────────────────────────────────────────

class AdminSetupRequest(BaseModel):
    username: str
    password: str = Field(min_length=8)
    telegram_chat_id: str          # numeric Telegram user ID as string
    setup_secret: str              # must match ADMIN_SETUP_SECRET env var
