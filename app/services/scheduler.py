"""
Draw Lifecycle Scheduler
========================
APScheduler-backed job runner for the weekly Sunday draw lifecycle.

Four jobs:

  1. job_preparation()       — T-2H (default Sunday 11:30 UTC = 5:00 PM IST)
       Calls start_draw_preparation(): LPI snapshot, Brain-5 routing,
       SDE pre-processing, admin override gate.

  2. job_override_watchdog() — every 5 minutes (all days)
       BUG 4 enforcement: calls auto_select_on_timeout() for any
       WeeklyDrawState row where the admin override deadline has passed
       but no choice was submitted.  Runs continuously so the auto-select
       fires even if the scheduler restarted after T-2H.

  3. job_weekly_draw()       — T+0 (default Sunday 13:30 UTC = 7:00 PM IST)
       a. One final auto_select_on_timeout() belt-and-suspenders call.
       b. execute_weekly_draw() — draws all eligible full pools.
       c. Marks WeeklyDrawState.draw_executed = True + draw_executed_at.

  4. job_post_cleanup()      — T+5 min (default Sunday 13:35 UTC = 7:05 PM IST)
       post_draw_cleanup(): resets weekly draw flags, releases draw lock.

Configuration (environment variables — all have safe defaults):

  DRAW_HOUR_UTC      default "13"    — UTC hour of the draw
  DRAW_MINUTE_UTC    default "30"    — UTC minute of the draw
  SCHEDULER_ENABLED  default "false" — set to "true" to activate

Design invariants:
  • Each job creates its own DB session via _get_db() and closes it in
    finally — no session is ever shared across jobs.
  • Job failures are caught, logged with full traceback, and do NOT
    propagate — the scheduler stays alive through transient errors.
  • All underlying service functions are idempotent — safe to re-run.
  • max_instances=1 on every job prevents overlap if a run takes too long.
  • misfire_grace_time allows delayed execution up to N seconds after the
    scheduled trigger — handles cold starts and brief server downtime.
  • AsyncIOScheduler shares the FastAPI event loop: no extra threads.
"""

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

_logger = logging.getLogger(__name__)

# ── Draw time configuration ───────────────────────────────────────────────────
# Sunday 7:00 PM IST  =  Sunday 13:30 UTC.
# Override with DRAW_HOUR_UTC / DRAW_MINUTE_UTC env vars.
_DRAW_HOUR_UTC   = int(os.getenv("DRAW_HOUR_UTC",   "13"))
_DRAW_MINUTE_UTC = int(os.getenv("DRAW_MINUTE_UTC", "30"))

# Derived times (all in minutes-from-midnight UTC)
_DRAW_TOTAL_MIN    = _DRAW_HOUR_UTC * 60 + _DRAW_MINUTE_UTC         # 810
_PREP_TOTAL_MIN    = _DRAW_TOTAL_MIN - 120                           # 690  (T-2H)
_CLEANUP_TOTAL_MIN = _DRAW_TOTAL_MIN + 5                             # 815  (T+5 min)

_PREP_HOUR_UTC      = _PREP_TOTAL_MIN // 60                          # 11
_PREP_MINUTE_UTC    = _PREP_TOTAL_MIN % 60                           # 30
_CLEANUP_HOUR_UTC   = _CLEANUP_TOTAL_MIN // 60                       # 13
_CLEANUP_MINUTE_UTC = _CLEANUP_TOTAL_MIN % 60                        # 35

# Day-of-week for prep job — handles edge case where draw < 02:00 UTC
# (prep would fall on the previous Saturday).
# For all IST-based draw times (earliest realistically 06:30 UTC = 12 PM IST)
# this is always Sunday.  The guard is here for correctness only.
_PREP_DOW    = "sun" if _PREP_TOTAL_MIN >= 0 else "sat"
_CLEANUP_DOW = "sun" if _CLEANUP_TOTAL_MIN < 24 * 60 else "mon"

# Singleton scheduler instance — started/stopped via start_scheduler() /
# stop_scheduler() from the FastAPI lifespan.
_scheduler: AsyncIOScheduler | None = None


# ── DB session context manager ────────────────────────────────────────────────

@contextmanager
def _get_db() -> Generator:
    """
    Yield a SQLAlchemy session scoped to the calling job.
    Always closes the session in finally — never leaks a connection.
    """
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Job 1 — T-2H Draw Preparation
# ═══════════════════════════════════════════════════════════════════════════════

