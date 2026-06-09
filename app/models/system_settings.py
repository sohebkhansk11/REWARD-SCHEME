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
"""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class SystemSettings(Base):
    __tablename__ = "system_settings"

    key        = Column(String, primary_key=True, index=True)
    value_int  = Column(Integer,  nullable=True)   # used by numeric settings
    value_str  = Column(String,   nullable=True)   # reserved for string settings
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
