# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
app/services/manual_sim.py
==========================
Manual Event-Timeline Simulator — "Time Machine" core.

WHAT THIS IS
------------
``RealSimEngine`` (app/services/real_simulation.py) drives the AUTOMATED stress
test: it opens one synchronous ``with ChronosEngine(...)`` block and races the
clock through every weekly cycle without stopping.  The Time Machine inverts that
control flow.  Here the clock is MANUAL: a developer jumps event → event along
the exact same milestone spine, and at each event only the real-world actions
valid at that instant are offered.

ZERO BUSINESS-LOGIC DUPLICATION
-------------------------------
This module owns NO financial rule.  It is a clock + event-state machine + a
thin persistence layer.  Every action a developer triggers at an event re-uses
the SAME production service that the live app and RealSimEngine call (auto-pay,
A/B/C grace settlement, draw preparation, draw execution, cleanup), each wrapped
in a request-scoped ``ChronosEngine`` so the strategy READS and WRITES the
simulated instant.  If a production rule changes, the Time Machine reflects it
automatically — there is no second implementation to drift.

THE CENTRAL ARCHITECTURE PROBLEM IT SOLVES
------------------------------------------
``ChronosEngine`` patches ``datetime`` process-wide and installs ``sim_clock``
for exactly the lifespan of a ``with`` block.  A manual stepper, by contrast,
advances across SEPARATE HTTP requests minutes or hours apart, so the clock
state must survive between requests AND must never leave a process-wide patch
installed while the server is idle (that would corrupt any concurrent request).

The solution has two halves:
  1. PERSISTENT STATE — the simulated instant, the anchoring draw time, the
     cycle number and the current event are stored in a single ``system_settings``
     JSON row (key ``manual_sim_state``).  It survives request boundaries and
     server restarts.
  2. REQUEST-SCOPED CLOCK — the ``ChronosEngine`` patch is installed ONLY for the
     duration of one action request (read sim_now → patch → run the production
     service → un-patch) and is NEVER held open between requests.  Concurrent
     traffic is therefore never exposed to a stale simulated clock.  See
     ``manual_clock()`` below; the action endpoints (Phase 3) use it.

EVENT SPINE — IDENTICAL TO _SimMilestones
-----------------------------------------
The seven manual events map one-to-one to the frozen ``_SimMilestones`` fields,
in the same strict order:

    CYCLE_START < DUE_DATE < GRACE_PERIOD_START < G_CLOSE < T_02H < T_00H < T_05M

