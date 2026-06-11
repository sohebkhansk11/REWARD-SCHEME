"""
SystemLock — advisory distributed mutex table
=============================================
Provides a simple DB-level mutex for critical sections that must not run
concurrently (condensation Phase 3, SDE execution, T-2H preparation).

Design:
  - Single row per named lock.  INSERT … ON CONFLICT DO NOTHING is atomic
    at the DB level — first writer wins, all others get a "conflict" signal.
  - Lock expiry: every lock has an expires_at.  Expired locks are treated as
    released even without explicit DELETE (prevents deadlock on process crash).
  - Holders must heartbeat (UPDATE expires_at) for long-running jobs or set
    an expiry long enough to cover the expected duration + safety margin.

Defined lock names (document here to avoid typos in callers):
  'draw_engine'      — held from T-2H start until T+0H:10 post-draw cleanup.
                       Blocks condensation Phase 3 and SDE initiation.
  'condensation'     — held during waitlist Phase 3.  Prevents concurrent
                       pool-dissolve operations from two scheduler threads.
  'sde_execution'    — held per SDE session execution.  One session at a time.
"""
from sqlalchemy import Column, DateTime, String
from sqlalchemy.sql import func
from app.database import Base


class SystemLock(Base):
    __tablename__ = "system_locks"

    # The name IS the primary key — there can only be one lock with a given name.
    lock_name   = Column(String(50), primary_key=True)

    # When the lock was last acquired or heartbeated
    acquired_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Hard expiry — jobs must set this generously (lock_duration + safety margin).
    # After this timestamp the lock is logically released even if the row persists.
    expires_at  = Column(DateTime(timezone=True), nullable=False)

    # Free-form identifier of the holder (process ID, job name, week_id, etc.)
    # Used for debugging; has no functional enforcement.
    held_by     = Column(String(100), nullable=True)
