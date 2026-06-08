"""
Developer Mode Guard
====================
Reads the ENABLE_DEV_MODE environment variable.

- "true" / "1" / "yes"  → allowed
- anything else (or unset) → HTTP 403 Forbidden

Usage:
    router = APIRouter(dependencies=[Depends(require_dev_mode), Depends(require_admin_jwt)])

Or per-route:
    @router.post("/dev/something")
    def my_route(_: None = Depends(require_dev_mode)):
        ...

The admin JWT check is always applied separately; dev mode is an *additional*
gate on top of authentication — not a replacement for it.
"""

import os
from fastapi import Depends, HTTPException, status
from app.core.security import require_admin_jwt


def require_dev_mode(_: str = Depends(require_admin_jwt)) -> None:
    """
    Allow access only when ENABLE_DEV_MODE=true in the environment.
    Also requires a valid Admin JWT (via the injected dependency above).
    Returns 403 in all other cases.
    """
    raw = os.getenv("ENABLE_DEV_MODE", "false").strip().lower()
    if raw not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Developer mode is disabled on this server. "
                "Set ENABLE_DEV_MODE=true in environment variables to enable."
            ),
        )