A subtle, deliberately-faithful seam: for every cycle after the first,
CYCLE_START(N+1) == T_00H(N) (the draw instant IS the next cycle's opening).
To keep simulated time strictly MONOTONIC (it must only ever move forward), the
stepper begins cycle 1 at its dedicated CYCLE_START, and on every rollover
(after T_05M cleanup) advances cycle_num and lands on the next cycle's DUE_DATE
— the next genuinely-future event.  The draw event therefore doubles as the
new cycle's start, exactly as production behaves.  The "inject users" action is
available at EVERY event (24×7), so nothing is lost by folding the repeat
CYCLE_START into the draw.

SAFETY
------
Nothing here runs unless ENABLE_DEV_MODE is true — re-checked on every clock
install (``manual_clock`` refuses otherwise) as defence-in-depth on top of the
``require_dev_mode`` router gate.  The persisted session carries a TTL; a stale
session auto-expires so a forgotten "ON" state cannot linger.  In production
(ENABLE_DEV_MODE unset/false) the whole feature is inert.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.system_settings import SystemSettings
# ZERO-DUPLICATION: the clock + milestone arithmetic are imported from the same
# module RealSimEngine uses.  This module never re-derives a timestamp formula.
from app.services.real_simulation import (
    ChronosEngine,
    _compute_milestones,
    _SimMilestones,
)

_logger = logging.getLogger(__name__)

# Single system_settings row that holds the entire manual-sim session as JSON.
_STATE_KEY = "manual_sim_state"

# Default lifespan of a manual-sim session before it auto-expires.  A developer
# who forgets to "stop" the Time Machine will have it silently reverted rather
# than leaving the linked-clock banner up indefinitely.
_DEFAULT_TTL_HOURS = 6

# ── Event spine — EXACT order of _SimMilestones fields ───────────────────────
# Index position IS the chronological rank; jump-next walks this tuple.
EVENT_SPINE: tuple[str, ...] = (
    "CYCLE_START",
    "DUE_DATE",
    "GRACE_PERIOD_START",
    "G_CLOSE",
    "T_02H",
    "T_00H",
    "T_05M",
)

# Per-event presentation + the action keys valid at that instant.  "inject_users"
# is present on every event because user injection is available 24×7.  Action
# keys are wired to real production endpoints in Phase 3; the panel renders them
# from here so backend stays the single source of truth for what is offered.
EVENT_META: dict[str, dict] = {
    "CYCLE_START": {
        "label": "Cycle start",
        "short": "cycle start",
        "icon":  "ti-flag",
        "note":  "payment window opens",
        "actions": ["inject_users"],
    },
    "DUE_DATE": {
        "label": "Due date",
        "short": "due date",
        "icon":  "ti-cash",
        "note":  "on-time payment window closes",
        "actions": ["pay_all_installments", "set_late_pct", "pay_remaining", "inject_users"],
    },
    "GRACE_PERIOD_START": {
        "label": "Grace open",
        "short": "grace open",
        "icon":  "ti-hourglass-high",
        "note":  "grace window opens — late-fee vs grace-without-fee",
        "actions": ["grace_settlement", "inject_users"],
    },
    "G_CLOSE": {
        "label": "Grace close",
        "short": "grace close",
        "icon":  "ti-gavel",
        "note":  "guillotine — eliminations finalize",
        "actions": ["finalize_eliminations", "inject_users"],
    },
    "T_02H": {
        "label": "Draw prep −2h",
        "short": "draw prep",
        "icon":  "ti-settings-bolt",
        "note":  "lock acquired, L4 flagged, SDE meta-pool, re-assessor",
        "actions": ["prepare_draw", "inject_users"],
    },
    "T_00H": {
        "label": "Draw 00h",
        "short": "draw",
        "icon":  "ti-dice",
        "note":  "all pool draws execute — also opens the next cycle",
        "actions": ["execute_draw", "inject_users"],
    },
    "T_05M": {
        "label": "Cleanup +5m",
        "short": "cleanup",
        "icon":  "ti-broom",
        "note":  "weekly flags reset, lock released (then jump-next to roll over)",
        "actions": ["run_cleanup", "inject_users"],
    },
}

# Default A/B/C settlement knobs, carried in session state so the grace-window
# settlement can run with the late-ratio chosen at the due-date event.  These are
# PARAMETERS fed to the production apply_abc_model — never a re-implementation of
# its rules.
_DEFAULT_SETTLEMENT = {
    "late_ratio":  0.15,   # fraction of active members treated as late this cycle
    "elim_pct_a":  80.0,   # A — % of late directly eliminated (skip grace)
    "grace_pct_c": 15.0,   # C — % of grace-eligible late who pay and survive
}


# ── Dev-mode gate (defence-in-depth, independent of the router dependency) ────
def _dev_mode_enabled() -> bool:
    """True only when ENABLE_DEV_MODE is explicitly truthy in the environment.

    Mirrors app.core.dev_guard so the clock-install path enforces the same gate
    even if ever called outside the router (background task, test, REPL).
    """
    return os.getenv("ENABLE_DEV_MODE", "").strip().lower() in ("true", "1", "yes")


# ── Small datetime helpers (always tz-aware UTC) ─────────────────────────────
def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _default_draw_anchor(now: datetime) -> datetime:
    """Next Sunday 00:00 UTC — the production weekly draw moment (T_00H).

    Cycle 1's simulated clock starts one ``cycle_length`` before this, at the
    computed CYCLE_START, so the developer steps forward through a believable
    week with a real day-of-week.
    """
    # Python weekday(): Monday=0 … Sunday=6.
    days_ahead = (6 - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


# ── Persistence (single system_settings JSON row) ────────────────────────────
def _state_row(db: Session) -> Optional[SystemSettings]:
    return (
        db.query(SystemSettings)
        .filter(SystemSettings.key == _STATE_KEY)
        .one_or_none()
    )


def load_state(db: Session) -> Optional[dict]:
    """Return the persisted manual-sim session dict, or None when absent/blank."""
    row = _state_row(db)
    if row is None or not row.value_str:
        return None
    try:
        return json.loads(row.value_str)
    except (ValueError, TypeError):
        # Corrupt payload — treat as no session rather than crash the panel.
        _logger.warning("manual_sim: unreadable state payload; treating as inactive")
        return None


def save_state(db: Session, state: dict) -> None:
    """Upsert the manual-sim session JSON row."""
    row = _state_row(db)
    payload = json.dumps(state)
    if row is None:
        db.add(SystemSettings(key=_STATE_KEY, value_str=payload))
    else:
        row.value_str = payload
    db.commit()


def clear_state(db: Session) -> None:
    """Blank the session row (idempotent — safe when no row exists)."""
    row = _state_row(db)
    if row is not None:
        row.value_str = None
        db.commit()


# ── Request-scoped time-travel context ───────────────────────────────────────
def manual_clock(sim_now: datetime) -> ChronosEngine:
    """Return a request-scoped ``ChronosEngine`` pinned to ``sim_now``.

    Used by the Phase-3 action endpoints as::

        with manual_clock(sim_now):
            start_draw_preparation(db, ...)   # reads + writes the simulated time

    The patch is installed on ``__enter__`` and removed on ``__exit__`` of that
    single ``with`` block — NEVER held open across requests.  Refuses outright
    unless ENABLE_DEV_MODE is true, so a simulated clock can never be installed
    on a production process.
    """
    if not _dev_mode_enabled():
        raise RuntimeError(
            "manual_clock refused: ENABLE_DEV_MODE is not true — "
            "the simulation clock must never be installed in production."
        )
    pinned = sim_now if sim_now.tzinfo else sim_now.replace(tzinfo=timezone.utc)
    return ChronosEngine(pinned)


# ── Read model: lightweight snapshot for the watch panel ─────────────────────
def _snapshot(db: Session) -> dict:
    """Minimal real-DB counts for the Time Machine header (matches live-stats).

    Kept deliberately small — the full live-stats endpoint remains the rich
    dashboard source; this is only the at-a-glance state beside the watch.
    """
    from sqlalchemy import func
    from app.models.user import User, UserStatus, WeeklyPaymentStatus
    from app.models.pool import Pool, PoolStatus

    active = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active
    ).scalar() or 0
    waitlist = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Waitlist
    ).scalar() or 0
    paid = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Paid,
    ).scalar() or 0
    pools_active = db.query(func.count(Pool.id)).filter(
        Pool.status == PoolStatus.Active
    ).scalar() or 0
    pools_paused = db.query(func.count(Pool.id)).filter(
        Pool.status == PoolStatus.Paused_Awaiting_Members
    ).scalar() or 0

    return {
        "live_members": active,
        "waitlist":     waitlist,
        "paid_on_time": paid,
        "unpaid":       active - paid,
        "pools_active": pools_active,
        "pools_paused": pools_paused,
    }


