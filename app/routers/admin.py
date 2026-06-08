from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import func
from sqlalchemy.orm import Session
from dataclasses import asdict

from app.core.config import LATE_FEE_DAILY_INR
from app.database import get_db
from app.models.user import UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.models.token import Token, TokenType, TokenStatus
from app.schemas.admin import (
    TokenGenerateRequest,
    TokenRedeemRequest,
    RedeemResponse,
    DrawResultResponse,
    WinnerResultResponse,
    WaitlistCheckResponse,
)
from app.schemas.token import TokenResponse
from app.services import tokens as svc_tokens
from app.services import waitlist as svc_waitlist
from app.services import draw as svc_draw
from app.models.user import User
from app.schemas.user import UserResponse
from app.schemas.pool import PoolResponse

router = APIRouter(tags=["Admin"])


# ── Aggregate Stats ───────────────────────────────────────────────────────────

@router.get("/admin/stats")
def get_stats(db: Session = Depends(get_db)):
    """Single call for all dashboard metrics."""
    total_capital = db.query(func.sum(Token.value_inr)).filter(
        Token.type == TokenType.Deposit, Token.status == TokenStatus.Burned
    ).scalar() or 0

    return {
        "active_users":          db.query(User).filter(User.status == UserStatus.Active).count(),
        "waitlist_count":        db.query(User).filter(User.status == UserStatus.Waitlist).count(),
        "active_pools":          db.query(Pool).filter(Pool.status == PoolStatus.Active).count(),
        "total_capital_inr":     float(total_capital),
        "eliminated_count":      db.query(User).filter(
                                     User.status.in_([UserStatus.Eliminated, UserStatus.Eliminated_Won])
                                 ).count(),
        "total_tokens_issued":   db.query(func.count(Token.id)).scalar() or 0,
        "active_tokens":         db.query(func.count(Token.id)).filter(
                                     Token.status == TokenStatus.Active
                                 ).scalar() or 0,
    }


# ── Token Burn ────────────────────────────────────────────────────────────────

@router.post("/admin/tokens/{code}/burn", response_model=TokenResponse)
def burn_withdraw_token(code: str, db: Session = Depends(get_db)):
    """Admin: mark a Withdraw token as Burned when paying out a winner."""
    from app.crud import token as crud_token
    from app.schemas.token import TokenUpdate

    token = crud_token.get_token_by_code(db, code)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.type != TokenType.Withdraw:
        raise HTTPException(status_code=400, detail="Only Withdraw tokens can be burned this way")
    if token.status == TokenStatus.Burned:
        raise HTTPException(status_code=400, detail="Token is already burned")

    return crud_token.update_token(db, token.id, TokenUpdate(status=TokenStatus.Burned))


# ── Token Management ──────────────────────────────────────────────────────────

@router.post("/admin/tokens/generate", response_model=TokenResponse, status_code=201)
def generate_token(body: TokenGenerateRequest, db: Session = Depends(get_db)):
    """Admin: create a new Deposit, Withdraw, or Referral token."""
    token = svc_tokens.admin_generate_token(
        db, token_type=body.type, value_inr=body.value_inr, user_id=body.user_id
    )
    return token


