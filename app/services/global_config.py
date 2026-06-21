"""
Global Dynamic Configuration Service
=====================================
# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
Single source of truth for ALL runtime-configurable system constants.

All values are stored in the system_settings table (key → value_int /
value_float / value_str).  Each getter uses a 60-second process-local
cache to avoid a DB round-trip on every call.  When a DB row does not
exist, the compiled-in config.py constant is returned as the default —
this guarantees zero-touch backward compatibility on first deployment.

Supported configuration dimensions
------------------------------------
  1. Financial amounts:
       base_installment_inr, payout_fee_inr,
       late_fee_daily_inr, late_fee_max_cap_inr
       (referral_reward_inr already covered by settings.py — not duplicated here)

  2. Level payouts (L1–L6 gross + net INR):
       level_{N}_gross_inr / level_{N}_net_inr   for N in 1..6
       Stored as direct INR values, independent of base installment.
       Default: config.py LEVEL_PAYOUTS dict (unchanged if rows absent).

  3. LPI / pressure thresholds (float):
       lpi_regular_max, lpi_type_a_min, lpi_sde_proactive,
       lpi_l3_win_exception, cascade_prevent_l3_thresh,
       accel_diss_trigger_ratio

  4. Draw chronology:
       draw_frequency  (value_str: 'daily' / 'weekly' / 'monthly')
       draw_day_of_week  (value_int: 0=Mon … 6=Sun)
       grace_period_hours  (value_int)
       cleanup_offset_minutes  (value_int)
       (draw_hour_utc / draw_minute_utc / draw_prep_hours stay in settings.py)

Cache pattern
-------------
Each configurable dimension has its own process-local dict slot:
  {"value": <cached_value or None>, "expires": <monotonic timestamp>}
TTL = 60 seconds.  Thread-safe under CPython GIL for scalar reads/writes.

set_*() functions zero their cache slot immediately so the next call
reads the freshly committed DB value without waiting up to 60 seconds.

Design rule
-----------
NO caller should import any of the constants below from app.core.config:
  LEVEL_PAYOUTS, PAYOUT_FEE_INR, DEPOSIT_AMOUNT_INR,
  LATE_FEE_DAILY_INR, LATE_FEE_MAX_CAP_INR,
  LPI_REGULAR_MAX, LPI_TYPE_A_MIN, LPI_SDE_PROACTIVE,
  LPI_L3_WIN_EXCEPTION, CASCADE_PREVENT_L3_THRESH, ACCEL_DISS_TRIGGER_RATIO
Import from this module instead.
"""

import time
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

import app.core.config as _cfg
from app.models.system_settings import SystemSettings

# ── Cache TTL ─────────────────────────────────────────────────────────────────
_TTL: float = 60.0   # seconds


# ══════════════════════════════════════════════════════════════════════════════
# Internal cache factory + read/write primitives
# ══════════════════════════════════════════════════════════════════════════════

def _cache() -> dict:
    """Return a fresh empty cache slot (value=None, expires=0 → always stale)."""
    return {"value": None, "expires": 0.0}


def _read_int(db: Session, key: str, default: int, slot: dict) -> int:
    now = time.monotonic()
    if slot["value"] is not None and now < slot["expires"]:
        return slot["value"]
    row: Optional[SystemSettings] = (
        db.query(SystemSettings).filter(SystemSettings.key == key).first()
    )
    result: int = (
        row.value_int
        if (row is not None and row.value_int is not None)
        else default
    )
    slot["value"]   = result
    slot["expires"] = now + _TTL
    return result


def _read_float(db: Session, key: str, default: float, slot: dict) -> float:
    now = time.monotonic()
    if slot["value"] is not None and now < slot["expires"]:
        return slot["value"]
    row: Optional[SystemSettings] = (
        db.query(SystemSettings).filter(SystemSettings.key == key).first()
    )
    if row is not None and row.value_float is not None:
        result: float = float(row.value_float)
    else:
        result = default
    slot["value"]   = result
    slot["expires"] = now + _TTL
    return result


