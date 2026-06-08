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

from app.services.auth import decode_jwt, decode_user_jwt

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
