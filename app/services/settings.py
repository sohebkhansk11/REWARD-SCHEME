"""
System Settings Service
=======================
Thin helpers for reading and writing the `system_settings` table.

All numeric settings return a Python int; callers should never need to
know about the DB schema details.

Supported keys
--------------
pool_creation_threshold   — minimum paid Waitlist members needed before
                            check_and_scale_waitlist() creates a new pool.
                            Default: WAITLIST_TRIGGER (24) from config.py.

Adaptive Threshold (POINT 7)
-----------------------------
get_adaptive_threshold(db) computes an LPI-pressure-adjusted threshold.

Problem: with exactly 2 new registrations/week and 1 active pool consuming
2 WL slots/week for post-draw refills, the WL net growth is ZERO.  The
threshold of 24 is NEVER reached.  The system is stuck in single-pool
equilibrium indefinitely with no mechanism to form a second pool.

Fix: reduce the threshold proportionally to LPI pressure:
  effective_threshold = max(ADAPTIVE_THRESHOLD_MIN,
                            WAITLIST_TRIGGER × (1 − pressure_factor))
  pressure_factor = min(0.5, current_LPI / 100)

  At LPI = 0%:   effective = 24  (normal operation)
  At LPI = 14%:  effective ≈ 21  (mild reduction)
  At LPI = 25%:  effective ≈ 18  (moderate reduction)
  At LPI = 50%:  effective = 12  (minimum = POOL_CAPACITY)

Emergency override: if growth_rate ≤ pool_consumption_rate AND LPI > 10%,
clamp to ADAPTIVE_THRESHOLD_MIN (12) immediately.
"""

import time

from sqlalchemy.orm import Session

from app.core.config import (
    WAITLIST_TRIGGER,
    ADAPTIVE_THRESHOLD_ENABLED,
    ADAPTIVE_THRESHOLD_MIN,
    ADAPTIVE_THRESHOLD_LPI_FULL,
    POOL_CAPACITY,
)
from app.models.system_settings import SystemSettings

# ── Constants ─────────────────────────────────────────────────────────────────

_KEY_THRESHOLD = "pool_creation_threshold"

# Process-local cache — avoids a DB round-trip on every waitlist trigger call.
# TTL of 60 seconds means threshold changes take effect within one minute.
# Thread-safe in CPython: dict reads/writes on simple scalar values are atomic
# under the GIL; no explicit lock needed for this single-writer pattern.
_THRESHOLD_CACHE: dict = {"value": None, "expires": 0.0}
_CACHE_TTL_S = 60


# ── Internal helper ───────────────────────────────────────────────────────────

def _get_or_create_row(db: Session, key: str, default_int: int) -> SystemSettings:
    """
    Return the SystemSettings row for `key`, creating it with `default_int`
    if it does not yet exist.  Caller is responsible for db.commit() if they
    intend to persist the auto-created row (typically not needed since the next
    call also creates it lazily).
    """
    row: SystemSettings | None = (
        db.query(SystemSettings).filter(SystemSettings.key == key).first()
    )
    if row is None:
        row = SystemSettings(key=key, value_int=default_int)
        db.add(row)
        db.flush()   # assigns any server defaults without a full commit
    return row


# ── Public API ────────────────────────────────────────────────────────────────

def get_pool_threshold(db: Session) -> int:
    """
    Return the current pool-creation threshold.

    Served from a 60-second process-local cache to avoid a DB hit on every
    waitlist trigger call.  Falls back to the compiled-in WAITLIST_TRIGGER (24)
    when the row does not exist, keeping GET paths read-only.
    """
    now = time.monotonic()
    if _THRESHOLD_CACHE["value"] is not None and now < _THRESHOLD_CACHE["expires"]:
        return _THRESHOLD_CACHE["value"]

    row: SystemSettings | None = (
        db.query(SystemSettings)
        .filter(SystemSettings.key == _KEY_THRESHOLD)
        .first()
    )
    result = row.value_int if (row is not None and row.value_int is not None) else WAITLIST_TRIGGER
    _THRESHOLD_CACHE["value"]   = result
    _THRESHOLD_CACHE["expires"] = now + _CACHE_TTL_S
    return result