def _read_str(db: Session, key: str, default: str, slot: dict) -> str:
    now = time.monotonic()
    if slot["value"] is not None and now < slot["expires"]:
        return slot["value"]
    row: Optional[SystemSettings] = (
        db.query(SystemSettings).filter(SystemSettings.key == key).first()
    )
    result: str = (
        row.value_str
        if (row is not None and row.value_str is not None)
        else default
    )
    slot["value"]   = result
    slot["expires"] = now + _TTL
    return result


def _upsert_int(db: Session, key: str, value: int) -> None:
    row = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    if row:
        row.value_int = value
    else:
        db.add(SystemSettings(key=key, value_int=value))
    db.commit()


def _upsert_float(db: Session, key: str, value: float) -> None:
    row = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    if row:
        row.value_float = Decimal(str(value))
    else:
        db.add(SystemSettings(key=key, value_float=Decimal(str(value))))
    db.commit()


def _upsert_str(db: Session, key: str, value: str) -> None:
    row = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    if row:
        row.value_str = value
    else:
        db.add(SystemSettings(key=key, value_str=value))
    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# DIMENSION 1 — Financial Amounts
# ══════════════════════════════════════════════════════════════════════════════

_C_BASE_INSTALLMENT: dict = _cache()
_C_PAYOUT_FEE:       dict = _cache()
_C_LATE_FEE_DAILY:   dict = _cache()
_C_LATE_FEE_CAP:     dict = _cache()


def get_base_installment(db: Session) -> int:
    """
    Weekly installment amount every Active member pays.
    DB key: base_installment_inr.  Default: DEPOSIT_AMOUNT_INR (₹1,000).
    """
    return _read_int(db, "base_installment_inr", _cfg.DEPOSIT_AMOUNT_INR, _C_BASE_INSTALLMENT)


def set_base_installment(db: Session, value: int) -> None:
    if not (100 <= value <= 10_000):
        raise ValueError("base_installment_inr must be ₹100–₹10,000.")
    _upsert_int(db, "base_installment_inr", value)
    _C_BASE_INSTALLMENT["value"] = None


def get_payout_fee(db: Session) -> int:
    """
    Fee deducted from gross payout before issuing WIT token.
    DB key: payout_fee_inr.  Default: PAYOUT_FEE_INR (₹500).
    """
    return _read_int(db, "payout_fee_inr", _cfg.PAYOUT_FEE_INR, _C_PAYOUT_FEE)


def set_payout_fee(db: Session, value: int) -> None:
    if not (0 <= value <= 5_000):
        raise ValueError("payout_fee_inr must be ₹0–₹5,000.")
    _upsert_int(db, "payout_fee_inr", value)
    _C_PAYOUT_FEE["value"] = None


def get_late_fee_daily(db: Session) -> int:
    """
    INR accrued each day a member is Unpaid past due date.
    DB key: late_fee_daily_inr.  Default: LATE_FEE_DAILY_INR (₹50).
    """
    return _read_int(db, "late_fee_daily_inr", _cfg.LATE_FEE_DAILY_INR, _C_LATE_FEE_DAILY)


def set_late_fee_daily(db: Session, value: int) -> None:
    if not (0 <= value <= 500):
        raise ValueError("late_fee_daily_inr must be ₹0–₹500.")
    _upsert_int(db, "late_fee_daily_inr", value)
    _C_LATE_FEE_DAILY["value"] = None


def get_late_fee_cap(db: Session) -> int:
    """
    Maximum total late fee a member can accumulate.
    DB key: late_fee_max_cap_inr.  Default: LATE_FEE_MAX_CAP_INR (₹500).
    """
    return _read_int(db, "late_fee_max_cap_inr", _cfg.LATE_FEE_MAX_CAP_INR, _C_LATE_FEE_CAP)


def set_late_fee_cap(db: Session, value: int) -> None:
    if not (0 <= value <= 5_000):
        raise ValueError("late_fee_max_cap_inr must be ₹0–₹5,000.")
    _upsert_int(db, "late_fee_max_cap_inr", value)
    _C_LATE_FEE_CAP["value"] = None


# ══════════════════════════════════════════════════════════════════════════════
# DIMENSION 2 — Level Payouts (L1–L6)
# ══════════════════════════════════════════════════════════════════════════════
# Stored as individual DB rows:
#   level_{N}_gross_inr  (value_int)
#   level_{N}_net_inr    (value_int)
# for N in 1..6.
#
# If a row is absent, config.py LEVEL_PAYOUTS[N] is used as fallback.
# Admin can set each level independently of base_installment_inr.

