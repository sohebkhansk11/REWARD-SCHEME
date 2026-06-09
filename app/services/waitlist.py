"""
Waitlist Services — Double-FIFO Auto-Refill Engine
===================================================
Public API
----------
  assign_waitlist_to_pools(db)
      Master function.  Call after EVERY event that creates pool vacancies OR
      adds a user to the Waitlist:
        • after every draw (single or global mass draw)
        • after eliminating unpaid members
        • when a new user registers / pays
        • when an admin manually triggers a check

  manual_create_pool(db)
      Admin-triggered; bypasses the auto-creation toggle and threshold.

Backward-compatible shims (kept for legacy call sites)
-------------------------------------------------------
  fill_pool_vacancies(db)     → calls assign_waitlist_to_pools; returns Phase 1 list
  check_and_scale_waitlist(db) → calls assign_waitlist_to_pools; returns Phase 2 Pool

Phase 1 — Double-FIFO ordering
-------------------------------
  Pool  priority : Pool.created_at  ASC  (oldest under-capacity pool filled first)
  Member priority: User.join_date   ASC  (longest-waiting Waitlist user first)
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import WAITLIST_TRIGGER, NEW_POOL_INTAKE, POOL_CAPACITY  # noqa: F401
from app.core.pool_settings import get_auto_pool_creation
from app.crud import user as crud_user, pool as crud_pool
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.schemas.pool import PoolCreate, PoolUpdate
from app.schemas.user import UserUpdate
from app.services.settings import get_pool_threshold

_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _next_pool_name(db: Session) -> str:
    """Generate Pool A, B, …, Z, AA, … based on total pool count."""
    count = db.query(Pool).count()
    letters = ""
    n = count
    while True:
        letters = chr(65 + n % 26) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return f"Pool {letters}"


def _activate_user(db: Session, user: User, pool: Pool, phase: str) -> None:
    """
    State-machine transition: Waitlist → Active pool.

    Sets: status=Active, pool_id=pool.id, level=1, payment=Paid.
    Credits Rule-39 referral bonus if the user was referred.
    Caller must db.commit() after processing a complete batch.
    """
    # Local import — avoids the circular import between draw.py and waitlist.py
    from app.services.draw import _credit_referral_bonus

    crud_user.update_user(
        db,
        user.id,
        UserUpdate(
            status=UserStatus.Active,
            current_pool_id=pool.id,
            current_level=1,
            weekly_payment_status=WeeklyPaymentStatus.Paid,
        ),
    )
    db.refresh(user)

    if user.referred_by_user_id:
        _credit_referral_bonus(db, user.referred_by_user_id)

    _logger.info(
        "[%s] FIFO-ASSIGN  @%-20s  (id=%5d  joined=%s)  →  %s (id=%d)",
        phase,
        user.username,
        user.id,
        user.join_date.strftime("%Y-%m-%dT%H:%M") if user.join_date else "unknown",
        pool.name,
        pool.id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MASTER FUNCTION — Double-FIFO Auto-Refill Engine
# ─────────────────────────────────────────────────────────────────────────────

def assign_waitlist_to_pools(db: Session) -> dict:
    """
    Double-FIFO Auto-Refill Engine — the single source of truth for all
    waitlist-to-pool assignment logic.

    ┌─ Phase 1: Refill Existing Pools (Highest Priority) ──────────────────────┐
    │  Step 1 — Fetch all Active pools with < 12 members, ordered created_at   │
    │           ASC (oldest under-capacity pool gets priority).                 │
    │  Step 2 — Fetch all Waitlist/Paid users, ordered join_date ASC           │
    │           (longest-waiting user gets priority — strict FIFO).            │
    │  Step 3 — Iterate pools oldest-first: assign exactly (12 − count)        │
    │           oldest users to each pool.                                      │
    │  Step 4 — Stop when all pools are full OR the queue is exhausted.        │
    └───────────────────────────────────────────────────────────────────────────┘
    ┌─ Phase 2: Auto-Scale New Pools (only if Waitlist is large enough) ────────┐
    │  After Phase 1, if AUTO_POOL_CREATION is ON AND remaining paid-waitlist  │
    │  count >= pool_creation_threshold (default 24):                           │
    │    a. Derive next sequential pool name.                                   │
    │    b. Create a new Active Pool.                                           │
    │    c. Assign the next 12 oldest Waitlist/Paid users into it.             │
    │    d. Remaining members stay on Waitlist until the next trigger.          │
    └───────────────────────────────────────────────────────────────────────────┘

    Returns:
        {
          "phase1_assigned":     int,
          "phase1_pool_changes": [{"pool_id", "pool_name", "filled", "total_after"}],
          "phase2_pool_created": str | None,   # new pool name, or None
          "phase2_assigned":     int,
        }
    """
    _logger.info("══ assign_waitlist_to_pools — Double-FIFO engine START ══")

    # ── Phase 1 ──────────────────────────────────────────────────────────────

    # 1a. All Active AND Paused_Awaiting_Members pools ordered oldest-first.
    #     Paused pools are included so they can be refilled by waitlist members
    #     and restored to Active status when they reach capacity again.
    active_pools: list[Pool] = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .order_by(Pool.created_at.asc())
        .all()
    )

    # Compute real vacancy counts (never trust pool.total_members — it can lag)
    pools_needing_fill: list[tuple[Pool, int]] = []
    for pool in active_pools:
        actual: int = (
            db.query(User)
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .count()
        )
        vacancies = POOL_CAPACITY - actual
        if vacancies > 0:
            pools_needing_fill.append((pool, vacancies))

    total_vacancies = sum(v for _, v in pools_needing_fill)
    _logger.info(
        "Phase 1: %d pool(s) under capacity — %d total vacancy slot(s).",
        len(pools_needing_fill), total_vacancies,
    )

    phase1_assigned    = 0
    phase1_pool_changes: list[dict] = []

    if pools_needing_fill:
        # 1b. Oldest paid Waitlist members first — fetch only what we need
        candidates: list[User] = (
            db.query(User)
            .filter(
                User.status == UserStatus.Waitlist,
                User.weekly_payment_status == WeeklyPaymentStatus.Paid,
            )
            .order_by(User.join_date.asc())
            .limit(total_vacancies)
            .all()
        )
        _logger.info(
            "Phase 1: %d paid Waitlist candidate(s) available (need up to %d).",
            len(candidates), total_vacancies,
        )
        queue = list(candidates)

        # 1c. Fill each pool completely before moving to the next
        for pool, vacancies in pools_needing_fill:
            if not queue:
                _logger.info(
                    "Phase 1: Waitlist exhausted — %s still needs %d member(s).",
                    pool.name, vacancies,
                )
                break

            to_assign = min(vacancies, len(queue))
            batch     = queue[:to_assign]
            queue     = queue[to_assign:]

            _logger.info(
                "Phase 1: filling %s (%d/%d → %d/12) with %d user(s):",
                pool.name,
                POOL_CAPACITY - vacancies,
                POOL_CAPACITY,
                POOL_CAPACITY - vacancies + to_assign,
                to_assign,
            )
            for user in batch:
                _activate_user(db, user, pool, phase="P1")
            phase1_assigned += to_assign

            phase1_pool_changes.append({
                "pool_id":     pool.id,
                "pool_name":   pool.name,
                "filled":      to_assign,
                "total_after": POOL_CAPACITY - vacancies + to_assign,
            })

        if phase1_assigned:
            db.commit()
            # Sync pool.total_members AFTER commit so counts are accurate.
            # If a Paused_Awaiting_Members pool has been refilled to capacity,
            # restore it to Active status.
            for change in phase1_pool_changes:
                actual = (
                    db.query(User)
                    .filter(
                        User.current_pool_id == change["pool_id"],
                        User.status == UserStatus.Active,
                    )
                    .count()
                )
                pool_obj: Pool | None = (
                    db.query(Pool).filter(Pool.id == change["pool_id"]).first()
                )
                if (
                    pool_obj
                    and pool_obj.status == PoolStatus.Paused_Awaiting_Members
                    and actual >= POOL_CAPACITY
                ):
                    crud_pool.update_pool(
                        db,
                        change["pool_id"],
                        PoolUpdate(total_members=actual, status=PoolStatus.Active),
                    )
                    _logger.info(
                        "[P1] %s restored from Paused_Awaiting_Members → Active (%d/12).",
                        pool_obj.name,
                        actual,
                    )
                else:
                    crud_pool.update_pool(
                        db, change["pool_id"], PoolUpdate(total_members=actual)
                    )
                change["total_after"] = actual  # update to real post-commit count
            db.commit()

    _logger.info(
        "Phase 1 COMPLETE — %d user(s) assigned across %d pool(s).",
        phase1_assigned, len(phase1_pool_changes),
    )

    # ── Phase 2 ──────────────────────────────────────────────────────────────

    phase2_pool_name: str | None = None
    phase2_assigned:  int        = 0

    if not get_auto_pool_creation():
        _logger.info("Phase 2: AUTO_POOL_CREATION is OFF — skipping new pool creation.")
    else:
        threshold = get_pool_threshold(db)
        remaining: int = (
            db.query(User)
            .filter(
                User.status == UserStatus.Waitlist,
                User.weekly_payment_status == WeeklyPaymentStatus.Paid,
            )
            .count()
        )
        _logger.info(
            "Phase 2: remaining paid Waitlist = %d  |  threshold = %d",
            remaining, threshold,
        )

        if remaining >= threshold:
            pool_name = _next_pool_name(db)
            new_pool  = crud_pool.create_pool(
                db,
                PoolCreate(
                    name=pool_name,
                    status=PoolStatus.Active,
                    total_members=NEW_POOL_INTAKE,
                ),
            )
            _logger.info("Phase 2: created '%s' (id=%d).", pool_name, new_pool.id)

            new_members: list[User] = (
                db.query(User)
                .filter(
                    User.status == UserStatus.Waitlist,
                    User.weekly_payment_status == WeeklyPaymentStatus.Paid,
                )
                .order_by(User.join_date.asc())
                .limit(NEW_POOL_INTAKE)
                .all()
            )
            for user in new_members:
                _activate_user(db, user, new_pool, phase="P2")
                phase2_assigned += 1

            crud_pool.update_pool(db, new_pool.id, PoolUpdate(total_members=phase2_assigned))
            db.commit()
            phase2_pool_name = pool_name
            _logger.info(
                "Phase 2 COMPLETE — '%s' created with %d member(s).",
                pool_name, phase2_assigned,
            )
        else:
            _logger.info(
                "Phase 2: Waitlist (%d) below threshold (%d) — no new pool created.",
                remaining, threshold,
            )

    _logger.info(
        "Phase 1+2 DONE  |  P1: %d assigned  |  P2: %s — running Phase 3 check...",
        phase1_assigned,
        f"'{phase2_pool_name}' +{phase2_assigned}" if phase2_pool_name else "none",
    )

    # ── Phase 3 ──────────────────────────────────────────────────────────────
    # Dynamic Inter-Pool Condensation Engine
    #
    # Trigger: any Active or Paused_Awaiting_Members pool still has < 12 members
    #          after Phase 1 exhausted the Waitlist.
    #
    # Mechanism:
    #   Target pools  — under-capacity pools, ordered created_at ASC (save oldest first)
    #   Source pools  — FULL Active pools NOT in target set, ordered created_at DESC
    #                   (dismantle newest pools first)
    #
    # A pool cannot be both Target and Source in the same pass.
    # Member level, payment_status, and join_date are NEVER altered during transfer.
    # An emptied source pool is marked Merged_Dissolved.

    phase3_transfers: int        = 0
    phase3_events:    list[dict] = []
    phase3_dissolved: list[str]  = []

    # Re-query to capture pools freshly filled (or still short) after Phase 1
    p3_candidates: list[Pool] = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .order_by(Pool.created_at.asc())
        .all()
    )

    p3_targets: list[tuple[Pool, int]] = []
    for pool in p3_candidates:
        actual: int = (
            db.query(User)
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .count()
        )
        if actual < POOL_CAPACITY:
            p3_targets.append((pool, actual))

    if not p3_targets:
        _logger.info("Phase 3: All pools at capacity after Phase 1 — condensation not needed.")
    else:
        target_ids: set[int] = {pool.id for pool, _ in p3_targets}

        # Source pools: Active pools NOT in target set, ordered newest first
        source_pools: list[Pool] = (
            db.query(Pool)
            .filter(
                Pool.status == PoolStatus.Active,
                Pool.id.notin_(target_ids),
            )
            .order_by(Pool.created_at.desc())
            .all()
        )

        if not source_pools:
            _logger.info(
                "Phase 3: %d pool(s) still under capacity but no source pools available "
                "(all active pools are under capacity — condensation cannot proceed).",
                len(p3_targets),
            )
        else:
            # Cache live member counts per source pool to avoid N+1 queries in the loop
            src_counts: dict[int, int] = {
                sp.id: (
                    db.query(User)
                    .filter(User.current_pool_id == sp.id, User.status == UserStatus.Active)
                    .count()
                )
                for sp in source_pools
            }

            _logger.info(
                "Phase 3: %d target pool(s) need filling — "
                "harvesting from %d source pool(s): %s",
                len(p3_targets),
                len(source_pools),
                ", ".join(
                    f"{sp.name}({src_counts[sp.id]}/12)"
                    for sp in source_pools
                ),
            )

            src_idx = 0  # rolling pointer — advance when a source pool is exhausted

            for target_pool, target_actual in p3_targets:
                vacancies = POOL_CAPACITY - target_actual

                while vacancies > 0 and src_idx < len(source_pools):
                    source_pool = source_pools[src_idx]

                    if src_counts[source_pool.id] == 0:
                        src_idx += 1
                        continue

                    to_take = min(vacancies, src_counts[source_pool.id])

                    # FIFO within source: transfer oldest members first
                    transfer_batch: list[User] = (
                        db.query(User)
                        .filter(
                            User.current_pool_id == source_pool.id,
                            User.status == UserStatus.Active,
                        )
                        .order_by(User.join_date.asc())
                        .limit(to_take)
                        .all()
                    )

                    for member in transfer_batch:
                        # ── LEVEL & STATE PRESERVATION (CRITICAL) ──────────────
                        # Only reassign pool_id.
                        # Do NOT touch current_level, weekly_payment_status, join_date.
                        member.current_pool_id = target_pool.id
                        _logger.info(
                            "[P3-XFER]  @%-20s  (id=%5d  L%d  %s)  %s → %s",
                            member.username,
                            member.id,
                            member.current_level,
                            member.weekly_payment_status.value,
                            source_pool.name,
                            target_pool.name,
                        )

                    moved = len(transfer_batch)
                    vacancies                  -= moved
                    target_actual              += moved
                    src_counts[source_pool.id] -= moved
                    phase3_transfers           += moved

                    dissolved_this = (src_counts[source_pool.id] == 0)

                    if dissolved_this:
                        source_pool.status       = PoolStatus.Merged_Dissolved
                        source_pool.total_members = 0
                        phase3_dissolved.append(source_pool.name)
                        src_idx += 1

                    condensation_msg = (
                        f"Condensation Event: Moved {moved} member(s) from "
                        f"{source_pool.name} to {target_pool.name}."
                        + (f" {source_pool.name} dissolved." if dissolved_this else "")
                    )
                    _logger.info("[P3] %s", condensation_msg)

                    phase3_events.append({
                        "from_pool":     source_pool.name,
                        "to_pool":       target_pool.name,
                        "members_moved": moved,
                        "dissolved":     dissolved_this,
                    })

                if vacancies > 0:
                    _logger.info(
                        "[P3] %s still needs %d member(s) — "
                        "all source pools exhausted.",
                        target_pool.name,
                        vacancies,
                    )

            # ── Persist + sync all affected pools ──────────────────────────────
            if phase3_transfers:
                db.flush()  # push all pool_id changes to DB before counting

                all_affected_ids = target_ids | {sp.id for sp in source_pools}
                for pid in all_affected_ids:
                    pool_obj: Pool | None = (
                        db.query(Pool).filter(Pool.id == pid).first()
                    )
                    if not pool_obj:
                        continue

                    if pool_obj.status == PoolStatus.Merged_Dissolved:
                        # Already marked above — ensure member count is 0
                        pool_obj.total_members = 0
                        continue

                    new_actual: int = (
                        db.query(User)
                        .filter(
                            User.current_pool_id == pid,
                            User.status == UserStatus.Active,
                        )
                        .count()
                    )
                    pool_obj.total_members = new_actual

                    # Restore Paused → Active if now at full capacity
                    if (
                        pool_obj.status == PoolStatus.Paused_Awaiting_Members
                        and new_actual >= POOL_CAPACITY
                    ):
                        pool_obj.status = PoolStatus.Active
                        _logger.info(
                            "[P3] %s restored from Paused_Awaiting_Members → Active (%d/12).",
                            pool_obj.name,
                            new_actual,
                        )

                db.commit()

            _logger.info(
                "Phase 3 COMPLETE — %d member(s) transferred | %d event(s) | dissolved: [%s]",
                phase3_transfers,
                len(phase3_events),
                ", ".join(phase3_dissolved) if phase3_dissolved else "none",
            )

    _logger.info(
        "══ assign_waitlist_to_pools DONE  "
        "|  P1: %d  |  P2: %s  |  P3: %d xfers / %d dissolved ══",
        phase1_assigned,
        f"'{phase2_pool_name}' +{phase2_assigned}" if phase2_pool_name else "none",
        phase3_transfers,
        len(phase3_dissolved),
    )

    return {
        "phase1_assigned":     phase1_assigned,
        "phase1_pool_changes": phase1_pool_changes,
        "phase2_pool_created": phase2_pool_name,
        "phase2_assigned":     phase2_assigned,
        "phase3_transfers":    phase3_transfers,
        "phase3_events":       phase3_events,
        "phase3_dissolved":    phase3_dissolved,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatible shims
# ─────────────────────────────────────────────────────────────────────────────

def fill_pool_vacancies(db: Session) -> list[dict]:
    """
    Legacy wrapper — calls assign_waitlist_to_pools() and returns the Phase 1
    pool-change list so callers that rely on ``len(result)`` still work.

    Prefer assign_waitlist_to_pools() for new code.
    """
    result = assign_waitlist_to_pools(db)
    return result["phase1_pool_changes"]


def check_and_scale_waitlist(db: Session) -> Pool | None:
    """
    Legacy wrapper — runs the full assign_waitlist_to_pools() and returns the
    newly created pool (Phase 2 result) or None.

    Prefer assign_waitlist_to_pools() for new code.
    """
    result = assign_waitlist_to_pools(db)
    if not result["phase2_pool_created"]:
        return None
    return (
        db.query(Pool)
        .filter(Pool.name == result["phase2_pool_created"])
        .first()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Admin-triggered manual pool creation (bypasses toggle + threshold)
# ─────────────────────────────────────────────────────────────────────────────

def manual_create_pool(db: Session) -> Pool | None:
    """
    Force-create a new Active pool from paid Waitlist members regardless of the
    auto-creation toggle or current waitlist count.

    Returns the new Pool, or None if fewer than NEW_POOL_INTAKE paid members wait.
    Called exclusively from POST /admin/pools/manual-create.
    """
    paid_waitlist: list[User] = (
        db.query(User)
        .filter(
            User.status == UserStatus.Waitlist,
            User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        )
        .order_by(User.join_date.asc())
        .all()
    )

    if len(paid_waitlist) < NEW_POOL_INTAKE:
        _logger.info(
            "manual_create_pool: only %d paid member(s) available; need %d — aborted.",
            len(paid_waitlist), NEW_POOL_INTAKE,
        )
        return None

    pool_name = _next_pool_name(db)
    new_pool  = crud_pool.create_pool(
        db,
        PoolCreate(name=pool_name, status=PoolStatus.Active, total_members=NEW_POOL_INTAKE),
    )
    _logger.info("manual_create_pool: created '%s' (id=%d).", pool_name, new_pool.id)

    for member in paid_waitlist[:NEW_POOL_INTAKE]:
        _activate_user(db, member, new_pool, phase="MANUAL")

    crud_pool.update_pool(db, new_pool.id, PoolUpdate(total_members=NEW_POOL_INTAKE))
    db.commit()
    _logger.info(
        "manual_create_pool: '%s' populated with %d member(s).",
        pool_name, NEW_POOL_INTAKE,
    )
    return new_pool
