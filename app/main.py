import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler
from starlette.middleware.base import BaseHTTPMiddleware

_logger = logging.getLogger(__name__)

# 5 MB hard ceiling on request bodies — protects against DoS via large payloads
# while still allowing realistic CSV imports (typical 10k-user CSV ≈ 800 KB).
_MAX_BODY_BYTES = 5 * 1024 * 1024

class _BodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > _MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds the 5 MB limit."},
            )
        return await call_next(request)
from app.database import engine, Base
import app.models  # noqa: F401 — registers all ORM models with SQLAlchemy metadata
from app.routers import users, pools, tokens
from app.routers import admin
from app.routers import admin_data
from app.routers import admin_comms
from app.routers import admin_analytics
from app.routers.admin_analytics import _public_router as draw_schedule_router
from app.routers import admin_user_mgmt
from app.routers import referrals as referrals_router
from app.routers import dev as dev_router
from app.routers import auth as auth_router
from app.routers import user_auth as user_auth_router
from app.routers import admin_elimination as admin_elimination_router
# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Draw & Financial Strategy config router — backs the new admin sub-tab.
from app.routers import admin_financial_config as admin_financial_config_router
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Master Pool Re-assessment Manager router — backs the Pool Re-assessment review
# panel (verdict view + password-gated HOLD approval).
from app.routers import admin_reassessment as admin_reassessment_router

Base.metadata.create_all(bind=engine)

# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Bug #9 — Safe production migration for the two-phase SDE commit column.
# create_all() only creates MISSING tables, never adds new columns to existing
# ones.  This block adds the `executed` column to sde_checkpoints if absent.
# IF NOT EXISTS is a PostgreSQL 9.6+ feature — safe for Render/Supabase.
# The DEFAULT FALSE ensures all historical rows are treated as already-executed
# (they ran under the old single-phase system and do not need T-0H re-execution).
try:
    from sqlalchemy import text as _sa_text
    with engine.begin() as _mig_conn:
        _mig_conn.execute(_sa_text(
            "ALTER TABLE sde_checkpoints "
            "ADD COLUMN IF NOT EXISTS executed BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Mark ALL pre-existing rows as executed=TRUE so execute_staged_sde_draws()
        # does not attempt to re-process draws that already completed under the old
        # single-phase system.
        _mig_conn.execute(_sa_text(
            "UPDATE sde_checkpoints SET executed = TRUE "
            "WHERE executed = FALSE AND completed_at < NOW() - INTERVAL '1 hour'"
        ))
        # SESSION EDIT [Claude Session Jun-14 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Case C audit columns on sde_checkpoints + Case E True Defer column on users.
        # All IF NOT EXISTS — safe to re-run on restarts; idempotent.
        _mig_conn.execute(_sa_text(
            "ALTER TABLE sde_checkpoints "
            "ADD COLUMN IF NOT EXISTS case_c_transfer BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        _mig_conn.execute(_sa_text(
            "ALTER TABLE sde_checkpoints "
            "ADD COLUMN IF NOT EXISTS case_c_donor_pool_id INTEGER"
        ))
        _mig_conn.execute(_sa_text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS case_e_deferred_week VARCHAR(10)"
        ))
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # value_float column — NUMERIC(15,6) for LPI thresholds / cascade ratios.
        _mig_conn.execute(_sa_text(
            "ALTER TABLE system_settings "
            "ADD COLUMN IF NOT EXISTS value_float NUMERIC(15,6)"
        ))
    _logger.info("main: sde_checkpoints.executed + Case C audit + Case E defer column + system_settings.value_float migrations OK.")
except Exception as _mig_exc:
    _logger.warning(
        "main: sde_checkpoints.executed migration skipped (may already exist or "
        "non-PostgreSQL dialect): %s", _mig_exc,
    )

# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ── CRITICAL SCHEMA REPAIR: misspelled PostgreSQL enum type ────────────────────
# The production DB's enum type for users.weekly_payment_status was created long
# ago (when the Python enum class was once misspelled) as "weeklypaymentsatus"
# — note the MISSING second 't'. The model now correctly generates the name
# "weeklypaymentstatus". Single-row INSERTs coerce string→column-type and so they
# worked, but the simulator's bulk insertmanyvalues emits an explicit
# ::weeklypaymentstatus cast which PostgreSQL rejects against a weeklypaymentsatus
# column (psycopg2 DatatypeMismatch, sqlalche.me/e/20/f405). NOTE: a TRUNCATE /
# "nuke" does NOT fix this — it is a TYPE DEFINITION, not table data.
#
# This was first repaired in production via the one-shot GET /admin/repair-weekly-enum
# endpoint on Jun-16 (which confirmed: only users.weekly_payment_status used the
# misspelled type, the correctly-named type was a pure orphan, and the fix is the
# instant DROP-orphan + RENAME). This block makes the fix PERMANENT + self-healing
# so a fresh or regressed DB realigns automatically on deploy. Fully idempotent and
# finance-safe; statement_timeout/lock_timeout are disabled for THIS transaction so
# the ORIGINAL failure mode — the global statement timeout cancelling the table
# rewrite mid-flight, which silently defeated the very first attempt — cannot recur:
#   • only-misspelled-exists            → ALTER TYPE ... RENAME             (instant, catalog only)
#   • both-exist, correct is an orphan  → DROP correct orphan, then RENAME  (instant, no rewrite)
#   • both-exist, correct used elsewhere→ repoint users col (rewrite), then DROP misspelled
#   • only-correct / neither            → no-op
# Wrapped so any failure is logged and can never block API startup.
try:
    from sqlalchemy import text as _enum_text
    with engine.begin() as _enum_conn:
        _enum_conn.execute(_enum_text("SET LOCAL statement_timeout = 0"))
        _enum_conn.execute(_enum_text("SET LOCAL lock_timeout = 0"))
        _enum_conn.execute(_enum_text(
            "DO $$\n"
            "DECLARE\n"
            "    correct_in_use int;\n"
            "BEGIN\n"
            "    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'weeklypaymentsatus') THEN\n"
            "        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'weeklypaymentstatus') THEN\n"
            "            SELECT count(*) INTO correct_in_use\n"
            "              FROM pg_type t\n"
            "              JOIN pg_attribute a ON a.atttypid = t.oid\n"
            "              JOIN pg_class c ON a.attrelid = c.oid\n"
            "              WHERE t.typname = 'weeklypaymentstatus'\n"
            "                AND a.attnum > 0 AND NOT a.attisdropped\n"
            "                AND c.relkind IN ('r','p');\n"
            "            IF correct_in_use > 0 THEN\n"
            "                ALTER TABLE users\n"
            "                    ALTER COLUMN weekly_payment_status TYPE weeklypaymentstatus\n"
            "                    USING weekly_payment_status::text::weeklypaymentstatus;\n"
            "                DROP TYPE IF EXISTS weeklypaymentsatus;\n"
            "            ELSE\n"
            "                DROP TYPE weeklypaymentstatus;\n"
            "                ALTER TYPE weeklypaymentsatus RENAME TO weeklypaymentstatus;\n"
            "            END IF;\n"
            "        ELSE\n"
            "            ALTER TYPE weeklypaymentsatus RENAME TO weeklypaymentstatus;\n"
            "        END IF;\n"
            "    END IF;\n"
            "END $$;"
        ))
    _logger.info(
        "main: weekly_payment_status enum-type repair OK "
        "(DB type aligned to 'weeklypaymentstatus')."
    )
except Exception as _enum_exc:
    _logger.warning(
        "main: weekly_payment_status enum-type repair skipped/failed "
        "(may already be correct or non-PostgreSQL dialect): %s", _enum_exc,
    )

_IS_DEV_MODE        = os.getenv("ENABLE_DEV_MODE")   == "true"
_SCHEDULER_ENABLED  = os.getenv("SCHEDULER_ENABLED", "false").lower() == "true"


# ── FastAPI lifespan — scheduler start / stop ─────────────────────────────────
# The scheduler fires the Sunday draw lifecycle automatically:
#   T-2H  → start_draw_preparation()   (LPI snapshot, SDE pre-processing)
#   T+0   → execute_weekly_draw()      (global mass draw)
#   T+5m  → post_draw_cleanup()        (reset flags, release lock)
#   every 5min → admin override watchdog (BUG 4 auto-select)
#
# Set SCHEDULER_ENABLED=true in your Render / production env vars to activate.
# Leave unset (or false) for local dev — trigger jobs manually via admin API.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    if _SCHEDULER_ENABLED:
        try:
            from app.services.scheduler import start_scheduler
            start_scheduler()
            _logger.info(
                "APScheduler ACTIVE — Sunday draw lifecycle is running autonomously."
            )
        except Exception as exc:
            # Scheduler failure must never prevent the API from starting.
            _logger.error(
                "APScheduler failed to start — API will run WITHOUT scheduler. "
                "Error: %s: %s",
                type(exc).__name__, exc,
                exc_info=True,
            )
    else:
        _logger.info(
            "APScheduler DISABLED (SCHEDULER_ENABLED != 'true'). "
            "Trigger draw jobs manually via POST /admin/draw/prepare and "
            "POST /admin/draw/execute."
        )

    yield   # app is running

    # ── Shutdown ──────────────────────────────────────────────────────────────
    if _SCHEDULER_ENABLED:
        try:
            from app.services.scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass   # already logged inside stop_scheduler


app = FastAPI(
    title="Reward Scheme API",
    description="Pools, Users, Tokens — with Dual-Draw and Waitlist Auto-Scaling",
    version="1.0.0",
    docs_url="/docs" if _IS_DEV_MODE else None,
    redoc_url="/redoc" if _IS_DEV_MODE else None,
    lifespan=lifespan,
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

if _raw == "*":
    _logger.warning(
        "CORS is using wildcard origin (*). Set ALLOWED_ORIGINS in your Render "
        "environment variables to restrict access in production."
    )

app.add_middleware(_BodySizeMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # credentials requires explicit origins; disable when wildcard is active
    allow_credentials=(_raw != "*"),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_auth_router.router)          # /auth/*           — public user auth
app.include_router(user_auth_router.users_me_router) # /users/me/*       — authenticated user profile
app.include_router(auth_router.router)       # /admin/auth/* — public admin auth
app.include_router(pools.router)
app.include_router(users.router)
app.include_router(tokens.router)
app.include_router(admin.router)        # /admin/*              — core admin ops (JWT required)
app.include_router(admin_data.router)   # /admin/users|tokens|export|import  — data engine (JWT required)
app.include_router(admin_comms.router)      # /admin/broadcast         — communications (JWT required)
app.include_router(admin_analytics.router)    # /admin/stats/* + /admin/draw/* — analytics & ERP (JWT required)
app.include_router(draw_schedule_router)      # /draw/countdown               — public draw timer
app.include_router(admin_user_mgmt.router)    # /admin/users|tokens (destroy) — deep management (JWT required)
app.include_router(referrals_router.router)   # /users/request-referral-payout + /admin/referrals/* (JWT required)
app.include_router(dev_router.router)         # /dev/*                        — DEV MODE ONLY (JWT + ENABLE_DEV_MODE=true)
app.include_router(admin_elimination_router.router)  # /admin/elimination/*  — Payment Compliance engine (JWT required)
# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
app.include_router(admin_financial_config_router.router)  # /admin/financial-config/* — Draw & Financial Strategy (JWT required)
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
app.include_router(admin_reassessment_router.router)  # /admin/reassessment/* — Pool Re-assessment gate (JWT required)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "Reward Scheme API is running"}


@app.get("/time", tags=["Health"])
def server_time():
    """
    Return the current UTC epoch (milliseconds since 1970-01-01T00:00:00Z).
    Used by the user-app CountdownTimer to sync against server time and
    eliminate client-clock drift from the Sunday 7 PM IST draw countdown.
    """
    from datetime import datetime, timezone
    return {"epoch_ms": int(datetime.now(timezone.utc).timestamp() * 1000)}


@app.get("/health", tags=["Health"])
def health_check():
    """Render health-check probe. Returns 200 when the process is alive."""
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Include the deployed git commit so a single GET /health confirms WHICH
    # build is live. Kept trivial (no imports beyond os) so it can never
    # destabilise Render's health probe.
    import os
    return {
        "status": "healthy",
        "commit": os.environ.get("RENDER_GIT_COMMIT", "local"),
    }


# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
@app.get("/version", tags=["Health"])
def version_info():
    """
    Deploy-verification endpoint.

    Returns the exact git commit Render deployed (RENDER_GIT_COMMIT) PLUS a
    live check that the RealSimEngine module can be imported in THIS running
    process. This exists because a pre-existing IndentationError once made
    real_simulation.py un-importable in production, silently breaking EVERY
    simulation for ~10 sessions with no visible error. With this endpoint the
    question "is my fix actually deployed and is the engine loadable?" is
    answerable in one HTTP GET. Always returns 200 (import wrapped in
    try/except) so it can never destabilise health probing.
    """
    import os
    info: dict = {
        "commit":            os.environ.get("RENDER_GIT_COMMIT", "local"),
        "engine_importable": False,
        "engine_error":      None,
    }
    try:
        from app.services.real_simulation import RealSimEngine  # noqa: F401
        info["engine_importable"] = True
    except Exception as exc:  # defensive: report, never raise
        info["engine_error"] = f"{type(exc).__name__}: {exc}"

    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Live schema probe for the weekly_payment_status enum-type repair. Reports
    # the ACTUAL PostgreSQL type backing users.weekly_payment_status plus which
    # of the (mis)spelled type names still exist, so the startup repair can be
    # verified in one GET. Must read "weeklypaymentstatus", and the misspelled
    # "weeklypaymentsatus" must be gone once the fix has deployed. Fully guarded.
    info["weekly_payment_status_db_type"] = None
    info["enum_types_present"] = None
    try:
        from app.database import engine as _ver_engine
        from sqlalchemy import text as _ver_text
        with _ver_engine.connect() as _ver_conn:
            info["weekly_payment_status_db_type"] = _ver_conn.execute(_ver_text(
                "SELECT t.typname "
                "FROM pg_attribute a "
                "JOIN pg_class c ON a.attrelid = c.oid "
                "JOIN pg_type  t ON a.atttypid = t.oid "
                "WHERE c.relname = 'users' AND a.attname = 'weekly_payment_status'"
            )).scalar()
            info["enum_types_present"] = [
                r[0] for r in _ver_conn.execute(_ver_text(
                    "SELECT typname FROM pg_type "
                    "WHERE typname IN ('weeklypaymentstatus', 'weeklypaymentsatus') "
                    "ORDER BY typname"
                )).fetchall()
            ]
    except Exception as exc:  # defensive: report, never raise
        info["schema_check_error"] = f"{type(exc).__name__}: {exc}"
    return info
