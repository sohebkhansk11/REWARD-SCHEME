# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
DebugLog — System Debugger audit trail table.

Rows are written ONLY when the Global System Debugger is toggled ON via
POST /dev/debugger/toggle.  When the debugger is OFF this table receives
zero writes.  The table is safe to leave in production schema — it will
simply remain empty.

To fully remove debugger instrumentation before public launch:
  1. Drop this model and the debug_logs table.
  2. Delete app/services/system_debugger.py.
  3. Remove @debug_trace decorators from real_simulation.py.
"""

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class DebugLog(Base):
    __tablename__ = "debug_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)

    # Which simulation run produced this log entry (job_id hex prefix)
    run_id      = Column(String(32), nullable=False, index=True)

    # Simulated week number within the run (null for manual / run-level entries)
    week_num    = Column(Integer,    nullable=True)

    # Structured phase tag — format "TICK-N/step_name", e.g. "TICK-7/draw"
    phase       = Column(String(64), nullable=False, index=True)

    # Human-readable event label — function name or milestone description
    event       = Column(String(256), nullable=False)

    # JSON-serialised summary of the decorated function's return value
    # (list/bytes fields excluded; truncated to ~4 KB in the writer)
    data_json   = Column(Text, nullable=True)

    # Wall-clock execution time of the instrumented call in milliseconds
    duration_ms = Column(Float, nullable=True)

    # LPI snapshot at the moment this entry was written (null if not available)
    lpi         = Column(Float, nullable=True)

    # Exception string if the instrumented call raised — null on success
    error       = Column(Text, nullable=True)

    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