_C_LEVEL_PAYOUTS: dict[int, dict] = {n: _cache() for n in range(1, 7)}


def get_level_payout(db: Session, level: int) -> tuple[int, int]:
    """
    Return (gross_inr, net_inr) for the given level.

    Reads from DB first; falls back to config.py LEVEL_PAYOUTS[level].
    Level is clamped to [1, 6] — out-of-range values are silently clamped.
    Cache slot is per-level; reads are thread-safe under CPython GIL.

    Returns
    -------
    (gross_inr, net_inr) — both positive integers, gross > net.
    """
    level = max(1, min(level, 6))
    slot  = _C_LEVEL_PAYOUTS[level]
    now   = time.monotonic()
    if slot["value"] is not None and now < slot["expires"]:
        return slot["value"]

    default_gross, default_net = _cfg.LEVEL_PAYOUTS.get(level, (2500, 2000))
    gross_key = f"level_{level}_gross_inr"
    net_key   = f"level_{level}_net_inr"

    rows: dict[str, int] = {
        r.key: r.value_int
        for r in db.query(SystemSettings)
        .filter(SystemSettings.key.in_([gross_key, net_key]))
        .all()
        if r.value_int is not None
    }
    gross  = rows.get(gross_key, default_gross)
    net    = rows.get(net_key,   default_net)
    result = (gross, net)
    slot["value"]   = result
    slot["expires"] = now + _TTL
    return result


def set_level_payout(db: Session, level: int, gross_inr: int, net_inr: int) -> None:
    """
    Persist a new gross/net payout pair for a single level.

    Validates:
      - level in 1..6
      - 0 < net_inr < gross_inr
      - gross_inr ≤ ₹1,00,000 (safety cap)
    """
    if level not in range(1, 7):
        raise ValueError("level must be 1–6.")
    if net_inr <= 0:
        raise ValueError("net_inr must be > 0.")
    if net_inr >= gross_inr:
        raise ValueError("net_inr must be less than gross_inr.")
    if gross_inr > 100_000:
        raise ValueError("gross_inr exceeds ₹1,00,000 safety cap.")

    for key, val in [
        (f"level_{level}_gross_inr", gross_inr),
        (f"level_{level}_net_inr",   net_inr),
    ]:
        _upsert_int(db, key, val)

    _C_LEVEL_PAYOUTS[level]["value"] = None   # invalidate cache for this level


def get_all_level_payouts(db: Session) -> dict[int, tuple[int, int]]:
    """
    Return {level: (gross, net)} for all 6 levels.
    Used by the admin "Draw & Financial Strategy" UI config panel.
    """
    return {lvl: get_level_payout(db, lvl) for lvl in range(1, 7)}


# ══════════════════════════════════════════════════════════════════════════════
# DIMENSION 3 — LPI / Pressure Thresholds (float)
# ══════════════════════════════════════════════════════════════════════════════

_C_LPI_REGULAR_MAX:      dict = _cache()
_C_LPI_TYPE_A_MIN:       dict = _cache()
_C_LPI_SDE_PROACTIVE:    dict = _cache()
_C_LPI_L3_WIN_EXCEPTION: dict = _cache()
_C_CASCADE_THRESH:        dict = _cache()
_C_ACCEL_TRIGGER_RATIO:  dict = _cache()


def get_lpi_regular_max(db: Session) -> float:
    """LPI below this → Regular pool draw.  Default: 14.0."""
    return _read_float(db, "lpi_regular_max", _cfg.LPI_REGULAR_MAX, _C_LPI_REGULAR_MAX)


def set_lpi_regular_max(db: Session, value: float) -> None:
    if not (1.0 <= value <= 100.0):
        raise ValueError("lpi_regular_max must be 1.0–100.0.")
    _upsert_float(db, "lpi_regular_max", value)
    _C_LPI_REGULAR_MAX["value"] = None


def get_lpi_type_a_min(db: Session) -> float:
    """LPI at or above this → Type A pool (up to SDE_PROACTIVE).  Default: 14.0."""
    return _read_float(db, "lpi_type_a_min", _cfg.LPI_TYPE_A_MIN, _C_LPI_TYPE_A_MIN)