def _ordered_milestones(ms: _SimMilestones) -> list[tuple[str, datetime]]:
    """The seven (event_name, datetime) pairs in strict chronological order."""
    return [(name, getattr(ms, name)) for name in EVENT_SPINE]


def compute_state(db: Session, *, include_snapshot: bool = True) -> dict:
    """Build the full Time Machine view for the frontend.

    Returns ``{"active": False, ...}`` when no live session exists OR when the
    session has passed its TTL (in which case it is auto-cleared first).  When a
    session is live, returns the watch (sim time / day / date), the cycle number,
    the current event, the seven-node timeline with past/current flags, the
    actions available at the current event, and a real-DB snapshot.
    """
    st = load_state(db)
    if not st or not st.get("active"):
        return {"active": False, "dev_mode": _dev_mode_enabled()}

    # TTL auto-expiry — a forgotten session reverts instead of lingering.
    exp = st.get("expires_at")
    if exp and _parse(exp) <= datetime.now(timezone.utc):
        clear_state(db)
        _logger.info("manual_sim: session expired at %s — auto-cleared", exp)
        return {"active": False, "expired": True, "dev_mode": _dev_mode_enabled()}

    sim_now = _parse(st["sim_now"])
    t00h    = _parse(st["cycle_t00h"])
    cur     = st["current_event"]
    ms      = _compute_milestones(db, t00h)

    events: list[dict] = []
    for name, dt in _ordered_milestones(ms):
        meta = EVENT_META[name]
        events.append({
            "name":       name,
            "label":      meta["label"],
            "short":      meta["short"],
            "icon":       meta["icon"],
            "note":       meta["note"],
            "iso":        _iso(dt),
            "is_current": name == cur,
            "is_past":    (dt < sim_now) and name != cur,
            "actions":    meta["actions"],
        })

    out = {
        "active":              True,
        "dev_mode":            _dev_mode_enabled(),
        "link_global":         bool(st.get("link_global")),
        "sim_now":             _iso(sim_now),
        "day_of_week":         sim_now.strftime("%A"),
        "date_str":            sim_now.strftime("%d %b %Y"),
        "time_str":            sim_now.strftime("%H:%M:%S"),
        "cycle_num":           st.get("cycle_num", 1),
        "current_event":       cur,
        "current_event_index": EVENT_SPINE.index(cur),
        "current_event_meta":  EVENT_META[cur],
        "available_actions":   EVENT_META[cur]["actions"],
        "events":              events,
        "cycle_t00h":          _iso(t00h),
        "created_at":          st.get("created_at"),
        "expires_at":          st.get("expires_at"),
    }
    if include_snapshot:
        out["snapshot"] = _snapshot(db)
    return out


