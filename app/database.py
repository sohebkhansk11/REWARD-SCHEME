import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool, StaticPool, NullPool
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
#
# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
# SQLite-isolated diagnostic branch.  The PostgreSQL engine above uses a
# QueuePool plus the psycopg2-only ``connect_timeout`` connect-arg; both are
# REJECTED by the SQLite DBAPI and crash at connect time.  Multi-week
# validation runs (tools/run_isolated_sim.py) MUST point DATABASE_URL at a
# throwaway local SQLite shell and NEVER at the shared Supabase production DB.
# When — and only when — the URL scheme is sqlite, build a dialect-appropriate
# engine.  Two sub-cases, because transactional isolation matters:
#
#   ── in-memory (sqlite:///:memory:) → StaticPool ──────────────────────────────
#     A :memory: DB lives inside a single DBAPI connection; any second connection
#     is a SEPARATE empty database.  StaticPool keeps exactly one shared
#     connection so the schema and data survive across every Session.  The
#     trade-off is that all sessions share one connection — acceptable only for a
#     single-threaded serial caller.
#
#   ── file-backed (sqlite:///path.db) → NullPool ──────────────────────────────
#     A file DB can be opened by many independent connections.  NullPool hands
#     each Session its OWN fresh connection (opened on checkout, closed on
#     return), so the long-lived sim session and the forensic recorder's
#     short-lived flush session never share a transaction.  This reproduces the
#     production PostgreSQL isolation guarantee and removes any risk of a
#     mid-run forensic auto-flush committing the sim's in-flight transaction.
#     The multi-week validation driver (tools/run_isolated_sim.py) uses a file
#     for exactly this reason.
#
#   • check_same_thread=False    — the sim's services touch the connection from
#                                  helper threads; SQLite's default guard is too
#                                  strict for that and is safe to relax here.
#   • no connect_timeout / pool_pre_ping / recycle — all PostgreSQL-only knobs.
# The production PostgreSQL path (the ``else`` branch) is byte-for-byte the
# original configuration — nothing about the live deployment changes.
_IS_SQLITE      = DATABASE_URL.strip().lower().startswith("sqlite")
_IS_SQLITE_MEM  = _IS_SQLITE and ":memory:" in DATABASE_URL.lower()

if _IS_SQLITE:
    engine = create_engine(
        DATABASE_URL,
        poolclass=StaticPool if _IS_SQLITE_MEM else NullPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
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
# Only meaningful for the PostgreSQL QueuePool; the SQLite StaticPool has no
# size()/overflow capacity concept (single shared connection), so skip the hook
# entirely there — attaching it would raise AttributeError on every checkout.
if not _IS_SQLITE:
    @event.listens_for(engine, "checkout")
    def _on_checkout(dbapi_conn, conn_record, conn_proxy):
        pool = engine.pool
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Warn when 80% of total capacity is in use. checkedout() already counts
        # in-use overflow connections, so compare it directly against the static
        # capacity (pool_size + max_overflow), not the live overflow count.
        checked_out    = pool.checkedout()
        total_capacity = pool.size() + pool._max_overflow
        if checked_out >= int(total_capacity * 0.8):
            _log.warning(
                "[DB-POOL] High utilisation — checkedout=%d / capacity=%d",
                checked_out, total_capacity,
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

    SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
    The SQLite StaticPool used by isolated diagnostic runs does not expose the
    QueuePool sizing API (size()/overflow()/_max_overflow).  Production always
    runs PostgreSQL/QueuePool, so the live path is unchanged; we only degrade
    gracefully to a minimal shape if a non-QueuePool engine ever asks for status.
    """
    pool = engine.pool
    try:
        return {
            "pool_size":        pool.size(),
            "checked_out":      pool.checkedout(),
            "overflow":         pool.overflow(),
            "checked_in":       pool.checkedin(),
            "total_capacity":   pool.size() + pool._max_overflow,
        }
    except AttributeError:
        return {
            "pool_size":        None,
            "checked_out":      None,
            "overflow":         None,
            "checked_in":       None,
            "total_capacity":   None,
            "pool_class":       type(pool).__name__,
        }
