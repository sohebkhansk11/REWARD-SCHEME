"""
T-2H Draw Preparation Engine
==============================
Runs exactly 2 hours before the Sunday draw.

Responsibilities:
  1. Acquire the 'draw_engine' system lock — blocks condensation Phase 3.
  2. Freeze the level snapshot (LPI + distribution recorded into WeeklyDrawState).
  3. Catch-up flag any L4 members not yet tagged (belt-and-suspenders).
  4. Redistribute multi-L4 pools (BUG 2 resolution).
  5. Quantify SDE demand and check L1/L2 supply sufficiency.
  6. Check float sufficiency (projected payout vs current reserve).
  7. Run SDE backend processing — all sub-draws computed before draw time.
  8. If SDE overflow exists: set admin_override_required flag.
  9. Mark preparation_valid = True and countdown_active = True.
 10. Record idempotency key so a double-trigger is a no-op.

Two-flag countdown rule (security/UX contract):
  Frontend MUST receive BOTH (preparation_valid=True AND countdown_active=True)
  before displaying the countdown timer.  One flag alone is not sufficient.
  The API endpoint get_draw_countdown() enforces this rule server-side.

Atomicity guarantee:
  All state changes in _run_preparation() are committed in ONE transaction.
  If any step fails, the entire preparation is rolled back, the lock is
  released, and the error is re-raised for the scheduler to handle.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import (
    ADMIN_OVERRIDE_TIMEOUT_HOURS,
    DRAW_LOCK_TOTAL_MINUTES,
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # LEVEL_PAYOUTS removed — now served from global_config.py (DB-backed).
)
# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
from app.services.global_config import get_level_payout
from app.models.pool          import Pool, PoolStatus
from app.models.system_lock   import SystemLock
from app.models.user          import User, UserStatus
from app.models.weekly_draw_state import WeeklyDrawState

_logger = logging.getLogger(__name__)

# Lock name — must match the constant used in waitlist.py and post_draw_cleanup
_DRAW_ENGINE_LOCK = "draw_engine"


# ── Week ID helper ────────────────────────────────────────────────────────────

def _make_week_id(dt: datetime) -> str:
    """Format a datetime as an ISO week key: 'YYYY-Www'."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _make_idempotency_key(week_id: str, draw_time_utc: datetime) -> str:
    """SHA-256 of (week_id + draw_time_utc ISO string) — prevents duplicate prep."""
    raw = f"{week_id}|{draw_time_utc.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ── Draw window lock ──────────────────────────────────────────────────────────

def is_draw_window_active(db: Session) -> bool:
    """
    Returns True if the draw engine lock is currently held and has not expired.

    Called by waitlist.py Phase 3 to gate condensation.
    Also callable from admin endpoints as a status indicator.
    """
    now = datetime.now(timezone.utc)
    lock = (
        db.query(SystemLock)
        .filter(
            SystemLock.lock_name == _DRAW_ENGINE_LOCK,
            SystemLock.expires_at > now,
        )
        .first()
    )
    return lock is not None


def _acquire_draw_lock(db: Session, week_id: str) -> bool:
    """
    Attempt to acquire the draw engine lock.

    Uses INSERT … ON CONFLICT DO NOTHING — atomic at the DB level.
    The winning writer gets the lock; all others get a conflict signal.

    Returns True (lock acquired) or False (already held by another process).
    Does NOT commit — caller must commit or the row won't persist.
    """
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=DRAW_LOCK_TOTAL_MINUTES)

    # Delete expired locks first (handles crash-left stale locks)
    db.query(SystemLock).filter(
        SystemLock.lock_name  == _DRAW_ENGINE_LOCK,
        SystemLock.expires_at <= now,
    ).delete()

    try:
        lock = SystemLock(
            lock_name   = _DRAW_ENGINE_LOCK,
            acquired_at = now,
            expires_at  = expires,
            held_by     = week_id,
        )
        db.add(lock)
        db.flush()   # will raise IntegrityError if already held
        return True
    except Exception:
        db.rollback()
        return False


def _release_draw_lock(db: Session) -> None:
    """Release the draw engine lock.  Called by post_draw_cleanup."""
    db.query(SystemLock).filter(SystemLock.lock_name == _DRAW_ENGINE_LOCK).delete()


# ── Financial projection ──────────────────────────────────────────────────────