# ── Session lifecycle ────────────────────────────────────────────────────────
def start_session(
    db: Session,
    *,
    draw_anchor: Optional[datetime] = None,
    link_global: bool = False,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> dict:
    """Create (or replace) a manual-sim session anchored at cycle 1's draw.

    ``draw_anchor`` is the T_00H (draw moment) of cycle 1; when omitted it
    defaults to the next Sunday 00:00 UTC.  The simulated clock starts at the
    computed CYCLE_START (one cycle_length before the draw) so the developer
    begins at the top of a fresh week.
    """
    if not _dev_mode_enabled():
        raise RuntimeError("start_session refused: ENABLE_DEV_MODE is not true.")

    now  = datetime.now(timezone.utc)
    t00h = (draw_anchor or _default_draw_anchor(now))
    if t00h.tzinfo is None:
        t00h = t00h.replace(tzinfo=timezone.utc)

    ms = _compute_milestones(db, t00h)

    # Every synthetic user the Time Machine injects carries this 8-char prefix so
    # the dev DB stays cleanly attributable and resettable.  The injector username
    # counter is persisted across inject actions within the session so usernames
    # never collide when "inject users" is triggered repeatedly.
    inject_prefix = ("msim" + uuid.uuid4().hex[:4])[:8].ljust(8, "0")

    state = {
        "active":         True,
        "sim_now":        _iso(ms.CYCLE_START),
        "cycle_t00h":     _iso(t00h),
        "cycle_num":      1,
        "current_event":  "CYCLE_START",
        "link_global":    bool(link_global),
        "inject_prefix":  inject_prefix,
        "inject_counter": 0,
        "settlement":     dict(_DEFAULT_SETTLEMENT),
        "created_at":     _iso(now),
        "expires_at":     _iso(now + timedelta(hours=max(1, int(ttl_hours)))),
    }
    save_state(db, state)
    _logger.info(
        "manual_sim: session started — anchor=%s cycle_start=%s link_global=%s ttl=%dh",
        _iso(t00h), _iso(ms.CYCLE_START), bool(link_global), ttl_hours,
    )
    return compute_state(db)


def stop_session(db: Session) -> dict:
    """Tear down the manual-sim session and guarantee no clock is left installed."""
    clear_state(db)
    # Defensive: should never be installed between requests, but never leave a
    # simulated write-clock live after an explicit stop.
    try:
        from app.core import sim_clock
        sim_clock.uninstall()
    except Exception:
        pass
    _logger.info("manual_sim: session stopped — clock uninstalled")
    return {"active": False, "stopped": True, "dev_mode": _dev_mode_enabled()}


# ── Jump engine (event-state machine) ────────────────────────────────────────
class ManualSimError(RuntimeError):
    """Raised on an invalid manual-sim operation (mapped to HTTP 409 by router)."""


def _require_active(db: Session) -> dict:
    st = load_state(db)
    if not st or not st.get("active"):
        raise ManualSimError("No active manual-sim session. Start the Time Machine first.")
    exp = st.get("expires_at")
    if exp and _parse(exp) <= datetime.now(timezone.utc):
        clear_state(db)
        raise ManualSimError("Manual-sim session expired. Start a fresh Time Machine session.")
    return st


def jump_next(db: Session) -> dict:
    """Advance the simulated clock to the NEXT event on the spine.

    Within a cycle, walks CYCLE_START → … → T_05M.  At T_05M (cleanup) it rolls
    over: cycle_num is incremented, the anchor advances by one cycle_length, and
    the clock lands on the next cycle's DUE_DATE — the next genuinely-future
    event (the next CYCLE_START coincides with the just-executed draw, so it is
    folded in rather than re-visited, keeping simulated time strictly forward).

    Jumping does NOT run any business logic — it only moves the clock and sets
    the current event.  Logic runs only when an event's action is triggered.
    """
    st = _require_active(db)
    t00h = _parse(st["cycle_t00h"])
    cur  = st["current_event"]
    ms   = _compute_milestones(db, t00h)
    idx  = EVENT_SPINE.index(cur)

    if idx < len(EVENT_SPINE) - 1:
        nxt = EVENT_SPINE[idx + 1]
        st["current_event"] = nxt
        st["sim_now"] = _iso(getattr(ms, nxt))
    else:
        next_t00h = ms.T_00H + ms.cycle_length
        nms = _compute_milestones(db, next_t00h)
        st["cycle_t00h"]    = _iso(next_t00h)
        st["cycle_num"]     = int(st.get("cycle_num", 1)) + 1
        st["current_event"] = "DUE_DATE"
        st["sim_now"]       = _iso(nms.DUE_DATE)

    save_state(db, st)
    return compute_state(db)


def jump_to(db: Session, event: str) -> dict:
    """Forward-only jump to a named event within the CURRENT cycle.

    ``event`` must be one of EVENT_SPINE and must be strictly AHEAD of the
    current event (the timeline only moves forward — to revisit an earlier
    event, roll into the next cycle via repeated jump-next).  CYCLE_START is the
    initial state only and cannot be jumped to mid-run.
    """
    if event not in EVENT_SPINE:
        raise ManualSimError(f"Unknown event '{event}'. Valid: {', '.join(EVENT_SPINE)}.")

    st  = _require_active(db)
    cur = st["current_event"]
    cur_idx = EVENT_SPINE.index(cur)
    tgt_idx = EVENT_SPINE.index(event)

    if tgt_idx <= cur_idx:
        raise ManualSimError(
            f"Cannot jump backward from '{cur}' to '{event}'. "
            "Time only moves forward — use jump-next to roll into the next cycle."
        )

    t00h = _parse(st["cycle_t00h"])
    ms   = _compute_milestones(db, t00h)
    st["current_event"] = event
    st["sim_now"] = _iso(getattr(ms, event))
    save_state(db, st)
    return compute_state(db)


# ── Action support (Phase 3) ─────────────────────────────────────────────────
# These helpers back the per-event action endpoints in app/routers/dev.py.  They
# carry NO financial rule — they only resolve the simulated instant, enforce the
# event→action guard, and manage session bookkeeping.  Each endpoint then runs a
# real production service inside ``with manual_clock(sim_now()):``.
def sim_now(db: Session) -> datetime:
    """The current simulated instant of the active session (tz-aware UTC)."""
    st = _require_active(db)
    return _parse(st["sim_now"])


def current_event(db: Session) -> str:
    """The current event name of the active session."""
    return _require_active(db)["current_event"]


def assert_action(db: Session, action_key: str) -> dict:
    """Return the active state, or raise ManualSimError if ``action_key`` is not
    offered at the CURRENT event.

    This is the server-side authority for what a developer may do at the instant
    they are standing on — the panel renders the same ``EVENT_META`` action list,
    but the guard is enforced here so a stale/forged client cannot run an action
    out of its valid window (e.g. executing the draw before the −2h prep event).
    """
    st  = _require_active(db)
    cur = st["current_event"]
    allowed = EVENT_META[cur]["actions"]
    if action_key not in allowed:
        raise ManualSimError(
            f"Action '{action_key}' is not available at event '{cur}'. "
            f"Allowed here: {', '.join(allowed)}."
        )
    return st


def reserve_inject_counter(db: Session, count: int) -> tuple[str, int]:
    """Reserve a contiguous block of ``count`` injector ids for this session.

    Returns ``(inject_prefix, base)``.  A freshly-built ``MassLoadInjector`` seeded
    with ``_counter = base`` will mint usernames ``{prefix}_{base+1:06d} …`` that
    never collide with a previous inject in the same session, because the stored
    counter is advanced by ``count`` and persisted before the injector runs.
    """
    st = _require_active(db)
    prefix = st.get("inject_prefix") or ("msim" + uuid.uuid4().hex[:4])[:8].ljust(8, "0")
    base   = int(st.get("inject_counter", 0))
    st["inject_prefix"]  = prefix
    st["inject_counter"] = base + max(0, int(count))
    save_state(db, st)
    return prefix, base


def get_settlement(db: Session) -> dict:
    """The A/B/C settlement knobs for the active session, merged over defaults."""
    st = _require_active(db)
    merged = dict(_DEFAULT_SETTLEMENT)
    merged.update(st.get("settlement") or {})
    return merged


def set_settlement(
    db: Session,
    *,
    late_ratio: Optional[float] = None,
    elim_pct_a: Optional[float] = None,
    grace_pct_c: Optional[float] = None,
) -> dict:
    """Update the session's settlement knobs (only the provided values change).

    These feed the production ``apply_abc_model`` at the grace-window event; they
    are stored here so the late-ratio chosen at the due-date event flows into the
    grace settlement without pre-marking members (which would conflict with the
    model's own late sampling).  Returns the merged knobs.
    """
    st = _require_active(db)
    cur = dict(_DEFAULT_SETTLEMENT)
    cur.update(st.get("settlement") or {})
    if late_ratio is not None:
        cur["late_ratio"] = max(0.0, min(1.0, float(late_ratio)))
    if elim_pct_a is not None:
        cur["elim_pct_a"] = max(0.0, min(100.0, float(elim_pct_a)))
    if grace_pct_c is not None:
        cur["grace_pct_c"] = max(0.0, min(100.0, float(grace_pct_c)))
    st["settlement"] = cur
    save_state(db, st)
    return cur


def cycle_window(db: Session) -> tuple[datetime, datetime]:
    """``(CYCLE_START, T_05M)`` of the session's CURRENT cycle, tz-aware UTC.

    Used to scope read-only reporting (e.g. counting the eliminations finalized in
    this cycle) without leaking into adjacent cycles.
    """
    st   = _require_active(db)
    t00h = _parse(st["cycle_t00h"])
    ms   = _compute_milestones(db, t00h)
    return ms.CYCLE_START, ms.T_05M