def set_pool_threshold(db: Session, new_threshold: int) -> int:
    """
    Persist a new pool-creation threshold and return it.

    Validates: must be ≥ 1.  Callers should also enforce an upper bound if
    desired (the admin endpoint limits to 1–1000).
    """
    if new_threshold < 1:
        raise ValueError("pool_creation_threshold must be at least 1.")

    row = _get_or_create_row(db, _KEY_THRESHOLD, default_int=WAITLIST_TRIGGER)
    row.value_int = new_threshold
    db.commit()
    db.refresh(row)
    # Invalidate cache so next call reads the new value immediately
    _THRESHOLD_CACHE["value"] = None
    return row.value_int


def get_adaptive_threshold(db: Session, lpi: float | None = None) -> int:
    """
    Compute an LPI-pressure-adjusted pool creation threshold.

    POINT 7 FIX: The base threshold of 24 creates a mathematical deadlock when
    weekly growth ≤ pool_consumption_rate (active_pools × 2/week).  This function
    returns a reduced threshold so new pools can form even under slow growth.

    Algorithm:
      1. Read the admin-set base threshold (default 24).
      2. If ADAPTIVE_THRESHOLD_ENABLED is False → return base threshold unchanged.
      3. Compute pressure_factor from LPI (if provided):
             pressure_factor = min(0.5, lpi / 100)
      4. effective = max(ADAPTIVE_THRESHOLD_MIN,
                         int(base × (1 − pressure_factor)))
      5. Emergency override: if LPI > 50% → clamp to ADAPTIVE_THRESHOLD_MIN (12).

    Parameters
    ----------
    db  : Active DB session.
    lpi : Current LPI (0.0–100.0).  If None, reads the live LPI from the DB.
          Pass a pre-computed LPI to avoid an extra query.

    Returns
    -------
    Effective threshold as int (always ≥ ADAPTIVE_THRESHOLD_MIN).
    """
    base = get_pool_threshold(db)

    if not ADAPTIVE_THRESHOLD_ENABLED:
        return base

    # Resolve LPI if not provided
    if lpi is None:
        try:
            from app.services.brain5_lpi_engine import calculate_lpi
            lpi = calculate_lpi(db)
        except Exception:
            # If LPI calculation fails (e.g. on empty DB), return base unchanged
            return base

    # Emergency override: LPI ≥ ADAPTIVE_THRESHOLD_LPI_FULL (50%) → minimum
    if lpi >= ADAPTIVE_THRESHOLD_LPI_FULL:
        return ADAPTIVE_THRESHOLD_MIN

    # Pressure-based reduction
    pressure_factor = min(0.5, lpi / 100.0)
    reduced = int(base * (1.0 - pressure_factor))
    effective = max(ADAPTIVE_THRESHOLD_MIN, reduced)

    return effective


# ── Referral Reward ───────────────────────────────────────────────────────────

_KEY_REFERRAL_REWARD = "referral_reward_inr"

# Same 60-second TTL cache pattern as pool threshold — avoids a DB round-trip
# on every pool-entry event (Phase 1/2/3 refill + draw replacement).
_REFERRAL_REWARD_CACHE: dict = {"value": None, "expires": 0.0}


def get_referral_reward(db: Session) -> int:
    """
    Return the current per-referral reward in INR.

    Served from a 60-second process-local cache to avoid a DB hit on every
    pool-entry event (Rule 39).  Falls back to the compiled-in
    REFERRAL_REWARD_INR (250) when the DB row does not yet exist, keeping
    all GET paths read-only.

    Value of 0 is valid — it means referral rewards are temporarily disabled.
    """
    now = time.monotonic()
    if _REFERRAL_REWARD_CACHE["value"] is not None and now < _REFERRAL_REWARD_CACHE["expires"]:
        return _REFERRAL_REWARD_CACHE["value"]

    row: SystemSettings | None = (
        db.query(SystemSettings)
        .filter(SystemSettings.key == _KEY_REFERRAL_REWARD)
        .first()
    )
    from app.core.config import REFERRAL_REWARD_INR as _DEFAULT
    # NOTE: explicit `is not None` check so that 0 (disabled state) is preserved.
    result = row.value_int if (row is not None and row.value_int is not None) else _DEFAULT
    _REFERRAL_REWARD_CACHE["value"]   = result
    _REFERRAL_REWARD_CACHE["expires"] = now + _CACHE_TTL_S
    return result


