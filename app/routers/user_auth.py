"""
User Authentication Router
===========================

POST /auth/register           — Name + Mobile + Username + Password + Deposit Token
POST /auth/login              — Username + Password → JWT
GET  /auth/me                 — Return current user's profile (requires user JWT)
PATCH /auth/profile           — Update name / mobile (requires user JWT)
POST /auth/change-password    — Change password (requires user JWT)
POST /auth/rejoin             — Re-join waitlist after Eliminated_Won (requires user JWT)
POST /auth/deposit/redeem     — User-facing deposit token redemption (requires user JWT)
GET  /users/me/wallet-history — Full ledger of deposits + wins (requires user JWT)

Registration atomically:
  1. Validates the Deposit Token (must be active DEP-XXXXXX, value = ₹1,000).
  2. Resolves optional referral username → referred_by_user_id.
  3. Creates the User (status=Waitlist, weekly_payment=Paid).
  4. Burns the Deposit Token and assigns it to the new user.
  5. Triggers waitlist scaling + FIFO vacancy fill in the background.
  6. Returns a 30-day User JWT.
"""

import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import func, over
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
from app.services.waitlist import assign_waitlist_to_pools
from app.core.security import require_user_jwt
from app.core.config import DEPOSIT_AMOUNT_INR

# ── Referral code helpers ─────────────────────────────────────────────────────
_REF_ALPHABET = string.ascii_uppercase + string.digits  # 36 chars → 36^8 ≈ 2.8T combos

def _generate_referral_code() -> str:
    """Return a random 8-char uppercase-alphanumeric string."""
    return "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))

def _unique_referral_code(db: Session) -> str:
    """Generate a referral code guaranteed not to collide with existing ones."""
    while True:
        code = _generate_referral_code()
        if not crud_user.get_user_by_referral_code(db, code):
            return code

router = APIRouter(prefix="/auth", tags=["User Auth"])

