"""
Admin Deep User Management  (/admin/users & /admin/tokens — destructive ops)
=============================================================================

PUT    /admin/users/{user_id}/full-update   Patch any user field (username, password, etc.)
DELETE /admin/users/{user_id}               Permanently delete a user + their tokens
DELETE /admin/tokens/{token_id}             Permanently delete a token (admin password required)

All endpoints require Admin JWT.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_admin_jwt
from app.database import get_db
from app.models.admin import Admin
from app.models.pool import Pool
from app.models.token import Token, TokenType, TokenStatus
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.schemas.admin import (
    AdminFullUpdateRequest,
    AdminDeleteTokenRequest,
    DeleteUserResponse,
    DeleteTokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth import hash_password, verify_password
from app.crud import user as crud_user

router = APIRouter(tags=["Admin · User & Token Management"], dependencies=[Depends(require_admin_jwt)])


# ─────────────────────────────────────────────────────────────────────────────
# PUT /admin/users/{user_id}/full-update
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/admin/users/{user_id}/full-update", response_model=UserResponse)
def full_update_user(
    user_id: int,
    body: AdminFullUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Patch any field on a user record.  All body fields are optional — only
    those explicitly provided are written.

    Special handling:
    - `username`: uniqueness is checked against all OTHER users (not self).
    - `mobile`:   same uniqueness rule.
    - `new_password`: plain-text; hashed with bcrypt-12 before saving.
    - `current_pool_id`: if changed, the old and new pools' total_members are
      resynced automatically.
    """
    user: User | None = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found.")

    # ── Uniqueness checks ─────────────────────────────────────────────────────
    if body.username is not None and body.username != user.username:
        conflict = db.query(User).filter(
            User.username == body.username, User.id != user_id
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Username already taken by another user.")

    if body.mobile is not None and body.mobile != user.mobile:
        conflict = db.query(User).filter(
            User.mobile == body.mobile, User.id != user_id
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Mobile number already registered to another user.")

    # ── Pool membership resync ────────────────────────────────────────────────
    old_pool_id = user.current_pool_id
    new_pool_id = body.current_pool_id  # None means "not changing"

    # ── Apply scalar field updates ────────────────────────────────────────────
    field_map = {
        "name":                           body.name,
        "mobile":                         body.mobile,
        "username":                       body.username,
        "status":                         body.status,
        "current_pool_id":                body.current_pool_id,
        "weekly_payment_status":          body.weekly_payment_status,
        "late_fees_inr":                  body.late_fees_inr,
        "referred_by_user_id":            body.referred_by_user_id,
        "total_referrals_count":          body.total_referrals_count,
        "accumulated_referral_bonus_inr": body.accumulated_referral_bonus_inr,
        "telegram_chat_id":               body.telegram_chat_id,
    }
    # current_level has a 1-6 validator — apply separately
    if body.current_level is not None:
        if not (1 <= body.current_level <= 6):
            raise HTTPException(status_code=422, detail="current_level must be 1–6.")
        user.current_level = body.current_level

    for attr, value in field_map.items():
        if value is not None:
            setattr(user, attr, value)

    # ── Hash new password if provided ─────────────────────────────────────────
    if body.new_password is not None:
        user.hashed_password = hash_password(body.new_password)

    db.commit()
    db.refresh(user)

    # ── Resync pool total_members if pool assignment changed ──────────────────
    pools_to_resync = {pid for pid in (old_pool_id, new_pool_id) if pid is not None}
    if old_pool_id != new_pool_id and pools_to_resync:
        for pid in pools_to_resync:
            count = (
                db.query(User)
                .filter(User.current_pool_id == pid, User.status == UserStatus.Active)
                .count()
            )
            pool = db.query(Pool).filter(Pool.id == pid).first()
            if pool:
                pool.total_members = count
        db.commit()
        db.refresh(user)

    return UserResponse.model_validate(user)


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /admin/users/{user_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/admin/users/{user_id}", response_model=DeleteUserResponse)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
):
    """
    Permanently delete a user and all tokens they own.

    Safety cascade:
    1. Null out `referred_by_user_id` on any users who were referred by this user
       (so their accounts are not broken).
    2. Null out `redeemed_by_user_id` on any tokens burned by this user.
    3. Delete all tokens WHERE user_id = this user.
    4. If the user is in an Active pool, decrement pool.total_members.
    5. Delete the user row.

    Returns a summary including pool impact, tokens deleted, etc.
    """
    user: User | None = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found.")

    username  = user.username
    pool_id   = user.current_pool_id
    was_active_in_pool = (user.status == UserStatus.Active and pool_id is not None)

    # ── Step 1: Null referred_by references ───────────────────────────────────
    (
        db.query(User)
        .filter(User.referred_by_user_id == user_id)
        .update({"referred_by_user_id": None}, synchronize_session=False)
    )

    # ── Step 2: Null redeemed_by references on tokens ─────────────────────────
    (
        db.query(Token)
        .filter(Token.redeemed_by_user_id == user_id)
        .update({"redeemed_by_user_id": None}, synchronize_session=False)
    )

    # ── Step 3: Delete tokens owned by this user ──────────────────────────────
    tokens_deleted = (
        db.query(Token)
        .filter(Token.user_id == user_id)
        .delete(synchronize_session=False)
    )

    db.flush()

    # ── Step 4: Delete the user ───────────────────────────────────────────────
    db.delete(user)
    db.commit()

    # ── Step 5: Resync pool member count if user was active ───────────────────
    pool_members_remaining: int | None = None
    if was_active_in_pool and pool_id:
        remaining = (
            db.query(User)
            .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
            .count()
        )
        pool = db.query(Pool).filter(Pool.id == pool_id).first()
        if pool:
            pool.total_members = remaining
            db.commit()
        pool_members_remaining = remaining

    return DeleteUserResponse(
        deleted_user_id=user_id,
        deleted_username=username,
        tokens_deleted=tokens_deleted,
        was_in_active_pool=was_active_in_pool,
        pool_id=pool_id if was_active_in_pool else None,
        pool_members_remaining=pool_members_remaining,
        message=(
            f"User '{username}' and {tokens_deleted} token(s) permanently deleted. "
            + (
                f"Pool #{pool_id} now has {pool_members_remaining} active member(s) — "
                "run POST /admin/waitlist/check to auto-fill the vacant slot."
                if was_active_in_pool else
                "No pool membership was affected."
            )
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /admin/tokens/{token_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/admin/tokens/{token_id}", response_model=DeleteTokenResponse)
def delete_token(
    token_id: int,
    body: AdminDeleteTokenRequest,
    admin_username: str = Depends(require_admin_jwt),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a single token.

    Security gate: the calling admin's account password must be included
    in the request body (`admin_password`).  The password is verified
    against the stored bcrypt hash before the delete proceeds.

    Use cases: correcting fraudulent tokens, removing test data, emergency ops.
    """
    # ── Verify admin password ─────────────────────────────────────────────────
    admin: Admin | None = (
        db.query(Admin).filter(Admin.username == admin_username).first()
    )
    if not admin:
        raise HTTPException(status_code=401, detail="Admin account not found — re-authenticate.")

    dummy = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    stored = admin.hashed_password or dummy
    if not verify_password(body.admin_password, stored):
        raise HTTPException(
            status_code=401,
            detail="Admin password verification failed. Token was NOT deleted.",
        )

    # ── Locate token ──────────────────────────────────────────────────────────
    token: Token | None = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail=f"Token {token_id} not found.")

    code      = token.code
    tok_type  = str(token.type)
    value_inr = Decimal(str(token.value_inr))

    # ── Null audit back-references before deletion ────────────────────────────
    # Prevent FK violations if another token referenced this token's user as redeemer
    # (edge case — just defensive)
    db.delete(token)
    db.commit()

    return DeleteTokenResponse(
        deleted_token_id=token_id,
        deleted_token_code=code,
        token_type=tok_type,
        token_value_inr=value_inr,
        message=(
            f"Token '{code}' ({tok_type}, ₹{value_inr}) permanently deleted. "
            "This action cannot be undone."
        ),
    )