def set_referral_reward(db: Session, new_amount: int) -> int:
    """
    Persist a new per-referral reward amount and return it.

    Validates:
      - Must be ≥ 0  (0 = disable referral rewards without code change)
      - Must be ≤ 10,000  (prevents accidental ruinous value)

    Cache is invalidated immediately so the next pool-entry event uses the
    new amount without waiting up to 60 seconds.
    Caller is responsible for any surrounding transaction if needed.
    """
    if new_amount < 0:
        raise ValueError("referral_reward_inr must be ≥ 0 (0 = disabled).")
    if new_amount > 10_000:
        raise ValueError("referral_reward_inr must be ≤ ₹10,000.")

    from app.core.config import REFERRAL_REWARD_INR as _DEFAULT
    row = _get_or_create_row(db, _KEY_REFERRAL_REWARD, default_int=_DEFAULT)
    row.value_int = new_amount
    db.commit()
    db.refresh(row)
    # Invalidate cache — next call reads fresh value immediately.
    _REFERRAL_REWARD_CACHE["value"] = None
    return row.value_int


def get_adaptive_threshold_info(db: Session, lpi: float | None = None) -> dict:
    """
    Return the adaptive threshold calculation with full explanation.
    Used by the admin diagnostics panel to show WHY the threshold was reduced.
    """
    base = get_pool_threshold(db)

    if lpi is None:
        try:
            from app.services.brain5_lpi_engine import calculate_lpi
            lpi = calculate_lpi(db)
        except Exception:
            lpi = 0.0

    effective = get_adaptive_threshold(db, lpi=lpi)
    pressure_factor = min(0.5, lpi / 100.0)

    reduction_pct = round((1.0 - pressure_factor) * 100, 1)
    was_reduced   = (effective < base)

    return {
        "base_threshold":      base,
        "effective_threshold": effective,
        "current_lpi":         round(lpi, 2),
        "pressure_factor":     round(pressure_factor, 3),
        "reduction_pct":       reduction_pct,
        "was_reduced":         was_reduced,
        "adaptive_enabled":    ADAPTIVE_THRESHOLD_ENABLED,
        "minimum_floor":       ADAPTIVE_THRESHOLD_MIN,
        "note": (
            f"Threshold reduced from {base} → {effective} "
            f"due to LPI={lpi:.1f}% pressure."
            if was_reduced else
            f"Threshold unchanged at {base} (LPI={lpi:.1f}% — no pressure)."
        ),
    }


# ── Draw Schedule Settings ────────────────────────────────────────────────────
# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Draw Calendar — runtime-configurable draw timing stored in system_settings.
# Keys:
#   draw_hour_utc   (Integer, default 13)  — UTC hour of Sunday draw (0–23)
#   draw_minute_utc (Integer, default 30)  — UTC minute of Sunday draw (0–59)
#   draw_prep_hours (Integer, default 2)   — hours before draw for T-2H prep (1–6)
#
# The scheduler reads DRAW_HOUR_UTC / DRAW_MINUTE_UTC env vars at process start.
# These settings allow in-app adjustment without a Render env-var change + redeploy.
# Scheduler picks up new values on next Sunday's job fire via get_draw_schedule().

_KEY_DRAW_HOUR   = "draw_hour_utc"
_KEY_DRAW_MINUTE = "draw_minute_utc"
_KEY_DRAW_PREP   = "draw_prep_hours"

_DRAW_DEFAULTS = {
    _KEY_DRAW_HOUR:   13,   # 13:30 UTC = 7:00 PM IST
    _KEY_DRAW_MINUTE: 30,
    _KEY_DRAW_PREP:   2,    # T-2H preparation window
}

# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# 0=Mon … 6=Sun — identical convention to global_config.draw_day_of_week (the SSOT
# for the draw DAY) and to APScheduler's CronTrigger integer day_of_week numbering.
_DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
              4: "Friday", 5: "Saturday", 6: "Sunday"}


