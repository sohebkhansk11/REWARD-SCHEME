# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
System Debugger — Global Load-Test Monitor
==========================================

TOGGLE:  POST /dev/debugger/toggle  {"enabled": true | false}

When OFF (default production state):
  - @debug_trace decorators are PURE ZERO-OVERHEAD pass-throughs.
  - _write_log() is never called.
  - Zero DB writes, zero imports beyond the boolean check.

When ON (staging load-test mode):
  - Every @debug_trace-decorated function is timed (perf_counter).
  - Return value summary + exception text are serialised to JSON.
  - One DebugLog row is written per call via a SHORT-LIVED independent
    session — it NEVER interferes with the simulation's own session.
  - log_milestone() allows manual milestone entries (Chronos tick labels).

Architecture:
  _DEBUGGER_ENABLED  — module-level bool (GIL makes single-flag reads atomic)
  _CURRENT_RUN_ID    — hex job_id of the active simulation run
  _CURRENT_WEEK      — current simulated week number (set per-week by engine)

  @debug_trace(phase) — decorator factory; one boolean check on entry
  _write_log()        — DB insert; only reachable when debugger is ON
  log_milestone()     — manual entry; no-op when debugger is OFF
  DebuggerSession     — context manager; emits SIM/start + SIM/end markers

Easy removal (before public launch):
  1. Delete this file.
  2. Delete app/models/debug_log.py + drop the debug_logs table.
  3. Remove `from app.services.system_debugger import ...` lines in
     real_simulation.py and any @debug_trace decorators.
  Zero residual footprint — decorators never ship to production.
"""

import functools
import json
import logging
import time
from typing import Any, Callable

_logger = logging.getLogger(__name__)

# ── Global state (module-level — GIL protects single-assignment writes) ───────
_DEBUGGER_ENABLED: bool = False
_CURRENT_RUN_ID:   str  = ""
_CURRENT_WEEK:     int  = 0


# ── Toggle API ────────────────────────────────────────────────────────────────

def enable_debugger(run_id: str = "") -> None:
    """Enable the debugger and tag all subsequent logs with run_id."""
    global _DEBUGGER_ENABLED, _CURRENT_RUN_ID
    _DEBUGGER_ENABLED = True
    _CURRENT_RUN_ID   = run_id or "manual"
    _logger.info("SystemDebugger ENABLED  run_id=%s", _CURRENT_RUN_ID)


def disable_debugger() -> None:
    """Disable the debugger and clear run context."""
    global _DEBUGGER_ENABLED, _CURRENT_RUN_ID, _CURRENT_WEEK
    _DEBUGGER_ENABLED = False
    _CURRENT_RUN_ID   = ""
    _CURRENT_WEEK     = 0
    _logger.info("SystemDebugger DISABLED")


def set_debug_week(week: int) -> None:
    """Called once per simulated week so all log entries in that week carry week_num."""
    global _CURRENT_WEEK
    _CURRENT_WEEK = week


def is_debugger_on() -> bool:
    return _DEBUGGER_ENABLED


def get_debug_context() -> dict:
    return {
        "enabled": _DEBUGGER_ENABLED,
        "run_id":  _CURRENT_RUN_ID,
        "week":    _CURRENT_WEEK,
    }


# ── Internal DB writer ────────────────────────────────────────────────────────

def _write_log(
    phase:       str,
    event:       str,
    data:        Any   = None,
    duration_ms: float = None,
    lpi:         float = None,
    error:       str   = None,
) -> None:
    """
    Insert one DebugLog row using an independent short-lived session.

    Completely isolated from the simulation session — a write failure here
    can never roll back simulation data.  All exceptions are swallowed so
    a debugger bug cannot abort the simulation.
    """
    try:
        from app.database import SessionLocal
        from app.models.debug_log import DebugLog

        data_json = None
        if data is not None:
            try:
                raw = json.dumps(data, default=str)
                # Truncate oversized payloads to prevent runaway row sizes
                data_json = raw[:4096] if len(raw) > 4096 else raw
            except Exception:
                data_json = str(data)[:4096]

        row = DebugLog(
            run_id      = _CURRENT_RUN_ID or "manual",
            week_num    = _CURRENT_WEEK   or None,
            phase       = phase,
            event       = event,
            data_json   = data_json,
            duration_ms = duration_ms,
            lpi         = lpi,
            error       = error,
        )
        _db = SessionLocal()
        try:
            _db.add(row)
            _db.commit()
        finally:
            _db.close()

    except Exception as exc:
        # Debugger must never crash the system it is monitoring
        _logger.debug("SystemDebugger._write_log silently failed: %s", exc)


# ── Decorator factory ─────────────────────────────────────────────────────────

def debug_trace(phase: str):
    """
    Decorator that instruments a function with timing and DB logging.

    Usage:
        @debug_trace("TICK-2/payments")
        def tick2_on_time_payments(self, db, ...):
            ...

    When _DEBUGGER_ENABLED is False:
        wrapper() does exactly ONE boolean check, then calls fn() directly.
        No closure evaluation, no time call, no imports.  Pure pass-through.

    When _DEBUGGER_ENABLED is True:
        - Wall-clock duration measured with time.perf_counter()
        - If fn() returns a dict, a sanitised summary is stored in data_json
          (lists and bytes excluded to cap row size)
        - If fn() raises, the exception type+message is stored in error
          and the exception is re-raised unchanged
        - One DebugLog row is written via _write_log() in a separate session
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _DEBUGGER_ENABLED:
                return fn(*args, **kwargs)   # ← zero overhead pass-through

            t0      = time.perf_counter()
            result  = None
            err_str = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                err_str = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                duration_ms = round((time.perf_counter() - t0) * 1_000, 2)

                # Capture a safe subset of the return value for logging
                data_payload = None
                if isinstance(result, dict):
                    data_payload = {
                        k: v for k, v in result.items()
                        if not isinstance(v, (list, bytes, set))
                    }
                elif isinstance(result, int):
                    data_payload = {"count": result}

                _write_log(
                    phase       = phase,
                    event       = fn.__name__,
                    data        = data_payload,
                    duration_ms = duration_ms,
                    error       = err_str,
                )
        return wrapper
    return decorator


