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
    # SESSION EDIT [Jun-24]: cycle-rollover payment reset (carry-forward lifecycle).
    _fm_reset_payment_cycle,
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
        # A/B/C settlement — EVERY late member accrues a late fee; the buckets are
        # A (eliminated) / B (late fee, stay Unpaid in pool) / C (grace-pay survive).
        "note":  "A/B/C settlement — eliminate (A) · late-fee stay (B) · grace-pay survive (C)",
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

# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ── Event-driven HARD-BLOCK gating ("no override") ───────────────────────────
# Each event has a REQUIRED action that must be completed before the clock may
# advance off it.  A tuple means "any ONE of these satisfies" (the due-date can be
# settled either by paying everyone on time OR by setting a late-ratio and paying
# the remainder).  ``None`` = no required action (a pure marker event — only the
# always-optional inject_users is offered there, which never gates advancement).
# jump_next / jump_to refuse (ManualSimError → HTTP 409) until the requirement is
# met; the frontend dims the advance control and explains WHY it is dim.
REQUIRED_ACTION: dict[str, "Optional[tuple[str, ...]]"] = {
    "CYCLE_START":        None,
    "DUE_DATE":           ("pay_all_installments", "pay_remaining"),
    "GRACE_PERIOD_START": ("grace_settlement",),
    "G_CLOSE":            ("finalize_eliminations",),
    "T_02H":              ("prepare_draw",),
    "T_00H":              ("execute_draw",),
    "T_05M":              ("run_cleanup",),
}

# ── Mutual-exclusion / single-shot locks ("no overwrite") ────────────────────
# When the key action completes at its event, every action listed in the value is
# DIMMED for the remainder of that cycle:event visit.  An action that names itself
# is single-shot (it cannot be re-run).  pay-all and the set-late/pay-remaining
# path lock each other, so a settled due-date can never be re-settled (the user's
# "if I pay all then other buttons should be dim — no override no overwritten").
# inject_users is intentionally absent: member injection stays available 24×7.
ACTION_LOCKS: dict[str, tuple[str, ...]] = {
    "pay_all_installments":  ("pay_all_installments", "set_late_pct", "pay_remaining"),
    # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # set_late_pct is now a real money mutation (accrues per-member late fees + marks
    # the cohort at-risk), so it must be SINGLE-SHOT (re-running would double-accrue)
    # AND mutually exclusive with pay-all (a cycle settled "everyone on time" can
    # never also designate a late cohort — no override, no overwrite).
    "set_late_pct":          ("set_late_pct", "pay_all_installments"),
    "pay_remaining":         ("pay_remaining", "pay_all_installments"),
    "grace_settlement":      ("grace_settlement",),
    "finalize_eliminations": ("finalize_eliminations",),
    "prepare_draw":          ("prepare_draw",),
    "execute_draw":          ("execute_draw",),
    "run_cleanup":           ("run_cleanup",),
}

