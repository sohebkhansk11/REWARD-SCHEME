from decimal import Decimal
from datetime import datetime, timezone
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
    UpdateThresholdRequest,
    ThresholdResponse,
)
from app.schemas.token import TokenResponse
from app.services import tokens as svc_tokens
from app.services import waitlist as svc_waitlist
from app.services import draw as svc_draw
from app.models.user import User
from app.schemas.user import UserResponse
from app.schemas.pool import PoolResponse, PoolUpdate
from app.core.security import require_admin_jwt

# Every endpoint on this router requires a valid Admin JWT.
# The JWT is validated by require_admin_jwt before the handler runs.
router = APIRouter(tags=["Admin"], dependencies=[Depends(require_admin_jwt)])


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
def burn_token(code: str, db: Session = Depends(get_db)):
    """
    Admin: mark a Withdraw or Referral token as Burned once the cash/UPI/USDT
    payout has been physically handed to the user.

    Accepts:
    - WIT-XXXXXX  (winner payout, ₹2,000 – ₹8,000)
    - REF-XXXXXX  (referral reward, ₹250)
    """
    from app.crud import token as crud_token
    from app.schemas.token import TokenUpdate

    token = crud_token.get_token_by_code(db, code)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.type not in (TokenType.Withdraw, TokenType.Referral):
        raise HTTPException(
            status_code=400,
            detail="Only Withdraw (WIT-) or Referral (REF-) tokens can be burned.",
        )
    if token.status == TokenStatus.Burned:
        raise HTTPException(status_code=400, detail="Token is already burned.")

    return crud_token.update_token(
        db, token.id,
        TokenUpdate(status=TokenStatus.Burned, redeemed_at=datetime.now(timezone.utc)),
    )


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

    Step 1 — FIFO fill: assign paid Waitlist members to any existing pool
              vacancies (pools sitting below 12 members).
    Step 2 — Scale check: if ≥24 paid Waitlist members still remain after
              vacancy fill, create a new pool of 12.
    """
    from app.services.waitlist import fill_pool_vacancies

    # Step 1 — fill existing vacancies first
    fill_assignments = fill_pool_vacancies(db)

    paid_count: int = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .count()
    )

    # Step 2 — scale check for new pool creation
    new_pool: Pool | None = svc_waitlist.check_and_scale_waitlist(db)

    filled_msg = (
        f" Also filled {len(fill_assignments)} existing pool vacancy(s)."
        if fill_assignments else ""
    )

    if new_pool:
        return WaitlistCheckResponse(
            paid_waitlist_count=paid_count,
            pool_created=PoolResponse.model_validate(new_pool),
            message=f"New pool '{new_pool.name}' created with 12 members.{filled_msg}",
        )

    return WaitlistCheckResponse(
        paid_waitlist_count=paid_count,
        pool_created=None,
        message=f"Waitlist has {paid_count} paid members; {24 - paid_count} more needed to trigger pool creation.{filled_msg}",
    )


# ── System Settings — Configurable Threshold ──────────────────────────────────

@router.get("/admin/settings/threshold", response_model=ThresholdResponse)
def get_threshold(db: Session = Depends(get_db)):
    """
    Return the current pool-creation threshold.

    This is the minimum number of paid Waitlist members that must accumulate
    before check_and_scale_waitlist() creates a new pool automatically.
    Default: 24.  Configurable via PUT /admin/settings/threshold.
    """
    from app.services.settings import get_pool_threshold
    threshold = get_pool_threshold(db)
    return ThresholdResponse(
        pool_creation_threshold=threshold,
        message=(
            f"Current threshold: {threshold} paid Waitlist members needed to auto-trigger a new pool."
        ),
    )


@router.put("/admin/settings/threshold", response_model=ThresholdResponse)
def update_threshold(
    body: UpdateThresholdRequest,
    admin_username: str = Depends(require_admin_jwt),
    db: Session = Depends(get_db),
):
    """
    Update the pool-creation threshold.

    Security gate: the admin's account password is required in the request body
    alongside `new_threshold`.  The password is bcrypt-verified before the
    change is persisted.  This prevents CSRF-style tampering and accidental
    mis-clicks.

    The new value takes effect immediately for every subsequent call to
    check_and_scale_waitlist() — no server restart required.
    """
    from app.models.admin import Admin as AdminModel
    from app.services.settings import set_pool_threshold

    # ── Verify admin password ─────────────────────────────────────────────────
    admin: AdminModel | None = (
        db.query(AdminModel).filter(AdminModel.username == admin_username).first()
    )
    if not admin:
        raise HTTPException(status_code=401, detail="Admin account not found — re-authenticate.")

    dummy = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    stored = admin.hashed_password or dummy
    from app.services.auth import verify_password
    if not verify_password(body.admin_password, stored):
        raise HTTPException(
            status_code=401,
            detail="Admin password verification failed. Threshold was NOT changed.",
        )

    # ── Persist new threshold ─────────────────────────────────────────────────
    new_val = set_pool_threshold(db, body.new_threshold)

    return ThresholdResponse(
        pool_creation_threshold=new_val,
        message=(
            f"Pool-creation threshold updated to {new_val}. "
            "The auto-scale algorithm will now wait for "
            f"{new_val} paid Waitlist members before creating a new pool."
        ),
    )


# ── Pool Settings (auto-creation toggle) ─────────────────────────────────────

@router.get("/admin/pool-settings")
def get_pool_settings():
    """
    Return the current state of the AUTO_POOL_CREATION_ENABLED toggle.
    When disabled, the waitlist auto-scale (24 members → new pool) does NOT fire.
    Use POST /admin/pools/manual-create to form pools manually.
    """
    from app.core.pool_settings import get_auto_pool_creation
    enabled = get_auto_pool_creation()
    return {
        "auto_pool_creation_enabled": enabled,
        "message": (
            "Pools are created automatically when 24 paid Waitlist members accumulate."
            if enabled else
            "Auto pool creation is DISABLED. Use POST /admin/pools/manual-create."
        ),
    }


@router.post("/admin/pool-settings/auto-creation")
def set_pool_auto_creation(enabled: bool, db: Session = Depends(get_db)):
    """
    Toggle the AUTO_POOL_CREATION_ENABLED flag.

    Pass `?enabled=true` or `?enabled=false` as a query parameter.

    When switching back to enabled=True, immediately runs the scale check so
    any backed-up waitlist members get pooled without a manual trigger.
    """
    from app.core.pool_settings import set_auto_pool_creation
    set_auto_pool_creation(enabled)

    bonus_msg = ""
    if enabled:
        new_pool = svc_waitlist.check_and_scale_waitlist(db)
        if new_pool:
            bonus_msg = f" Immediately created '{new_pool.name}' from backed-up waitlist."

    return {
        "auto_pool_creation_enabled": enabled,
        "message": (
            f"Auto pool creation {'ENABLED' if enabled else 'DISABLED'}.{bonus_msg}"
        ),
    }


# ── Manual Pool Creation ──────────────────────────────────────────────────────

@router.post("/admin/pools/manual-create")
def manual_create_pool(db: Session = Depends(get_db)):
    """
    Admin: force-create a new Active pool from the oldest paid Waitlist members,
    bypassing the AUTO_POOL_CREATION_ENABLED flag and the 24-member threshold.

    Requires at least NEW_POOL_INTAKE (12) paid Waitlist members to be available.
    After pool creation, also runs FIFO vacancy fill across all active pools.
    """
    from app.services.waitlist import manual_create_pool as svc_manual_create, fill_pool_vacancies

    new_pool = svc_manual_create(db)
    if not new_pool:
        from app.core.config import NEW_POOL_INTAKE
        paid_count = (
            db.query(User)
            .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
            .count()
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Not enough paid Waitlist members to create a pool. "
                f"Need {NEW_POOL_INTAKE}, have {paid_count}."
            ),
        )

    fill_assignments = fill_pool_vacancies(db)

    return {
        "pool_id":      new_pool.id,
        "pool_name":    new_pool.name,
        "members_assigned": new_pool.total_members,
        "fifo_filled_other_pools": len(fill_assignments),
        "message": (
            f"Pool '{new_pool.name}' manually created with {new_pool.total_members} members. "
            f"FIFO fill also assigned {len(fill_assignments)} member(s) to other existing pools."
        ),
    }


# ── Pool Member Count Sync ────────────────────────────────────────────────────

@router.post("/admin/pools/sync-member-counts")
def sync_pool_member_counts(db: Session = Depends(get_db)):
    """
    Admin: recompute and persist pool.total_members for EVERY pool by counting
    Active users actually assigned to each pool.

    Use this to fix dashboard discrepancies caused by stale cached counts
    (e.g. after eliminations that didn't re-sync, or data migrations).
    Returns a list of pools whose stored count differed from reality.
    """
    pools = db.query(Pool).all()
    synced = []
    for pool in pools:
        actual: int = (
            db.query(func.count(User.id))
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .scalar() or 0
        )
        if pool.total_members != actual:
            synced.append({
                "pool_id":   pool.id,
                "pool_name": pool.name,
                "was":       pool.total_members,
                "now":       actual,
            })
            from app.crud import pool as crud_pool
            crud_pool.update_pool(db, pool.id, PoolUpdate(total_members=actual))

    return {
        "synced_count": len(synced),
        "changes":      synced,
        "message": (
            f"{len(synced)} pool(s) had stale member counts and were corrected."
            if synced else
            "All pool member counts are already accurate — no changes needed."
        ),
    }


# ── Dual-Draw ─────────────────────────────────────────────────────────────────

@router.post("/admin/pools/{pool_id}/draw", response_model=DrawResultResponse)
def trigger_draw(pool_id: int, db: Session = Depends(get_db)):
    """
    Admin: run the Smart Pairing Dual-Draw for an active pool.

    Normal mode (pool matured, week 4+):
      Winner 1 — randomly selected from Level 1–3
      Winner 2 — randomly selected from Level 4–6

    Edge-case mode (early weeks 1–3, no L4+ members yet):
      Two distinct winners randomly selected from the available levels.
      edge_case_used = true is returned in the response.

    Post-draw actions (both modes):
      - Level-based Withdraw token generated for each winner.
      - Both winners marked Eliminated_Won.
      - Top 2 paid Waitlist members inserted at Level 1 as replacements.
      - Referral tokens (₹250) issued for any referred replacements.
      - Surviving members advance one level (cap: L6).
      - All pool members reset to Unpaid for the new week.
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
        winner_1=_to_response(result.winner_1),
        winner_2=_to_response(result.winner_2),
        edge_case_used=result.edge_case_used,
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
        # Snapshot the pool_id BEFORE nullifying it — the ORM object's attribute
        # is set to None by update_user, so reading it afterwards always returns
        # None and the inline replacement placement was silently skipped.
        slot_pool_id = member.current_pool_id

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
        if replacement and slot_pool_id:
            crud_user.update_user(
                db,
                replacement.id,
                UserUpdate(status=UserStatus.Active, current_pool_id=slot_pool_id, current_level=1),
            )
            db.refresh(replacement)
            from app.services.draw import _issue_referral_token, _credit_referral_bonus
            # Rule 39: credit referral bonus when replacement enters the active pool.
            if replacement.referred_by_user_id:
                _credit_referral_bonus(db, replacement.referred_by_user_id)
            _issue_referral_token(db, replacement)   # no-op kept for backward compat

        eliminated.append({
            "user_id": member.id,
            "username": member.username,
            "forfeited_late_fees_inr": float(member.late_fees_inr or 0),
            "replaced_by": replacement.username if replacement else None,
        })

    # FIFO fill: immediately reassign all vacancies created by eliminations
    from app.services.waitlist import fill_pool_vacancies
    fill_assignments = fill_pool_vacancies(db)

    return {
        "eliminated_count": len(eliminated),
        "eliminated":       eliminated,
        "fifo_filled":      len(fill_assignments),
        "message": (
            f"{len(eliminated)} unpaid member(s) eliminated. "
            f"{len(fill_assignments)} waitlist member(s) auto-assigned via FIFO fill."
        ),
    }
