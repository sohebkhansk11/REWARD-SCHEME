"""
Waitlist Services — Bulk Double-FIFO Auto-Refill Engine
=======================================================
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
  fill_pool_vacancies(db)      → calls assign_waitlist_to_pools; returns Phase 1 list
  check_and_scale_waitlist(db) → calls assign_waitlist_to_pools; returns Phase 2 Pool

Phase 1 — Bulk Double-FIFO
--------------------------
  Pool  priority : Pool.created_at  ASC  (oldest under-capacity pool filled first)
  Member priority: User.join_date   ASC  (longest-waiting Waitlist user first)
  Execution      : ONE GROUP BY query for member counts; ONE UPDATE…WHERE id IN(…)
                   per pool — eliminates per-user ORM round-trips.

Phase 2 — Bulk Auto-Scale
-------------------------
  pools_to_make = remaining_waitlist // POOL_CAPACITY
  All new pools are bulk-inserted in a single sa_insert(Pool) call.
  All user assignments are bulk-updated in one UPDATE per new pool.

Phase 3 — Condensation (safeguarded)
--------------------------------------
  ONLY fires when wl_remaining == 0 AND pools with < 12 members still exist.
"""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, insert as sa_insert
from sqlalchemy.orm import Session

from app.core.config import WAITLIST_TRIGGER, NEW_POOL_INTAKE, POOL_CAPACITY  # noqa: F401
from app.services.ai_quant_engine import determine_reserve_multiplier
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

def _pool_name_for_index(n: int) -> str:
    """Convert a zero-based pool index to Pool A / B / … / Z / AA / …

    Examples:
      0  → "Pool A"
      25 → "Pool Z"
      26 → "Pool AA"
    """
    letters = ""
    while True:
        letters = chr(65 + n % 26) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return f"Pool {letters}"


def _next_pool_name(db: Session) -> str:
    """Generate the next sequential pool name based on the current total pool count."""
    return _pool_name_for_index(db.query(Pool).count())