# ── Manual milestone entry ────────────────────────────────────────────────────

def log_milestone(
    phase: str,
    event: str,
    data:  Any   = None,
    lpi:   float = None,
) -> None:
    """
    Write a DebugLog row for a named simulation milestone that is NOT a
    function call (e.g. "Chronos → T-02H", "Pool formation triggered").

    No-op when the debugger is OFF.  Never raises.
    """
    if not _DEBUGGER_ENABLED:
        return
    _write_log(phase=phase, event=event, data=data, lpi=lpi)


# ── Context manager for a full simulation run ─────────────────────────────────

class DebuggerSession:
    """
    Emits SIM/start and SIM/end markers around a simulation run.

    Does NOT enable or disable the debugger — that is controlled
    independently via toggle.  This only adds bracketing log entries so
    the log viewer can clearly separate runs.

    Usage:
        with DebuggerSession(run_id=self._run_id):
            ...simulation loop...
    """

    def __init__(self, run_id: str):
        self._run_id = run_id

    def __enter__(self) -> "DebuggerSession":
        if _DEBUGGER_ENABLED:
            _write_log(
                phase = "SIM/start",
                event = "simulation_started",
                data  = {"run_id": self._run_id},
            )
        return self

    def __exit__(self, exc_type, exc_val, _tb) -> bool:
        if _DEBUGGER_ENABLED:
            _write_log(
                phase = "SIM/end",
                event = "simulation_ended" if not exc_type else "simulation_aborted",
                data  = {
                    "run_id": self._run_id,
                    "error":  str(exc_val) if exc_val else None,
                },
            )
        return False   # never suppress exceptions