def _calculate_projected_payout(db: Session) -> int:
    """
    Worst-case total payout for the upcoming draw cycle.

    For each active pool, estimate maximum payout based on the highest-level
    upper-tier member present.  Sum across all eligible pools.

    This is a conservative upper bound — actual payouts will typically be lower.
    """
    from app.core.config import POOL_DRAW_SDE, POOL_DRAW_TYPE_A, POOL_DRAW_REGULAR

    active_pools = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .all()
    )

    total_projected = 0
    for pool in active_pools:
        # Find the highest level member in this pool
        max_level = (
            db.query(func.max(User.current_level))
            .filter(
                User.current_pool_id == pool.id,
                User.status          == UserStatus.Active,
            )
            .scalar()
        ) or 1

        # Upper winner payout at max level + lower winner at L1 (floor estimate)
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # LEVEL_PAYOUTS replaced with DB-backed dynamic getter.
        upper_net = get_level_payout(db, min(max_level, 4))[1]
        lower_net = get_level_payout(db, 1)[1]
        total_projected += upper_net + lower_net

    return total_projected


# ── Consecutive Type B check ──────────────────────────────────────────────────

def _count_consecutive_type_b_weeks(db: Session) -> int:
    """
    Count consecutive recent weeks where pool_draw_type contained 'type_b'.
    Reads the last 4 WeeklyDrawState rows ordered by week_id DESC.
    Stops counting at the first non-type_b week.
    """
    # Check DrawHistory for type_b draws in recent weeks
    from app.models.draw_history import DrawHistory
    recent_states = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.draw_executed == True)   # noqa: E712
        .order_by(WeeklyDrawState.week_id.desc())
        .limit(4)
        .all()
    )

    consecutive = 0
    for state in recent_states:
        # Check if any pool used type_b this week
        type_b_draws = (
            db.query(func.count(DrawHistory.id))
            .filter(
                DrawHistory.draw_timestamp >= state.preparation_started_at,
                DrawHistory.draw_type == "type_b",
            )
            .scalar()
        ) or 0

        if type_b_draws > 0:
            consecutive += 1
        else:
            break  # streak broken

    return consecutive


# ── Main preparation entry point ──────────────────────────────────────────────

def start_draw_preparation(
    db: Session,
    draw_time_utc: datetime,
    user_prefix: str | None = None,
) -> WeeklyDrawState:
    """
    T-2H draw preparation.  Call this exactly 2 hours before the draw.

    Idempotent: if preparation was already completed for this week, returns
    the existing WeeklyDrawState without re-running.

    Thread-safe: uses the system_locks table as a distributed mutex.

    Args:
      db:            SQLAlchemy session.
      draw_time_utc: UTC datetime of the draw (e.g. Sunday 13:30 UTC = 7 PM IST).
      user_prefix:   Optional run-scope prefix (None in production → all paid waitlist
                     users; set by the isolated sim so the STEP 3b merger refill only
                     touches that run's users).

    Returns:
      WeeklyDrawState with preparation_valid=True on success.

    Raises:
      RuntimeError — if the draw lock cannot be acquired (another prep is running).
      Exception    — re-raised from any step failure; lock released before raise.
    """
    week_id = _make_week_id(draw_time_utc)
    idem_key = _make_idempotency_key(week_id, draw_time_utc)

    # Idempotency check: already prepared this week?
    existing: WeeklyDrawState | None = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.week_id == week_id)
        .first()
    )
    if existing and existing.preparation_valid:
        _logger.info(
            "start_draw_preparation: week %s already prepared (idempotent return).",
            week_id,
        )
        return existing

    # Acquire draw lock
    if not _acquire_draw_lock(db, week_id):
        db.commit()  # commit the expired-lock delete
        lock = db.query(SystemLock).filter(
            SystemLock.lock_name == _DRAW_ENGINE_LOCK
        ).first()
        raise RuntimeError(
            f"Draw preparation for {week_id} cannot start — "
            f"draw_engine lock is held by '{lock.held_by if lock else 'unknown'}' "
            f"until {lock.expires_at if lock else 'unknown'}."
        )
    db.commit()   # commit the lock acquisition
    _logger.info("start_draw_preparation: draw engine lock acquired for week %s.", week_id)

    try:
        state = _run_preparation(
            db, week_id, draw_time_utc, idem_key, existing, user_prefix=user_prefix,
        )
        return state
    except Exception as exc:
        _logger.error(
            "start_draw_preparation: FAILED for week %s — %s.  Releasing lock.",
            week_id, exc,
        )
        db.rollback()
        # Release lock so the scheduler can retry
        _release_draw_lock(db)
        db.commit()
        raise


