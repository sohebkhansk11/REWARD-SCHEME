"""
Referral Payout System  (/users & /admin)
==========================================

User-facing:
  POST /users/request-referral-payout
        Request a payout when accumulated_referral_bonus_inr >= ₹1,000.
        Creates a Referral_Withdraw token with status Pending_Approval.
        Deducts the requested amount from the user's accumulated balance.

Admin-facing:
  GET  /admin/referrals/pending
        List all Referral_Withdraw tokens awaiting approval.

  PUT  /admin/referrals/{token_id}/status
        Approve → token becomes Active (user may present for cashout).
        Reject  → token burned; amount credited back to user balance.
"""

import random
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import require_user_jwt, require_admin_jwt
from app.database import get_db
from app.models.token import Token, TokenType, TokenStatus
from app.models.user import User
from app.schemas.admin import PendingReferralItem, ReferralStatusUpdateRequest

# Minimum accumulated balance required before a payout can be requested
_PAYOUT_THRESHOLD_INR: Decimal = Decimal("1000")

router = APIRouter(tags=["Referral Payouts"])


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unique_rw_code(db: Session) -> str:
    """Generate a collision-free RW-XXXXXX token code."""
    while True:
        code = "RW-" + "".join(
            random.choices(string.ascii_uppercase + string.digits, k=6)
        )
        if not db.query(Token).filter(Token.code == code).first():
            return code


# ─────────────────────────────────────────────────────────────────────────────
# Request schema (user-facing only; admin schemas live in schemas/admin.py)
# ─────────────────────────────────────────────────────────────────────────────

