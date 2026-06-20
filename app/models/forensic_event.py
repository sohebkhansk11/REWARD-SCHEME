# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
ForensicEvent — System Forensic Debugger / event-level audit trail.
====================================================================

The DebugLog table (system_debugger.py) traces *function calls* — one row per
decorated tick/step with timing + a return-value summary.  ForensicEvent is
finer-grained: it records every **domain event** the engine emits as it runs —
"every breath of the system" — a member joining a pool, a member winning a draw,
a pool being created / merged / dissolved, an L4 being flagged, an SDE lever
firing, a level advance, an elimination, a refill, a posture decision, etc.

Each row carries:
  * WHEN  — created_at (wall clock), run_id, week_id, tick (Chronos phase), seq
  * WHAT  — category (coarse) + event_type (fine) + severity
  * WHO   — actor (system / scheduler / admin:<id> / user:<id>)
  * ON    — entity_type + entity_id + entity_ref (human label)
  * STATE — before_json / after_json (the change), payload_json (extra context)
  * MONEY — amount_inr (signed paise/rupee delta for money-moving events)
  * WHY   — message (human one-liner)

Design contract (financial-grade — identical philosophy to DebugLog):
  * APPEND-ONLY immutable audit rows — never updated, never deleted by the engine.
  * Written ONLY when the Forensic Debugger is toggled ON (forensic.py).  When OFF
    the recorder is a single-boolean pass-through → zero rows, zero overhead.
  * Writes are buffered in-memory and flushed in BULK per tick via an independent
    short-lived session, so the money path (draw / payout) is never coupled to a
    forensic write and a forensic failure can never roll back engine data.
  * Safe to leave in the production schema — main.py create_all() will create the
    table; if the debugger is never enabled it simply stays empty.

Removal before public launch:
  1. Drop this model + the forensic_events table.
  2. Delete app/services/forensic.py.
  3. Remove `forensic.*` calls from the engine services.
"""

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class ForensicEvent(Base):
    __tablename__ = "forensic_events"

    id = Column(BigInteger().with_variant(Integer, "sqlite"),
                primary_key=True, autoincrement=True)

    # ── WHEN ──────────────────────────────────────────────────────────────────
    # Simulation run that produced this event (hex job_id prefix).  NULL / "live"
    # for real production traffic outside a stress-test run.
    run_id   = Column(String(32), nullable=True,  index=True)
    # Monotonic per-run sequence number — guarantees a stable total order even
    # when many events share the same millisecond timestamp.
    seq      = Column(Integer,    nullable=True)
    # Simulated (or real) week number.
    week_id  = Column(Integer,    nullable=True,  index=True)
    # Chronos phase the event fired in — e.g. "TICK6/T-2H", "TICK7/T-0H", "LIVE".
    tick     = Column(String(24), nullable=True)

    # ── WHAT ──────────────────────────────────────────────────────────────────
    # Coarse bucket: MEMBERSHIP / POOL / DRAW / SDE / MERGER / PAYMENT / LEVEL /
    # ELIMINATION / GRACE / REFILL / POSTURE / SYSTEM.
    category   = Column(String(24), nullable=False, index=True)
    # Fine type: member_joined / member_won / pool_dissolved / l4_flagged /
    # sde_lever_fired / level_advanced / eliminated / posture_decided / ...
    event_type = Column(String(48), nullable=False, index=True)
    # info / notice / warning / critical.
    severity   = Column(String(12), nullable=False, default="info", index=True)

    # ── WHO ───────────────────────────────────────────────────────────────────
    actor = Column(String(48), nullable=True)   # system / scheduler / admin:<id> / user:<id>

    # ── ON (subject entity) ───────────────────────────────────────────────────
    entity_type = Column(String(16), nullable=True)            # user / pool / draw / token / session
    entity_id   = Column(Integer,    nullable=True, index=True)
    entity_ref  = Column(String(64), nullable=True)            # "@rsim_ab12" / "Pool AQ"

    # ── MONEY (signed; +inflow / -outflow), NULL for non-money events ──────────
    amount_inr = Column(Integer, nullable=True)

    # ── STATE / CONTEXT (JSON text, truncated by the writer) ──────────────────
    before_json  = Column(Text, nullable=True)
    after_json   = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True)

    # ── WHY ───────────────────────────────────────────────────────────────────
    message = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                        nullable=False, index=True)