def _activate_user(db: Session, user: User, pool: Pool, phase: str) -> None:
    """
    State-machine transition: Waitlist → Active pool.

    Sets: status=Active, pool_id=pool.id, level=1, payment=Paid.
    Credits Rule-39 referral bonus if the user was referred.
    Caller must db.commit() after processing a complete batch.

    NOTE: This helper is used only by manual_create_pool (admin-triggered, low volume).
          The main assign_waitlist_to_pools function uses bulk SQL updates instead.
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
# MASTER FUNCTION — Bulk Double-FIFO Auto-Refill Engine
# ─────────────────────────────────────────────────────────────────────────────

def assign_waitlist_to_pools(db: Session) -> dict:
    """
    Bulk Double-FIFO Auto-Refill Engine — single source of truth for all
    waitlist-to-pool assignment logic.

    ┌─ Phase 1: Bulk Refill Existing Pools ────────────────────────────────────┐
    │  1. One GROUP BY query counts active members per pool (no N+1 queries).  │
    │  2. One Waitlist query fetches up to total_vacancies users (FIFO).       │
    │  3. Python FIFO distribution assigns users to pools in memory.           │
    │  4. One UPDATE…WHERE id IN(…) per pool — replaces per-user ORM calls.   │
    │  5. Post-commit pool count sync + Paused → Active restoration.           │
    └───────────────────────────────────────────────────────────────────────────┘
    ┌─ Phase 2: Bulk Auto-Scale New Pools ─────────────────────────────────────┐
    │  pools_to_make = remaining_waitlist // POOL_CAPACITY                     │
    │  Bulk sa_insert(Pool) creates all new pools in one round-trip.           │
    │  Per-pool bulk UPDATE assigns users into each new pool.                  │
    └───────────────────────────────────────────────────────────────────────────┘
    ┌─ Phase 3: Condensation (safeguarded) ────────────────────────────────────┐
    │  ONLY fires when paid waitlist == 0 AND under-capacity pools still exist.│
    │  Harvests newest full Active pools → oldest under-capacity pools.        │
    │  STRICTLY preserves current_level, weekly_payment_status, join_date.    │
    └───────────────────────────────────────────────────────────────────────────┘
    """
    _logger.info("══ assign_waitlist_to_pools — Bulk Double-FIFO engine START ══")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1 — Bulk refill existing under-capacity pools
    # ─────────────────────────────────────────────────────────────────────────

    # 1a. All Active AND Paused_Awaiting_Members pools, oldest first.
    active_pools: list[Pool] = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .order_by(Pool.created_at.asc())
        .all()
    )

    # 1b. Count active members per pool in ONE GROUP BY query (eliminates N+1).
    pool_ids = [p.id for p in active_pools]
    live_counts: dict[int, int] = {}
    if pool_ids:
        for row in (
            db.query(User.current_pool_id, func.count(User.id))
            .filter(
                User.current_pool_id.in_(pool_ids),
                User.status == UserStatus.Active,
            )
            .group_by(User.current_pool_id)
            .all()
        ):
            live_counts[row[0]] = row[1]

    # Build (pool, current_actual, vacancy) triples for under-capacity pools.
    pools_needing_fill: list[tuple[Pool, int, int]] = []
    for p in active_pools:
        actual = live_counts.get(p.id, 0)
        vac    = POOL_CAPACITY - actual
        if vac > 0:
            pools_needing_fill.append((p, actual, vac))

    total_vacancies = sum(v for _, _, v in pools_needing_fill)
    _logger.info(
        "Phase 1: %d pool(s) under capacity — %d vacancy slot(s).",
        len(pools_needing_fill), total_vacancies,
    )

    phase1_assigned     = 0
    phase1_pool_changes: list[dict] = []

    if pools_needing_fill and total_vacancies > 0:
        # 1c. Fetch exactly total_vacancies oldest paid Waitlist members.
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

        queue               = list(candidates)
        pool_assignments:   dict[int, list[int]] = {}   # pool_id → list of user IDs
        referrals_p1:       list[int]            = []   # referrer IDs to credit later

        # 1d. Python FIFO distribution — oldest pool first, oldest user first.
        for pool, actual, vacancies in pools_needing_fill:
            if not queue:
                _logger.info(
                    "Phase 1: Waitlist exhausted — %s still needs %d slot(s).",
                    pool.name, vacancies,
                )
                break

            to_assign = min(vacancies, len(queue))
            batch     = queue[:to_assign]
            queue     = queue[to_assign:]

            pool_assignments[pool.id] = [u.id for u in batch]
            new_total = actual + to_assign
            phase1_assigned += to_assign

            phase1_pool_changes.append({
                "pool_id":     pool.id,
                "pool_name":   pool.name,
                "filled":      to_assign,
                "total_after": new_total,
            })

            # Collect referrer IDs BEFORE the bulk UPDATE (objects still fresh in memory)
            for u in batch:
                if u.referred_by_user_id:
                    referrals_p1.append(u.referred_by_user_id)

            _logger.info(
                "Phase 1: %s  %d/12 → %d/12  (+%d, bulk).",
                pool.name, actual, new_total, to_assign,
            )

        if pool_assignments:
            # 1e. Bulk UPDATE — ONE SQL UPDATE per pool instead of per-user ORM calls.
            #     synchronize_session=False: we commit immediately after and expire
            #     the session, so ORM cache consistency is not a concern.
            for pool_id, user_ids in pool_assignments.items():
                db.query(User).filter(User.id.in_(user_ids)).update(
                    {
                        "current_pool_id":       pool_id,
                        "status":                UserStatus.Active,
                        "current_level":         1,
                        "weekly_payment_status": WeeklyPaymentStatus.Paid,
                    },
                    synchronize_session=False,
                )
            db.commit()

            # 1f. Sync pool.total_members; restore Paused → Active if now full.
            #     total_after was computed from live GROUP BY count + to_assign,
            #     so it is guaranteed accurate for the current transaction.
            for change in phase1_pool_changes:
                pool_obj = db.query(Pool).filter(Pool.id == change["pool_id"]).first()
                if not pool_obj:
                    continue
                pool_obj.total_members = change["total_after"]
                if (
                    pool_obj.status == PoolStatus.Paused_Awaiting_Members
                    and change["total_after"] >= POOL_CAPACITY
                ):
                    pool_obj.status = PoolStatus.Active
                    _logger.info(
                        "[P1] %s → Active (refilled to %d/12).",
                        pool_obj.name, change["total_after"],
                    )
            db.commit()

            # 1g. Referral bonuses — processed after commit so DB state is consistent.
            #     referrals_p1 contains raw integer IDs collected before the bulk UPDATE.
            if referrals_p1:
                from app.services.draw import _credit_referral_bonus
                for referrer_id in referrals_p1:
                    _credit_referral_bonus(db, referrer_id)
                db.commit()

    _logger.info(
        "Phase 1 COMPLETE — %d user(s) assigned across %d pool(s).",
        phase1_assigned, len(phase1_pool_changes),
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — Bulk auto-scale new pools
    # ─────────────────────────────────────────────────────────────────────────

    phase2_pool_name:   str | None = None
    phase2_pools_count: int        = 0
    phase2_assigned:    int        = 0

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

        # ── AI Quant Engine gate ──────────────────────────────────────────────
        # The admin threshold is the FLOOR.  The AI multiplier scales the
        # dynamic reserve needed before any of the waitlist is "available"
        # for spawning.  This prevents the system from exhausting the waitlist
        # during a Dry Phase or Flash Flood.
        _ai_multiplier, _ai_scenario = determine_reserve_multiplier(db)
        # Burn rate counts Active-only (paused pools don't exit members).
        # Reserve capacity must protect ALL operational pools (Active + Paused)
        # because paused pools still hold members that need replacement coverage.
        _active_pool_count = (
            db.query(func.count(Pool.id))
            .filter(Pool.status == PoolStatus.Active)
            .scalar()
        ) or 0
        _operational_pool_count = (
            db.query(func.count(Pool.id))
            .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
            .scalar()
        ) or 0
        _dynamic_reserve     = int(_operational_pool_count * POOL_CAPACITY * _ai_multiplier)
        _available_to_spawn  = max(0, remaining - _dynamic_reserve)
        _logger.info(
            "Phase 2 AI: scenario=%-20s  multiplier=%.2f  "
            "active_pools=%d  operational_pools=%d  dynamic_reserve=%d  "
            "waitlist=%d  available_to_spawn=%d  admin_floor=%d",
            _ai_scenario, _ai_multiplier, _active_pool_count, _operational_pool_count,
            _dynamic_reserve, remaining, _available_to_spawn, threshold,
        )

        if _available_to_spawn >= threshold:
            # Create as many FULL pools as the AI-available portion allows.
            # pools_to_make * POOL_CAPACITY <= _available_to_spawn (every pool is full).
            pools_to_make = _available_to_spawn // POOL_CAPACITY

            if pools_to_make > 0:
                base_count = db.query(Pool).count()   # current total pool count
                now        = datetime.now(timezone.utc)

                # Generate sequential pool names upfront.
                pool_names = [
                    _pool_name_for_index(base_count + i) for i in range(pools_to_make)
                ]

                # Bulk INSERT all new pools — one round-trip instead of N create_pool() calls.
                # Explicit created_at offsets guarantee deterministic ordering for Phase 3.
                pool_rows = [
                    {
                        "name":          pool_names[i],
                        "status":        PoolStatus.Active,
                        "total_members": POOL_CAPACITY,
                        "created_at":    now + timedelta(microseconds=i),
                    }
                    for i in range(pools_to_make)
                ]
                db.execute(sa_insert(Pool), pool_rows)
                db.flush()   # push inserts so we can SELECT the auto-generated IDs

                # Fetch new pool IDs in creation order.
                new_pools = (
                    db.query(Pool.id, Pool.name)
                    .filter(Pool.name.in_(pool_names))
                    .order_by(Pool.created_at.asc())
                    .all()
                )

                # Fetch exactly the waitlist users we need (FIFO order).
                users_needed = pools_to_make * POOL_CAPACITY
                new_members: list[User] = (
                    db.query(User)
                    .filter(
                        User.status == UserStatus.Waitlist,
                        User.weekly_payment_status == WeeklyPaymentStatus.Paid,
                    )
                    .order_by(User.join_date.asc())
                    .limit(users_needed)
                    .all()
                )

                # Distribute users to new pools in Python (FIFO).
                p2_assignments: dict[int, list[int]] = {}
                referrals_p2:   list[int]            = []

                for i, (pool_id, _pool_name) in enumerate(new_pools):
                    start = i * POOL_CAPACITY
                    end   = start + POOL_CAPACITY
                    batch = new_members[start:end]
                    if not batch:
                        break
                    p2_assignments[pool_id] = [u.id for u in batch]
                    for u in batch:
                        if u.referred_by_user_id:
                            referrals_p2.append(u.referred_by_user_id)
                    _logger.info(
                        "Phase 2: %s ← %d user(s) (bulk).", pool_names[i], len(batch)
                    )

                # Bulk UPDATE users into their new pools.
                for pool_id, user_ids in p2_assignments.items():
                    if not user_ids:
                        continue
                    db.query(User).filter(User.id.in_(user_ids)).update(
                        {
                            "current_pool_id":       pool_id,
                            "status":                UserStatus.Active,
                            "current_level":         1,
                            "weekly_payment_status": WeeklyPaymentStatus.Paid,
                        },
                        synchronize_session=False,
                    )
                db.commit()

                # Referral bonuses for Phase 2 activations.
                if referrals_p2:
                    from app.services.draw import _credit_referral_bonus
                    for referrer_id in referrals_p2:
                        _credit_referral_bonus(db, referrer_id)
                    db.commit()

                phase2_pool_name   = pool_names[0] if pool_names else None
                phase2_pools_count = pools_to_make
                phase2_assigned    = sum(len(ids) for ids in p2_assignments.values())

                _logger.info(
                    "Phase 2 COMPLETE — %d pool(s) bulk-created  |  %d user(s) assigned.",
                    pools_to_make, phase2_assigned,
                )
        else:
            _logger.info(
                "Phase 2: Waitlist (%d) below threshold (%d) — no new pool created.",
                remaining, threshold,
            )

    _logger.info(
        "Phase 1+2 DONE  |  P1: %d assigned  |  P2: %d pool(s) +%d users"
        " — running Phase 3 check...",
        phase1_assigned, phase2_pools_count, phase2_assigned,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3 — Dynamic Inter-Pool Condensation Engine
    # ─────────────────────────────────────────────────────────────────────────
    #
    # SAFEGUARDS — Phase 3 ONLY runs when ALL of the following hold:
    #   (a) The paid Waitlist is fully exhausted (wl_remaining == 0).
    #   (b) At least one pool still has < POOL_CAPACITY members.
    #   (c) The draw engine lock is NOT active (T-2H through T+0H:10 window).
    #       Dissolving pools during preparation or draw execution would corrupt
    #       the SDE session plan and pool routing tables.
    #
    # Per-pool guard (inside the source-pool loop):
    #   Any source pool whose contains_flagged_l4=True is IMMUNE to condensation.
    #   An L4-flagged pool must remain intact until SDE processes it this week.
    #
    # Mechanism when triggered:
    #   Target pools  — under-capacity Active/Paused pools, created_at ASC
    #   Source pools  — full Active pools NOT in target set AND not L4-flagged, created_at DESC
    #   Transfer      — FIFO within source (oldest member transferred first)
    #   Preservation  — current_level, weekly_payment_status, join_date NEVER altered

    phase3_transfers: int        = 0
    phase3_events:    list[dict] = []
    phase3_dissolved: list[str]  = []

    # ── Safeguard (c): draw window lock check (BUG 9 FIX) ────────────────────
    # Defer the import to avoid circular dependency at module load time.
    from app.models.system_lock import SystemLock
    from datetime import datetime, timezone as _tz
    draw_lock = (
        db.query(SystemLock)
        .filter(
            SystemLock.lock_name == "draw_engine",
            SystemLock.expires_at > datetime.now(_tz.utc),
        )
        .first()
    )
    if draw_lock:
        _logger.info(
            "Phase 3: SKIPPED — draw engine lock active (held by '%s', expires %s). "
            "Condensation is blocked during the T-2H → T+0H:10 draw window.",
            draw_lock.held_by,
            draw_lock.expires_at.isoformat(),
        )
        # Return early — Phase 1/2 results preserved, Phase 3 zeros out
        return {
            "phase1_assigned":     phase1_assigned,
            "phase1_pool_changes": phase1_pool_changes,
            "phase2_pool_created": phase2_pool_name,
            "phase2_pools_count":  phase2_pools_count,
            "phase2_assigned":     phase2_assigned,
            "phase3_transfers":    0,
            "phase3_events":       [],
            "phase3_dissolved":    [],
        }

    # ── Safeguard (a): check paid waitlist count ──────────────────────────────
    wl_remaining: int = (
        db.query(User)
        .filter(
            User.status == UserStatus.Waitlist,
            User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        )
        .count()
    )

    if wl_remaining > 0:
        _logger.info(
            "Phase 3: SKIPPED — %d paid Waitlist user(s) still pending assignment. "
            "Condensation only runs when the waitlist is fully exhausted.",
            wl_remaining,
        )
    else:
        # Re-query pools to get the post-Phase-1/2 state
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
            _logger.info(
                "Phase 3: All pools at capacity after Phase 1/2 — condensation not needed."
            )
        else:
            target_ids: set[int] = {pool.id for pool, _ in p3_targets}

            # Source pools: Active pools NOT in target set AND not L4-flagged.
            # SDE IMMUNITY (BUG 2 / CONDENSATION GUARD):
            #   Any pool with contains_flagged_l4=True must not be used as a
            #   condensation source.  Dissolving such a pool would scatter the
            #   L4 member(s) into random pools, breaking the SDE session plan
            #   that was built at T-2H.
            source_pools: list[Pool] = (
                db.query(Pool)
                .filter(
                    Pool.status == PoolStatus.Active,
                    Pool.id.notin_(target_ids),
                    Pool.contains_flagged_l4 == False,   # noqa: E712
                )
                .order_by(Pool.created_at.desc())
                .all()
            )

            if not source_pools:
                _logger.info(
                    "Phase 3: %d pool(s) under capacity but no full source pools available "
                    "(all active pools are under capacity — condensation cannot proceed).",
                    len(p3_targets),
                )
            else:
                # Cache live member counts per source pool to avoid N+1 queries
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
                        f"{sp.name}({src_counts[sp.id]}/12)" for sp in source_pools
                    ),
                )

                _MAX_P3_ITERS = 10_000   # explicit safety ceiling (#189)
                src_idx  = 0             # rolling pointer into source_pools list
                _p3_iter = 0             # iteration guard counter

                for target_pool, target_actual in p3_targets:
                    vacancies = POOL_CAPACITY - target_actual

                    while vacancies > 0 and src_idx < len(source_pools) and _p3_iter < _MAX_P3_ITERS:
                        _p3_iter += 1
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
                            # ── LEVEL & STATE PRESERVATION (CRITICAL) ──────────
                            # Only pool_id and journey counter change.
                            # current_level, weekly_payment_status, join_date: NEVER touched.
                            member.current_pool_id           = target_pool.id
                            member.dynamic_merges_experienced = (
                                (member.dynamic_merges_experienced or 0) + 1
                            )
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
                            source_pool.status        = PoolStatus.Merged_Dissolved
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
                            "[P3] %s still needs %d member(s) — all source pools exhausted.",
                            target_pool.name, vacancies,
                        )

                if _p3_iter >= _MAX_P3_ITERS:
                    _logger.error(
                        "Phase 3: safety limit reached (%d iterations) — "
                        "condensation halted early to prevent runaway loop.",
                        _MAX_P3_ITERS,
                    )

                # ── Persist + sync all affected pools ──────────────────────────
                if phase3_transfers:
                    db.flush()   # push all pool_id changes to DB before counting

                    all_affected_ids = target_ids | {sp.id for sp in source_pools}
                    for pid in all_affected_ids:
                        pool_obj: Pool | None = (
                            db.query(Pool).filter(Pool.id == pid).first()
                        )
                        if not pool_obj:
                            continue

                        if pool_obj.status == PoolStatus.Merged_Dissolved:
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

                        # Restore Paused → Active if condensation filled it to capacity
                        if (
                            pool_obj.status == PoolStatus.Paused_Awaiting_Members
                            and new_actual >= POOL_CAPACITY
                        ):
                            pool_obj.status = PoolStatus.Active
                            _logger.info(
                                "[P3] %s restored from Paused_Awaiting_Members → Active (%d/12).",
                                pool_obj.name, new_actual,
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
        "|  P1: %d  |  P2: %d pool(s) +%d  |  P3: %d xfers / %d dissolved ══",
        phase1_assigned,
        phase2_pools_count, phase2_assigned,
        phase3_transfers, len(phase3_dissolved),
    )

    return {
        "phase1_assigned":     phase1_assigned,
        "phase1_pool_changes": phase1_pool_changes,
        "phase2_pool_created": phase2_pool_name,       # first pool name (backward compat)
        "phase2_pools_count":  phase2_pools_count,     # total new pools created
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
    newly created pool (first Phase 2 result) or None.

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