def set_lpi_type_a_min(db: Session, value: float) -> None:
    if not (1.0 <= value <= 100.0):
        raise ValueError("lpi_type_a_min must be 1.0–100.0.")
    _upsert_float(db, "lpi_type_a_min", value)
    _C_LPI_TYPE_A_MIN["value"] = None


def get_lpi_sde_proactive(db: Session) -> float:
    """LPI at or above this → SDE proactive regardless of L4 count.  Default: 25.0."""
    return _read_float(db, "lpi_sde_proactive", _cfg.LPI_SDE_PROACTIVE, _C_LPI_SDE_PROACTIVE)


def set_lpi_sde_proactive(db: Session, value: float) -> None:
    if not (1.0 <= value <= 100.0):
        raise ValueError("lpi_sde_proactive must be 1.0–100.0.")
    _upsert_float(db, "lpi_sde_proactive", value)
    _C_LPI_SDE_PROACTIVE["value"] = None


def get_lpi_l3_win_exception(db: Session) -> float:
    """LPI above this → L3 allowed to win SDE lower tier.  Default: 50.0."""
    return _read_float(
        db, "lpi_l3_win_exception", _cfg.LPI_L3_WIN_EXCEPTION, _C_LPI_L3_WIN_EXCEPTION
    )


def set_lpi_l3_win_exception(db: Session, value: float) -> None:
    if not (1.0 <= value <= 100.0):
        raise ValueError("lpi_l3_win_exception must be 1.0–100.0.")
    _upsert_float(db, "lpi_l3_win_exception", value)
    _C_LPI_L3_WIN_EXCEPTION["value"] = None


def get_cascade_prevent_thresh(db: Session) -> float:
    """
    cascade_risk above this → Preventive L3 draw triggered.  Default: 2.0.
    cascade_risk = L3_count / max(L1+L2_count, 1).
    """
    return _read_float(
        db, "cascade_prevent_l3_thresh", _cfg.CASCADE_PREVENT_L3_THRESH, _C_CASCADE_THRESH
    )


def set_cascade_prevent_thresh(db: Session, value: float) -> None:
    if not (0.1 <= value <= 10.0):
        raise ValueError("cascade_prevent_l3_thresh must be 0.1–10.0.")
    _upsert_float(db, "cascade_prevent_l3_thresh", value)
    _C_CASCADE_THRESH["value"] = None


def get_accel_diss_trigger_ratio(db: Session) -> float:
    """
    Fraction of pool members that must be L4+ to trigger Accelerated Dissolution.
    Default: 0.60 (60%).
    """
    return _read_float(
        db, "accel_diss_trigger_ratio", _cfg.ACCEL_DISS_TRIGGER_RATIO, _C_ACCEL_TRIGGER_RATIO
    )


def set_accel_diss_trigger_ratio(db: Session, value: float) -> None:
    if not (0.10 <= value <= 1.00):
        raise ValueError("accel_diss_trigger_ratio must be 0.10–1.00.")
    _upsert_float(db, "accel_diss_trigger_ratio", value)
    _C_ACCEL_TRIGGER_RATIO["value"] = None


# ══════════════════════════════════════════════════════════════════════════════
# DIMENSION 4 — Draw Chronology
# ══════════════════════════════════════════════════════════════════════════════

_C_DRAW_FREQUENCY:      dict = _cache()
_C_DRAW_DAY_OF_WEEK:    dict = _cache()
_C_GRACE_PERIOD_HOURS:  dict = _cache()
_C_CLEANUP_OFFSET_MINS: dict = _cache()

_DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
              4: "Friday", 5: "Saturday", 6: "Sunday"}


def get_draw_frequency(db: Session) -> str:
    """
    Draw cycle frequency.
    Returns: 'daily' | 'weekly' | 'monthly'.  Default: 'weekly'.
    DB key: draw_frequency (value_str).
    """
    return _read_str(db, "draw_frequency", "weekly", _C_DRAW_FREQUENCY)


