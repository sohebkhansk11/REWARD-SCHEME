import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler
from app.database import engine, Base
import app.models  # noqa: F401 — registers all ORM models with SQLAlchemy metadata
from app.routers import users, pools, tokens
from app.routers import admin
from app.routers import admin_data
from app.routers import admin_comms
from app.routers import dev as dev_router
from app.routers import auth as auth_router
from app.routers import user_auth as user_auth_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Reward Scheme API",
    description="Pools, Users, Tokens — with Dual-Draw and Waitlist Auto-Scaling",
    version="1.0.0",
)


# ── Global exception handler ──────────────────────────────────────────────────
# Without this, unhandled exceptions (e.g. SQLAlchemy DataError) propagate
# PAST the CORSMiddleware before any response headers are sent.  ServerError-
# Middleware then returns a 500 with no CORS headers, and the browser blocks
# the response with "No Access-Control-Allow-Origin" even though CORS is
# configured correctly.  Registering this handler inside FastAPI ensures the
# error response always travels back through the CORS layer.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error — {type(exc).__name__}: {exc}"},
    )

# CORS — reads from ALLOWED_ORIGINS env var (comma-separated list).
# Defaults to wildcard so the deployed frontends work immediately.
# After deployment, set ALLOWED_ORIGINS in Render to your exact Vercel URLs.
_raw = os.getenv("ALLOWED_ORIGINS", "*")
_origins: list[str] = [o.strip() for o in _raw.split(",")] if _raw != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # credentials requires explicit origins; disable when wildcard is active
    allow_credentials=(_raw != "*"),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_auth_router.router)  # /auth/*       — public user auth
app.include_router(auth_router.router)       # /admin/auth/* — public admin auth
app.include_router(pools.router)
app.include_router(users.router)
app.include_router(tokens.router)
app.include_router(admin.router)        # /admin/*              — core admin ops (JWT required)
app.include_router(admin_data.router)   # /admin/users|tokens|export|import  — data engine (JWT required)
app.include_router(admin_comms.router)  # /admin/broadcast      — communications (JWT required)
app.include_router(dev_router.router)   # /dev/*                — DEV MODE ONLY (JWT + ENABLE_DEV_MODE=true)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "Reward Scheme API is running"}
