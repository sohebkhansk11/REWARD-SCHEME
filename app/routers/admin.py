from decimal import Decimal
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from dataclasses import asdict

from app.core.config import LATE_FEE_DAILY_INR
from app.database import get_db, get_pool_status
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
    UpdateReferralRewardRequest,
    ReferralRewardResponse,
    UpdateDrawScheduleRequest,
    DrawScheduleResponse,
    DissolvePoolRequest,
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


# ── System Health Watchdog ────────────────────────────────────────────────────

@router.get("/admin/health")
def get_system_health(db: Session = Depends(get_db)):
    """
    Real-time system health snapshot — called by the Diagnostics page every 30 s.

    Returns:
      db_reachable          — True if a test query succeeds within connect_timeout
      db_pool               — Connection pool utilisation stats from SQLAlchemy
      active_users          — Users in Active status (in pools)
      waitlist_count        — Users waiting for pool assignment
      pools_active          — Pools with status=Active
      pools_paused          — Pools paused (SafeStopped / awaiting members)
      pools_under_capacity  — Active+Paused pools with < 12 members
      last_draw_at          — ISO timestamp of the most recent completed draw
      last_pool_created_at  — ISO timestamp of the most recently created pool
      checked_at            — ISO timestamp of this response
    """
    checked_at = datetime.now(timezone.utc).isoformat()

    # ── Database connectivity check ───────────────────────────────────────────
    db_reachable = False
    db_error: str | None = None
    try:
        db.execute(text("SELECT 1"))
        db_reachable = True
    except Exception as exc:
        db_error = str(exc)

    # ── Pool stats ────────────────────────────────────────────────────────────
    pool_status_snap = {}
    try:
        pool_status_snap = get_pool_status()
    except Exception:
        pass

    # ── User & pool counts ────────────────────────────────────────────────────
    active_users   = 0
    waitlist_count = 0
    pools_active   = 0
    pools_paused   = 0
    pools_under_cap = 0
    last_draw_at: str | None   = None
    last_pool_at:  str | None  = None

    try:
        active_users   = db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar()   or 0
        waitlist_count = db.query(func.count(User.id)).filter(User.status == UserStatus.Waitlist).scalar() or 0
        pools_active   = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Active).scalar()   or 0
        pools_paused   = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Paused_Awaiting_Members).scalar() or 0

        # Count pools where active members < POOL_CAPACITY (12)
        all_op_pools = (
            db.query(Pool)
            .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
            .all()
        )
        for p in all_op_pools:
            members_count = (
                db.query(func.count(User.id))
                .filter(User.current_pool_id == p.id, User.status == UserStatus.Active)
                .scalar() or 0
            )
            if members_count < 12:
                pools_under_cap += 1

        # Last draw timestamp
        from app.models.draw_history import DrawHistory
        last_dh = (
            db.query(DrawHistory.draw_timestamp)
            .order_by(DrawHistory.draw_timestamp.desc())
            .first()
        )
        if last_dh:
            last_draw_at = last_dh[0].isoformat() if last_dh[0] else None

        # Last pool created
        last_p = (
            db.query(Pool.created_at)
            .order_by(Pool.created_at.desc())
            .first()
        )
        if last_p and last_p[0]:
            last_pool_at = last_p[0].isoformat()

    except Exception:
        pass   # partial data is still useful; db_reachable=False signals the root cause

    # ── Capacity utilisation rating ───────────────────────────────────────────
    # "critical" when DB pool is 80%+ full OR DB is unreachable
    checked_out  = pool_status_snap.get("checked_out", 0)
    total_cap    = pool_status_snap.get("total_capacity", 40)
    utilisation  = round(checked_out / max(total_cap, 1) * 100, 1)
    if not db_reachable:
        health_rating = "critical"
    elif utilisation >= 80:
        health_rating = "warning"
    elif utilisation >= 60:
        health_rating = "caution"
    else:
        health_rating = "healthy"

    return {
        "checked_at":          checked_at,
        "health_rating":       health_rating,
        "db_reachable":        db_reachable,
        "db_error":            db_error,
        "db_pool":             pool_status_snap,
        "db_pool_utilisation_pct": utilisation,
        "active_users":        active_users,
        "waitlist_count":      waitlist_count,
        "pools_active":        pools_active,
        "pools_paused":        pools_paused,
        "pools_under_capacity": pools_under_cap,
        "last_draw_at":        last_draw_at,
        "last_pool_created_at": last_pool_at,
    }


