"""
SystemSettings ORM Model
========================
A simple key → typed-value table for runtime-configurable system parameters.

Current keys:
  pool_creation_threshold  (Integer)  — min paid waitlist members before a new pool
                                        auto-forms via check_and_scale_waitlist().
                                        Default: 24  (WAITLIST_TRIGGER in config.py).

The row is created lazily the first time get_pool_threshold() is called if it
does not already exist, so no manual seed migration is required.

# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# value_float column added for LPI thresholds, cascade risk ratio, and accel
# trigger ratio — values that require decimal precision (e.g. 14.0, 2.0, 0.60).
# Column is nullable=True — zero-downtime migration; existing rows unaffected.
# SQLite: ALTER TABLE adds nullable column with no default (no data loss).
# PostgreSQL: ALTER TABLE system_settings ADD COLUMN value_float NUMERIC(15,6).
"""

from sqlalchemy import Column, DateTime, Integer, Numeric, String
from sqlalchemy.sql import func

from app.database import Base


class SystemSettings(Base):
    __tablename__ = "system_settings"

    key          = Column(String,  primary_key=True, index=True)
    value_int    = Column(Integer,  nullable=True)
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    value_float  = Column(Numeric(precision=15, scale=6), nullable=True)
    value_str    = Column(String,   nullable=True)
    updated_at   = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
