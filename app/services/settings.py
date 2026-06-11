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
"""

import time

from sqlalchemy.orm import Session

from app.core.config import WAITLIST_TRIGGER
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