def set_draw_frequency(db: Session, value: str) -> None:
    if value not in ("daily", "weekly", "monthly"):
        raise ValueError("draw_frequency must be 'daily', 'weekly', or 'monthly'.")
    _upsert_str(db, "draw_frequency", value)
    _C_DRAW_FREQUENCY["value"] = None


def get_draw_day_of_week(db: Session) -> int:
    """
    Day of week for the draw.
    0=Monday … 6=Sunday.  Default: 6 (Sunday).
    DB key: draw_day_of_week (value_int).
    """
    return _read_int(db, "draw_day_of_week", 6, _C_DRAW_DAY_OF_WEEK)


def set_draw_day_of_week(db: Session, value: int) -> None:
    if not (0 <= value <= 6):
        raise ValueError("draw_day_of_week must be 0 (Monday) to 6 (Sunday).")
    _upsert_int(db, "draw_day_of_week", value)
    _C_DRAW_DAY_OF_WEEK["value"] = None


def get_grace_period_hours(db: Session) -> int:
    """
    Duration of the grace window (hours) between due date and draw T-0H.
    Default: 48.  DB key: grace_period_hours (value_int).
    """
    return _read_int(db, "grace_period_hours", 48, _C_GRACE_PERIOD_HOURS)


def set_grace_period_hours(db: Session, value: int) -> None:
    if not (1 <= value <= 168):
        raise ValueError("grace_period_hours must be 1–168 (1h–7d).")
    _upsert_int(db, "grace_period_hours", value)
    _C_GRACE_PERIOD_HOURS["value"] = None


def get_cleanup_offset_minutes(db: Session) -> int:
    """
    Minutes after draw T-0H before post-draw cleanup fires.
    Default: 5.  DB key: cleanup_offset_minutes (value_int).
    """
    return _read_int(db, "cleanup_offset_minutes", 5, _C_CLEANUP_OFFSET_MINS)


def set_cleanup_offset_minutes(db: Session, value: int) -> None:
    if not (1 <= value <= 60):
        raise ValueError("cleanup_offset_minutes must be 1–60.")
    _upsert_int(db, "cleanup_offset_minutes", value)
    _C_CLEANUP_OFFSET_MINS["value"] = None


# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# 29th key — payment_due_offset_days: how many days after CYCLE_START before
# payment is due.  Default 4 = Monday → Thursday (classic production cadence).
# Consumed by _compute_milestones() in real_simulation.py to derive DUE_DATE
# dynamically.  Without this key DUE_DATE is not configurable and the Chronos
# Engine would need to hardcode "3 days 23 h 59 min" (Thursday).
_C_PAYMENT_DUE_DAYS: dict = _cache()


def get_payment_due_offset_days(db: Session) -> int:
    """
    Days after CYCLE_START when the on-time payment window closes (DUE_DATE).
    Default: 4 (Monday → Thursday for a weekly Sunday draw).
    DB key: payment_due_offset_days (value_int).
    """
    return _read_int(db, "payment_due_offset_days", 4, _C_PAYMENT_DUE_DAYS)


def set_payment_due_offset_days(db: Session, days: int) -> None:
    if not (1 <= days <= 27):
        raise ValueError("payment_due_offset_days must be 1–27.")
    _upsert_int(db, "payment_due_offset_days", days)
    _C_PAYMENT_DUE_DAYS["value"] = None


# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# 30th key — grace_close_offset_minutes: minutes before T_02H when grace window
# closes and guillotine list is locked.  Default 5.  Previously hardcoded in
# _compute_milestones() as `timedelta(minutes=5)`; now DB-configurable so admins
# can extend the close window without a code deploy.
_C_GRACE_CLOSE_MINS: dict = _cache()


def get_grace_close_offset_minutes(db: Session) -> int:
    """
    Minutes before T_02H (draw preparation) when the grace period closes.
    G_CLOSE = T_02H − grace_close_offset_minutes.
    Default: 5.  DB key: grace_close_offset_minutes (value_int).
    """
    return _read_int(db, "grace_close_offset_minutes", 5, _C_GRACE_CLOSE_MINS)


def set_grace_close_offset_minutes(db: Session, minutes: int) -> None:
    if not (1 <= minutes <= 119):
        raise ValueError("grace_close_offset_minutes must be 1–119.")
    _upsert_int(db, "grace_close_offset_minutes", minutes)
    _C_GRACE_CLOSE_MINS["value"] = None


# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# 31st key — auto_deploy_on_admin_unavailable (Task 3, Jun-21).
# Master safety toggle for the Master Pool Re-assessor's AUTO-DEPLOY engine.
#
# When a re-assessment HOLD is raised at T-2H and NO admin acts before the draw
# fires at T-0H (the admin is "unavailable" past the 2-hour override window), the
# weekly draw would normally stay frozen — clearing ZERO L4 and GROWING the backlog,
# which damages future projections.  With this toggle ON, the system instead runs
# auto_deploy_resolve_hold(): it scores every deployable candidate by FUTURE-health
# projection (solvency weighted so heavily that any solvent option always wins) and
# deploys the LEAST-BAD safe option automatically — either releasing the prepared
# draw as-is, or applying the re-assessor's pyramid-safe L4-defer first.
#
# Stored as value_int 0/1.  DEFAULT 0 (OFF) — admin must explicitly opt in, because
# this lets money move without a human in the loop (locked decision: default OFF).
# value_int 0 = OFF (HOLD freezes the draw until an admin approves — current
#   behaviour, unchanged for every existing deployment).
# value_int 1 = ON  (auto-deploy fires at T-0H when the admin did not act).
_C_AUTO_DEPLOY_ON_UNAVAIL: dict = _cache()


def get_auto_deploy_on_unavailable(db: Session) -> bool:
    """
    Master toggle for the re-assessor AUTO-DEPLOY engine.
    Returns True only when the stored value_int is exactly 1.  Default: False (OFF).
    DB key: auto_deploy_on_admin_unavailable (value_int 0/1).
    """
    return _read_int(db, "auto_deploy_on_admin_unavailable", 0, _C_AUTO_DEPLOY_ON_UNAVAIL) == 1


def set_auto_deploy_on_unavailable(db: Session, enabled: bool) -> None:
    """Enable/disable the auto-deploy engine.  Password-gated at the router layer."""
    _upsert_int(db, "auto_deploy_on_admin_unavailable", 1 if enabled else 0)
    _C_AUTO_DEPLOY_ON_UNAVAIL["value"] = None


# ══════════════════════════════════════════════════════════════════════════════
# BULK READ — Admin "Draw & Financial Strategy" panel
# ══════════════════════════════════════════════════════════════════════════════

def get_all_financial_config(db: Session) -> dict:
    """
    Return the complete financial + threshold + chronology config in one dict.

    Used by GET /admin/financial-config.
    All values are served from cache (60s TTL) where warm — single DB
    round-trip set for all 30 keys when cache is cold.
    """
    lvl_payouts = get_all_level_payouts(db)
    return {
        # Financial amounts
        "base_installment_inr":      get_base_installment(db),
        "payout_fee_inr":            get_payout_fee(db),
        "late_fee_daily_inr":        get_late_fee_daily(db),
        "late_fee_max_cap_inr":      get_late_fee_cap(db),
        # Level payouts
        "level_payouts": {
            str(lvl): {"gross_inr": g, "net_inr": n}
            for lvl, (g, n) in lvl_payouts.items()
        },
        # LPI / pressure thresholds
        "lpi_regular_max":           get_lpi_regular_max(db),
        "lpi_type_a_min":            get_lpi_type_a_min(db),
        "lpi_sde_proactive":         get_lpi_sde_proactive(db),
        "lpi_l3_win_exception":      get_lpi_l3_win_exception(db),
        "cascade_prevent_l3_thresh": get_cascade_prevent_thresh(db),
        "accel_diss_trigger_ratio":  get_accel_diss_trigger_ratio(db),
        # Draw chronology
        "draw_frequency":            get_draw_frequency(db),
        "draw_day_of_week":          get_draw_day_of_week(db),
        "draw_day_name":             _DAY_NAMES.get(get_draw_day_of_week(db), "Sunday"),
        "grace_period_hours":        get_grace_period_hours(db),
        "cleanup_offset_minutes":    get_cleanup_offset_minutes(db),
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        "payment_due_offset_days":   get_payment_due_offset_days(db),
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        "grace_close_offset_minutes": get_grace_close_offset_minutes(db),
    }
