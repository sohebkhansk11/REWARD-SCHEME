# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
Forensic Debugger — event-level recorder ("every breath of the system").
========================================================================

TOGGLE:  POST /dev/forensic/toggle  {"enabled": true|false}

When OFF (default production state):
  - record() / every helper does exactly ONE boolean check, then returns.
  - Zero buffering, zero DB writes, zero imports beyond the flag read.

When ON (stress-test / forensic-capture mode):
  - Each domain event is appended to an in-memory buffer (O(1), lock-guarded).
  - flush() bulk-inserts the buffer into forensic_events via a SHORT-LIVED
    independent session — the engine's own session is never touched, so a
    forensic write can never roll back draw / payout data.
  - The engine flushes once per Chronos tick (and at week end); the recorder
    also auto-flushes if the buffer crosses _MAX_BUFFER to bound memory.

Money-grade guarantees:
  * APPEND-ONLY — the recorder never updates or deletes rows.
  * FAILURE-ISOLATED — every public function is wrapped so a recorder bug can
    never raise into the engine.
  * ORDER-STABLE — a monotonic per-run `seq` is stamped on every event so the
    timeline is reconstructable even within a single millisecond.

Public surface:
  enable_forensic / disable_forensic / is_on / get_context
  set_run / set_week / set_tick
  record(...)                      — generic recorder
  member_joined / member_exited / member_won
  pool_event / merger_event
  draw_event / sde_event / level_event
  payment_event / grace_event / elimination_event / refill_event
  posture_event / system_event / anomaly
  flush(reason)                    — bulk-persist the buffer (called per tick)
  ForensicRun (context manager)    — brackets a run with start/end markers