class ReferralPayoutRequest(BaseModel):
    amount_inr: Optional[Decimal] = Field(
        None,
        gt=0,
        description=(
            "Amount to request (must be ≤ accumulated balance). "
            "Omit to request the full accumulated balance."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /users/request-referral-payout
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/users/request-referral-payout")
def request_referral_payout(
    body: ReferralPayoutRequest,
    user_id: int = Depends(require_user_jwt),
    db: Session = Depends(get_db),
):
    """
    Request a referral payout.

    Rules:
    - User's accumulated_referral_bonus_inr must be >= ₹1,000.
    - amount_inr (if provided) must be ≤ accumulated balance.
    - Omitting amount_inr pays out the full balance.
    - Each user may only have ONE Pending_Approval payout at a time.

    On success:
    - A Referral_Withdraw token (RW-XXXXXX) with status Pending_Approval is created.
    - The requested amount is deducted from the user's accumulated balance immediately.
    - The admin queue (GET /admin/referrals/pending) shows this token.
    """
    user: User | None = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    balance = Decimal(str(user.accumulated_referral_bonus_inr or 0))

    # ── Threshold check ───────────────────────────────────────────────────────
    if balance < _PAYOUT_THRESHOLD_INR:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient referral balance. "
                f"You need at least ₹{_PAYOUT_THRESHOLD_INR} to request a payout "
                f"(current balance: ₹{balance})."
            ),
        )

    # ── Resolve amount ────────────────────────────────────────────────────────
    amount = body.amount_inr if body.amount_inr is not None else balance
    if amount > balance:
        raise HTTPException(
            status_code=400,
            detail=f"Requested amount ₹{amount} exceeds accumulated balance ₹{balance}.",
        )

    # ── One-at-a-time guard ───────────────────────────────────────────────────
    existing = (
        db.query(Token)
        .filter(
            Token.user_id == user_id,
            Token.type == TokenType.Referral_Withdraw,
            Token.status == TokenStatus.Pending_Approval,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"You already have a pending referral payout request ({existing.code}). "
                "Wait for admin review before submitting another."
            ),
        )

    # ── Deduct balance + create token ─────────────────────────────────────────
    user.accumulated_referral_bonus_inr = balance - amount

    code = _unique_rw_code(db)
    new_token = Token(
        code=code,
        type=TokenType.Referral_Withdraw,
        value_inr=amount,
        status=TokenStatus.Pending_Approval,
        user_id=user_id,
    )
    db.add(new_token)
    db.commit()
    db.refresh(new_token)
    db.refresh(user)

    return {
        "message":           "Referral payout request submitted successfully.",
        "token_code":        code,
        "amount_inr":        float(amount),
        "status":            TokenStatus.Pending_Approval,
        "balance_remaining": float(user.accumulated_referral_bonus_inr),
        "note":              "The admin will review your request. Token becomes Active upon approval.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /admin/referrals/pending
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/admin/referrals/pending",
    response_model=list[PendingReferralItem],
    dependencies=[Depends(require_admin_jwt)],
)
def list_pending_referrals(db: Session = Depends(get_db)):
    """
    Return all Referral_Withdraw tokens currently awaiting admin approval,
    enriched with the requesting user's name, username, and referral stats.
    """
    rows = (
        db.query(Token, User)
        .outerjoin(User, Token.user_id == User.id)
        .filter(
            Token.type   == TokenType.Referral_Withdraw,
            Token.status == TokenStatus.Pending_Approval,
        )
        .order_by(Token.created_at.asc())
        .all()
    )

    result = []
    for token, user in rows:
        result.append(
            PendingReferralItem(
                token_id=token.id,
                token_code=token.code,
                token_value_inr=Decimal(str(token.value_inr)),
                created_at=token.created_at,
                user_id=user.id if user else None,
                username=user.username if user else None,
                user_name=user.name if user else None,
                total_referrals_count=(user.total_referrals_count if user else 0),
                accumulated_bonus_inr=Decimal(str(user.accumulated_referral_bonus_inr or 0)) if user else Decimal("0"),
            )
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PUT /admin/referrals/{token_id}/status
# ─────────────────────────────────────────────────────────────────────────────

@router.put(
    "/admin/referrals/{token_id}/status",
    dependencies=[Depends(require_admin_jwt)],
)
def update_referral_status(
    token_id: int,
    body: ReferralStatusUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Approve or reject a pending referral payout request.

    Approve:
    - Token status → Active.  User may now present this token for physical cashout.
    - No balance change (amount was already deducted when the request was created).

    Reject:
    - Token status → Burned.
    - Requested amount is credited back to user.accumulated_referral_bonus_inr.
    - Effectively reverses the payout request as if it never happened.
    """
    token: Token | None = (
        db.query(Token)
        .filter(
            Token.id     == token_id,
            Token.type   == TokenType.Referral_Withdraw,
            Token.status == TokenStatus.Pending_Approval,
        )
        .first()
    )
    if not token:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Token {token_id} not found, is not a Referral_Withdraw token, "
                "or is not in Pending_Approval status."
            ),
        )

    now = datetime.now(timezone.utc)

    if body.action == "approve":
        # ── Approve: mark Active so user can cash out ──────────────────────
        token.status = TokenStatus.Active
        db.commit()

        return {
            "message":    f"Referral payout {token.code} approved.",
            "token_id":   token_id,
            "token_code": token.code,
            "amount_inr": float(token.value_inr),
            "new_status": TokenStatus.Active,
            "note":       "Token is now Active. The user may present it for cashout.",
        }

    else:  # reject
        # ── Reject: burn token + credit amount back to user ────────────────
        amount = Decimal(str(token.value_inr))

        token.status      = TokenStatus.Burned
        token.redeemed_at = now

        # Credit amount back if user still exists
        user: User | None = (
            db.query(User).filter(User.id == token.user_id).first()
            if token.user_id else None
        )
        balance_after: Optional[Decimal] = None
        if user:
            user.accumulated_referral_bonus_inr = (
                Decimal(str(user.accumulated_referral_bonus_inr or 0)) + amount
            )
            balance_after = Decimal(str(user.accumulated_referral_bonus_inr))

        db.commit()

        return {
            "message":       f"Referral payout {token.code} rejected and reversed.",
            "token_id":      token_id,
            "token_code":    token.code,
            "amount_inr":    float(amount),
            "new_status":    TokenStatus.Burned,
            "balance_after": float(balance_after) if balance_after is not None else None,
            "note":          (
                f"₹{amount} credited back to user balance."
                if user else
                "User not found — balance not restored."
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# PUT /admin/referrals/{token_id}/settle
# ─────────────────────────────────────────────────────────────────────────────

@router.put(
    "/admin/referrals/{token_id}/settle",
    dependencies=[Depends(require_admin_jwt)],
)
def settle_referral_payout(
    token_id: int,
    db: Session = Depends(get_db),
):
    """
    Confirm physical cash payment and close the referral payout lifecycle.

    Lifecycle: Pending_Approval → (approve) → Active → (settle) → Burned

    The approve step (PUT /admin/referrals/{id}/status) marks the token Active,
    meaning the admin has authorised the payout.  This settle step marks it
    Burned, confirming the cash has been physically handed to the user.

    Only tokens in Active status can be settled — Pending and already-Burned
    tokens are rejected with 404 to prevent double-settlement.
    """
    token: Token | None = (
        db.query(Token)
        .filter(
            Token.id     == token_id,
            Token.type   == TokenType.Referral_Withdraw,
            Token.status == TokenStatus.Active,
        )
        .first()
    )
    if not token:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Token {token_id} not found, is not a Referral_Withdraw token, "
                "or is not in Active (approved) status. "
                "Only approved tokens can be settled."
            ),
        )

    token.status      = TokenStatus.Burned
    token.redeemed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "message":    f"Referral payout {token.code} settled.",
        "token_id":   token_id,
        "token_code": token.code,
        "amount_inr": float(token.value_inr),
        "new_status": TokenStatus.Burned,
        "note":       "Cash confirmed paid out. Token lifecycle complete.",
    }
