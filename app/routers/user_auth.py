"""
User Authentication Router
===========================

POST /auth/register   — Name + Mobile + Username + Password + Deposit Token
POST /auth/login      — Username + Password → JWT
GET  /auth/me         — Return current user's profile (requires user JWT)

Registration atomically:
  1. Validates the Deposit Token (must be active DEP-XXXXXX, value = ₹1,000).
  2. Resolves optional referral username → referred_by_user_id.
  3. Creates the User (status=Waitlist, weekly_payment=Paid).
  4. Burns the Deposit Token and assigns it to the new user.
  5. Triggers the Waitlist auto-scaling check in the background.
  6. Returns a 30-day User JWT.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.token import Token, TokenType, TokenStatus
from app.schemas.auth import (
    UserRegisterRequest, UserLoginRequest, UserJWTResponse,
    UserProfileUpdate, ChangePasswordRequest, RejoinRequest,
)
from app.schemas.user import UserResponse
from app.crud import user as crud_user, token as crud_token
from app.services.auth import hash_password, verify_password, create_user_jwt
from app.services.waitlist import check_and_scale_waitlist
from app.core.security import require_user_jwt
from app.core.config import DEPOSIT_AMOUNT_INR

router = APIRouter(prefix="/auth", tags=["User Auth"])


def _serialize_user(user: User) -> dict:
    return UserResponse.model_validate(user).model_dump(mode="json")


# ── Register ───────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserJWTResponse, status_code=201)
def register(
    body: UserRegisterRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Create a new user account.  A valid Deposit Token is required — it serves
    as the ₹1,000 entry fee that places the user on the Waitlist.
    """
    # 1. Validate the Deposit Token before touching the user table
    token: Token | None = crud_token.get_token_by_code(db, body.deposit_token)
    if not token:
        raise HTTPException(status_code=400, detail="Deposit token not found.")
    if token.type != TokenType.Deposit:
        raise HTTPException(status_code=400, detail="Only Deposit tokens (DEP-...) are accepted.")
    if token.status != TokenStatus.Active:
        raise HTTPException(status_code=400, detail="This deposit token has already been used.")
    if float(token.value_inr) != float(DEPOSIT_AMOUNT_INR):
        raise HTTPException(
            status_code=400,
            detail=f"Token face value must be ₹{DEPOSIT_AMOUNT_INR}."
        )

    # 2. Check uniqueness
    if crud_user.get_user_by_mobile(db, body.mobile):
        raise HTTPException(status_code=400, detail="Mobile number already registered.")
    if crud_user.get_user_by_username(db, body.username):
        raise HTTPException(status_code=400, detail="Username already taken.")

    # 3. Resolve referral
    referred_by_id: int | None = None
    if body.referred_by_username:
        referrer = crud_user.get_user_by_username(db, body.referred_by_username)
        if not referrer:
            raise HTTPException(status_code=400, detail="Referral username not found.")
        referred_by_id = referrer.id

    # 4. Create user (Waitlist + Paid — the deposit token covers week 1)
    new_user = User(
        name=body.name,
        mobile=body.mobile,
        username=body.username,
        hashed_password=hash_password(body.password),
        status=UserStatus.Waitlist,
        weekly_payment_status=WeeklyPaymentStatus.Paid,
        current_level=1,
        referred_by_user_id=referred_by_id,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 5. Burn the deposit token — stamp the full audit trail
    now = datetime.now(timezone.utc)
    token.user_id             = new_user.id
    token.status              = TokenStatus.Burned
    token.redeemed_at         = now
    token.redeemed_by_user_id = new_user.id
    db.commit()
    db.refresh(new_user)

    # 6. Check if waitlist has hit 24 paid members (non-blocking)
    # NOTE: Referral bonus (₹250) is credited to the referrer when the new user
    # ENTERS AN ACTIVE POOL — not at registration.  See waitlist.py and draw.py.
    background_tasks.add_task(check_and_scale_waitlist, db)

    access_token = create_user_jwt(new_user.id)
    return UserJWTResponse(access_token=access_token, user=_serialize_user(new_user))


# ── Login ──────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=UserJWTResponse)
def login(body: UserLoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with username + password.
    Returns a 30-day JWT and the user's current profile.
    """
    user: User | None = crud_user.get_user_by_username(db, body.username)

    # Constant-time: always call verify_password even on miss
    _dummy = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    stored = user.hashed_password if (user and user.hashed_password) else _dummy
    ok = verify_password(body.password, stored)

    if not user or not ok:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if user.status in (UserStatus.Eliminated,):
        raise HTTPException(
            status_code=403,
            detail="Your account has been eliminated. Contact the admin.",
        )

    access_token = create_user_jwt(user.id)
    return UserJWTResponse(access_token=access_token, user=_serialize_user(user))


# ── Me ─────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserJWTResponse)
def get_me(
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """
    Return the latest profile for the authenticated user.
    Call this on app start to refresh stale cached data.
    """
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    # Re-issue token so the 30-day window slides on active use
    access_token = create_user_jwt(user.id)
    return UserJWTResponse(access_token=access_token, user=_serialize_user(user))


# ── Update profile (name + mobile only — username is immutable) ───────────────

@router.patch("/profile", response_model=UserJWTResponse)
def update_profile(
    body: UserProfileUpdate,
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """Update name and/or mobile number. Username cannot be changed."""
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    if body.mobile and body.mobile != user.mobile:
        if crud_user.get_user_by_mobile(db, body.mobile):
            raise HTTPException(status_code=400, detail="Mobile number already in use.")

    if body.name is not None:
        user.name = body.name.strip()
    if body.mobile is not None:
        user.mobile = body.mobile.strip()

    db.commit()
    db.refresh(user)
    return UserJWTResponse(access_token=create_user_jwt(user.id), user=_serialize_user(user))


# ── Change password ────────────────────────────────────────────────────────────

@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """Verify old password then set a new bcrypt hash."""
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    stored = user.hashed_password or "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    if not verify_password(body.old_password, stored):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    user.hashed_password = hash_password(body.new_password)
    db.commit()
    return {"message": "Password updated successfully."}


# ── Re-join (Eliminated_Won users only) ───────────────────────────────────────

@router.post("/rejoin", response_model=UserJWTResponse)
def rejoin(
    body: RejoinRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """
    Allow a user with status Eliminated_Won to re-enter the waitlist
    by providing a fresh Deposit Token. Resets their level to 1.
    """
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    if user.status != UserStatus.Eliminated_Won:
        raise HTTPException(
            status_code=400,
            detail="Only accounts with Eliminated_Won status can re-join.",
        )

    token = crud_token.get_token_by_code(db, body.deposit_token)
    if not token:
        raise HTTPException(status_code=400, detail="Deposit token not found.")
    if token.type != TokenType.Deposit:
        raise HTTPException(status_code=400, detail="Only Deposit tokens (DEP-...) are accepted.")
    if token.status != TokenStatus.Active:
        raise HTTPException(status_code=400, detail="This deposit token has already been used.")
    if float(token.value_inr) != float(DEPOSIT_AMOUNT_INR):
        raise HTTPException(status_code=400, detail=f"Token face value must be ₹{DEPOSIT_AMOUNT_INR}.")

    # Reset user to Waitlist at Level 1
    user.status                = UserStatus.Waitlist
    user.weekly_payment_status = WeeklyPaymentStatus.Paid
    user.current_level         = 1
    user.current_pool_id       = None

    # Burn the deposit token — stamp full audit trail
    now = datetime.now(timezone.utc)
    token.user_id             = user.id
    token.status              = TokenStatus.Burned
    token.redeemed_at         = now
    token.redeemed_by_user_id = user.id
    db.commit()
    db.refresh(user)

    background_tasks.add_task(check_and_scale_waitlist, db)

    return UserJWTResponse(access_token=create_user_jwt(user.id), user=_serialize_user(user))