"""

import json
import logging
import threading
from typing import Any, Optional

_logger = logging.getLogger(__name__)

# ── Global state (module-level; lock-guarded for the mutable bits) ────────────
_FORENSIC_ENABLED: bool = False
_RUN_ID:   Optional[str] = None
_WEEK:     Optional[int] = None
_TICK:     str = "LIVE"
_SEQ:      int = 0
_BUFFER:   list[dict] = []
_LOCK = threading.Lock()

# Flush the buffer automatically once it crosses this many pending events, so a
# very chatty week can never balloon process memory before the per-tick flush.
_MAX_BUFFER = 2000
# Hard caps so one event can never write a runaway row.
_JSON_CAP = 4096
_MSG_CAP  = 512

# Valid coarse categories (documentation / light validation only).
CATEGORIES = {
    "MEMBERSHIP", "POOL", "DRAW", "SDE", "MERGER", "PAYMENT", "LEVEL",
    "ELIMINATION", "GRACE", "REFILL", "POSTURE", "SYSTEM", "ANOMALY",
}


# ── Toggle / context API ──────────────────────────────────────────────────────

def enable_forensic(run_id: str = "") -> None:
    """Enable the forensic recorder and tag subsequent events with run_id."""
    global _FORENSIC_ENABLED, _RUN_ID, _SEQ
    with _LOCK:
        _FORENSIC_ENABLED = True
        _RUN_ID = run_id or "live"
        _SEQ = 0
        _BUFFER.clear()
    _logger.info("ForensicDebugger ENABLED  run_id=%s", _RUN_ID)


def disable_forensic() -> None:
    """Flush any pending events, then disable and clear run context."""
    global _FORENSIC_ENABLED, _RUN_ID, _WEEK, _TICK
    flush("disable")
    with _LOCK:
        _FORENSIC_ENABLED = False
        _RUN_ID = None
        _WEEK = None
        _TICK = "LIVE"
    _logger.info("ForensicDebugger DISABLED")


def set_run(run_id: str) -> None:
    global _RUN_ID
    _RUN_ID = run_id or "live"


def set_week(week: Optional[int]) -> None:
    global _WEEK
    _WEEK = week


def set_tick(tick: str) -> None:
    global _TICK
    _TICK = tick or "LIVE"


def is_on() -> bool:
    return _FORENSIC_ENABLED


def get_context() -> dict:
    return {
        "enabled":  _FORENSIC_ENABLED,
        "run_id":   _RUN_ID,
        "week":     _WEEK,
        "tick":     _TICK,
        "buffered": len(_BUFFER),
        "seq":      _SEQ,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _json(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        raw = json.dumps(value, default=str)
    except Exception:
        raw = str(value)
    return raw[:_JSON_CAP] if len(raw) > _JSON_CAP else raw


def _next_seq() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


# ── Core recorder ─────────────────────────────────────────────────────────────

def record(
    category:   str,
    event_type: str,
    *,
    severity:    str = "info",
    actor:       Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id:   Optional[int] = None,
    entity_ref:  Optional[str] = None,
    amount_inr:  Optional[int] = None,
    before:      Any = None,
    after:       Any = None,
    payload:     Any = None,
    message:     Optional[str] = None,
) -> None:
    """
    Buffer one forensic event.  No-op + zero overhead when the debugger is OFF.
    Never raises — a recorder failure can never reach the engine.
    """
    if not _FORENSIC_ENABLED:
        return
    try:
        row = {
            "run_id":       _RUN_ID,
            "seq":          _next_seq(),
            "week_id":      _WEEK,
            "tick":         _TICK,
            "category":     str(category)[:24],
            "event_type":   str(event_type)[:48],
            "severity":     str(severity)[:12],
            "actor":        (str(actor)[:48] if actor is not None else None),
            "entity_type":  (str(entity_type)[:16] if entity_type is not None else None),
            "entity_id":    (int(entity_id) if entity_id is not None else None),
            "entity_ref":   (str(entity_ref)[:64] if entity_ref is not None else None),
            "amount_inr":   (int(amount_inr) if amount_inr is not None else None),
            "before_json":  _json(before),
            "after_json":   _json(after),
            "payload_json": _json(payload),
            "message":      (str(message)[:_MSG_CAP] if message is not None else None),
        }
        over = False
        with _LOCK:
            _BUFFER.append(row)
            over = len(_BUFFER) >= _MAX_BUFFER
        if over:
            flush("buffer_full")
    except Exception as exc:  # pragma: no cover — defensive
        _logger.debug("forensic.record swallowed: %s", exc)


# ── Typed convenience wrappers (thin; all funnel into record) ─────────────────

def member_joined(uid, ref, pool_id, *, level=None, payload=None, message=None):
    record("MEMBERSHIP", "member_joined", actor="system",
           entity_type="user", entity_id=uid, entity_ref=ref,
           after={"pool_id": pool_id, "level": level},
           payload=payload, message=message or f"{ref} joined pool {pool_id}")


def member_exited(uid, ref, *, reason, level=None, payload=None, message=None):
    record("MEMBERSHIP", "member_exited", actor="system",
           entity_type="user", entity_id=uid, entity_ref=ref,
           before={"level": level}, payload={"reason": reason, **(payload or {})},
           message=message or f"{ref} exited ({reason})")


def member_won(uid, ref, *, pool_id, level, draw_type, amount_inr=None,
               payload=None, message=None):
    record("DRAW", "member_won", severity="notice", actor="system",
           entity_type="user", entity_id=uid, entity_ref=ref,
           amount_inr=amount_inr,
           after={"pool_id": pool_id, "level": level, "draw_type": draw_type},
           payload=payload,
           message=message or f"{ref} WON @L{level} in pool {pool_id} ({draw_type})")


def pool_event(event_type, pool_id, *, ref=None, severity="info",
               before=None, after=None, payload=None, message=None):
    record("POOL", event_type, severity=severity, actor="system",
           entity_type="pool", entity_id=pool_id, entity_ref=ref,
           before=before, after=after, payload=payload, message=message)


def merger_event(event_type, *, pool_id=None, ref=None, severity="info",
                 before=None, after=None, payload=None, message=None):
    record("MERGER", event_type, severity=severity, actor="system",
           entity_type="pool", entity_id=pool_id, entity_ref=ref,
           before=before, after=after, payload=payload, message=message)


def draw_event(event_type, *, pool_id=None, ref=None, draw_type=None,
               severity="info", payload=None, message=None):
    record("DRAW", event_type, severity=severity, actor="system",
           entity_type="pool", entity_id=pool_id, entity_ref=ref,
           payload={"draw_type": draw_type, **(payload or {})},
           message=message)


def sde_event(event_type, *, lever=None, pool_id=None, ref=None,
              severity="notice", payload=None, message=None):
    record("SDE", event_type, severity=severity, actor="system",
           entity_type="pool", entity_id=pool_id, entity_ref=ref,
           payload={"lever": lever, **(payload or {})}, message=message)


def level_event(uid, ref, *, from_level, to_level, pool_id=None,
                payload=None, message=None):
    record("LEVEL", "level_advanced", actor="system",
           entity_type="user", entity_id=uid, entity_ref=ref,
           before={"level": from_level}, after={"level": to_level, "pool_id": pool_id},
           payload=payload,
           message=message or f"{ref} advanced L{from_level}→L{to_level}")


def payment_event(event_type, *, uid=None, ref=None, amount_inr=None,
                  severity="info", payload=None, message=None):
    record("PAYMENT", event_type, severity=severity, actor="system",
           entity_type="user", entity_id=uid, entity_ref=ref,
           amount_inr=amount_inr, payload=payload, message=message)


def grace_event(event_type, *, uid=None, ref=None, amount_inr=None,
                payload=None, message=None):
    record("GRACE", event_type, severity="notice", actor="system",
           entity_type="user", entity_id=uid, entity_ref=ref,
           amount_inr=amount_inr, payload=payload, message=message)


def elimination_event(*, uid=None, ref=None, reason=None, level=None,
                      payload=None, message=None):
    record("ELIMINATION", "eliminated", severity="warning", actor="system",
           entity_type="user", entity_id=uid, entity_ref=ref,
           before={"level": level}, payload={"reason": reason, **(payload or {})},
           message=message or f"{ref} ELIMINATED ({reason})")


def refill_event(event_type, *, pool_id=None, ref=None, payload=None, message=None):
    record("REFILL", event_type, actor="system",
           entity_type="pool", entity_id=pool_id, entity_ref=ref,
           payload=payload, message=message)


def posture_event(*, posture, scenario, multiplier=None, payload=None, message=None):
    record("POSTURE", "posture_decided", actor="system",
           after={"posture": posture, "scenario": scenario, "multiplier": multiplier},
           payload=payload,
           message=message or f"posture={posture} scenario={scenario} mult={multiplier}")


def system_event(event_type, *, severity="info", payload=None, message=None):
    record("SYSTEM", event_type, severity=severity, actor="system",
           payload=payload, message=message)


def anomaly(event_type, *, severity="critical", payload=None, message=None,
            entity_type=None, entity_id=None, entity_ref=None):
    """A self-diagnostic red flag (capacity breach, reconciliation mismatch, ...)."""
    record("ANOMALY", event_type, severity=severity, actor="system",
           entity_type=entity_type, entity_id=entity_id, entity_ref=entity_ref,
           payload=payload, message=message)


# ── Bulk flush ────────────────────────────────────────────────────────────────

def flush(reason: str = "") -> int:
    """
    Bulk-persist and clear the buffer via an independent short-lived session.
    Returns the number of rows written.  Never raises.
    """
    if not _BUFFER:
        return 0
    with _LOCK:
        if not _BUFFER:
            return 0
        pending = _BUFFER[:]
        _BUFFER.clear()
    try:
        from app.database import SessionLocal
        from app.models.forensic_event import ForensicEvent

        rows = [ForensicEvent(**r) for r in pending]
        _db = SessionLocal()
        try:
            _db.bulk_save_objects(rows)
            _db.commit()
        finally:
            _db.close()
        return len(rows)
    except Exception as exc:
        # Re-queue is unsafe (could double-write on partial commit); drop + log.
        _logger.debug("forensic.flush(%s) swallowed %d events: %s",
                      reason, len(pending), exc)
        return 0


# ── Run bracketing context manager ────────────────────────────────────────────

class ForensicRun:
    """
    Brackets a simulation/operation run with run_started / run_ended markers and
    guarantees a final flush.  Does NOT toggle the debugger — that is controlled
    independently so the recorder stays OFF in production unless explicitly enabled.

        with ForensicRun(run_id):
            ...engine loop...
    """

    def __init__(self, run_id: str):
        self._run_id = run_id

    def __enter__(self) -> "ForensicRun":
        if _FORENSIC_ENABLED:
            set_run(self._run_id)
            system_event("run_started", payload={"run_id": self._run_id},
                         message=f"forensic run {self._run_id} started")
        return self

    def __exit__(self, exc_type, exc_val, _tb) -> bool:
        if _FORENSIC_ENABLED:
            system_event(
                "run_ended" if not exc_type else "run_aborted",
                severity="info" if not exc_type else "critical",
                payload={"run_id": self._run_id,
                         "error": str(exc_val) if exc_val else None},
                message=f"forensic run {self._run_id} "
                        f"{'ended' if not exc_type else 'ABORTED'}")
        flush("run_exit")
        return False  # never suppress exceptions