def _utc_to_ist_label(hour_utc: int, minute_utc: int, day_idx: int = 6) -> str:
    """
    Convert a UTC draw time + UTC draw day to an IST label string (IST = UTC+5:30).

    SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    The day is no longer hardcoded "Sunday".  When the +5:30 offset pushes the time
    past midnight UTC, the IST weekday rolls forward by one, so the label always names
    the weekday on which the draw actually lands in IST.
    """
    total_min = hour_utc * 60 + minute_utc + 330   # +5h30m
    day_roll  = total_min // (24 * 60)             # 0 or 1 (offset is < 24h)
    ist_hour  = (total_min // 60) % 24
    ist_min   = total_min % 60
    period    = "PM" if ist_hour >= 12 else "AM"
    h12       = ist_hour % 12 or 12
    ist_day   = _DAY_NAMES.get((day_idx + day_roll) % 7, "Sunday")
    return f"{h12}:{ist_min:02d} {period} IST ({ist_day})"


def get_draw_schedule(db: Session) -> dict:
    """
    Return the current draw schedule settings — the consolidated Draw-Calendar view.

    Reads draw_hour_utc / draw_minute_utc / draw_prep_hours from system_settings, and
    the draw DAY from global_config.draw_day_of_week (the single source of truth for
    the day).  Falls back to compiled-in defaults (Sunday 13:30 UTC = 7:00 PM IST,
    T-2H prep) when rows do not exist.
    """
    keys = [_KEY_DRAW_HOUR, _KEY_DRAW_MINUTE, _KEY_DRAW_PREP]
    rows = {
        r.key: r.value_int
        for r in db.query(SystemSettings).filter(SystemSettings.key.in_(keys)).all()
        if r.value_int is not None
    }
    hour   = rows.get(_KEY_DRAW_HOUR,   _DRAW_DEFAULTS[_KEY_DRAW_HOUR])
    minute = rows.get(_KEY_DRAW_MINUTE, _DRAW_DEFAULTS[_KEY_DRAW_MINUTE])
    prep   = rows.get(_KEY_DRAW_PREP,   _DRAW_DEFAULTS[_KEY_DRAW_PREP])

    # Draw DAY is owned by global_config (shared with the financial-config calendar
    # and the stress simulator).  Lazy import avoids any module-load cycle.
    from app.services.global_config import get_draw_day_of_week
    day_idx = get_draw_day_of_week(db)   # 0=Mon … 6=Sun

    return {
        "draw_hour_utc":     hour,
        "draw_minute_utc":   minute,
        "draw_prep_hours":   prep,
        "draw_day_of_week":  day_idx,
        "draw_day":          _DAY_NAMES.get(day_idx, "Sunday"),
        "draw_time_ist":     _utc_to_ist_label(hour, minute, day_idx),
    }


def set_draw_schedule(
    db:              Session,
    draw_hour_utc:   int,
    draw_minute_utc: int,
    draw_prep_hours: int,
    draw_day_of_week: int | None = None,
) -> dict:
    """
    Persist new draw schedule settings.

    Validates all values and writes them atomically.  When draw_day_of_week is
    provided (0=Mon … 6=Sun) it is persisted via global_config (the SSOT for the
    day); when None the existing day is left unchanged — preserving backward
    compatibility for callers that only edit the time.

    SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    Callers MUST trigger scheduler.reschedule_draw_jobs(db) after this returns so the
    live APScheduler cron re-points immediately (done in the admin router layer).
    """
    if not (0 <= draw_hour_utc <= 23):
        raise ValueError("draw_hour_utc must be 0–23.")
    if not (0 <= draw_minute_utc <= 59):
        raise ValueError("draw_minute_utc must be 0–59.")
    if not (1 <= draw_prep_hours <= 6):
        raise ValueError("draw_prep_hours must be 1–6.")

    updates = {
        _KEY_DRAW_HOUR:   draw_hour_utc,
        _KEY_DRAW_MINUTE: draw_minute_utc,
        _KEY_DRAW_PREP:   draw_prep_hours,
    }
    for key, val in updates.items():
        row = db.query(SystemSettings).filter(SystemSettings.key == key).first()
        if row:
            row.value_int = val
        else:
            db.add(SystemSettings(key=key, value_int=val))

    db.commit()

    # Persist the DAY through the SSOT accessor (validates 0–6, invalidates its cache).
    if draw_day_of_week is not None:
        from app.services.global_config import set_draw_day_of_week
        set_draw_day_of_week(db, draw_day_of_week)

    return get_draw_schedule(db)
