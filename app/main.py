import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
import app.models  # noqa: F401 — registers all ORM models with SQLAlchemy metadata
from app.routers import users, pools, tokens
from app.routers import admin

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Reward Scheme API",
    description="Pools, Users, Tokens — with Dual-Draw and Waitlist Auto-Scaling",
    version="1.0.0",
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

app.include_router(pools.router)
app.include_router(users.router)
app.include_router(tokens.router)
app.include_router(admin.router)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "Reward Scheme API is running"}