# Human-readable labels for the gating notes / dim reasons surfaced to the panel.
ACTION_LABELS: dict[str, str] = {
    "inject_users":          "Inject members",
    "pay_all_installments":  "Pay all installments",
    "set_late_pct":          "Set late %",
    "pay_remaining":         "Pay remaining",
    "grace_settlement":      "A/B/C grace settlement",
    "finalize_eliminations": "Finalize eliminations",
    "prepare_draw":          "Prepare draw",
    "execute_draw":          "Execute draw",
    "run_cleanup":           "Run cleanup",
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


# ── Always-on audit trail (independent of the Forensic Debugger toggle) ───────
def _audit(
    db: Session,
    event_type: str,
    *,
    event: Optional[str] = None,
    cycle_num: Optional[int] = None,
    sim_now: Optional[datetime] = None,
    payload: Optional[dict] = None,
    severity: str = "info",
    message: Optional[str] = None,
) -> None:
    """Append one immutable ForensicEvent row for a Time-Machine operation.

    Manual time-travel mutates REAL (dev-DB) money state, so every start / stop /
    jump / link-toggle / action must leave an append-only audit trail REGARDLESS
    of whether the Forensic Debugger capture toggle is on (forensic.record() is a
    no-op when off).  We therefore write the row directly, tagged run_id
    "manual_sim" and tick "MANUAL/<event>" so it is trivially filterable and never
    confused with a stress-test capture.

    Failure-isolated: an audit hiccup must never break the operation it records.
    """
    try:
        from app.models.forensic_event import ForensicEvent
        row = ForensicEvent(
            run_id="manual_sim",
            week_id=(int(cycle_num) if cycle_num is not None else None),
            tick=(f"MANUAL/{event}" if event else "MANUAL"),
            category="SYSTEM",
            event_type=str(event_type)[:48],
            severity=str(severity)[:12],
            actor="dev:manual_sim",
            entity_type="session",
            entity_ref=(sim_now.strftime("%a %d %b %H:%M") if sim_now else None),
            payload_json=(json.dumps(payload, default=str)[:4096] if payload else None),
            message=(str(message or event_type)[:512]),
        )
        db.add(row)
        db.commit()
    except Exception as exc:        # audit must never break the operation
        try:
            db.rollback()
        except Exception:
            pass
        _logger.debug("manual_sim audit swallowed: %s", exc)


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


# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
def _compliance(db: Session, *, window: "Optional[tuple[datetime, datetime]]" = None) -> dict:
    """Real-DB payment-compliance breakdown for the Time Machine panel.

    Every count is read straight from the production tables (no override, no
    synthetic figure) so the developer sees exactly what the strategy will act on
    before advancing.  ``window`` (CYCLE_START, T_05M) scopes the elimination count
    to the CURRENT cycle so it does not leak across rollovers.
    """
    from sqlalchemy import func
    from app.models.user import User, UserStatus, WeeklyPaymentStatus
    from app.models.pool import Pool, PoolStatus
    from app.models.elimination_event import EliminationEvent

    active = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active
    ).scalar() or 0
    paid = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Paid,
    ).scalar() or 0
    unpaid = active - paid
    # Late = Unpaid AND carrying an accrued late fee (the production "late payer"
    # state apply_abc_model produces; distinct from merely not-yet-paid).
    late_payers = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
        User.late_fees_inr > 0,
    ).scalar() or 0
    grace_active = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active,
        User.grace_active.is_(True),
    ).scalar() or 0
    grace_fee_paid = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active,
        User.grace_fee_paid.is_(True),
    ).scalar() or 0
    at_risk = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active,
        User.elimination_risk.is_(True),
    ).scalar() or 0
    waitlist = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Waitlist
    ).scalar() or 0

    eliminated_this_cycle = 0
    if window is not None:
        start, end = window
        eliminated_this_cycle = db.query(func.count(EliminationEvent.id)).filter(
            EliminationEvent.created_at >= start,
            EliminationEvent.created_at <= end,
        ).scalar() or 0

    pools_active = db.query(func.count(Pool.id)).filter(
        Pool.status == PoolStatus.Active
    ).scalar() or 0
    pools_paused = db.query(func.count(Pool.id)).filter(
        Pool.status == PoolStatus.Paused_Awaiting_Members
    ).scalar() or 0

    return {
        "active":                active,
        "paid_on_time":          paid,
        "unpaid":                unpaid,
        "late_payers":           late_payers,
        "grace_active":          grace_active,
        "grace_fee_paid":        grace_fee_paid,
        "at_risk":               at_risk,
        "eliminated_this_cycle": eliminated_this_cycle,
        "waitlist":              waitlist,
        "pools_active":          pools_active,
        "pools_paused":          pools_paused,
    }