def _run_preparation(
    db: Session,
    week_id: str,
    draw_time_utc: datetime,
    idem_key: str,
    existing: WeeklyDrawState | None,
    user_prefix: str | None = None,
) -> WeeklyDrawState:
    """
    Core preparation logic.  Called only when the lock is held.

    All steps run in sequence.  The final db.commit() at the end of
    _run_preparation() is the single atomic commit for all preparation state.
    Each step calls db.flush() to get DB-assigned IDs without committing.

    SDE processing commits internally (each sub-draw is its own transaction).
    WeeklyDrawState is finalised after SDE processing completes.
    """
    from app.services.brain5_lpi_engine import (
        calculate_lpi, get_level_distribution, get_forward_signal,
        flag_l4_members, get_sde_demand, get_total_active_count,
    )
    from app.services.sde_engine import run_sde_meta_pool

    now = datetime.now(timezone.utc)

    # ── STEP 1: Create or update WeeklyDrawState ──────────────────────────────
    if existing:
        state = existing
        state.preparation_started_at = now
        state.preparation_valid      = False   # reset in case of retry
        state.countdown_active       = False
    else:
        state = WeeklyDrawState(
            week_id                  = week_id,
            draw_time_utc            = draw_time_utc,
            preparation_started_at   = now,
            preparation_valid        = False,
            countdown_active         = False,
            idempotency_key          = idem_key,
        )
        db.add(state)

    db.flush()

    # ── STEP 2: Snapshot lock — freeze level data ─────────────────────────────
    dist = get_level_distribution(db)
    lpi  = calculate_lpi(db)
    state.lpi_snapshot       = lpi
    state.total_l4_count     = dist.l4
    state.total_l3_count     = dist.l3
    state.total_active_count = get_total_active_count(db)

    _logger.info(
        "Preparation STEP 2: snapshot — LPI=%.2f%%  L4=%d  L3=%d  total=%d",
        lpi, dist.l4, dist.l3, state.total_active_count,
    )

    # ── STEP 3: Catch-up flag any un-flagged L4 members ──────────────────────
    newly_flagged = flag_l4_members(db)
    if newly_flagged:
        _logger.warning(
            "Preparation STEP 3: catch-up flagged %d L4 member(s) "
            "(should be 0 in normal operation — indicates draw.py flag may have missed them).",
            newly_flagged,
        )

    # ── STEP 3b: T-2H merger convergence (Jun-19 dual-tick, Point 2) ──────────
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # After grace closes (TICK5) and L4 flagging is final (STEP 3, so
    # contains_flagged_l4 is accurate for SDE immunity), pack every non-flagged pool
    # to 12 BEFORE the eligibility gate runs at T-0H.  run_merger_refill_converge
    # loops two-pointer compaction + waitlist refill until all consolidatable pools
    # are full and the remainder is topped up from the waitlist — so more pools sit at
    # exactly 12/12 and become draw-eligible this week (the user's "merger also runs
    # in T-2H preparation, same as Point 1" rule).  Runs BEFORE STEP 8 SDE staging so
    # the SDE draw operates on packed pools.  Non-fatal: a failure here is logged and
    # preparation continues (the draw still runs; refill back-fills at T-0H).
    from app.services.waitlist import run_merger_refill_converge
    try:
        _conv = run_merger_refill_converge(db, user_prefix=user_prefix)
        _logger.info(
            "Preparation STEP 3b: T-2H merger convergence packed pools in %d round(s) "
            "— %d member(s) compacted, %d pool(s) dissolved.",
            _conv["rounds"], _conv["transfers"], len(_conv["dissolved"]),
        )
    except Exception as _conv_exc:
        try:
            db.rollback()
        except Exception:
            pass
        _logger.error(
            "Preparation STEP 3b: T-2H merger convergence failed (non-fatal) — "
            "preparation continues, T-0H refill will back-fill: %s",
            _conv_exc, exc_info=True,
        )

    # ── STEP 4: Quantify SDE demand ───────────────────────────────────────────
    sde_demand = get_sde_demand(db)
    state.sde_sessions_planned = sde_demand.sessions_needed

    _logger.info(
        "Preparation STEP 4: SDE demand — L4=%d  sessions=%d  "
        "L1L2_needed=%d  L1L2_have=%d  clearable=%d  overflow=%d",
        sde_demand.l4_count, sde_demand.sessions_needed,
        sde_demand.l1l2_threshold, sde_demand.l1l2_available,
        sde_demand.clearable_count, sde_demand.overflow_count,
    )

    # ── STEP 5: Admin override flag ───────────────────────────────────────────
    if sde_demand.overflow_requires_admin:
        state.admin_override_required = True
        state.admin_override_deadline = (
            now + timedelta(hours=ADMIN_OVERRIDE_TIMEOUT_HOURS)
        )
        state.sde_overflow_count = sde_demand.overflow_count
        _logger.warning(
            "Preparation STEP 5: admin override REQUIRED — %d L4 member(s) "
            "cannot be cleared (supply shortage).  Deadline: %s",
            sde_demand.overflow_count,
            state.admin_override_deadline.isoformat(),
        )

    # ── STEP 6: Float sufficiency check ──────────────────────────────────────
    projected = _calculate_projected_payout(db)
    state.float_projection_inr = projected
    _logger.info(
        "Preparation STEP 6: float projection = ₹%d (worst-case draw payout)",
        projected,
    )

    # ── STEP 7: Consecutive Type B alert ─────────────────────────────────────
    consecutive_b = _count_consecutive_type_b_weeks(db)
    state.consecutive_type_b_weeks = consecutive_b
    if consecutive_b >= 2:
        _logger.warning(
            "Preparation STEP 7: TYPE B used for %d consecutive week(s) — "
            "L1/L2 supply is persistently low.  Consider admin intervention.",
            consecutive_b,
        )

    # ── STEP 8: SDE backend processing ───────────────────────────────────────
    # Only run SDE if there are L4 members AND admin override is NOT blocking.
    # If admin override is required, the admin must decide first; SDE will run
    # after their decision is applied (via admin_override.py).
    if sde_demand.l4_count > 0 and not state.admin_override_required:
        _logger.info(
            "Preparation STEP 8: running SDE meta-pool for %d L4 member(s)...",
            sde_demand.l4_count,
        )
        sde_result = run_sde_meta_pool(db, week_id)
        state.sde_sessions_completed = len(sde_result.sessions)
        state.sde_overflow_count     = sde_result.overflow_l4_count

        if sde_result.overflow_l4_count > 0:
            _logger.warning(
                "Preparation STEP 8: SDE processed with %d overflow L4 member(s).",
                sde_result.overflow_l4_count,
            )
    elif sde_demand.l4_count > 0 and state.admin_override_required:
        _logger.info(
            "Preparation STEP 8: SDE DEFERRED — admin override required first.  "
            "%d L4 member(s) waiting for admin decision.",
            sde_demand.l4_count,
        )
    else:
        _logger.info("Preparation STEP 8: no L4 members — SDE not needed.")

    # ── STEP 8b: Master Pool Re-assessment — virtual pre-deployment gate ──────
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Runs AFTER STEP 8 (SDE winners staged, executed=False) and BEFORE STEP 9
    # (countdown activation), so it sees the FULL prepared result. It virtually
    # dissolves every pool, projects the entire week's winner set (staged SDE +
    # projected regular draws), and cross-verifies "purity of the draw" against the
    # five financial-grade checks. A ReassessmentReport row is persisted (committed
    # together with STEP 9). On HOLD, the row sits unapproved and the T-0H gate in
    # execute_weekly_draw blocks deployment until an admin approves the corrected
    # plan with their password (locked decision #1). Failure-isolated: if the gate
    # itself errors, we FAIL CLOSED — persist a HOLD report carrying the error so
    # the T-0H gate still blocks (money-safe), while preparation continues so the
    # countdown/UI state stays consistent.
    try:
        from app.services.pool_reassessor import run_reassessment, persist_report
        _ra = run_reassessment(db, week_id)
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # ROUTE-VIA-REASSESSMENT (Task 2): the T-2H merge already ran at STEP 3b, so
        # THIS gate is the re-assessment OF the newly merged/dissolved layout (the
        # user's "pre-draw T-2H: merge first → draw sequence → THEN re-assess the
        # merged pools" flow).  Tag the trigger so the decision trail shows this
        # report assessed the post-merge structure (no extra report / no migration).
        try:
            _ra.audit["routed_trigger"] = "pre_draw_t2h_post_merge"
        except Exception:
            pass
        _report = persist_report(db, _ra)
        # NOTE: hold state is read back from this report row (reassessment_reports
        # is the single source of truth) — deliberately NO mirror column on
        # WeeklyDrawState, so no schema migration is required.
        if _ra.is_hold:
            _logger.error(
                "Preparation STEP 8b: RE-ASSESSMENT HOLD for week %s (report #%d) — "
                "DEPLOYMENT BLOCKED pending admin approval. Failed hard gate(s): %s. "
                "Corrected plan: %d action(s). payout=₹%d available_float=₹%d.",
                week_id, _report.id, ", ".join(_ra.failed_hard_gates) or "none",
                len(_ra.corrected_plan), _ra.projected_payout_inr, _ra.available_float_inr,
            )
        else:
            _logger.info(
                "Preparation STEP 8b: RE-ASSESSMENT PASS for week %s (report #%d) — "
                "clear to deploy. payout=₹%d available_float=₹%d.",
                week_id, _report.id, _ra.projected_payout_inr, _ra.available_float_inr,
            )
    except Exception as _ra_exc:
        # FAIL CLOSED — the gate erred; record an explicit HOLD report so the T-0H
        # gate blocks deployment until an admin reviews it. Never crash preparation.
        _logger.critical(
            "Preparation STEP 8b: RE-ASSESSMENT ENGINE ERROR for week %s — "
            "failing CLOSED (writing HOLD report; deployment will block): %s",
            week_id, _ra_exc, exc_info=True,
        )
        try:
            import json as _json
            from app.models.reassessment_report import ReassessmentReport
            db.add(ReassessmentReport(
                week_id=week_id, verdict="HOLD",
                purity_pass=True, level_advance_pass=True,
                float_pass=False, pyramid_pass=False, reconcile_pass=False,
                projected_payout_inr=int(state.float_projection_inr or 0),
                available_float_inr=0, net_float_inr=0,
                audit_json=_json.dumps({"engine_error": str(_ra_exc)}),
                corrected_plan_json=_json.dumps([{
                    "gate": "engine", "severity": "critical",
                    "finding": f"Re-assessment engine raised: {_ra_exc}",
                    "action": "Investigate the gate error, then re-run preparation or "
                              "approve explicitly to override the fail-closed hold.",
                    "params": {},
                }]),
                approved=False,
            ))
            db.flush()
        except Exception:
            _logger.critical("Preparation STEP 8b: could not even persist the "
                             "fail-closed HOLD report.", exc_info=True)

    # ── STEP 9: Mark preparation complete — two-flag activation ──────────────
    state.preparation_completed_at = datetime.now(timezone.utc)
    state.preparation_valid        = True    # FLAG 1
    state.countdown_active         = True    # FLAG 2
    state.draw_time_utc            = draw_time_utc

    db.commit()

    _logger.info(
        "Draw preparation COMPLETE for week %s — "
        "countdown_active=True  preparation_valid=True  "
        "draw_at=%s",
        week_id,
        draw_time_utc.isoformat(),
    )
    return state


