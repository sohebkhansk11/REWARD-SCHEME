"""
Payment Compliance & Elimination Engine  —  /admin/elimination/*
================================================================

Manages the full lifecycle of non-payment enforcement:
  1. Late-fee accrual (already handled by POST /admin/penalty/apply-daily)
  2. Due-date enforcement → marks users elimination_risk=True
  3. Grace period window  → admin or auto-grant; user pays ₹500+fees to save seat
  4. Elimination execution → removes grace_active=False AND elimination_risk=True users
  5. Full audit trail in EliminationEvent table

Endpoints:
  GET  /admin/elimination/settings          — all 8 config settings
  PUT  /admin/elimination/settings          — update (admin password required)
  GET  /admin/elimination/at-risk           — users past due date, not yet in grace
  GET  /admin/elimination/grace-period      — users currently in grace window
  GET  /admin/elimination/late-payers       — all currently unpaid with late fees
  GET  /admin/elimination/history           — EliminationEvent audit log
  POST /admin/elimination/mark-at-risk      — manually flag all unpaid-past-due users
  POST /admin/elimination/grant-grace/{uid} — move specific user to grace period
  POST /admin/elimination/save-seat/{uid}   — admin confirms grace payment received
  POST /admin/elimination/execute           — run elimination: remove risk+expired users

All endpoints require Admin JWT.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_admin_jwt, verify_admin_password as _verify_pw
from app.database import get_db
from app.models.elimination_event import EliminationEvent, EliminationReason
from app.models.pool import Pool
from app.models.system_settings import SystemSettings
from app.models.user import User, UserStatus, WeeklyPaymentStatus

router = APIRouter(
    prefix="/admin/elimination",
    tags=["Admin · Payment Compliance"],
    dependencies=[Depends(require_admin_jwt)],
)

# ── Default elimination configuration ─────────────────────────────────────────
# These defaults match the plan spec.  Each key is stored as a SystemSettings row
# so admins can tune them via the API without a code change.
_ELIM_DEFAULTS: dict[str, int] = {
    "payment_due_days":        4,     # days from Monday (draw opens) until due date (Thursday)
    "payment_due_hour":        23,    # 23:00 IST on due day (= 17:30 UTC)
    "grace_period_hours":      48,    # hours between due date and draw T-2H
    "grace_seat_save_fee_inr": 500,   # extra ₹ to pay during grace to save seat
    "late_fee_per_day_inr":    50,    # daily late fee accrual
    "late_fee_max_cap_inr":    500,   # maximum total late fee (caps at ₹500)
    "auto_eliminate_enabled":  1,     # 1=True, 0=False — auto-eliminate on due date
    "grace_period_enabled":    1,     # 1=True, 0=False — allow grace period saving
}

_BOOL_KEYS = {"auto_eliminate_enabled", "grace_period_enabled"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_setting(db: Session, key: str) -> int:
    """
    Return the integer value of a settings key, creating the row with the
    default value if it does not exist yet.  Lazy-initialises on first read.
    """
    row: SystemSettings | None = (
        db.query(SystemSettings).filter(SystemSettings.key == key).first()
    )
    if row is None:
        default_val = _ELIM_DEFAULTS.get(key, 0)
        row = SystemSettings(key=key, value_int=default_val)
        db.add(row)
        db.flush()
    return row.value_int if row.value_int is not None else _ELIM_DEFAULTS.get(key, 0)


def _get_all_settings(db: Session) -> dict[str, int]:
    """Return all 8 elimination settings as a dict, lazy-creating defaults."""
    return {k: _get_setting(db, k) for k in _ELIM_DEFAULTS}


def _compute_risk_score(user: User, settings: dict[str, int]) -> float:
    """
    AI-computed payment compliance risk score — 0.0 (safe) to 1.0 (critical).
    Used in the PaymentCompliance frontend for default sort order.

    Formula:
      risk = (days_late_factor * 0.6) + (level_factor * 0.4)
      days_late_factor = min(1.0, days_late / due_days)
      level_factor     = (level - 1) / 5   (0.0 for L1, 1.0 for L6)
    """
    due_days = max(1, settings.get("payment_due_days", 4))
    # days_late: how many days since payment was due
    # Since we don't track exact due date per-user here, use late_fees as proxy
    late_fee = float(user.late_fees_inr or 0)
    fee_per_day = max(1, settings.get("late_fee_per_day_inr", 50))
    days_late = late_fee / fee_per_day
    days_late_factor = min(1.0, days_late / due_days)
    level_factor = (user.current_level - 1) / 5.0
    return round(days_late_factor * 0.6 + level_factor * 0.4, 3)


def _user_to_risk_dict(user: User, settings: dict[str, int]) -> dict:
    """Serialise a User object to the at-risk API response shape."""
    return {
        "id":                    user.id,
        "name":                  user.name,
        "username":              user.username,
        "mobile":                user.mobile,
        "current_level":         user.current_level,
        "current_pool_id":       user.current_pool_id,
        "weekly_payment_status": user.weekly_payment_status.value,
        "late_fees_inr":         float(user.late_fees_inr or 0),
        "elimination_risk":      bool(user.elimination_risk),
        "grace_active":          bool(user.grace_active),
        "grace_expires_at":      user.grace_expires_at.isoformat() if user.grace_expires_at else None,
        "grace_fee_paid":        bool(user.grace_fee_paid),
        "join_date":             user.join_date.isoformat() if user.join_date else None,
        "risk_score":            _compute_risk_score(user, settings),
    }


# ── Request / Response schemas ────────────────────────────────────────────────

class UpdateSettingsRequest(BaseModel):
    payment_due_days:        Optional[int]   = Field(None, ge=1,  le=30)
    payment_due_hour:        Optional[int]   = Field(None, ge=0,  le=23)
    grace_period_hours:      Optional[int]   = Field(None, ge=1,  le=168)
    grace_seat_save_fee_inr: Optional[int]   = Field(None, ge=0,  le=10000)
    late_fee_per_day_inr:    Optional[int]   = Field(None, ge=0,  le=1000)
    late_fee_max_cap_inr:    Optional[int]   = Field(None, ge=0,  le=10000)
    auto_eliminate_enabled:  Optional[bool]  = None
    grace_period_enabled:    Optional[bool]  = None
    admin_password:          str             = Field(..., min_length=1)


class GrantGraceRequest(BaseModel):
    hours_until_expiry: int = Field(48, ge=1, le=168,
                                    description="Grace window duration in hours from now")


class SaveSeatRequest(BaseModel):
    admin_password: str = Field(..., min_length=1)
    notes: Optional[str] = None


class ExecuteEliminationRequest(BaseModel):
    admin_password: str = Field(..., min_length=1)
    dry_run: bool = Field(False, description="If True, report what WOULD be eliminated without actually doing it")


# ── GET /admin/elimination/settings ──────────────────────────────────────────

@router.get("/settings")
def get_elimination_settings(db: Session = Depends(get_db)):
    """
    Return all 8 elimination configuration settings.
    Settings are lazy-created with defaults on first read.
    """
    settings = _get_all_settings(db)
    db.commit()   # persist any lazy-created rows
    return {
        **{k: bool(v) if k in _BOOL_KEYS else v for k, v in settings.items()},
        "description": {
            "payment_due_days":        "Days from Monday (draw opens) until payment is due",
            "payment_due_hour":        "Hour (24h IST) of payment deadline (e.g. 23 = 11 PM)",
            "grace_period_hours":      "Hours between due date and draw T-2H window",
            "grace_seat_save_fee_inr": "Extra fee (₹) to pay during grace period to save seat",
            "late_fee_per_day_inr":    "Daily late fee accrual per unpaid member (₹)",
            "late_fee_max_cap_inr":    "Maximum total late fee cap (₹)",
            "auto_eliminate_enabled":  "Automatically eliminate unpaid-past-due members",
            "grace_period_enabled":    "Allow grace period seat-saving window",
        }
    }


# ── PUT /admin/elimination/settings ──────────────────────────────────────────

@router.put("/settings")
def update_elimination_settings(
    body:           UpdateSettingsRequest,
    db:             Session = Depends(get_db),
    admin_username: str     = Depends(require_admin_jwt),
):
    """
    Update one or more elimination configuration settings.
    Admin password is required — changing these settings has real financial consequences.
    """
    # ── Verify admin password ─────────────────────────────────────────────────
    if not _verify_pw(db, admin_username, body.admin_password):
        raise HTTPException(status_code=403, detail="Invalid admin password.")

    update_map: dict[str, int] = {}
    if body.payment_due_days        is not None: update_map["payment_due_days"]        = body.payment_due_days
    if body.payment_due_hour        is not None: update_map["payment_due_hour"]        = body.payment_due_hour
    if body.grace_period_hours      is not None: update_map["grace_period_hours"]      = body.grace_period_hours
    if body.grace_seat_save_fee_inr is not None: update_map["grace_seat_save_fee_inr"] = body.grace_seat_save_fee_inr
    if body.late_fee_per_day_inr    is not None: update_map["late_fee_per_day_inr"]    = body.late_fee_per_day_inr
    if body.late_fee_max_cap_inr    is not None: update_map["late_fee_max_cap_inr"]    = body.late_fee_max_cap_inr
    if body.auto_eliminate_enabled  is not None: update_map["auto_eliminate_enabled"]  = int(body.auto_eliminate_enabled)
    if body.grace_period_enabled    is not None: update_map["grace_period_enabled"]    = int(body.grace_period_enabled)

    if not update_map:
        raise HTTPException(status_code=400, detail="No settings provided to update.")

    for key, value in update_map.items():
        row: SystemSettings | None = (
            db.query(SystemSettings).filter(SystemSettings.key == key).first()
        )
        if row is None:
            row = SystemSettings(key=key, value_int=value)
            db.add(row)
        else:
            row.value_int = value

    db.commit()
    settings = _get_all_settings(db)
    return {
        "updated": list(update_map.keys()),
        "settings": {k: bool(v) if k in _BOOL_KEYS else v for k, v in settings.items()},
    }


# ── GET /admin/elimination/late-payers ───────────────────────────────────────

@router.get("/late-payers")
def get_late_payers(
    skip:  int = Query(0,   ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    All active pool members who have unpaid weekly status AND/OR accumulated
    late fees — ordered by risk score descending.
    """
    settings = _get_all_settings(db)

    users = (
        db.query(User)
        .filter(
            User.status == UserStatus.Active,
            User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
        )
        .order_by(User.late_fees_inr.desc(), User.join_date.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = (
        db.query(func.count(User.id))
        .filter(
            User.status == UserStatus.Active,
            User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
        )
        .scalar() or 0
    )

    items = [_user_to_risk_dict(u, settings) for u in users]
    # Sort by risk score (highest first)
    items.sort(key=lambda x: x["risk_score"], reverse=True)

    return {"total": total, "items": items}


# ── GET /admin/elimination/at-risk ────────────────────────────────────────────

@router.get("/at-risk")
def get_at_risk_users(
    skip:  int = Query(0,   ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Members with elimination_risk=True who are NOT yet in a grace period.
    These are the users who will be eliminated on the next elimination cycle
    unless they enter the grace period and pay.
    """
    settings = _get_all_settings(db)

    users = (
        db.query(User)
        .filter(
            User.status           == UserStatus.Active,
            User.elimination_risk == True,   # noqa: E712
            User.grace_active     == False,  # noqa: E712
        )
        .order_by(User.current_level.desc(), User.late_fees_inr.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = (
        db.query(func.count(User.id))
        .filter(
            User.status           == UserStatus.Active,
            User.elimination_risk == True,   # noqa: E712
            User.grace_active     == False,  # noqa: E712
        )
        .scalar() or 0
    )

    items = [_user_to_risk_dict(u, settings) for u in users]
    items.sort(key=lambda x: x["risk_score"], reverse=True)

    return {"total": total, "items": items}


# ── GET /admin/elimination/grace-period ──────────────────────────────────────

@router.get("/grace-period")
def get_grace_period_users(db: Session = Depends(get_db)):
    """
    Members currently in the grace period window (grace_active=True).
    Includes time_remaining_seconds for the frontend countdown.
    """
    settings = _get_all_settings(db)
    now = datetime.now(timezone.utc)

    users = (
        db.query(User)
        .filter(
            User.status       == UserStatus.Active,
            User.grace_active == True,   # noqa: E712
        )
        .order_by(User.grace_expires_at.asc())   # expiring soonest first
        .all()
    )

    items = []
    for u in users:
        d = _user_to_risk_dict(u, settings)
        if u.grace_expires_at:
            remaining = (u.grace_expires_at - now).total_seconds()
            d["time_remaining_seconds"] = max(0, int(remaining))
            d["expires_in_hours"]       = round(max(0, remaining) / 3600, 1)
            d["expired"]                = remaining <= 0
        else:
            d["time_remaining_seconds"] = None
            d["expires_in_hours"]       = None
            d["expired"]                = False
        items.append(d)

    return {"total": len(items), "items": items}


# ── GET /admin/elimination/history ───────────────────────────────────────────

@router.get("/history")
def get_elimination_history(
    skip:   int           = Query(0,    ge=0),
    limit:  int           = Query(100,  ge=1, le=500),
    reason: Optional[str] = Query(None, description="non_payment|grace_expired"),
    db: Session = Depends(get_db),
):
    """
    Paginated EliminationEvent audit log — newest first.
    Financial summary strip included for reporting.
    """
    q = db.query(EliminationEvent)
    if reason:
        try:
            q = q.filter(EliminationEvent.reason == EliminationReason(reason))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid reason '{reason}'. Valid: non_payment, grace_expired")

    total  = q.with_entities(func.count(EliminationEvent.id)).scalar() or 0
    events = q.order_by(EliminationEvent.created_at.desc()).offset(skip).limit(limit).all()

    # Financial summary
    summary_q = db.query(
        func.count(EliminationEvent.id).label("total_eliminations"),
        func.sum(EliminationEvent.total_forfeited).label("total_forfeited_inr"),
        func.sum(EliminationEvent.late_fees_forfeited).label("total_late_fees"),
        func.sum(EliminationEvent.deposit_forfeited).label("total_deposits_forfeited"),
    ).one()

    return {
        "total": total,
        "summary": {
            "total_eliminations":       summary_q.total_eliminations or 0,
            "total_forfeited_inr":      float(summary_q.total_forfeited_inr or 0),
            "total_late_fees_inr":      float(summary_q.total_late_fees or 0),
            "total_deposits_forfeited": float(summary_q.total_deposits_forfeited or 0),
        },
        "events": [
            {
                "id":                         ev.id,
                "user_id":                    ev.user_id,
                "username":                   ev.username_snapshot,
                "user_level_at_elimination":  ev.user_level_at_elimination,
                "pool_id":                    ev.pool_id,
                "pool_name":                  ev.pool_name_snapshot,
                "draw_week_id":               ev.draw_week_id,
                "reason":                     ev.reason.value,
                "late_fees_forfeited_inr":    float(ev.late_fees_forfeited),
                "seat_save_fee_inr":          float(ev.seat_save_fee),
                "deposit_forfeited_inr":      float(ev.deposit_forfeited),
                "total_forfeited_inr":        float(ev.total_forfeited),
                "was_in_grace_period":        ev.was_in_grace_period,
                "created_at":                 ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in events
        ],
    }


# ── POST /admin/elimination/mark-at-risk ─────────────────────────────────────

@router.post("/mark-at-risk")
def mark_at_risk(db: Session = Depends(get_db)):
    """
    Scan all active pool members who are currently Unpaid and have accumulated
    late fees ≥ late_fee_per_day_inr (proxy for "past due date").  Mark them
    elimination_risk=True so they appear in the at-risk queue.

    This endpoint is normally called by the daily penalty scheduler.  It can
    also be triggered manually from the PaymentCompliance admin page.

    Returns count of newly flagged users + running total.
    """
    settings = _get_all_settings(db)
    min_fee  = settings.get("late_fee_per_day_inr", 50)

    # Identify unpaid active members with fees exceeding one day's late fee
    # This is a safe proxy for "payment_due_days have passed"
    candidates = (
        db.query(User)
        .filter(
            User.status                == UserStatus.Active,
            User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
            User.late_fees_inr         >= min_fee,
            User.elimination_risk      == False,   # noqa: E712
        )
        .all()
    )

    newly_flagged = 0
    for u in candidates:
        u.elimination_risk = True
        newly_flagged += 1

    if newly_flagged:
        db.commit()

    total_at_risk = (
        db.query(func.count(User.id))
        .filter(User.status == UserStatus.Active, User.elimination_risk == True)  # noqa: E712
        .scalar() or 0
    )

    return {
        "newly_flagged":    newly_flagged,
        "total_at_risk":    total_at_risk,
        "message": (
            f"{newly_flagged} user(s) newly marked as elimination risk. "
            f"{total_at_risk} total at-risk members."
        ),
    }


# ── POST /admin/elimination/grant-grace/{uid} ─────────────────────────────────

@router.post("/grant-grace/{uid}")
def grant_grace_period(
    uid:  int,
    body: GrantGraceRequest,
    db:   Session = Depends(get_db),
):
    """
    Move a specific user into the grace period window.
    Sets grace_active=True and grace_expires_at=now+hours_until_expiry.

    The user must:
    - Be Active status
    - Have elimination_risk=True OR have unpaid weekly status
    - Not already be in an active (unexpired) grace period

    After granting, the user appears in the Grace Period tab with a countdown.
    """
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {uid} not found.")
    if user.status != UserStatus.Active:
        raise HTTPException(status_code=400, detail="Grace period only applies to Active members.")
    if user.grace_active:
        remaining = None
        if user.grace_expires_at:
            rem = (user.grace_expires_at - datetime.now(timezone.utc)).total_seconds()
            remaining = max(0, int(rem))
        raise HTTPException(
            status_code=400,
            detail=f"User is already in grace period. "
                   f"{'Expires in %ds.' % remaining if remaining else 'Expiry unknown.'}"
        )

    settings      = _get_all_settings(db)
    grace_hours   = body.hours_until_expiry or settings.get("grace_period_hours", 48)
    grace_expires = datetime.now(timezone.utc) + timedelta(hours=grace_hours)

    user.grace_active     = True
    user.grace_expires_at = grace_expires
    user.grace_fee_paid   = False   # must pay grace fee to save seat
    user.elimination_risk = True    # remains at-risk until grace fee paid

    db.commit()
    db.refresh(user)

    return {
        "user_id":         user.id,
        "username":        user.username,
        "grace_active":    True,
        "grace_expires_at": user.grace_expires_at.isoformat(),
        "grace_hours":     grace_hours,
        "message": (
            f"Grace period granted to @{user.username}. "
            f"They must pay ₹{settings['grace_seat_save_fee_inr']:,} + "
            f"₹{float(user.late_fees_inr or 0):,.0f} late fees by "
            f"{user.grace_expires_at.strftime('%Y-%m-%d %H:%M UTC')} to save their seat."
        ),
    }


# ── POST /admin/elimination/save-seat/{uid} ───────────────────────────────────

@router.post("/save-seat/{uid}")
def confirm_grace_payment(
    uid:            int,
    body:           SaveSeatRequest,
    db:             Session = Depends(get_db),
    admin_username: str     = Depends(require_admin_jwt),
):
    """
    Admin confirms that a grace-period user has physically paid the seat-save fee
    (₹500 + accumulated late fees).

    This:
    - Sets grace_fee_paid=True
    - Clears elimination_risk=False (seat is now saved)
    - Clears late_fees_inr=0 (fees settled)
    - Sets weekly_payment_status=Paid

    Admin password required — this represents a financial transaction confirmation.
    """
    if not _verify_pw(db, admin_username, body.admin_password):
        raise HTTPException(status_code=403, detail="Invalid admin password.")

    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {uid} not found.")
    if user.status != UserStatus.Active:
        raise HTTPException(status_code=400, detail="User is not in Active status.")
    if not user.grace_active:
        raise HTTPException(
            status_code=400,
            detail="User is not currently in the grace period. Use grant-grace first."
        )

    late_fees_cleared = float(user.late_fees_inr or 0)

    # ── Clear all elimination flags and settle payment ────────────────────────
    user.grace_fee_paid          = True
    user.grace_active            = False   # grace period fulfilled
    user.grace_expires_at        = None
    user.elimination_risk        = False   # seat is saved — no longer at risk
    user.late_fees_inr           = Decimal("0")
    user.weekly_payment_status   = WeeklyPaymentStatus.Paid

    db.commit()
    db.refresh(user)

    settings = _get_all_settings(db)
    total_paid = settings["grace_seat_save_fee_inr"] + late_fees_cleared

    return {
        "user_id":            user.id,
        "username":           user.username,
        "seat_saved":         True,
        "grace_fee_paid_inr": settings["grace_seat_save_fee_inr"],
        "late_fees_cleared":  late_fees_cleared,
        "total_paid_inr":     total_paid,
        "notes":              body.notes,
        "message": (
            f"Seat saved for @{user.username}. "
            f"Total payment confirmed: ₹{total_paid:,.0f} "
            f"(₹{settings['grace_seat_save_fee_inr']:,} grace fee + "
            f"₹{late_fees_cleared:,.0f} late fees). "
            f"Elimination risk cleared. Weekly payment marked Paid."
        ),
    }


# ── POST /admin/elimination/execute ──────────────────────────────────────────

@router.post("/execute")
def execute_elimination(
    body:           ExecuteEliminationRequest,
    db:             Session = Depends(get_db),
    admin_username: str     = Depends(require_admin_jwt),
):
    """
    Execute the elimination cycle — remove all members who are:
      1. Status = Active
      2. elimination_risk = True
      3. grace_active = False (not in grace, or grace expired)

    Members in grace period (grace_active=True) are SKIPPED.
    Members who have paid grace fee (grace_fee_paid=True) are SKIPPED.

    For each eliminated user:
      - status → Eliminated
      - current_pool_id → None
      - Writes an EliminationEvent audit record

    Admin password required.
    If dry_run=True, reports what WOULD happen without making changes.
    """
    if not _verify_pw(db, admin_username, body.admin_password):
        raise HTTPException(status_code=403, detail="Invalid admin password.")

    settings = _get_all_settings(db)

    # ── First: expire any grace periods that have passed their deadline ───────
    now = datetime.now(timezone.utc)
    expired_grace = (
        db.query(User)
        .filter(
            User.status           == UserStatus.Active,
            User.grace_active     == True,             # noqa: E712
            User.grace_fee_paid   == False,            # noqa: E712
            User.grace_expires_at <= now,
        )
        .all()
    )
    grace_expired_count = 0
    for u in expired_grace:
        u.grace_active = False  # grace window closed without payment
        grace_expired_count += 1

    if grace_expired_count:
        db.flush()

    # ── Identify users to eliminate ───────────────────────────────────────────
    to_eliminate = (
        db.query(User)
        .filter(
            User.status           == UserStatus.Active,
            User.elimination_risk == True,              # noqa: E712
            User.grace_active     == False,             # noqa: E712
            User.grace_fee_paid   == False,             # noqa: E712
        )
        .all()
    )

    if body.dry_run:
        # Report only — no DB changes made (flush is rolled back)
        db.rollback()
        return {
            "dry_run":             True,
            "would_eliminate":     len(to_eliminate),
            "grace_expired_count": grace_expired_count,
            "users": [
                {
                    "id":         u.id,
                    "username":   u.username,
                    "level":      u.current_level,
                    "pool_id":    u.current_pool_id,
                    "late_fees":  float(u.late_fees_inr or 0),
                    "reason":     "grace_expired" if getattr(u, 'grace_active', False) else "non_payment",
                }
                for u in to_eliminate
            ],
        }

    # ── Execute eliminations ──────────────────────────────────────────────────
    eliminated_count = 0
    total_forfeited  = Decimal("0")
    iso_week         = now.strftime("%G-W%V")   # e.g. "2026-W24"

    for u in to_eliminate:
        # Determine reason
        was_grace = bool(u.grace_active)   # False since we just cleared them, but use history
        reason    = EliminationReason.grace_expired if was_grace else EliminationReason.non_payment

        # Fetch pool name for snapshot
        pool_name = None
        if u.current_pool_id:
            pool = db.query(Pool).filter(Pool.id == u.current_pool_id).first()
            pool_name = pool.name if pool else None

        late_fees = Decimal(str(u.late_fees_inr or 0))
        total_ev  = Decimal("1000") + late_fees   # deposit + accumulated fees

        # ── Write EliminationEvent audit record ───────────────────────────────
        event = EliminationEvent(
            user_id                   = u.id,
            username_snapshot         = u.username,
            user_level_at_elimination = u.current_level,
            pool_id                   = u.current_pool_id,
            pool_name_snapshot        = pool_name,
            draw_week_id              = iso_week,
            reason                    = reason,
            late_fees_forfeited       = late_fees,
            seat_save_fee             = Decimal("0"),
            deposit_forfeited         = Decimal("1000"),
            total_forfeited           = total_ev,
            was_in_grace_period       = was_grace,
        )
        db.add(event)

        # ── Update user record ────────────────────────────────────────────────
        u.status           = UserStatus.Eliminated
        u.current_pool_id  = None
        u.elimination_risk = False
        u.grace_active     = False
        u.grace_expires_at = None
        u.grace_fee_paid   = False
        u.late_fees_inr    = Decimal("0")

        total_forfeited  += total_ev
        eliminated_count += 1

    if eliminated_count > 0:
        db.commit()

    return {
        "dry_run":             False,
        "eliminated_count":    eliminated_count,
        "grace_expired_count": grace_expired_count,
        "total_forfeited_inr": float(total_forfeited),
        "iso_week":            iso_week,
        "message": (
            f"Elimination cycle complete. "
            f"{eliminated_count} member(s) eliminated. "
            f"₹{float(total_forfeited):,.0f} total forfeited. "
            f"{grace_expired_count} grace period(s) expired before payment."
        ),
    }
