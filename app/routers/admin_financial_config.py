"""
Admin — Draw & Financial Strategy Configuration Router
=======================================================
# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
REST endpoints backing the "Draw & Financial Strategy" sub-tab in the
Admin System Settings page.

All GET endpoints: read-only, no admin password required (admin JWT sufficient).
All PUT endpoints: mutate SystemSettings rows — REQUIRE admin_password in body.

Endpoint map
------------
  GET  /admin/financial-config                  — full config snapshot (30 keys)
  PUT  /admin/financial-config/base             — base_installment_inr + payout_fee
  PUT  /admin/financial-config/late-fees        — late_fee_daily_inr + cap
  PUT  /admin/financial-config/level-payout     — one level's gross + net
  PUT  /admin/financial-config/level-payouts    — bulk update all 6 levels at once
  PUT  /admin/financial-config/thresholds       — LPI + cascade + accel thresholds
  PUT  /admin/financial-config/draw-calendar    — frequency, day, grace, cleanup

Security model:
  - Router-level: require_admin_jwt (JWT must be present and valid)
  - Endpoint-level (PUT): admin_password verified against stored bcrypt hash
    before ANY mutation is committed — same pattern as admin.py
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from app.core.security import require_admin_jwt
from app.database import get_db
from app.services.global_config import (
    get_all_financial_config,
    get_base_installment,    set_base_installment,
    get_payout_fee,          set_payout_fee,
    get_late_fee_daily,      set_late_fee_daily,
    get_late_fee_cap,        set_late_fee_cap,
    get_level_payout,        set_level_payout,
    get_all_level_payouts,
    get_lpi_regular_max,     set_lpi_regular_max,
    get_lpi_type_a_min,      set_lpi_type_a_min,
    get_lpi_sde_proactive,   set_lpi_sde_proactive,
    get_lpi_l3_win_exception, set_lpi_l3_win_exception,
    get_cascade_prevent_thresh, set_cascade_prevent_thresh,
    get_accel_diss_trigger_ratio, set_accel_diss_trigger_ratio,
    get_draw_frequency,       set_draw_frequency,
    get_draw_day_of_week,     set_draw_day_of_week,
    get_grace_period_hours,   set_grace_period_hours,
    get_cleanup_offset_minutes, set_cleanup_offset_minutes,
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    get_payment_due_offset_days, set_payment_due_offset_days,
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    get_grace_close_offset_minutes, set_grace_close_offset_minutes,
)

router = APIRouter(
    prefix="/admin/financial-config",
    tags=["Admin — Financial Config"],
    dependencies=[Depends(require_admin_jwt)],
)

# ── Shared admin-password verifier ────────────────────────────────────────────

def _verify_admin_password(db: Session, admin_password: str) -> None:
    """
    Verify the supplied password against the stored admin bcrypt hash.
    Raises HTTP 401 if verification fails.
    Same pattern used throughout admin.py.
    """
    from app.models.admin import Admin as AdminModel
    from app.services.auth import verify_password

    admin_username = "admin"
    admin: AdminModel | None = (
        db.query(AdminModel).filter(AdminModel.username == admin_username).first()
    )
    dummy = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    stored = (admin.hashed_password if admin else None) or dummy
    if not verify_password(admin_password, stored):
        raise HTTPException(
            status_code=401,
            detail="Admin password verification failed. Configuration was NOT changed.",
        )


# ══════════════════════════════════════════════════════════════════════════════
# Request / Response models
# ══════════════════════════════════════════════════════════════════════════════

class UpdateBaseFinancialRequest(BaseModel):
    admin_password:      str = Field(..., description="Admin password for verification")
    base_installment_inr: int = Field(..., ge=100, le=10_000, description="Weekly installment ₹100–₹10,000")
    payout_fee_inr:       int = Field(..., ge=0,   le=5_000,  description="Fee deducted from gross payout ₹0–₹5,000")


class UpdateLateFeesRequest(BaseModel):
    admin_password:    str = Field(..., description="Admin password for verification")
    late_fee_daily_inr: int = Field(..., ge=0, le=500,   description="Daily late fee ₹0–₹500")
    late_fee_max_cap_inr: int = Field(..., ge=0, le=5_000, description="Late fee cap ₹0–₹5,000")


class UpdateLevelPayoutRequest(BaseModel):
    admin_password: str = Field(..., description="Admin password for verification")
    level:          int = Field(..., ge=1, le=6, description="Level 1–6")
    gross_inr:      int = Field(..., ge=1, description="Gross payout amount INR")
    net_inr:        int = Field(..., ge=1, description="Net payout amount INR (after fee deduction)")


class LevelPayoutEntry(BaseModel):
    gross_inr: int = Field(..., ge=1)
    net_inr:   int = Field(..., ge=1)


class UpdateAllLevelPayoutsRequest(BaseModel):
    admin_password: str = Field(..., description="Admin password for verification")
    payouts: dict[str, LevelPayoutEntry] = Field(
        ...,
        description='Map of level (as string "1"–"6") to {gross_inr, net_inr}',
    )


class UpdateThresholdsRequest(BaseModel):
    admin_password:          str   = Field(..., description="Admin password for verification")
    lpi_regular_max:         float = Field(..., ge=1.0,  le=100.0, description="LPI < this → Regular draw")
    lpi_type_a_min:          float = Field(..., ge=1.0,  le=100.0, description="LPI ≥ this → Type A (up to SDE)")
    lpi_sde_proactive:       float = Field(..., ge=1.0,  le=100.0, description="LPI ≥ this → SDE proactive")
    lpi_l3_win_exception:    float = Field(..., ge=1.0,  le=100.0, description="LPI > this → L3 wins SDE lower tier")
    cascade_prevent_l3_thresh: float = Field(..., ge=0.1, le=10.0,  description="cascade_risk > this → Preventive L3 draw")
    accel_diss_trigger_ratio: float = Field(..., ge=0.10, le=1.00,  description="L4+ fraction of pool → Accelerated Dissolution")


class UpdateDrawCalendarRequest(BaseModel):
    admin_password:           str = Field(..., description="Admin password for verification")
    draw_frequency:           str = Field(..., description="'daily' | 'weekly' | 'monthly'")
    draw_day_of_week:         int = Field(..., ge=0, le=6, description="0=Monday … 6=Sunday")
    grace_period_hours:       int = Field(..., ge=1, le=168, description="Grace window duration (hours)")
    cleanup_offset_minutes:   int = Field(..., ge=1, le=60,  description="Minutes after draw before cleanup fires")
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # 29th key — Chronos Engine DUE_DATE milestone: CYCLE_START + payment_due_offset_days
    payment_due_offset_days:  int = Field(4,   ge=1, le=27,
                                          description="Days after cycle start before on-time payment window closes (default 4 = Mon→Thu)")
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # 30th key — G_CLOSE = T_02H − grace_close_offset_minutes (was hardcoded 5)
    grace_close_offset_minutes: int = Field(5, ge=1, le=119,
                                            description="Minutes before T-02H when grace period closes and elimination list locks (default 5)")


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/financial-config
# ══════════════════════════════════════════════════════════════════════════════

@router.get("", summary="Get full Draw & Financial Strategy configuration")
def get_financial_config(db: Session = Depends(get_db)) -> dict:
    """
    Return all 30 runtime-configurable financial/threshold/chronology values
    in a single response.  Values are served from the 60-second TTL cache
    (warm) or read fresh from system_settings (cold).

    No admin password required — read-only, JWT sufficient.
    """
    return get_all_financial_config(db)


# ══════════════════════════════════════════════════════════════════════════════
# PUT /admin/financial-config/base
# ══════════════════════════════════════════════════════════════════════════════

@router.put("/base", summary="Update base installment and payout fee")
def update_base_financial(
    body: UpdateBaseFinancialRequest,
    db:   Session = Depends(get_db),
) -> dict:
    """
    Persist new base_installment_inr and payout_fee_inr.

    ADMIN PASSWORD REQUIRED.
    Takes effect within 60 seconds (cache TTL) on all running instances.
    The net payout for every level remains whatever is stored in
    level_{N}_net_inr — changing base does NOT auto-recompute level payouts.
    Update level payouts separately via PUT /admin/financial-config/level-payouts.
    """
    _verify_admin_password(db, body.admin_password)

    set_base_installment(db, body.base_installment_inr)
    set_payout_fee(db, body.payout_fee_inr)

    return {
        "base_installment_inr": get_base_installment(db),
        "payout_fee_inr":       get_payout_fee(db),
        "message": (
            f"Base installment updated to ₹{body.base_installment_inr} "
            f"and payout fee to ₹{body.payout_fee_inr}. "
            "Changes active within 60 seconds across all instances."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUT /admin/financial-config/late-fees
# ══════════════════════════════════════════════════════════════════════════════

@router.put("/late-fees", summary="Update late fee daily rate and cap")
def update_late_fees(
    body: UpdateLateFeesRequest,
    db:   Session = Depends(get_db),
) -> dict:
    """
    Persist new late_fee_daily_inr and late_fee_max_cap_inr.

    ADMIN PASSWORD REQUIRED.
    late_fee_daily_inr accrues each day a member is Unpaid past due date.
    late_fee_max_cap_inr is the ceiling after which no further accrual occurs.
    """
    _verify_admin_password(db, body.admin_password)

    set_late_fee_daily(db, body.late_fee_daily_inr)
    set_late_fee_cap(db, body.late_fee_max_cap_inr)

    return {
        "late_fee_daily_inr":   get_late_fee_daily(db),
        "late_fee_max_cap_inr": get_late_fee_cap(db),
        "message": (
            f"Late fee: ₹{body.late_fee_daily_inr}/day, "
            f"capped at ₹{body.late_fee_max_cap_inr}. "
            "Changes active within 60 seconds."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUT /admin/financial-config/level-payout
# ══════════════════════════════════════════════════════════════════════════════

@router.put("/level-payout", summary="Update payout for a single level (L1–L6)")
def update_level_payout(
    body: UpdateLevelPayoutRequest,
    db:   Session = Depends(get_db),
) -> dict:
    """
    Update gross_inr and net_inr for one specific level.

    ADMIN PASSWORD REQUIRED.
    Validates: net_inr < gross_inr, gross_inr ≤ ₹1,00,000.
    """
    _verify_admin_password(db, body.admin_password)

    try:
        set_level_payout(db, body.level, body.gross_inr, body.net_inr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    gross, net = get_level_payout(db, body.level)
    return {
        "level":     body.level,
        "gross_inr": gross,
        "net_inr":   net,
        "message":   f"L{body.level} payout updated: gross=₹{gross}, net=₹{net}.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUT /admin/financial-config/level-payouts
# ══════════════════════════════════════════════════════════════════════════════

@router.put("/level-payouts", summary="Bulk update all 6 level payouts")
def update_all_level_payouts(
    body: UpdateAllLevelPayoutsRequest,
    db:   Session = Depends(get_db),
) -> dict:
    """
    Update gross/net for multiple levels in one atomic admin operation.

    ADMIN PASSWORD REQUIRED.
    Body: { "payouts": { "1": {"gross_inr": 2500, "net_inr": 2000}, ... } }
    Only levels present in the payload are updated — absent levels are unchanged.
    """
    _verify_admin_password(db, body.admin_password)

    errors: list[str] = []
    updated: list[int] = []

    for level_str, entry in body.payouts.items():
        try:
            lvl = int(level_str)
            set_level_payout(db, lvl, entry.gross_inr, entry.net_inr)
            updated.append(lvl)
        except (ValueError, TypeError) as exc:
            errors.append(f"L{level_str}: {exc}")

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Partial failure — some levels rejected.", "errors": errors},
        )

    return {
        "updated_levels": sorted(updated),
        "all_level_payouts": {
            str(lvl): {"gross_inr": g, "net_inr": n}
            for lvl, (g, n) in get_all_level_payouts(db).items()
        },
        "message": f"Level payouts updated for L{sorted(updated)}. Active within 60 seconds.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUT /admin/financial-config/thresholds
# ══════════════════════════════════════════════════════════════════════════════

@router.put("/thresholds", summary="Update LPI pressure + cascade + accel thresholds")
def update_thresholds(
    body: UpdateThresholdsRequest,
    db:   Session = Depends(get_db),
) -> dict:
    """
    Persist all 6 LPI / pressure threshold values.

    ADMIN PASSWORD REQUIRED.
    These thresholds control the Brain-5 draw-type routing:
      lpi_regular_max    → < this = Regular pool draw
      lpi_type_a_min     → ≥ this = Type A (Execution Pool)
      lpi_sde_proactive  → ≥ this = SDE proactive regardless of L4 count
      lpi_l3_win_exception → > this = L3 eligible for SDE lower tier
      cascade_prevent_l3_thresh → cascade_risk > this = Preventive L3 draw
      accel_diss_trigger_ratio → L4+ fraction > this = Accelerated Dissolution

    WARNING: Setting lpi_type_a_min > lpi_sde_proactive creates a
    routing gap. The API does not prevent this but will log a warning.
    """
    _verify_admin_password(db, body.admin_password)

    try:
        set_lpi_regular_max(db,         body.lpi_regular_max)
        set_lpi_type_a_min(db,          body.lpi_type_a_min)
        set_lpi_sde_proactive(db,       body.lpi_sde_proactive)
        set_lpi_l3_win_exception(db,    body.lpi_l3_win_exception)
        set_cascade_prevent_thresh(db,  body.cascade_prevent_l3_thresh)
        set_accel_diss_trigger_ratio(db, body.accel_diss_trigger_ratio)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if body.lpi_type_a_min > body.lpi_sde_proactive:
        import logging
        logging.getLogger(__name__).warning(
            "Financial config: lpi_type_a_min (%.1f) > lpi_sde_proactive (%.1f) — "
            "no Type A window exists between these thresholds.",
            body.lpi_type_a_min, body.lpi_sde_proactive,
        )

    return {
        "lpi_regular_max":           get_lpi_regular_max(db),
        "lpi_type_a_min":            get_lpi_type_a_min(db),
        "lpi_sde_proactive":         get_lpi_sde_proactive(db),
        "lpi_l3_win_exception":      get_lpi_l3_win_exception(db),
        "cascade_prevent_l3_thresh": get_cascade_prevent_thresh(db),
        "accel_diss_trigger_ratio":  get_accel_diss_trigger_ratio(db),
        "message": "Pressure thresholds updated. Changes active within 60 seconds.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUT /admin/financial-config/draw-calendar
# ══════════════════════════════════════════════════════════════════════════════

@router.put("/draw-calendar", summary="Update draw frequency, day, grace period, cleanup offset")
def update_draw_calendar(
    body: UpdateDrawCalendarRequest,
    db:   Session = Depends(get_db),
) -> dict:
    """
    Persist draw chronology settings.

    ADMIN PASSWORD REQUIRED.
    draw_frequency: 'daily' | 'weekly' | 'monthly'
    draw_day_of_week: 0 (Monday) to 6 (Sunday)
    grace_period_hours: time between due date and draw T-0H
    cleanup_offset_minutes: T+N minutes after draw before cleanup fires

    NOTE: draw_hour_utc / draw_minute_utc / draw_prep_hours are managed
    by PUT /admin/draw/schedule (existing endpoint in admin_analytics.py).
    This endpoint covers the higher-level chronological strategy only.
    """
    _verify_admin_password(db, body.admin_password)

    try:
        set_draw_frequency(db,           body.draw_frequency)
        set_draw_day_of_week(db,         body.draw_day_of_week)
        set_grace_period_hours(db,       body.grace_period_hours)
        set_cleanup_offset_minutes(db,   body.cleanup_offset_minutes)
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        set_payment_due_offset_days(db,    body.payment_due_offset_days)
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        set_grace_close_offset_minutes(db, body.grace_close_offset_minutes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    _day_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                  4: "Friday", 5: "Saturday", 6: "Sunday"}

    return {
        "draw_frequency":           get_draw_frequency(db),
        "draw_day_of_week":         get_draw_day_of_week(db),
        "draw_day_name":            _day_names.get(get_draw_day_of_week(db), "Sunday"),
        "grace_period_hours":       get_grace_period_hours(db),
        "cleanup_offset_minutes":   get_cleanup_offset_minutes(db),
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        "payment_due_offset_days":    get_payment_due_offset_days(db),
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        "grace_close_offset_minutes": get_grace_close_offset_minutes(db),
        "message": (
            f"Draw calendar: {body.draw_frequency} on {_day_names.get(body.draw_day_of_week, 'Sunday')}, "
            f"grace={body.grace_period_hours}h, close T-2H−{body.grace_close_offset_minutes}min, "
            f"cleanup T+{body.cleanup_offset_minutes}min, due_offset={body.payment_due_offset_days}d. "
            "Active within 60 seconds."
        ),
    }