# ── Countdown API ─────────────────────────────────────────────────────────────

def get_draw_countdown(db: Session) -> dict:
    """
    Two-flag countdown response.

    Returns countdown data ONLY when BOTH flags are True:
      preparation_valid=True  AND  countdown_active=True

    If either is False, returns a non-countdown response with a status message.
    Frontend must check countdown_active before rendering the timer.

    Used by: GET /draw/countdown
    """
    now     = datetime.now(timezone.utc)
    iso     = now.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"

    state: WeeklyDrawState | None = (
        db.query(WeeklyDrawState)
        .filter(WeeklyDrawState.week_id == week_id)
        .first()
    )

    # ── Gate: both flags must be True ────────────────────────────────────────
    if not state or not state.preparation_valid or not state.countdown_active:
        return {
            "countdown_active":  False,
            "preparation_valid": state.preparation_valid if state else False,
            "week_id":           week_id,
            "message":           "Draw preparation in progress — timer will appear when ready.",
        }

    if not state.draw_time_utc:
        return {
            "countdown_active":  False,
            "preparation_valid": True,
            "week_id":           week_id,
            "message":           "Draw time not set.  Contact admin.",
        }

    remaining_seconds = (state.draw_time_utc - now).total_seconds()

    if remaining_seconds < 0:
        # Draw time has passed — either draw is running or already complete
        return {
            "countdown_active":  False,
            "preparation_valid": True,
            "draw_executed":     state.draw_executed,
            "week_id":           week_id,
            "message":           "Draw time reached" if not state.draw_executed else "Draw complete.",
        }

    return {
        "countdown_active":  True,
        "preparation_valid": True,
        "remaining_seconds": int(remaining_seconds),
        "draw_time_utc":     state.draw_time_utc.isoformat(),
        "week_id":           week_id,
        # Extra context for admin display
        "lpi_snapshot":      float(state.lpi_snapshot or 0),
        "sde_sessions":      state.sde_sessions_planned,
        "admin_override_required": state.admin_override_required,
    }