# Separate router for /users/me/* routes (wallet history, etc.)
users_me_router = APIRouter(prefix="/users/me", tags=["User Profile"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize_user(user: User) -> dict:
    """Serialize a User ORM object to a plain dict (via UserResponse)."""
    return UserResponse.model_validate(user).model_dump(mode="json")


def _background_waitlist_tasks(db: Session) -> None:
    """
    On-Join Instant Refill Trigger.

    Called in the background after every registration, deposit redemption,
    and re-join.  Runs the full Double-FIFO engine so that a pool sitting at
    11/12 gets filled the moment the next user joins — without waiting for
    the next scheduled Sunday draw.
    """
    assign_waitlist_to_pools(db)


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

    # 3. Resolve referral via unique referral_code (not username)
    referred_by_id: int | None = None
    if body.referred_by_code and body.referred_by_code.strip():
        referrer = crud_user.get_user_by_referral_code(db, body.referred_by_code)
        if not referrer:
            raise HTTPException(status_code=400, detail="Referral code not found.")
        if referrer.username == body.username:
            raise HTTPException(status_code=400, detail="You cannot refer yourself.")
        referred_by_id = referrer.id

    # 4. Create user (Waitlist + Paid — the deposit token covers week 1)
    new_user = User(
        name=body.name.strip(),
        mobile=body.mobile,
        username=body.username,
        hashed_password=hash_password(body.password),
        status=UserStatus.Waitlist,
        weekly_payment_status=WeeklyPaymentStatus.Paid,
        current_level=1,
        referred_by_user_id=referred_by_id,
        referral_code=_unique_referral_code(db),   # unique invite code for sharing
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

    # 6. Check vacancies + waitlist threshold in background (non-blocking)
    # NOTE: Referral bonus (₹250) is credited when the new user ENTERS AN ACTIVE POOL,
    # not at registration.  See waitlist.py and draw.py.
    background_tasks.add_task(_background_waitlist_tasks, db)

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


# ── Referral code validation ──────────────────────────────────────────────────

@router.get("/validate-referral/{code}")
def validate_referral(code: str, db: Session = Depends(get_db)):
    """
    Real-time referral code validation used by the registration form.

    Rules:
      - Blank / empty code  → 200  {"valid": True,  "message": "No referral code"}
      - Valid 8-char code    → 200  {"valid": True,  "referrer_username": "..."}
      - Unknown code         → 404  {"valid": False, "message": "Referral code not found"}

    No authentication required — called before the user creates an account.
    """
    stripped = code.strip()

    # Blank code is acceptable (user chose not to enter a referral)
    if not stripped:
        return {"valid": True, "message": "No referral code entered."}

    referrer = crud_user.get_user_by_referral_code(db, stripped)
    if not referrer:
        raise HTTPException(
            status_code=404,
            detail=f"Referral code '{stripped}' not found.",
        )

    return {
        "valid":              True,
        "referrer_username":  referrer.username,
        "referrer_name":      referrer.name,
        "message":            f"Valid — referred by @{referrer.username}",
    }


# ── Admin backfill: generate referral codes for legacy users ──────────────────

@router.post("/admin/backfill-referral-codes")
def backfill_referral_codes(
    db: Session = Depends(get_db),
    _: str = Depends(__import__("app.core.security", fromlist=["require_admin_jwt"]).require_admin_jwt),
):
    """
    Admin-only: generate and persist referral_code for any user that was
    registered before the referral_code column existed (i.e. referral_code IS NULL).

    Safe to call multiple times — only touches rows where referral_code is NULL.
    """
    users_missing_code: list[User] = (
        db.query(User)
        .filter(User.referral_code == None)  # noqa: E711
        .all()
    )

    updated = 0
    for user in users_missing_code:
        user.referral_code = _unique_referral_code(db)
        updated += 1

    if updated:
        db.commit()

    return {
        "backfilled": updated,
        "message": f"Referral codes generated for {updated} legacy user(s).",
    }


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

    background_tasks.add_task(_background_waitlist_tasks, db)

    return UserJWTResponse(access_token=create_user_jwt(user.id), user=_serialize_user(user))


# ── User-facing deposit token redemption ──────────────────────────────────────

class DepositRedeemRequest(BaseModel):
    deposit_token: str = Field(description="Active DEP-XXXXXX token code")


@router.post("/deposit/redeem", response_model=UserJWTResponse)
def redeem_deposit(
    body: DepositRedeemRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """
    User redeems a Deposit token (DEP-XXXXXX) to mark their weekly instalment
    as Paid.  This endpoint uses the user's own JWT — NOT the admin JWT — so it
    never risks triggering the frontend 401-logout interceptor.

    Advance-payment guard:
      Active users who are already Paid for the current week cannot deposit
      again until the Sunday draw resets their payment status to Unpaid.
      (Maximum 1 advance instalment at a time.)

    On success:
      - Token burned, stamped with user_id and redeemed_at.
      - User's weekly_payment_status → Paid.
      - Waitlist FIFO fill triggered in background (covers Waitlist→Active on join).
      - Returns fresh user profile + new JWT.
    """
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    # ── Advance-payment guard (Active users only) ─────────────────────────────
    if (
        user.status == UserStatus.Active
        and user.weekly_payment_status == WeeklyPaymentStatus.Paid
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "You've already paid for this week. "
                "You can only deposit 1 instalment in advance — "
                "your payment status resets to Unpaid after the Sunday draw."
            ),
        )

    # ── Validate token ────────────────────────────────────────────────────────
    code = body.deposit_token.strip().upper()
    token = crud_token.get_token_by_code(db, code)
    if not token:
        raise HTTPException(status_code=400, detail="Deposit token not found.")
    if token.type != TokenType.Deposit:
        raise HTTPException(status_code=400, detail="Only Deposit tokens (DEP-...) are accepted.")
    if token.status != TokenStatus.Active:
        raise HTTPException(status_code=400, detail="This deposit token has already been used.")
    if float(token.value_inr) != float(DEPOSIT_AMOUNT_INR):
        raise HTTPException(status_code=400, detail=f"Token face value must be ₹{DEPOSIT_AMOUNT_INR}.")

    # ── Burn the token ────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    token.user_id             = user.id
    token.status              = TokenStatus.Burned
    token.redeemed_at         = now
    token.redeemed_by_user_id = user.id

    # ── Mark user as Paid + accumulate deposit total ──────────────────────────
    user.weekly_payment_status = WeeklyPaymentStatus.Paid
    user.total_deposited_inr   = (user.total_deposited_inr or 0) + DEPOSIT_AMOUNT_INR
    db.commit()
    db.refresh(user)

    # ── Background: fill vacancies + check for new pool threshold ─────────────
    background_tasks.add_task(_background_waitlist_tasks, db)

    return UserJWTResponse(
        access_token=create_user_jwt(user.id),
        user=_serialize_user(user),
    )


# ── Waitlist Rank ──────────────────────────────────────────────────────────────

@users_me_router.get("/waitlist-rank")
def get_waitlist_rank(
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """
    Return the authenticated user's real-time position in the Waitlist queue.

    Uses an SQL window function so the rank is always live and never needs a
    mass-update when other members join or leave:

        SELECT rank FROM (
            SELECT id,
                   ROW_NUMBER() OVER (ORDER BY join_date ASC) AS rank
            FROM   users
            WHERE  status = 'Waitlist'
        ) sub
        WHERE id = :user_id

    Response:
        {
          "rank":           7,          -- 1-based position (1 = next to enter a pool)
          "total_waiting":  1077,       -- all paid + unpaid Waitlist members
          "status":         "Waitlist"  -- or "Active" / "Eliminated_Won" / …
        }

    Non-Waitlist users receive rank: null with their current status.
    """
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    # Not on the waitlist — return status with no rank
    if user.status != UserStatus.Waitlist:
        return {
            "rank":          None,
            "total_waiting": None,
            "status":        user.status.value,
            "message":       f"Your account status is '{user.status.value}' — not currently on the Waitlist.",
        }

    # ── Window function subquery ──────────────────────────────────────────────
    # ROW_NUMBER() OVER (ORDER BY join_date ASC) gives each Waitlist user their
    # exact FIFO position.  Wrapping it in a subquery lets us filter to the
    # specific user in the outer WHERE clause without recomputing the window.
    rank_col  = func.row_number().over(order_by=User.join_date.asc()).label("rank")
    subq = (
        db.query(User.id, rank_col)
        .filter(User.status == UserStatus.Waitlist)
        .subquery()
    )

    rank: int | None = (
        db.query(subq.c.rank)
        .filter(subq.c.id == user_id)
        .scalar()
    )

    total_waiting: int = (
        db.query(func.count(User.id))
        .filter(User.status == UserStatus.Waitlist)
        .scalar() or 0
    )

    if rank is None:
        # Rare edge: user is Waitlist but somehow not in the window (shouldn't happen)
        return {
            "rank":          None,
            "total_waiting": total_waiting,
            "status":        user.status.value,
            "message":       "Could not determine rank — please try again.",
        }

    return {
        "rank":          int(rank),
        "total_waiting": total_waiting,
        "status":        user.status.value,
        "message":       (
            f"You are #{rank} in the waitlist queue out of {total_waiting} members. "
            f"The next pool forms when the queue reaches the configured threshold."
        ),
    }


# ── Wallet History ─────────────────────────────────────────────────────────────

class WalletTransaction(BaseModel):
    id:         int
    code:       str
    type:       str             # "Deposit" | "Withdraw"
    amount_inr: float
    status:     str
    pool_name:  Optional[str]  = None
    date:       datetime


class WalletHistoryResponse(BaseModel):
    total_deposited_all_time: float
    total_won_all_time:       float
    transactions:             list[WalletTransaction]


@users_me_router.get("/wallet-history", response_model=WalletHistoryResponse)
def get_wallet_history(
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """
    Return a consolidated ledger of the authenticated user's financial activity:
      - All Deposit tokens (DEP-) burned by this user  →  what they put in
      - All Withdraw tokens (WIT-) issued to this user →  what they won

    Each entry includes the Pool Name (for WIT tokens) and date.
    Aggregated lifetime totals are also returned.
    """
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    # ── Fetch all relevant tokens in one query ────────────────────────────────
    tokens: list[Token] = (
        db.query(Token)
        .filter(
            Token.type.in_([TokenType.Deposit, TokenType.Withdraw]),
            Token.user_id == user_id,
        )
        .order_by(Token.created_at.desc())
        .all()
    )

    transactions: list[WalletTransaction] = []
    total_deposited = 0.0
    total_won       = 0.0

    for t in tokens:
        # Resolve pool name (WIT tokens have pool_id stamped at draw time)
        pool_name: Optional[str] = None
        if t.pool_id and t.pool:
            pool_name = t.pool.name

        entry_date = t.redeemed_at or t.created_at

        transactions.append(
            WalletTransaction(
                id=t.id,
                code=t.code,
                type=t.type.value,
                amount_inr=float(t.value_inr),
                status=t.status.value,
                pool_name=pool_name,
                date=entry_date,
            )
        )

        if t.type == TokenType.Deposit and t.status == TokenStatus.Burned:
            total_deposited += float(t.value_inr)
        elif t.type == TokenType.Withdraw:
            total_won += float(t.value_inr)

    return WalletHistoryResponse(
        total_deposited_all_time=round(total_deposited, 2),
        total_won_all_time=round(total_won, 2),
        transactions=transactions,
    )
