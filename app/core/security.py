"""
FastAPI security dependency
===========================
Import `require_admin_jwt` and add it to any route or router that must be
protected:

    router = APIRouter(dependencies=[Depends(require_admin_jwt)])

or per-route:

    @router.get("/something")
    def my_route(admin: str = Depends(require_admin_jwt)):
        ...
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

from app.services.auth import decode_jwt, decode_user_jwt, verify_password

# HTTPBearer extracts the token from the Authorization: Bearer <token> header.
# auto_error=True means FastAPI returns 403 automatically if the header is absent.
_bearer_scheme      = HTTPBearer(auto_error=True)
_user_bearer_scheme = HTTPBearer(auto_error=True)


def require_user_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(_user_bearer_scheme),
) -> int:
    """
    Validate the Bearer JWT in the Authorization header for regular users.
    Returns the user_id (int) on success. Raises HTTP 401 on failure.
    """
    try:
        return decode_user_jwt(credentials.credentials)
    except (JWTError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User authentication failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_admin_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """
    Validate the Bearer JWT in the Authorization header.
    Returns the admin_username on success.
    Raises HTTP 401 on any failure.
    """
    try:
        admin_username = decode_jwt(credentials.credentials)
        return admin_username
    except (JWTError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Admin authentication failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_admin_password(db: Session, admin_username: str, password: str) -> bool:
    """
    Verify that `password` matches the stored bcrypt hash for `admin_username`.

    Returns True on success.  Returns False (never raises) on mismatch so
    callers can raise their own context-appropriate HTTP 403.

    Always runs a bcrypt check (even with a dummy hash if the admin row is not
    found) to prevent timing-based username enumeration attacks.
    """
    from app.models.admin import Admin  # local import avoids circular dependency

    _DUMMY_HASH = "$2b$12$invalidhashplaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXX"

    admin: Admin | None = (
        db.query(Admin).filter(Admin.username == admin_username).first()
    )
    stored = (admin.hashed_password or _DUMMY_HASH) if admin else _DUMMY_HASH
    return verify_password(password, stored)