def task_list(event: str, c: dict, settlement: dict) -> list[str]:
    """Event-aware "what must happen here" checklist, derived from live counts.

    Pure presentation — every number comes from ``_compliance`` (the production
    tables).  Answers the user's "har event par task list aani chahie" so the
    developer knows, at each event, how many members must pay / are late / are
    grace-eligible / are eliminated before advancing.
    """
    late_ratio = float(settlement.get("late_ratio", 0.0) or 0.0)
    tasks: list[str] = []
    if event == "CYCLE_START":
        tasks.append(f"Payment window open — {c['active']} active, {c['waitlist']} on waitlist.")
        tasks.append("Optional: inject members (random join-time within today's date).")
    elif event == "DUE_DATE":
        tasks.append(f"{c['unpaid']} of {c['active']} active members must pay this week's installment.")
        tasks.append(f"Projected late this cycle (knob): {int(c['active'] * late_ratio)} @ late-ratio {late_ratio:.0%}.")
        tasks.append("Settle: Pay-all (everyone on time) OR Set-late % then Pay-remaining.")
    elif event == "GRACE_PERIOD_START":
        # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Truthful A/B/C model — bucket B no longer "pays late-fee & stays Unpaid".
        # B is granted grace that EXPIRES at G_CLOSE → swept (grace_expired) by the
        # guillotine.  Only C (grace-fee paid) survives; A & B are both eliminated.
        tasks.append(f"{c['at_risk']} at-risk (Unpaid) member(s) to settle via A/B/C.")
        tasks.append("A% eliminate (non-payment) · C% grace-pay & survive · "
                     "B remainder grace-expires at G_CLOSE → eliminated.")
        tasks.append(f"Grace-active now: {c['grace_active']} · grace-fee paid: {c['grace_fee_paid']}.")
    elif event == "G_CLOSE":
        # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Finalize is the REAL guillotine now: eliminate every Active member still
        # risk=True AND grace_active=False (A → non_payment) plus those whose grace
        # expired at this instant (B → grace_expired).  After close, NO Unpaid member
        # may remain Active — that is the production invariant we assert.
        tasks.append(f"Finalize the guillotine — {c['at_risk']} at-risk member(s) pending: "
                     "A → non-payment, B → grace-expired; C (grace-paid) survives.")
        tasks.append("After G_CLOSE no Unpaid member may stay Active (vacancies refill from waitlist).")
    elif event == "T_02H":
        tasks.append(f"Prepare draw — {c['active']} active across {c['pools_active']} pool(s).")
        tasks.append("Acquires draw lock, flags L4, plans SDE meta-pool, freezes LPI snapshot.")
    elif event == "T_00H":
        tasks.append(f"Execute draw across {c['pools_active']} active pool(s).")
        tasks.append(f"{c['pools_paused']} pool(s) paused awaiting members; {c['waitlist']} on waitlist.")
    elif event == "T_05M":
        tasks.append("Cleanup — reset weekly flags, release draw lock, settle referral-RW.")
        tasks.append("Then jump-next to roll into the next cycle (lands on its Due-date).")
    return tasks