def job_preparation() -> None:
    """
    T-2H preparation job.  Fires at _PREP_HOUR_UTC:_PREP_MINUTE_UTC every Sunday.

    Computes draw_time_utc as (now + 2 hours) rounded to the nearest minute.
    This is deliberately NOT derived from the cron config so that the clock
    drift between the scheduler trigger time and wall-clock is automatically
    absorbed — the draw_time_utc will always be within ±1 minute of reality.
    """
    draw_time_utc = (
        datetime.now(timezone.utc) + timedelta(hours=2)
    ).replace(second=0, microsecond=0)

    _logger.info(
        "Scheduler ▶ job_preparation  draw_time_utc=%s",
        draw_time_utc.isoformat(),
    )

    try:
        with _get_db() as db:
            from app.services.draw_preparation import start_draw_preparation
            state = start_draw_preparation(db, draw_time_utc)

        _logger.info(
            "Scheduler ✓ job_preparation COMPLETE  "
            "week=%s  prep_valid=%s  override_required=%s  "
            "sde_sessions_planned=%d  lpi=%.2f%%",
            state.week_id,
            state.preparation_valid,
            state.admin_override_required,
            state.sde_sessions_planned or 0,
            float(state.lpi_snapshot or 0),
        )

    except RuntimeError as exc:
        # Lock already held — another instance or retry beat us.  Not fatal.
        _logger.warning(
            "Scheduler ⚠ job_preparation SKIPPED (lock contention): %s", exc,
        )
    except Exception as exc:
        _logger.error(
            "Scheduler ✗ job_preparation FAILED  %s: %s",
            type(exc).__name__, exc,
            exc_info=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Job 2 — Admin Override Auto-Select Watchdog (every 5 min)
# ═══════════════════════════════════════════════════════════════════════════════

def job_override_watchdog() -> None:
    """
    BUG 4 FIX enforcement.  Runs every 5 minutes on all days.

    Scans WeeklyDrawState for rows where:
      - admin_override_required = True
      - admin_override_choice   IS NULL   (admin has not yet decided)
      - admin_override_deadline < NOW      (deadline has passed)

    For each such row, calls auto_select_on_timeout() which computes the
    lower-cost option and applies it automatically.

    This is the primary enforcement mechanism — the final call in
    job_weekly_draw() is belt-and-suspenders only.
    """
    try:
        with _get_db() as db:
            from app.models.weekly_draw_state import WeeklyDrawState
            from app.services.admin_override  import auto_select_on_timeout

            now = datetime.now(timezone.utc)

            pending = (
                db.query(WeeklyDrawState)
                .filter(
                    WeeklyDrawState.admin_override_required == True,    # noqa: E712
                    WeeklyDrawState.admin_override_choice   == None,    # noqa: E711
                    WeeklyDrawState.admin_override_deadline <  now,
                )
                .all()
            )

            for state in pending:
                chosen = auto_select_on_timeout(db, state.week_id)
                if chosen:
                    _logger.warning(
                        "Scheduler ⚠ override_watchdog auto-selected '%s' for week %s  "
                        "(deadline was %s).",
                        chosen,
                        state.week_id,
                        state.admin_override_deadline.isoformat()
                        if state.admin_override_deadline else "unknown",
                    )

    except Exception as exc:
        _logger.error(
            "Scheduler ✗ job_override_watchdog FAILED  %s: %s",
            type(exc).__name__, exc,
            exc_info=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Job 3 — Weekly Draw
# ═══════════════════════════════════════════════════════════════════════════════

def job_weekly_draw() -> None:
    """
    Sunday draw execution.  Fires at _DRAW_HOUR_UTC:_DRAW_MINUTE_UTC every Sunday.

    Sequence:
      (a) Belt-and-suspenders auto_select_on_timeout() — catches the case
          where the watchdog missed the override deadline in the last 5-min
          window before the draw.
      (b) execute_weekly_draw() — draws all eligible full pools.
      (c) Mark WeeklyDrawState.draw_executed=True + draw_executed_at=now.
    """
    _logger.info("Scheduler ▶ job_weekly_draw")

    try:
        with _get_db() as db:
            from app.services.draw             import execute_weekly_draw
            from app.services.admin_override   import auto_select_on_timeout
            from app.models.weekly_draw_state  import WeeklyDrawState

            now     = datetime.now(timezone.utc)
            iso     = now.isocalendar()
            week_id = f"{iso.year}-W{iso.week:02d}"

            # ── (a) Last-chance override resolution ───────────────────────────
            late_choice = auto_select_on_timeout(db, week_id)
            if late_choice:
                _logger.warning(
                    "Scheduler ⚠ job_weekly_draw: late override auto-selected '%s' "
                    "for week %s (fired at draw time).",
                    late_choice, week_id,
                )

            # ── (b) Execute the global mass draw ─────────────────────────────
            result = execute_weekly_draw(db)

            _logger.info(
                "Scheduler ✓ job_weekly_draw DRAW COMPLETE  "
                "pools_drawn=%d  sde_pre_drawn=%d  "
                "skipped=%d  paused=%d  "
                "P1_assigned=%d  P2_pool=%s",
                result.pools_drawn,
                len(result.sde_pre_drawn),
                len(result.skipped_pools),
                len(result.paused_pools),
                result.refill.get("phase1_assigned", 0),
                result.refill.get("phase2_pool_created") or "none",
            )

            # ── (c) Mark draw_executed in WeeklyDrawState ─────────────────────
            state: WeeklyDrawState | None = (
                db.query(WeeklyDrawState)
                .filter(WeeklyDrawState.week_id == week_id)
                .first()
            )
            if state:
                state.draw_executed    = True
                state.draw_executed_at = now
                state.countdown_active = False   # draw has fired — stop the timer
                db.commit()
                _logger.info(
                    "Scheduler ✓ WeeklyDrawState.draw_executed=True  "
                    "countdown_active=False  week=%s",
                    week_id,
                )
            else:
                # Preparation did not run for this week (manual draw or cold start)
                _logger.warning(
                    "Scheduler ⚠ WeeklyDrawState not found for week %s — "
                    "preparation may not have run.  draw_executed NOT marked.",
                    week_id,
                )

    except ValueError as exc:
        # No eligible full pools found — not fatal; can happen early in the week
        # before pools are filled, or in dev environments with no data.
        _logger.warning(
            "Scheduler ⚠ job_weekly_draw: no eligible pools — %s", exc,
        )
    except Exception as exc:
        _logger.error(
            "Scheduler ✗ job_weekly_draw FAILED  %s: %s",
            type(exc).__name__, exc,
            exc_info=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Job 4 — Post-Draw Cleanup (T+5 min)
# ═══════════════════════════════════════════════════════════════════════════════

def job_post_cleanup() -> None:
    """
    Post-draw cleanup.  Fires 5 minutes after the draw.

    Calls post_draw_cleanup() which:
      1. Resets draw_completed_this_week=False on all non-dissolved pools.
      2. Resets pool_draw_type=None on all non-dissolved pools.
      3. Clears contains_flagged_l4 on pools whose L4 members all exited.
      4. Orphan-clears sde_required on any Eliminated_Won members.
      5. Releases the draw_engine system lock.
    """
    _logger.info("Scheduler ▶ job_post_cleanup")
    try:
        with _get_db() as db:
            from app.services.draw import post_draw_cleanup
            summary = post_draw_cleanup(db)

        _logger.info(
            "Scheduler ✓ job_post_cleanup COMPLETE  "
            "pools_reset=%s  l4_pools_cleared=%s  orphan_sde_cleared=%s  lock_released=True",
            summary.get("pools_reset"),
            summary.get("l4_pools_cleared"),
            summary.get("orphan_sde_cleared"),
        )

    except Exception as exc:
        _logger.error(
            "Scheduler ✗ job_post_cleanup FAILED  %s: %s",
            type(exc).__name__, exc,
            exc_info=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Job 5 — Data Integrity Auto-Repair (every 6 hours)
# ═══════════════════════════════════════════════════════════════════════════════

def job_data_integrity_check() -> None:
    """
    Runs every 6 hours — detects and repairs data inconsistencies that can
    accumulate over time from partial transactions, timeouts, or race conditions.

    Repairs performed (all idempotent — safe to run multiple times):

      1. Pool member count sync
         Sets pool.total_members = COUNT(active users in that pool)
         for every pool whose stored total_members differs from the real count.
         Root cause: concurrent draws or large injections can leave totals stale.

      2. Orphaned SDE flags
         Clears sde_required=True on users whose status is NOT Active.
         (Eliminated or Waitlist users should never have sde_required=True.)

      3. Expired grace periods
         Clears grace_active=True on users whose grace_expires_at is in the past
         AND grace_fee_paid=False.  These users should already be elimination_risk=True.

      4. Pool contains_flagged_l4 consistency
         Sets contains_flagged_l4 = True/False on each pool based on whether
         any active member in that pool has sde_required=True.

    All corrections are logged with counts so admins can monitor for patterns.
    """
    _logger.info("Scheduler ▶ job_data_integrity_check")
    corrections: dict[str, int] = {}

    try:
        with _get_db() as db:
            from app.models.pool import Pool, PoolStatus
            from app.models.user import User, UserStatus
            from sqlalchemy import func as _func, text as _text

            now = datetime.now(timezone.utc)

            # ── 1. Sync pool.total_members ─────────────────────────────────────
            pools = (
                db.query(Pool)
                .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
                .all()
            )
            pool_fixes = 0
            for pool in pools:
                real_count = (
                    db.query(_func.count(User.id))
                    .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
                    .scalar() or 0
                )
                if pool.total_members != real_count:
                    _logger.warning(
                        "DataIntegrity: pool %d (%s) total_members=%d → correcting to %d",
                        pool.id, pool.name, pool.total_members, real_count,
                    )
                    pool.total_members = real_count
                    pool_fixes += 1
            if pool_fixes:
                db.commit()
            corrections["pool_member_count_fixed"] = pool_fixes

            # ── 2. Orphaned SDE flags ─────────────────────────────────────────
            orphan_sde = (
                db.query(User)
                .filter(
                    User.sde_required == True,       # noqa: E712
                    User.status       != UserStatus.Active,
                )
                .all()
            )
            for u in orphan_sde:
                _logger.warning(
                    "DataIntegrity: orphaned sde_required on non-Active user %d (%s status=%s) — clearing",
                    u.id, u.username, u.status.value,
                )
                u.sde_required = False
            if orphan_sde:
                db.commit()
            corrections["orphan_sde_flags_cleared"] = len(orphan_sde)

            # ── 3. Expired grace periods ──────────────────────────────────────
            try:
                expired_grace = (
                    db.query(User)
                    .filter(
                        User.grace_active     == True,       # noqa: E712
                        User.grace_fee_paid   == False,      # noqa: E712
                        User.grace_expires_at <= now,
                    )
                    .all()
                )
                for u in expired_grace:
                    _logger.warning(
                        "DataIntegrity: expired grace period on user %d (%s) — closing",
                        u.id, u.username,
                    )
                    u.grace_active = False
                    u.elimination_risk = True   # grace expired without payment = at risk
                if expired_grace:
                    db.commit()
                corrections["expired_grace_cleared"] = len(expired_grace)
            except Exception as _e:
                # grace_active column may not exist yet on older DBs
                corrections["expired_grace_cleared"] = 0
                _logger.debug("DataIntegrity: grace period check skipped (column may not exist): %s", _e)

            # ── 4. Pool contains_flagged_l4 consistency ───────────────────────
            l4_fixes = 0
            for pool in pools:
                has_l4 = (
                    db.query(_func.count(User.id))
                    .filter(
                        User.current_pool_id == pool.id,
                        User.status          == UserStatus.Active,
                        User.sde_required    == True,         # noqa: E712
                    )
                    .scalar() or 0
                ) > 0
                if bool(pool.contains_flagged_l4) != has_l4:
                    pool.contains_flagged_l4 = has_l4
                    l4_fixes += 1
            if l4_fixes:
                db.commit()
            corrections["l4_flag_fixes"] = l4_fixes

        _logger.info(
            "Scheduler ✓ job_data_integrity_check COMPLETE  "
            "pool_fixes=%d  orphan_sde=%d  grace_expired=%d  l4_fixes=%d",
            corrections.get("pool_member_count_fixed",   0),
            corrections.get("orphan_sde_flags_cleared",  0),
            corrections.get("expired_grace_cleared",     0),
            corrections.get("l4_flag_fixes",             0),
        )

    except Exception as exc:
        _logger.error(
            "Scheduler ✗ job_data_integrity_check FAILED  %s: %s",
            type(exc).__name__, exc,
            exc_info=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduler lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

def start_scheduler() -> AsyncIOScheduler:
    """
    Build, configure, and START the AsyncIOScheduler.

    Called from the FastAPI lifespan startup handler.
    Stores the instance in the module-level _scheduler variable so that
    get_scheduler_status() and stop_scheduler() can access it.

    Returns the running scheduler instance.

    Raises:
      RuntimeError — if the scheduler is already running.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        raise RuntimeError("Scheduler is already running.")

    sched = AsyncIOScheduler(timezone="UTC")

    # ── Job 1: T-2H Preparation ───────────────────────────────────────────────
    sched.add_job(
        job_preparation,
        trigger=CronTrigger(
            day_of_week=_PREP_DOW,
            hour=_PREP_HOUR_UTC,
            minute=_PREP_MINUTE_UTC,
            timezone="UTC",
        ),
        id="draw_preparation",
        name="T-2H Draw Preparation",
        replace_existing=True,
        misfire_grace_time=600,   # 10-min tolerance — handles cold start delays
        max_instances=1,
        coalesce=True,            # if multiple misfires stacked, run only once
    )

    # ── Job 2: Override Watchdog (every 5 minutes) ────────────────────────────
    sched.add_job(
        job_override_watchdog,
        trigger=CronTrigger(minute="*/5", timezone="UTC"),
        id="override_watchdog",
        name="Admin Override Auto-Select Watchdog",
        replace_existing=True,
        misfire_grace_time=120,
        max_instances=1,
        coalesce=True,
    )

    # ── Job 3: Weekly Draw ────────────────────────────────────────────────────
    sched.add_job(
        job_weekly_draw,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=_DRAW_HOUR_UTC,
            minute=_DRAW_MINUTE_UTC,
            timezone="UTC",
        ),
        id="weekly_draw",
        name="Sunday Weekly Draw",
        replace_existing=True,
        misfire_grace_time=300,   # 5-min tolerance — draw accuracy matters
        max_instances=1,
        coalesce=True,
    )

    # ── Job 4: Post-Draw Cleanup ──────────────────────────────────────────────
    sched.add_job(
        job_post_cleanup,
        trigger=CronTrigger(
            day_of_week=_CLEANUP_DOW,
            hour=_CLEANUP_HOUR_UTC,
            minute=_CLEANUP_MINUTE_UTC,
            timezone="UTC",
        ),
        id="post_draw_cleanup",
        name="Post-Draw Cleanup (T+5 min)",
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1,
        coalesce=True,
    )

    # ── Job 5: Data Integrity Check (every 6 hours) ───────────────────────────
    sched.add_job(
        job_data_integrity_check,
        trigger=CronTrigger(hour="*/6", timezone="UTC"),   # 00:00, 06:00, 12:00, 18:00 UTC
        id="data_integrity_check",
        name="Data Integrity Auto-Repair (6h)",
        replace_existing=True,
        misfire_grace_time=1800,   # 30 min tolerance — non-critical job
        max_instances=1,
        coalesce=True,
    )

    sched.start()
    _scheduler = sched

    _logger.info(
        "APScheduler STARTED  ·  "
        "prep=%s %02d:%02dUTC  "
        "draw=sun %02d:%02dUTC  "
        "cleanup=%s %02d:%02dUTC  "
        "watchdog=every-5min  "
        "integrity=every-6h",
        _PREP_DOW, _PREP_HOUR_UTC, _PREP_MINUTE_UTC,
        _DRAW_HOUR_UTC, _DRAW_MINUTE_UTC,
        _CLEANUP_DOW, _CLEANUP_HOUR_UTC, _CLEANUP_MINUTE_UTC,
    )

    return sched


def stop_scheduler() -> None:
    """
    Gracefully shut down the scheduler.
    Called from the FastAPI lifespan shutdown handler.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _logger.info("APScheduler STOPPED.")
    _scheduler = None


def get_scheduler_status() -> dict:
    """
    Return scheduler running state and next-run times for all registered jobs.
    Used by GET /admin/draw/scheduler-status.
    """
    if _scheduler is None or not _scheduler.running:
        return {
            "running": False,
            "enabled": os.getenv("SCHEDULER_ENABLED", "false").lower() == "true",
            "jobs":    [],
            "schedule": {
                "draw_utc":    f"sun {_DRAW_HOUR_UTC:02d}:{_DRAW_MINUTE_UTC:02d}",
                "prep_utc":    f"{_PREP_DOW} {_PREP_HOUR_UTC:02d}:{_PREP_MINUTE_UTC:02d}",
                "cleanup_utc": f"{_CLEANUP_DOW} {_CLEANUP_HOUR_UTC:02d}:{_CLEANUP_MINUTE_UTC:02d}",
            },
        }

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id":       job.id,
            "name":     job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })

    return {
        "running": True,
        "enabled": True,
        "jobs":    jobs,
        "schedule": {
            "draw_utc":    f"sun {_DRAW_HOUR_UTC:02d}:{_DRAW_MINUTE_UTC:02d}",
            "prep_utc":    f"{_PREP_DOW} {_PREP_HOUR_UTC:02d}:{_PREP_MINUTE_UTC:02d}",
            "cleanup_utc": f"{_CLEANUP_DOW} {_CLEANUP_HOUR_UTC:02d}:{_CLEANUP_MINUTE_UTC:02d}",
        },
    }
