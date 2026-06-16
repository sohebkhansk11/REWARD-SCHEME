# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
app/core/sim_clock.py
=====================
Single source of truth for "what time is it?" at the DATABASE-WRITE layer.

WHY THIS MODULE EXISTS
----------------------
The ChronosEngine (app/services/real_simulation.py) time-travels a simulation by
patching the Python ``datetime`` symbol inside a fixed set of strategy modules, so
that production STRATEGY LOGIC that *reads* ``datetime.now()`` (e.g. "is it past
the due date?", "is it draw time?") observes the simulated instant.

That patch governs LOGIC (reads) but has ZERO effect on the timestamps the strategy
*writes*, because every audit model —

    DrawHistory.draw_timestamp   (app/models/draw_history.py)
    Token.created_at             (app/models/token.py)
    Pool.created_at              (app/models/pool.py)
    EliminationEvent.created_at  (app/models/elimination_event.py)

— defaults its timestamp with SQLAlchemy ``server_default=func.now()``, a DDL
default that PostgreSQL evaluates SERVER-SIDE with the real wall-clock at INSERT
time.  Chronos cannot reach the database server's clock, so during a simulation
every audit row collapses onto the single real moment the run actually executed,
destroying any week-by-week view of the data (all simulated weeks fold into one
ISO calendar week).

This module closes that gap.  It exposes a process-wide virtual-clock override that
the ChronosEngine installs for EXACTLY the lifespan of its datetime patches (see
ChronosEngine.__enter__/__exit__).  The audit models use ``now()`` below as a
Python-side ``default=``, so:

  * During a simulation -> now() returns the simulated instant (the Chronos clock),
                           so every DrawHistory / Token / Pool / EliminationEvent
                           row is stamped with the correct virtual week.
  * In production        -> no override is installed, so now() returns the real UTC
                           wall-clock — functionally identical to the prior
                           ``server_default=func.now()`` behaviour (the app server
                           and the Render PostgreSQL instance are both UTC /
                           NTP-synced; the sub-second difference between app-clock
                           and db-clock is immaterial for audit ordering).

CONCURRENCY / SAFETY
--------------------
The override is a single process-wide reference, installed and removed in lockstep
with the ChronosEngine datetime patches (which are themselves process-wide via
unittest.mock.patch).  Simulations only run when ENABLE_DEV_MODE is true, which is
NEVER the case in production, so the override is never live alongside real
money-bearing traffic.  The model columns RETAIN ``server_default=func.now()`` as a
defence-in-depth fallback for any raw-SQL / non-ORM insert path that omits the
column entirely.

This module imports ONLY the standard library, so models may import it without any
risk of a circular import (models depend downward on app.core; app.core never
imports models).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, Optional

# Process-wide virtual-clock provider.  None => no simulation active => real clock.
_clock_fn: "Optional[Callable[[], datetime]]" = None
# Guards install/uninstall so the reference swap is atomic across threads.
_lock = threading.Lock()


def install(clock_fn: "Callable[[], datetime]") -> None:
    """Install a virtual-clock provider (called by ChronosEngine.__enter__).

    ``clock_fn`` must return a timezone-aware datetime representing the current
    simulated instant.  Replaces any previously installed provider.
    """
    global _clock_fn
    with _lock:
        _clock_fn = clock_fn


def uninstall() -> None:
    """Remove the virtual-clock provider (called by ChronosEngine.__exit__)."""
    global _clock_fn
    with _lock:
        _clock_fn = None


def is_simulated() -> bool:
    """True when a virtual-clock provider is installed (a simulation is active)."""
    return _clock_fn is not None


def now() -> datetime:
    """Return the current instant for DB-write timestamps.

    Used as the Python-side ``default=`` on every audit model's timestamp column,
    and called explicitly at the bulk-insert sites that bypass the ORM default.

    Returns the simulated instant when a ChronosEngine is active, otherwise the
    real UTC wall-clock.  ALWAYS returns a timezone-aware (UTC) datetime so that
    DateTime(timezone=True) columns never receive a naive value.
    """
    fn = _clock_fn
    if fn is not None:
        ts = fn()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    return datetime.now(timezone.utc)