def _disabled_actions(event: str, done_here: list[str]) -> list[str]:
    """Actions to DIM at ``event`` given what's already been done this visit.

    Applies the ACTION_LOCKS mutual-exclusion / single-shot rules and intersects
    with the actions actually offered at this event.  inject_users is never dimmed.
    """
    disabled: set[str] = set()
    for done in done_here:
        for locked in ACTION_LOCKS.get(done, ()):
            disabled.add(locked)
    disabled.discard("inject_users")
    return [a for a in EVENT_META[event]["actions"] if a in disabled]


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

    # TTL countdown for the red "Time Machine is LIVE" banner — seconds until the
    # session auto-expires (never negative; 0 means it is about to revert).
    ttl_remaining = None
    if exp:
        ttl_remaining = max(0, int((_parse(exp) - datetime.now(timezone.utc)).total_seconds()))

    cyc = int(st.get("cycle_num", 1))
    events: list[dict] = []
    for name, dt in _ordered_milestones(ms):
        meta = EVENT_META[name]
        req  = REQUIRED_ACTION.get(name)
        ev_done = _event_done(st, cyc, name)
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
            # SESSION EDIT [Jun-24]: per-event gating telemetry for the timeline.
            "required":      list(req) if req else [],
            "required_done": (not req) or any(a in ev_done for a in req),
        })

    # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Event-driven gating + dim-lock telemetry for the CURRENT event.
    cur_required = REQUIRED_ACTION.get(cur)
    can_adv, adv_reason = advance_gate(st)
    done_here = _event_done(st, cyc, cur)
    disabled  = _disabled_actions(cur, done_here)
    settlement = dict(_DEFAULT_SETTLEMENT)
    settlement.update(st.get("settlement") or {})

    out = {
        "active":              True,
        "dev_mode":            _dev_mode_enabled(),
        "link_global":         bool(st.get("link_global")),
        "sim_now":             _iso(sim_now),
        "day_of_week":         sim_now.strftime("%A"),
        "date_str":            sim_now.strftime("%d %b %Y"),
        "time_str":            sim_now.strftime("%H:%M:%S"),
        "cycle_num":           cyc,
        "current_event":       cur,
        "current_event_index": EVENT_SPINE.index(cur),
        "current_event_meta":  EVENT_META[cur],
        "available_actions":   EVENT_META[cur]["actions"],
        "events":              events,
        "cycle_t00h":          _iso(t00h),
        "created_at":          st.get("created_at"),
        "expires_at":          st.get("expires_at"),
        "ttl_hours":           st.get("ttl_hours", _DEFAULT_TTL_HOURS),
        "ttl_remaining_seconds": ttl_remaining,
        # ── Event-driven gating (hard-block, no override) ────────────────────
        "required_action":     list(cur_required) if cur_required else [],
        "required_done":       (not cur_required) or any(a in done_here for a in cur_required),
        "can_advance":         can_adv,
        "advance_block_reason": adv_reason,
        "actions_done":        done_here,
        "disabled_actions":    disabled,
        "settlement":          settlement,
    }
    if include_snapshot:
        out["snapshot"] = _snapshot(db)
        # Real-DB compliance breakdown + per-event task list (payment compliance).
        compliance = _compliance(db, window=(ms.CYCLE_START, ms.T_05M))
        out["compliance"] = compliance
        out["task_list"]  = task_list(cur, compliance, settlement)
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

    ttl = max(1, int(ttl_hours))
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
        # SESSION EDIT [Jun-24]: the REAL late cohort designated at the due-date event
        # (ids).  pay-remaining skips them; rollover + pay-all clear them.
        "late_cohort_ids": [],
        "ttl_hours":      ttl,
        "created_at":     _iso(now),
        "expires_at":     _iso(now + timedelta(hours=ttl)),
    }
    save_state(db, state)
    _logger.info(
        "manual_sim: session started — anchor=%s cycle_start=%s link_global=%s ttl=%dh",
        _iso(t00h), _iso(ms.CYCLE_START), bool(link_global), ttl,
    )
    _audit(db, "session_started", event="CYCLE_START", cycle_num=1,
           sim_now=ms.CYCLE_START,
           payload={"anchor": _iso(t00h), "link_global": bool(link_global), "ttl_hours": ttl},
           message=f"Time Machine started — anchor {_iso(t00h)}, link={bool(link_global)}")
    return compute_state(db)


def stop_session(db: Session) -> dict:
    """Tear down the manual-sim session and guarantee no clock is left installed."""
    prev = load_state(db)
    clear_state(db)
    # Defensive: should never be installed between requests, but never leave a
    # simulated write-clock live after an explicit stop.
    try:
        from app.core import sim_clock
        sim_clock.uninstall()
    except Exception:
        pass
    _logger.info("manual_sim: session stopped — clock uninstalled")
    if prev and prev.get("active"):
        _audit(db, "session_stopped", event=prev.get("current_event"),
               cycle_num=prev.get("cycle_num"),
               message="Time Machine stopped — clock uninstalled")
    return {"active": False, "stopped": True, "dev_mode": _dev_mode_enabled()}


def touch_session(db: Session) -> None:
    """Slide the session's TTL forward by its original window on activity.

    A session that is being actively driven (jumps / actions) must not expire
    mid-work, yet a forgotten session must still revert.  Each operation pushes
    ``expires_at`` to ``now + ttl_hours`` — so the safety timer measures IDLE time,
    not total session age.  No-op if there is no active session.
    """
    st = load_state(db)
    if not st or not st.get("active"):
        return
    ttl = max(1, int(st.get("ttl_hours", _DEFAULT_TTL_HOURS)))
    st["expires_at"] = _iso(datetime.now(timezone.utc) + timedelta(hours=ttl))
    save_state(db, st)


def set_link(db: Session, link_global: bool) -> dict:
    """Toggle whether the global watch is linked to the simulation watch.

    The simulated clock is always request-scoped (installed only inside an action
    request and never held open), so this flag is a DISPLAY/intent switch: when on,
    the frontend mirrors the global watch to the simulated instant while a session
    is live.  Requires an active session.
    """
    st = _require_active(db)
    st["link_global"] = bool(link_global)
    save_state(db, st)
    _audit(db, "link_toggled", event=st.get("current_event"),
           cycle_num=st.get("cycle_num"),
           payload={"link_global": bool(link_global)},
           message=f"Global-watch link {'ON' if link_global else 'OFF'}")
    return compute_state(db)


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


# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ── Event-driven gating helpers ──────────────────────────────────────────────
def _event_key(st: dict) -> str:
    """Stable per-visit key ``"<cycle>:<event>"`` for action-completion tracking.

    Including the cycle number means each rollover starts a fresh slate — the new
    cycle's Due-date gate is independent of the previous cycle's settlement.
    """
    return f"{int(st.get('cycle_num', 1))}:{st.get('current_event')}"


def _event_done(st: dict, cycle_num: int, event: str) -> list[str]:
    """The list of action keys completed at a given cycle:event (never None)."""
    return list((st.get("actions_done") or {}).get(f"{int(cycle_num)}:{event}", []))


def record_action(db: Session, action_key: str) -> None:
    """Mark ``action_key`` complete for the CURRENT cycle:event.

    Drives both the advance-gate (required action satisfied) and the dim locks
    (mutual-exclusion / single-shot).  Called by the action spine AFTER the
    production service has committed, so a failed action records nothing.
    """
    st = _require_active(db)
    done = st.setdefault("actions_done", {})
    key  = _event_key(st)
    bucket = done.setdefault(key, [])
    if action_key not in bucket:
        bucket.append(action_key)
    save_state(db, st)


def advance_gate(st: dict) -> tuple[bool, str]:
    """Whether the clock may step OFF the current event, and why not.

    Hard-block / no-override: if the current event has a REQUIRED action, at least
    one of its options must already be recorded for this cycle:event.  Returns
    ``(can_advance, reason)`` — reason is "" when advancement is allowed.
    """
    cur = st.get("current_event")
    required = REQUIRED_ACTION.get(cur)
    if not required:
        return True, ""
    done = _event_done(st, st.get("cycle_num", 1), cur)
    if any(a in done for a in required):
        return True, ""
    labels = " or ".join(ACTION_LABELS.get(a, a) for a in required)
    return False, f"Complete “{labels}” at {EVENT_META[cur]['label']} before advancing — no override."


def _path_gate(st: dict, target_event: str) -> tuple[bool, str]:
    """Multi-step forward jump guard: EVERY event from the current one up to (but
    excluding) ``target_event`` must have its required action satisfied.

    This enforces the user's "without event-driven, next event can't be jumped"
    rule even for a timeline shortcut that skips intermediate nodes — you cannot
    leap past an event whose work is still pending.
    """
    cur_idx = EVENT_SPINE.index(st["current_event"])
    tgt_idx = EVENT_SPINE.index(target_event)
    cyc = int(st.get("cycle_num", 1))
    for i in range(cur_idx, tgt_idx):
        ev = EVENT_SPINE[i]
        required = REQUIRED_ACTION.get(ev)
        if not required:
            continue
        if not any(a in _event_done(st, cyc, ev) for a in required):
            labels = " or ".join(ACTION_LABELS.get(a, a) for a in required)
            return False, (f"Complete “{labels}” at {EVENT_META[ev]['label']} "
                           f"before jumping past it — no override.")
    return True, ""


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
    # HARD-BLOCK gate — the current event's required action must be done first.
    ok, why = advance_gate(st)
    if not ok:
        raise ManualSimError(why)
    t00h = _parse(st["cycle_t00h"])
    cur  = st["current_event"]
    ms   = _compute_milestones(db, t00h)
    idx  = EVENT_SPINE.index(cur)

    if idx < len(EVENT_SPINE) - 1:
        nxt = EVENT_SPINE[idx + 1]
        st["current_event"] = nxt
        st["sim_now"] = _iso(getattr(ms, nxt))
        rolled = False
    else:
        # SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Cycle rollover (T_05M → next cycle's DUE_DATE).  Carry-forward + reset:
        # the new week's installment is owed, so every SURVIVING Active member is
        # reset Paid→Unpaid via the REAL production helper (_fm_reset_payment_cycle).
        # Members injected AFTER this point join Paid, so the next due-date
        # enforcement never touches fresh joiners (bug #1).  The previous cycle's
        # designated late cohort is cleared — a brand-new week starts clean.
        _fm_reset_payment_cycle(db)            # commits the survivors→Unpaid reset
        st["late_cohort_ids"] = []
        next_t00h = ms.T_00H + ms.cycle_length
        nms = _compute_milestones(db, next_t00h)
        st["cycle_t00h"]    = _iso(next_t00h)
        st["cycle_num"]     = int(st.get("cycle_num", 1)) + 1
        st["current_event"] = "DUE_DATE"
        st["sim_now"]       = _iso(nms.DUE_DATE)
        rolled = True

    ttl = max(1, int(st.get("ttl_hours", _DEFAULT_TTL_HOURS)))
    st["expires_at"] = _iso(datetime.now(timezone.utc) + timedelta(hours=ttl))
    save_state(db, st)
    _audit(db, "rollover" if rolled else "jump_next",
           event=st["current_event"], cycle_num=st["cycle_num"],
           sim_now=_parse(st["sim_now"]),
           message=("rolled into cycle %d → %s" % (st["cycle_num"], st["current_event"]))
                   if rolled else ("jumped to %s" % st["current_event"]))
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

    # HARD-BLOCK gate — cannot leap past any event whose required action is pending.
    ok, why = _path_gate(st, event)
    if not ok:
        raise ManualSimError(why)

    t00h = _parse(st["cycle_t00h"])
    ms   = _compute_milestones(db, t00h)
    st["current_event"] = event
    st["sim_now"] = _iso(getattr(ms, event))
    ttl = max(1, int(st.get("ttl_hours", _DEFAULT_TTL_HOURS)))
    st["expires_at"] = _iso(datetime.now(timezone.utc) + timedelta(hours=ttl))
    save_state(db, st)
    _audit(db, "jump_to", event=event, cycle_num=st.get("cycle_num"),
           sim_now=_parse(st["sim_now"]), message=f"jumped to {event}")
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


# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
def milestones(db: Session) -> _SimMilestones:
    """The frozen ``_SimMilestones`` for the session's CURRENT cycle.

    Exposes every milestone instant (notably ``G_CLOSE``) so an action can pin a
    production deadline to the exact simulated milestone — e.g. the grace-window
    settlement grants bucket-B grace expiring AT ``G_CLOSE`` so the guillotine sweeps
    them precisely when the window closes.
    """
    st   = _require_active(db)
    return _compute_milestones(db, _parse(st["cycle_t00h"]))


# ── Late-cohort carry-forward (the REAL due-date late set) ────────────────────
# The ids of members designated late at the due-date event are persisted so the
# straggler pay-remaining can skip them (they must stay Unpaid + at-risk into the
# grace window).  Cleared at rollover (new week) and by pay-all (everyone on time).
def set_late_cohort(db: Session, ids: "list[int]") -> None:
    """Persist the designated late-cohort member ids for the current cycle."""
    st = _require_active(db)
    st["late_cohort_ids"] = [int(i) for i in (ids or [])]
    save_state(db, st)


def get_late_cohort(db: Session) -> "list[int]":
    """The designated late-cohort member ids for the current cycle (never None)."""
    st = _require_active(db)
    return [int(i) for i in (st.get("late_cohort_ids") or [])]


def clear_late_cohort(db: Session) -> None:
    """Clear the designated late cohort (idempotent — safe when already empty)."""
    st = _require_active(db)
    if st.get("late_cohort_ids"):
        st["late_cohort_ids"] = []
        save_state(db, st)


# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
def inject_window(db: Session) -> tuple[datetime, datetime]:
    """Random-injection time window for the CURRENT event (requirement #4).

    Returns ``(start, end)`` where ``start`` is the simulated instant and ``end`` is
    the END OF THAT EVENT'S OWN CALENDAR DAY — but never crossing into the next
    milestone (whichever is sooner).  Only the TIME-OF-DAY is randomised inside this
    window; the DATE is never overridden (events stay event-driven).  A minimum
    5-minute window is guaranteed so an inject at end-of-day still distributes.
    """
    st   = _require_active(db)
    now  = _parse(st["sim_now"])
    t00h = _parse(st["cycle_t00h"])
    ms   = _compute_milestones(db, t00h)

    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    future = [getattr(ms, n) for n in EVENT_SPINE if getattr(ms, n) > now]
    next_evt = min(future) if future else None
    end = end_of_day
    if next_evt is not None and next_evt < end:
        end = next_evt
    if end <= now:                                  # already at the boundary
        end = now + timedelta(minutes=5)
    return now, end
