"""
Pool Creation Settings
======================
In-memory global toggle that controls whether the waitlist auto-scaling logic
(24 paid Waitlist members → new Active pool) fires automatically.

When AUTO_POOL_CREATION_ENABLED is False:
  - check_and_scale_waitlist() returns None immediately without creating a pool.
  - Admin must call POST /admin/pools/manual-create to form pools explicitly.
  - fill_pool_vacancies() is UNAFFECTED — it still fills slots in *existing* pools.

State persists for the lifetime of the worker process.  On Render free-tier
(single process) this is consistent within a session.  A restart resets to True.
"""

_auto_pool_creation: bool = True


def get_auto_pool_creation() -> bool:
    """Return current auto-pool-creation state."""
    return _auto_pool_creation


def set_auto_pool_creation(enabled: bool) -> None:
    """Toggle auto-pool-creation on or off."""
    global _auto_pool_creation
    _auto_pool_creation = enabled
