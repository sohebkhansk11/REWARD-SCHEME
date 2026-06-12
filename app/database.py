import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool
import logging

# Resolve .env relative to this file so uvicorn's reloader subprocess finds it
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

_log = logging.getLogger(__name__)

# ── Connection Pool Configuration ────────────────────────────────────────────
# Sized to handle large user injections (2000–100,000 users) without exhaustion.
#
#   pool_size=20       — persistent connections kept open at all times.
#                        Default SQLAlchemy is 5 — WAY too low for concurrent
#                        API calls + background pool-formation loops.
#   max_overflow=20    — burst headroom above pool_size for spike traffic.
#                        Total max concurrent connections = pool_size + max_overflow = 40.
#   pool_pre_ping=True — each connection is tested with SELECT 1 before use.
#                        Prevents "server closed the connection unexpectedly"
#                        errors on idle connections recycled after 30 min.
#   pool_recycle=1800  — connections older than 30 min are silently replaced.
#                        Guards against PostgreSQL's idle-in-transaction timeout
#                        and cloud provider session kill-offs (Render, Supabase).
#   pool_timeout=30    — raise TimeoutError after 30 s of waiting for a free
#                        connection rather than hanging indefinitely.
#   connect_args       — 10 s TCP connection timeout so a hung DB host fails
#                        fast instead of blocking the worker thread forever.
#
# IMPORTANT: pool_pre_ping adds one round-trip per checkout but is mandatory
# for long-running servers on cloud DBs that drop idle connections.
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
    connect_args={"connect_timeout": 10},
    echo=False,   # set True temporarily for SQL query debugging; NEVER in prod
)

# ── Connection-level event hooks ──────────────────────────────────────────────
# Log pool exhaustion warnings so ops teams can detect saturation early.
@event.listens_for(engine, "checkout")
def _on_checkout(dbapi_conn, conn_record, conn_proxy):
    pool = engine.pool
    checked_out = pool.checkedout()
    pool_sz     = pool.size()
    overflow    = pool.overflow()
    # Warn when 80% of total capacity is in use
    if (checked_out + overflow) >= int((pool_sz + pool.overflow()) * 0.8):
        _log.warning(
            "[DB-POOL] High utilisation — checkedout=%d  pool_size=%d  overflow=%d",
            checked_out, pool_sz, overflow,
        )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """
    FastAPI dependency — yields a database session per request.

    The session is always closed in the finally block regardless of exceptions.
    Connection is returned to the pool (not destroyed) when db.close() is called;
    pool_pre_ping ensures the next checkout gets a live connection.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_pool_status() -> dict:
    """
    Return a real-time snapshot of the connection pool state.
    Used by GET /admin/health and GET /admin/pipeline-health.
    """
    pool = engine.pool
    return {
        "pool_size":        pool.size(),
        "checked_out":      pool.checkedout(),
        "overflow":         pool.overflow(),
        "checked_in":       pool.checkedin(),
        "total_capacity":   pool.size() + pool._max_overflow,
    }