@router.post("/tokens/{code}/redeem", response_model=RedeemResponse)
def redeem_token(
    code: str,
    body: TokenRedeemRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    User redeems a Deposit token (₹1000).

    - Marks user's weekly payment as Paid.
    - If user was unclassified, moves them to Waitlist.
    - Automatically checks waitlist scaling in the background.
    """
    try:
        token, user = svc_tokens.redeem_deposit_token(db, code=code, user_id=body.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Trigger waitlist check as a background task so the response isn't delayed
    background_tasks.add_task(_run_waitlist_check, db)

    return RedeemResponse(
        token=TokenResponse.model_validate(token),
        user=UserResponse.model_validate(user),
        message="Token redeemed successfully. Weekly payment marked as Paid.",
    )


def _run_waitlist_check(db: Session):
    """Background helper — checks waitlist and creates pool if threshold met."""
    svc_waitlist.check_and_scale_waitlist(db)


# ── Waitlist ──────────────────────────────────────────────────────────────────

@router.post("/admin/waitlist/check", response_model=WaitlistCheckResponse)
def trigger_waitlist_check(db: Session = Depends(get_db)):
    """
    Admin: manually trigger the waitlist auto-scaling check.

    Creates a new pool and moves the top 12 paid Waitlist members into it
    when paid Waitlist count reaches 24.
    """
    paid_count: int = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .count()
    )

    new_pool: Pool | None = svc_waitlist.check_and_scale_waitlist(db)

    if new_pool:
        return WaitlistCheckResponse(
            paid_waitlist_count=paid_count,
            pool_created=PoolResponse.model_validate(new_pool),
            message=f"New pool '{new_pool.name}' created with 12 members.",
        )

    return WaitlistCheckResponse(
        paid_waitlist_count=paid_count,
        pool_created=None,
        message=f"Waitlist has {paid_count} paid members; {24 - paid_count} more needed to trigger pool creation.",
    )


# ── Dual-Draw ─────────────────────────────────────────────────────────────────

@router.post("/admin/pools/{pool_id}/draw", response_model=DrawResultResponse)
def trigger_draw(pool_id: int, db: Session = Depends(get_db)):
    """
    Admin: run the Dual-Draw for an active pool.

    - Selects one winner from Level 1–3 and one from Level 4–6.
    - Generates a Withdraw token for each winner (net = ₹{BASE} − ₹500 fee).
    - Marks both winners as Eliminated_Won.
    - Replaces each winner with the earliest paid Waitlist member at Level 1.
    """
    try:
        result = svc_draw.run_dual_draw(db, pool_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def _to_response(w: svc_draw.WinnerResult) -> WinnerResultResponse:
        return WinnerResultResponse(**asdict(w))

    return DrawResultResponse(
        pool_id=result.pool_id,
        pool_name=result.pool_name,
        winner_low_level=_to_response(result.winner_low_level),
        winner_high_level=_to_response(result.winner_high_level),
    )


# ── Late Payment Penalties ────────────────────────────────────────────────────

@router.post("/admin/penalty/apply-daily")
def apply_daily_penalty(db: Session = Depends(get_db)):
    """
    Admin: call once per day (Monday–Saturday) to accrue ₹50 on every Active
    member who has not yet paid for the current week.
    """
    unpaid: list[User] = (
        db.query(User)
        .filter(User.status == UserStatus.Active, User.weekly_payment_status == WeeklyPaymentStatus.Unpaid)
        .all()
    )
    if not unpaid:
        return {"penalised_count": 0, "message": "No unpaid active members."}

    from app.crud import user as crud_user
    from app.schemas.user import UserUpdate

    for member in unpaid:
        new_late = Decimal(str(member.late_fees_inr or 0)) + Decimal(str(LATE_FEE_DAILY_INR))
        crud_user.update_user(db, member.id, UserUpdate(late_fees_inr=new_late))

    return {
        "penalised_count": len(unpaid),
        "daily_fee_inr": LATE_FEE_DAILY_INR,
        "message": f"₹{LATE_FEE_DAILY_INR} penalty applied to {len(unpaid)} unpaid member(s).",
    }


@router.post("/admin/penalty/eliminate-unpaid")
def eliminate_unpaid_members(db: Session = Depends(get_db)):
    """
    Admin: call each Sunday before the draw to eliminate Active members who are
    still Unpaid. Their slot is forfeited (no refund); the next paid Waitlist
    member fills the vacancy.
    """
    from app.crud import user as crud_user
    from app.schemas.user import UserUpdate

    unpaid: list[User] = (
        db.query(User)
        .filter(User.status == UserStatus.Active, User.weekly_payment_status == WeeklyPaymentStatus.Unpaid)
        .all()
    )
    if not unpaid:
        return {"eliminated_count": 0, "message": "No unpaid active members to eliminate."}

    eliminated = []
    for member in unpaid:
        # Forfeit the slot — no refund
        crud_user.update_user(
            db,
            member.id,
            UserUpdate(status=UserStatus.Eliminated, current_pool_id=None, late_fees_inr=Decimal("0")),
        )

        # Pull next replacement from waitlist
        replacement = (
            db.query(User)
            .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
            .order_by(User.join_date)
            .first()
        )
        if replacement and member.current_pool_id:
            crud_user.update_user(
                db,
                replacement.id,
                UserUpdate(status=UserStatus.Active, current_pool_id=member.current_pool_id, current_level=1),
            )
            db.refresh(replacement)
            from app.services.draw import _issue_referral_token
            _issue_referral_token(db, replacement)

        eliminated.append({
            "user_id": member.id,
            "username": member.username,
            "forfeited_late_fees_inr": float(member.late_fees_inr or 0),
            "replaced_by": replacement.username if replacement else None,
        })

    return {
        "eliminated_count": len(eliminated),
        "eliminated": eliminated,
        "message": f"{len(eliminated)} unpaid member(s) eliminated. Slots forfeited.",
    }
