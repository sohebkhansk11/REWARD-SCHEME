from pydantic import BaseModel, Field
from typing import Optional


# ── User registration & login ──────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    name:          str
    mobile:        str
    username:      str
    password:      str = Field(min_length=6)
    deposit_token: str = Field(description="Active DEP-XXXXXX token code")
    # 8-char referral code from an existing user's invite link.
    # Blank / omitted = no referral.  Validated against users.referral_code column.
    referred_by_code: Optional[str] = None


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
    username:     str
    password:     str = Field(min_length=8)
    setup_secret: str              # must match ADMIN_SETUP_SECRET env var


class AdminSetupResponse(BaseModel):
    totp_uri:    str   # otpauth:// URI — scan with Google Authenticator / Authy
    totp_secret: str   # base32 secret — for manual entry if QR scan fails
    message:     str


# ── User profile management ────────────────────────────────────────────────────

class UserProfileUpdate(BaseModel):
    """Only name and mobile may be changed. Username is immutable."""
    name:   Optional[str] = None
    mobile: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class RejoinRequest(BaseModel):
    deposit_token: str = Field(description="Active DEP-XXXXXX token for re-entry")