# ── Pipeline Health ──────────────────────────────────────────────────────────

@router.get("/admin/pipeline-health")
def get_pipeline_health(db: Session = Depends(get_db)):
    """
    Comprehensive pipeline health snapshot — includes DB connection pool,
    user/pool counts, injection task status, and data integrity last run.

    Called by the Diagnostics page every 30 s.  More detailed than /admin/health.
    """
    from datetime import datetime, timezone as _tz
    from app.database import get_pool_status as _gps
    from app.models.pool import PoolStatus as _PS

    checked_at = datetime.now(_tz.utc).isoformat()

    # ── DB pool ───────────────────────────────────────────────────────────────
    pool_snap: dict = {}
    db_reachable = False
    try:
        db.execute(text("SELECT 1"))
        db_reachable = True
        pool_snap    = _gps()
    except Exception as exc:
        pool_snap    = {"error": str(exc)}

    # ── User/pool counts ──────────────────────────────────────────────────────
    try:
        active_users   = db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar()   or 0
        waitlist_count = db.query(func.count(User.id)).filter(User.status == UserStatus.Waitlist).scalar() or 0
        pools_active   = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Active).scalar()   or 0
        pools_paused   = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Paused_Awaiting_Members).scalar() or 0

        # Pools with fewer than 12 active members (under capacity)
        all_op_pools = (
            db.query(Pool)
            .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
            .all()
        )
        pools_under_cap = sum(
            1 for p in all_op_pools
            if (db.query(func.count(User.id))
                .filter(User.current_pool_id == p.id, User.status == UserStatus.Active)
                .scalar() or 0) < 12
        )
    except Exception:
        active_users = waitlist_count = pools_active = pools_paused = pools_under_cap = None

    # ── Last draw timestamp ───────────────────────────────────────────────────
    last_draw_at: str | None = None
    try:
        from app.models.draw_history import DrawHistory
        dh = db.query(DrawHistory.draw_timestamp).order_by(DrawHistory.draw_timestamp.desc()).first()
        if dh and dh[0]: last_draw_at = dh[0].isoformat()
    except Exception:
        pass

    # ── Last pool created ──────────────────────────────────────────────────────
    last_pool_at: str | None = None
    try:
        lp = db.query(Pool.created_at).order_by(Pool.created_at.desc()).first()
        if lp and lp[0]: last_pool_at = lp[0].isoformat()
    except Exception:
        pass

    # ── Injection background tasks ─────────────────────────────────────────────
    try:
        from app.routers.dev import _INJECT_STATUS, _INJECT_LOCK
        with _INJECT_LOCK:
            running_injects = sum(1 for v in _INJECT_STATUS.values() if v.get("status") == "running")
    except Exception:
        running_injects = 0

    # ── Data integrity last run ────────────────────────────────────────────────
    # We don't persist the last-run time yet, so approximate from the scheduler log
    integrity_last_run: str | None = None   # future: persist in SystemSettings

    utilisation = round(
        pool_snap.get("checked_out", 0) / max(pool_snap.get("total_capacity", 40), 1) * 100, 1
    )
    health_rating = (
        "critical" if not db_reachable
        else "warning" if utilisation >= 80
        else "caution" if utilisation >= 60
        else "healthy"
    )

    return {
        "checked_at":              checked_at,
        "health_rating":           health_rating,
        "db_reachable":            db_reachable,
        "db_pool":                 pool_snap,
        "db_pool_utilisation_pct": utilisation,
        "active_users":            active_users,
        "waitlist_count":          waitlist_count,
        "pools_active":            pools_active,
        "pools_paused":            pools_paused,
        "pools_under_capacity":    pools_under_cap,
        "last_draw_at":            last_draw_at,
        "last_pool_created_at":    last_pool_at,
        "injection_tasks_running": running_injects,
        "data_integrity_last_run": integrity_last_run,
    }


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


# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ── SSOT RECONCILIATION (A2 — Jun-21) ──────────────────────────────────────────
@router.get("/admin/stats/reconciliation")
def get_reconciliation_stats(db: Session = Depends(get_db)):
    """
    SINGLE SOURCE OF TRUTH (SSOT) for every dashboard headline.

    The user's complaint — "pool shows 84 active, where did 577 go?" and "each
    statistic frontend shows different data" — is caused by every view computing
    its own denominator: server counts vs a client-side .filter() over a
    truncated /users/?limit=500 page vs pools.length (which still includes
    dissolved pools).  This endpoint is the ONE authoritative, server-computed
    payload that every view MUST consume so they can never disagree again.

    MONEY-GRADE GUARANTEES:
      • Every count is computed authoritatively from the User table (membership
        truth) and the Pool table (pool-status truth) — NEVER from the
        denormalized pool.total_members counter.
      • pool.total_members is instead AUDITED here (stored vs live Active) and the
        drift is reported as a health signal, not used as a source.
      • The reconciliation identities the dashboard must satisfy are computed and
        flagged explicitly:
            total_rows == Active + Waitlist + Eliminated + Eliminated_Won
            Active     == in_live_pool + orphans
    """
    from app.core.config import POOL_CAPACITY

    # ── 1. Users by status (authoritative head-counts) ─────────────────────────
    by_status = dict(
        db.query(User.status, func.count(User.id)).group_by(User.status).all()
    )
    active_total     = by_status.get(UserStatus.Active, 0)
    waitlist_total   = by_status.get(UserStatus.Waitlist, 0)
    eliminated_total = by_status.get(UserStatus.Eliminated, 0)
    won_total        = by_status.get(UserStatus.Eliminated_Won, 0)
    total_users      = db.query(func.count(User.id)).scalar() or 0
    status_sum       = active_total + waitlist_total + eliminated_total + won_total

    # ── 2. Active-member PLACEMENT (where each Active member physically sits) ───
    pool_status = {pid: st for pid, st in db.query(Pool.id, Pool.status).all()}
    in_active_pool = in_paused_pool = orphan_dissolved = orphan_null = orphan_other = 0
    for (pid,) in (
        db.query(User.current_pool_id)
        .filter(User.status == UserStatus.Active)
        .all()
    ):
        if pid is None:
            orphan_null += 1
        elif pid not in pool_status:
            orphan_dissolved += 1                        # points at a row that's gone
        elif pool_status[pid] == PoolStatus.Merged_Dissolved:
            orphan_dissolved += 1
        elif pool_status[pid] == PoolStatus.Paused_Awaiting_Members:
            in_paused_pool += 1
        elif pool_status[pid] in (
            PoolStatus.Active, PoolStatus.Full, PoolStatus.Waiting,
        ):
            in_active_pool += 1
        else:
            orphan_other += 1
    orphans_total = orphan_dissolved + orphan_null + orphan_other
    in_live_pool  = in_active_pool + in_paused_pool

    # ── 3. Pools by status ─────────────────────────────────────────────────────
    pools_by_status = dict(
        db.query(Pool.status, func.count(Pool.id)).group_by(Pool.status).all()
    )
    pools_active    = pools_by_status.get(PoolStatus.Active, 0)
    pools_paused    = pools_by_status.get(PoolStatus.Paused_Awaiting_Members, 0)
    pools_full      = pools_by_status.get(PoolStatus.Full, 0)
    pools_waiting   = pools_by_status.get(PoolStatus.Waiting, 0)
    pools_dissolved = pools_by_status.get(PoolStatus.Merged_Dissolved, 0)
    pools_total     = db.query(func.count(Pool.id)).scalar() or 0
    pools_live      = pools_total - pools_dissolved      # the number the dashboard shows

    # ── 4. Active members per level (L1..L6) ───────────────────────────────────
    level_rows = dict(
        db.query(User.current_level, func.count(User.id))
        .filter(User.status == UserStatus.Active)
        .group_by(User.current_level)
        .all()
    )
    per_level = {f"L{lvl}": int(level_rows.get(lvl, 0)) for lvl in range(1, 7)}
    per_level_other = sum(
        int(c) for lvl, c in level_rows.items()
        if lvl is None or lvl < 1 or lvl > 6
    )

    # ── 5. Winners + money (deposits in / payouts out) ─────────────────────────
    total_payout = db.query(func.sum(Token.value_inr)).filter(
        Token.type == TokenType.Withdraw, Token.status == TokenStatus.Burned
    ).scalar() or 0
    total_capital = db.query(func.sum(Token.value_inr)).filter(
        Token.type == TokenType.Deposit, Token.status == TokenStatus.Burned
    ).scalar() or 0

    # ── 6. pool.total_members staleness audit (HEALTH SIGNAL, not a source) ────
    live_counts = dict(
        db.query(User.current_pool_id, func.count(User.id))
        .filter(User.status == UserStatus.Active, User.current_pool_id.isnot(None))
        .group_by(User.current_pool_id)
        .all()
    )
    stale_pool_counters = 0
    dissolved_with_members = 0
    sum_stored_live = 0
    for p in db.query(Pool).all():
        stored = p.total_members or 0
        actual = int(live_counts.get(p.id, 0))
        if p.status == PoolStatus.Merged_Dissolved:
            if actual > 0:
                dissolved_with_members += 1
            if stored != 0:
                stale_pool_counters += 1
        else:
            sum_stored_live += stored
            if stored != actual:
                stale_pool_counters += 1

    # ── 7. reconciliation identities + overall integrity verdict ───────────────
    status_sum_ok    = (status_sum == total_users)
    placement_sum    = in_live_pool + orphans_total
    placement_ok     = (placement_sum == active_total)
    integrity_ok = (
        status_sum_ok and placement_ok
        and orphans_total == 0
        and dissolved_with_members == 0
        and stale_pool_counters == 0
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pool_capacity": POOL_CAPACITY,
        "users": {
            "total":          total_users,
            "active":         active_total,
            "waitlist":       waitlist_total,
            "eliminated":     eliminated_total,
            "eliminated_won": won_total,
            "status_sum":     status_sum,
            "status_sum_ok":  status_sum_ok,
        },
        "active_placement": {
            "in_active_pool":   in_active_pool,
            "in_paused_pool":   in_paused_pool,
            "in_live_pool":     in_live_pool,
            "orphan_dissolved": orphan_dissolved,
            "orphan_null":      orphan_null,
            "orphan_other":     orphan_other,
            "orphans_total":    orphans_total,
            "placement_sum":    placement_sum,
            "placement_ok":     placement_ok,
        },
        "pools": {
            "total":     pools_total,
            "live":      pools_live,
            "active":    pools_active,
            "paused":    pools_paused,
            "full":      pools_full,
            "waiting":   pools_waiting,
            "dissolved": pools_dissolved,
        },
        "active_by_level": {**per_level, "other": per_level_other},
        "winners": {
            "total":            won_total,
            "total_payout_inr": float(total_payout),
        },
        "capital": {
            "total_deposits_inr": float(total_capital),
        },
        "integrity": {
            "ok":                          integrity_ok,
            "orphans_total":               orphans_total,
            "stale_pool_counters":         stale_pool_counters,
            "dissolved_with_members":      dissolved_with_members,
            "sum_stored_total_members_live": sum_stored_live,
            "sum_actual_active_in_pools":  in_live_pool,
        },
        # ── Flat back-compat headline fields (simple consumers / fallbacks) ────
        "active_users":   active_total,
        "waitlist_count": waitlist_total,
        "active_pools":   pools_active,
        "live_pools":     pools_live,
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
    Admin: manually trigger the Double-FIFO Auto-Refill Engine.

    Phase 1 — FIFO fill existing vacancies (oldest pool first, oldest user first).
    Phase 2 — Create a new pool if remaining waitlist >= pool_creation_threshold.
    """
    from app.services.waitlist import assign_waitlist_to_pools

    result = assign_waitlist_to_pools(db)

    paid_count: int = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .count()
    )

    p1 = result["phase1_assigned"]
    p2 = result["phase2_pool_created"]

    new_pool: Pool | None = (
        db.query(Pool).filter(Pool.name == p2).first() if p2 else None
    )

    if new_pool:
        return WaitlistCheckResponse(
            paid_waitlist_count=paid_count,
            pool_created=PoolResponse.model_validate(new_pool),
            message=(
                f"New pool '{new_pool.name}' created with 12 members. "
                f"Also filled {p1} vacancy slot(s) in existing pools."
            ),
        )

    return WaitlistCheckResponse(
        paid_waitlist_count=paid_count,
        pool_created=None,
        message=(
            f"Phase 1: {p1} member(s) assigned to existing pools. "
            f"Phase 2: {paid_count} paid Waitlist member(s) remain "
            f"(threshold not met — no new pool created)."
        ),
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
    from app.services.settings import get_pool_threshold, get_adaptive_threshold_info
    threshold          = get_pool_threshold(db)
    adaptive_info      = get_adaptive_threshold_info(db)
    effective_threshold = adaptive_info["effective_threshold"]
    return ThresholdResponse(
        pool_creation_threshold=effective_threshold,
        message=(
            f"Base threshold: {threshold}. "
            f"Effective (adaptive): {effective_threshold}. "
            f"{adaptive_info['note']}"
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


# ── Adaptive Threshold Info ───────────────────────────────────────────────────

@router.get("/admin/settings/adaptive-threshold")
def get_adaptive_threshold_detail(db: Session = Depends(get_db)):
    """
    POINT 7 — Return full adaptive threshold calculation with explanation.

    Shows WHY the effective threshold differs from the admin-set base threshold.
    Useful for diagnosing why new pools are (or aren't) forming.
    """
    from app.services.settings import get_adaptive_threshold_info
    return get_adaptive_threshold_info(db)


# ── System Settings — Configurable Referral Reward ───────────────────────────

@router.get("/admin/settings/referral-reward", response_model=ReferralRewardResponse)
def get_referral_reward_setting(db: Session = Depends(get_db)):
    """
    Return the current per-referral reward amount (INR).

    This is the amount credited to a referrer's accumulated_referral_bonus_inr
    each time a user they referred ENTERS an active pool (Rule 39).
    Default: ₹250.  Configurable via PUT /admin/settings/referral-reward.
    """
    from app.services.settings import get_referral_reward
    amount = get_referral_reward(db)
    status_note = "Referral rewards DISABLED (₹0)." if amount == 0 else f"₹{amount} credited per qualifying pool entry."
    return ReferralRewardResponse(
        referral_reward_inr=amount,
        message=status_note,
    )


@router.put("/admin/settings/referral-reward", response_model=ReferralRewardResponse)
def update_referral_reward_setting(
    body: UpdateReferralRewardRequest,
    admin_username: str = Depends(require_admin_jwt),
    db: Session = Depends(get_db),
):
    """
    Update the per-referral reward amount.

    Security gate: the admin's account password is required alongside
    new_amount_inr.  The password is bcrypt-verified before the change is
    persisted.  This prevents accidental changes to a financial parameter.

    The new value takes effect immediately for every subsequent pool-entry
    event — no server restart required (60-second cache, invalidated on save).

    Setting to 0 disables referral rewards without any code change.
    Referral count statistics are still tracked even at ₹0.
    """
    from app.models.admin import Admin as AdminModel
    from app.services.settings import set_referral_reward

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
            detail="Admin password verification failed. Referral reward was NOT changed.",
        )

    # ── Persist new reward ────────────────────────────────────────────────────
    try:
        new_val = set_referral_reward(db, body.new_amount_inr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    status_note = (
        "Referral rewards DISABLED — no bonus will be credited on future pool entries."
        if new_val == 0 else
        f"Referral reward updated to ₹{new_val}. "
        "Credited immediately on next qualifying pool entry (Rule 39)."
    )
    return ReferralRewardResponse(
        referral_reward_inr=new_val,
        message=status_note,
    )


# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Draw Calendar settings — runtime-configurable draw timing.
# GET reads current schedule; PUT requires admin password to change.

@router.get("/admin/settings/draw-schedule", response_model=DrawScheduleResponse)
def get_draw_schedule_setting(db: Session = Depends(get_db)):
    """
    Return the current draw schedule (day, UTC time, prep window).

    Default: Sunday 13:30 UTC (7:00 PM IST), T-2H prep window.
    Configurable via PUT /admin/settings/draw-schedule without a server restart.
    The scheduler picks up new timing on the NEXT scheduled APScheduler fire.
    """
    from app.services.settings import get_draw_schedule
    sched = get_draw_schedule(db)
    return DrawScheduleResponse(
        draw_hour_utc   = sched["draw_hour_utc"],
        draw_minute_utc = sched["draw_minute_utc"],
        draw_prep_hours = sched["draw_prep_hours"],
        draw_time_ist   = sched["draw_time_ist"],
        draw_day        = sched["draw_day"],
        message         = (
            f"Draw scheduled every {sched['draw_day']} at "
            f"{sched['draw_hour_utc']:02d}:{sched['draw_minute_utc']:02d} UTC "
            f"({sched['draw_time_ist']}). "
            f"Preparation starts {sched['draw_prep_hours']}h before draw time."
        ),
    )


@router.put("/admin/settings/draw-schedule", response_model=DrawScheduleResponse)
def update_draw_schedule_setting(
    body:           UpdateDrawScheduleRequest,
    admin_username: str     = Depends(require_admin_jwt),
    db:             Session = Depends(get_db),
):
    """
    Update the weekly draw schedule.

    Security gate: admin account password required.  Changes the UTC draw hour,
    minute, and T-2H prep window.  The APScheduler jobs on Render pick up the
    new values on the next fire — no redeploy needed.

    Draw day is always Sunday.  To change the draw day, a code change is required.
    """
    from app.models.admin import Admin as AdminModel
    from app.services.settings import set_draw_schedule
    from app.services.auth import verify_password

    admin: AdminModel | None = (
        db.query(AdminModel).filter(AdminModel.username == admin_username).first()
    )
    if not admin:
        raise HTTPException(status_code=401, detail="Admin account not found — re-authenticate.")

    dummy  = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    stored = admin.hashed_password or dummy
    if not verify_password(body.admin_password, stored):
        raise HTTPException(
            status_code=401,
            detail="Admin password verification failed. Draw schedule was NOT changed.",
        )

    try:
        sched = set_draw_schedule(
            db,
            draw_hour_utc   = body.draw_hour_utc,
            draw_minute_utc = body.draw_minute_utc,
            draw_prep_hours = body.draw_prep_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return DrawScheduleResponse(
        draw_hour_utc   = sched["draw_hour_utc"],
        draw_minute_utc = sched["draw_minute_utc"],
        draw_prep_hours = sched["draw_prep_hours"],
        draw_time_ist   = sched["draw_time_ist"],
        draw_day        = sched["draw_day"],
        message         = (
            f"Draw schedule updated: every {sched['draw_day']} at "
            f"{sched['draw_hour_utc']:02d}:{sched['draw_minute_utc']:02d} UTC "
            f"({sched['draw_time_ist']}). "
            f"Prep window: {sched['draw_prep_hours']}h before draw. "
            "Takes effect on the next APScheduler fire — no server restart needed."
        ),
    )


# ── SDE Extension II/III Check ────────────────────────────────────────────────

@router.post("/admin/sde/run-extensions")
def run_sde_extensions(db: Session = Depends(get_db)):
    """
    POINT 2+3 — Manually trigger SDE Extension II/III check and execution.

    Scans ALL active pools for L5 (Ext-II) or L6 (Ext-III) members and runs
    forced-exit draws for each.  Normally this runs automatically at the start
    of execute_weekly_draw().  Use this endpoint if the weekly draw was skipped
    or if L5/L6 members need to be cleared immediately.

    Returns list of draws executed (if any).
    """
    from app.services.sde_engine import check_and_run_sde_extensions
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"

    results = check_and_run_sde_extensions(db, week_id)
    return {
        "week_id":        week_id,
        "draws_executed": len(results),
        "draws": [
            {
                "pool_id":             r.pool_id,
                "pool_name":           r.pool_name,
                "draw_type":           r.draw_type,
                "upper_winner":        {
                    "level":      r.upper_winner_level,
                    "payout_inr": float(r.upper_winner_payout),
                },
                "lower_winner":        {
                    "level":      r.lower_winner_level,
                    "payout_inr": float(r.lower_winner_payout),
                },
                "drawdown_projection": r.drawdown_projection,
            }
            for r in results
        ],
        "note": (
            f"{len(results)} SDE Ext-II/III draw(s) executed. "
            "L5/L6 members have been forced to exit their pools."
            if results else
            "No L5 or L6 members found across any active pools. System is healthy."
        ),
    }


# ── Accelerated Dissolution ───────────────────────────────────────────────────

@router.post("/admin/pools/{pool_id}/accelerated-dissolution")
def trigger_accelerated_dissolution(
    pool_id: int,
    db: Session = Depends(get_db),
):
    """
    POINT 5 — Trigger accelerated dissolution for a specific pool.

    Used when a pool has ≥60% L4+ members and normal weekly draws are too slow
    to clear the upper-tier backlog.  Both winners are drawn from L4+ tier.
    A new relief pool is automatically created from waitlist if available.

    Conditions checked:
      • Pool must be Active
      • Pool must not have drawn this week yet
      • Pool must have ≥ 2 L4+ members

    Returns the draw result and dissolution status.
    """
    from app.services.draw import run_accelerated_dissolution_draw, check_accelerated_dissolution
    from app.models.pool import Pool as PoolModel

    pool = db.query(PoolModel).filter(PoolModel.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail=f"Pool {pool_id} not found.")

    # Show the current L4+ ratio alongside the result
    from app.models.user import User as UserModel, UserStatus as US
    members = db.query(UserModel).filter(
        UserModel.current_pool_id == pool_id,
        UserModel.status == US.Active,
    ).all()
    l4plus_count = sum(1 for m in members if m.current_level >= 4)
    l4plus_ratio = l4plus_count / max(1, len(members))

    try:
        result = run_accelerated_dissolution_draw(db, pool_id, create_relief_pool=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "pool_id":         pool_id,
        "pool_name":       pool.name,
        "l4plus_ratio_pct": round(l4plus_ratio * 100, 1),
        "winner_upper": {
            "username":   result.winner_1.winner_username,
            "level":      result.winner_1.winner_level,
            "payout_inr": float(result.winner_1.net_payout_inr),
        },
        "winner_lower": {
            "username":   result.winner_2.winner_username,
            "level":      result.winner_2.winner_level,
            "payout_inr": float(result.winner_2.net_payout_inr),
        },
        "relief_pool_created": result.relief_pool_id is not None,
        "relief_pool_id":      result.relief_pool_id,
        "pool_dissolved":      result.pool_dissolved,
        "note": (
            f"Pool dissolved — {len(members) - 2} members returned to waitlist for redistribution."
            if result.pool_dissolved else
            f"Accelerated draw complete — 2 L4+ members exited. Pool continues."
        ),
    }


# ── Manual Pool Dissolver (Point 5 — donor↔receiver merger) ──────────────────

# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Manual pool dissolver button backend (Point 5).  Jun-21.
@router.post("/admin/pools/{pool_id}/dissolve")
def dissolve_pool_manual(
    pool_id: int,
    body: DissolvePoolRequest,
    admin_username: str = Depends(require_admin_jwt),
    db: Session = Depends(get_db),
):
    """
    POINT 5 — MANUAL pool dissolver (donor↔receiver merger).

    Relocates EVERY Active member of the chosen pool into other live pools,
    fully PRESERVING each member's journey (current_level, weekly_payment_status,
    join_date, sde_required / sde_flagged_week are NEVER touched — only
    current_pool_id and the dynamic_merges_experienced counter change), then
    marks the emptied pool Merged_Dissolved.  No draw runs, nobody is paid,
    nobody is demoted to the waitlist, and NO level is reset.

    This is fundamentally DIFFERENT from accelerated dissolution, which runs a
    DRAW (pays 2 L4+ winners) and returns survivors to the WAITLIST at Level 1.

    Receivers are oldest-first under-capacity live pools (Active /
    Paused_Awaiting_Members), excluding the donor; if no vacancy exists fresh
    Active pools are created for the overflow.  SDE-flagged members carry their
    flag and every receiver's contains_flagged_l4 is recomputed so SDE routing
    stays correct.  The whole operation is one atomic transaction.

    Security gate: the admin's account password is required in the request body
    and is bcrypt-verified before anything is moved.  This prevents accidental
    mis-clicks and CSRF-style tampering on a money-bearing structural change.
    """
    from app.models.admin import Admin as AdminModel
    from app.models.pool import Pool as PoolModel, PoolStatus as PS

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
            detail="Admin password verification failed. Pool was NOT dissolved.",
        )

    # ── Existence / state pre-check (friendly 404 / 400 before the move) ──────
    pool = db.query(PoolModel).filter(PoolModel.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail=f"Pool {pool_id} not found.")
    if pool.status == PS.Merged_Dissolved:
        raise HTTPException(status_code=400, detail=f"Pool '{pool.name}' is already dissolved.")

    # ── Execute the donor↔receiver dissolve (atomic, money-safe) ──────────────
    try:
        result = svc_waitlist.dissolve_pool_manually(db, pool_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # ROUTE-VIA-REASSESSMENT (Task 2): the dissolve has structurally changed the pool
    # layout (members relocated into receivers / fresh pools).  Route it through the
    # virtual integrity gate so the resulting structure is re-verified + recorded
    # (locked decision #3 — VALIDATE + REPORT, never roll back the dissolve, which is
    # already a level-preserving move).  Failure-isolated + fail-closed inside the
    # helper; the dissolve is already committed, so a gate error cannot undo it.
    try:
        from app.services.pool_reassessor import route_pool_change_via_reassessment
        from app.services.draw_preparation import _make_week_id
        from datetime import datetime, timezone
        _wk = _make_week_id(datetime.now(timezone.utc))
        _rep = route_pool_change_via_reassessment(
            db, _wk, trigger="manual_dissolve", commit=True,
        )
        if _rep is not None:
            result["reassessment"] = {
                "week_id":        _wk,
                "report_id":      _rep.id,
                "verdict":        _rep.verdict,
                "is_active_hold": (_rep.verdict == "HOLD" and not bool(_rep.approved)),
            }
    except Exception as _ra_exc:
        # Reporting only — a re-assessment failure must never fail the dissolve, which
        # is already durable.  Surface it softly so the admin knows to check the panel.
        result["reassessment"] = {"error": str(_ra_exc)}

    result["note"] = (
        f"Pool '{result['pool_name']}' dissolved — {result['members_relocated']} "
        f"member(s) relocated into {len(result['receivers'])} pool(s) "
        f"({result['new_pools_created']} newly created). Levels & journeys preserved; "
        "no draw, no payout."
        if result["members_relocated"] else
        f"Pool '{result['pool_name']}' was empty — dissolved with no members to relocate."
    )
    return result


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

def _unique_penalty_code(db: Session, prefix: str) -> str:
    """
    Collision-safe token code generator for compliance penalty tokens.
    Uses os.urandom via secrets — NOT the MT19937 PRNG.
    Format: "{prefix}{6 uppercase alphanumeric chars}"  e.g. "LF-A3KZ9W"
    """
    import secrets, string
    from app.crud.token import get_token_by_code
    _alpha = string.ascii_uppercase + string.digits
    while True:
        code = prefix + "".join(secrets.choice(_alpha) for _ in range(6))
        if not get_token_by_code(db, code):
            return code


@router.post("/admin/penalty/apply-daily")
def apply_daily_penalty(db: Session = Depends(get_db)):
    """
    Admin: call once per day (Monday–Saturday) to accrue ₹50 on every Active
    member who has not yet paid for the current week.

    For each penalised member:
      1. Adds LATE_FEE_DAILY_INR (₹50) to user.late_fees_inr.
      2. Creates an immutable Late_Fee token (Burned, ₹50) as a receipt.
         This token represents confirmed cash that will be collected either
         at grace payment (save-seat) or forfeited at elimination.

    The Late_Fee token serves as the audit trail: the token ledger always
    reflects the full late-fee liability, not just the user model field.
    """
    unpaid: list[User] = (
        db.query(User)
        .filter(User.status == UserStatus.Active, User.weekly_payment_status == WeeklyPaymentStatus.Unpaid)
        .all()
    )
    if not unpaid:
        return {"penalised_count": 0, "daily_fee_inr": LATE_FEE_DAILY_INR,
                "message": "No unpaid active members."}

    from app.crud import user as crud_user
    from app.schemas.user import UserUpdate
    from app.core.config import LATE_FEE_MAX_CAP_INR  # ₹500 cap

    _fee_dec = Decimal(str(LATE_FEE_DAILY_INR))
    _cap_dec = Decimal(str(LATE_FEE_MAX_CAP_INR))
    tokens_created = 0

    for member in unpaid:
        current_late = Decimal(str(member.late_fees_inr or 0))

        # Respect the max cap — do not accrue past ₹500 total
        if current_late >= _cap_dec:
            continue   # already at cap, no new accrual or token

        accrual = min(_fee_dec, _cap_dec - current_late)   # partial if near cap
        new_late = current_late + accrual
        crud_user.update_user(db, member.id, UserUpdate(late_fees_inr=new_late))

        # Create immutable Late_Fee token — receipt of this day's accrual
        code = _unique_penalty_code(db, "LF-")
        db.add(Token(
            code      = code,
            type      = TokenType.Late_Fee,
            status    = TokenStatus.Burned,
            value_inr = accrual,
            user_id   = member.id,
            pool_id   = member.current_pool_id,
        ))
        tokens_created += 1

    db.commit()
    return {
        "penalised_count":   len(unpaid),
        "tokens_created":    tokens_created,
        "daily_fee_inr":     LATE_FEE_DAILY_INR,
        "max_cap_inr":       LATE_FEE_MAX_CAP_INR,
        "message": (
            f"₹{LATE_FEE_DAILY_INR} penalty accrued on {len(unpaid)} unpaid member(s). "
            f"{tokens_created} Late_Fee token(s) created as receipts."
        ),
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

    # Double-FIFO refill: fill vacancies from eliminations AND check Phase 2 threshold
    from app.services.waitlist import assign_waitlist_to_pools
    refill = assign_waitlist_to_pools(db)
    p1 = refill["phase1_assigned"]
    p2 = refill["phase2_pool_created"]

    return {
        "eliminated_count": len(eliminated),
        "eliminated":       eliminated,
        "fifo_filled":      p1,
        "new_pool_created": p2,
        "message": (
            f"{len(eliminated)} unpaid member(s) eliminated. "
            f"Phase 1: {p1} waitlist member(s) assigned via FIFO fill."
            + (f" Phase 2: new pool '{p2}' created." if p2 else "")
        ),
    }
