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
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# LEVER 3b — compute_dynamic_reserve is the shared gated-reserve helper; importing
# it keeps the Phase-2 spawn gate below in lockstep with admin telemetry.
from app.services.ai_quant_engine import determine_reserve_multiplier, compute_dynamic_reserve
from app.core.pool_settings import get_auto_pool_creation
from app.crud import user as crud_user, pool as crud_pool
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.schemas.pool import PoolCreate, PoolUpdate
from app.schemas.user import UserUpdate
from app.services.settings import get_pool_threshold, get_adaptive_threshold

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

# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Added user_prefix parameter — when set (simulation only), all Waitlist user
# queries are scoped to usernames matching the prefix. Default None = no filter
# = production behaviour unchanged. Without this, the simulation was fetching
# and processing 2000+ real Waitlist users every week, causing a 10+ min hang.
def assign_waitlist_to_pools(db: Session, *, user_prefix: str | None = None) -> dict:
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
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        _p1_filters = [
            User.status == UserStatus.Waitlist,
            User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        ]
        if user_prefix:
            _p1_filters.append(User.username.like(f"{user_prefix}%"))
        candidates: list[User] = (
            db.query(User)
            .filter(*_p1_filters)
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
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        _p1_join_records:   list[tuple]          = []   # (uid, username, pool_id, pool_name)

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

            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Forensic: capture (id, username) NOW while objects are live in memory —
            # the bulk UPDATE below carries synchronize_session=False so the ORM cache
            # is expired afterward. We emit the join events after the commit succeeds.
            for u in batch:
                _p1_join_records.append((u.id, u.username, pool.id, pool.name))

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

            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Forensic: one member_joined event per filled vacancy (Phase 1 refill).
            try:
                from app.services import forensic as _forensic
                if _forensic.is_on():
                    for _uid, _uname, _pid, _pname in _p1_join_records:
                        _forensic.member_joined(
                            _uid, _uname, _pid, level=1,
                            payload={"phase": "P1_vacancy_fill", "pool_name": _pname},
                            message=f"{_uname} joined pool '{_pname}' @L1 (vacancy fill)",
                        )
            except Exception:
                pass

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
        # POINT 7 FIX: Use adaptive threshold (LPI-pressure-adjusted) instead of
        # the fixed base threshold.  This prevents the mathematical deadlock where
        # growth_rate ≤ pool_consumption_rate means WL never reaches 24.
        # At LPI ≥ 50%, threshold auto-reduces to POOL_CAPACITY (12).
        threshold = get_adaptive_threshold(db)   # was: get_pool_threshold(db)
        base_threshold = get_pool_threshold(db)
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        _p2_count_filters = [
            User.status == UserStatus.Waitlist,
            User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        ]
        if user_prefix:
            _p2_count_filters.append(User.username.like(f"{user_prefix}%"))
        remaining: int = (
            db.query(User)
            .filter(*_p2_count_filters)
            .count()
        )
        _logger.info(
            "Phase 2: remaining paid Waitlist = %d  |  effective_threshold = %d  "
            "(base=%d — adaptive reduction applied if different)",
            remaining, threshold, base_threshold,
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
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # LEVER 3b — gated reserve: healthy scenarios (SUSTAINABLE_WAVE /
        # BOOM_GOLDEN_CROSS) hold a lean 4/pool floor so live pools are not starved
        # of supply; every other scenario keeps the protective × 12 × multiplier
        # solvency-defense reserve. Single source of truth in ai_quant_engine.
        _dynamic_reserve     = compute_dynamic_reserve(
            _operational_pool_count, _ai_multiplier, _ai_scenario
        )
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
                        "name":                   pool_names[i],
                        "status":                 PoolStatus.Active,
                        "total_members":          POOL_CAPACITY,
                        "created_at":             now + timedelta(microseconds=i),
                        # CRITICAL: must be explicitly False in bulk INSERT.
                        # SQLite uses server_default="false" (the string 'false') when
                        # this column is omitted.  SQLAlchemy Boolean reads 'false' via
                        # Python's bool() → True (non-empty string is truthy).
                        # That causes execute_weekly_draw to sde_skip ALL new pools
                        # (draw_completed_this_week check at line 677), producing 0
                        # draws every week until post_draw_cleanup corrects the flag.
                        "draw_completed_this_week": False,
                        "pool_draw_type":           None,
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
                # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                users_needed = pools_to_make * POOL_CAPACITY
                _p2_member_filters = [
                    User.status == UserStatus.Waitlist,
                    User.weekly_payment_status == WeeklyPaymentStatus.Paid,
                ]
                if user_prefix:
                    _p2_member_filters.append(User.username.like(f"{user_prefix}%"))
                new_members: list[User] = (
                    db.query(User)
                    .filter(*_p2_member_filters)
                    .order_by(User.join_date.asc())
                    .limit(users_needed)
                    .all()
                )

                # Distribute users to new pools in Python (FIFO).
                p2_assignments: dict[int, list[int]] = {}
                referrals_p2:   list[int]            = []
                # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                _p2_join_records: list[tuple] = []   # (uid, username, pool_id, pool_name)
                _p2_pool_created: list[tuple] = []   # (pool_id, pool_name, member_count)

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
                        # Capture (id, username) live — bulk UPDATE below expires the cache.
                        _p2_join_records.append((u.id, u.username, pool_id, _pool_name))
                    _p2_pool_created.append((pool_id, _pool_name, len(batch)))
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

                # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # Forensic: pool_created per new pool + member_joined per founding member.
                try:
                    from app.services import forensic as _forensic
                    if _forensic.is_on():
                        for _pid, _pname, _cnt in _p2_pool_created:
                            _forensic.pool_event(
                                "pool_created", _pid, ref=_pname, severity="notice",
                                after={"member_count": _cnt, "status": "Active"},
                                payload={"phase": "P2_new_pool"},
                                message=f"POOL CREATED: '{_pname}' (id={_pid}) with {_cnt} founding member(s)",
                            )
                        for _uid, _uname, _pid, _pname in _p2_join_records:
                            _forensic.member_joined(
                                _uid, _uname, _pid, level=1,
                                payload={"phase": "P2_new_pool", "pool_name": _pname},
                                message=f"{_uname} joined NEW pool '{_pname}' @L1",
                            )
                except Exception:
                    pass

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
    draw_lock = (
        db.query(SystemLock)
        .filter(
            SystemLock.lock_name == "draw_engine",
            SystemLock.expires_at > datetime.now(timezone.utc),
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
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    _p3_wl_filters = [
        User.status == UserStatus.Waitlist,
        User.weekly_payment_status == WeeklyPaymentStatus.Paid,
    ]
    if user_prefix:
        _p3_wl_filters.append(User.username.like(f"{user_prefix}%"))
    wl_remaining: int = (
        db.query(User)
        .filter(*_p3_wl_filters)
        .count()
    )

    if wl_remaining > 0:
        _logger.info(
            "Phase 3: SKIPPED — %d paid Waitlist user(s) still pending assignment. "
            "Condensation only runs when the waitlist is fully exhausted.",
            wl_remaining,
        )
    else:
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # LEVER 3a — Phase 3 condensation core extracted into _condense_pools_once()
        # so this waitlist-exhaustion-gated Phase 3 and the new proactive every-week
        # Pool Merger Engine (run_pool_merger_engine) share ONE implementation.  The
        # wl_remaining gate and the draw-engine SystemLock check ABOVE remain here
        # (Phase-3 semantics); the merger calls the same core at its own controlled
        # in-draw point, deliberately without those gates.
        _p3 = _condense_pools_once(db)
        phase3_transfers = _p3["transfers"]
        phase3_events    = _p3["events"]
        phase3_dissolved = _p3["dissolved"]

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
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# LEVER 3a — Inter-Pool Condensation core + proactive Pool Merger Engine.
# ─────────────────────────────────────────────────────────────────────────────

def _condense_pools_once(db: Session) -> dict:
    """
    Shared inter-pool condensation core — TWO-POINTER COMPACTION
    (donor → receiver → dissolve).

    SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    MERGER REWRITE (Jun-19 dual-tick work).  The previous model could only SOURCE
    members out of FULL 12/12 non-flagged pools into under-capacity targets, so it
    was structurally inert post-draw (every pool sits at 10/12 → zero full sources →
    nothing ever merged; two half-empty pools could never consolidate because both
    were targets and neither a source).  This rewrite compacts over the set of ALL
    non-flagged UNDER-CAPACITY pools with a stable two-pointer sweep:

        receiver = OLDEST under-cap pool  (created_at ASC, lo pointer)
        donor    = NEWEST under-cap pool  (created_at DESC, hi pointer)

    Members move FIFO out of the donor into the receiver until the receiver hits
    POOL_CAPACITY; emptied donors are dissolved (status = Merged_Dissolved,
    total_members = 0).  Paused_Awaiting_Members → Active is restored when a pool
    refills to capacity, and pool.total_members is kept in sync.

      [7,7]       → [12,2]            (one pool now drawable)
      [10,10,2]   → [12,10] + dissolve the emptied 2-pool
      [10,12]     → [10,12] unchanged (full pool excluded → no churn)

    MONEY-GRADE PRESERVATION: every moved member keeps current_level,
    weekly_payment_status, join_date and ALL sde_* fields untouched — ONLY
    current_pool_id changes and dynamic_merges_experienced increments.  No pool ever
    exceeds POOL_CAPACITY (take = min(receiver-vacancy, donor-count)).

    SDE IMMUNITY: a pool with contains_flagged_l4 == True is NEVER a donor OR a
    receiver, so an L4 member is never scattered out of (nor diluted into) the pool
    its SDE session was planned against.  Flagged pools draw via SDE staging
    regardless of fullness, so their exclusion never starves them.

    This is the single implementation shared by:
      • Phase 3 inside assign_waitlist_to_pools (gated on an exhausted waitlist +
        the draw-engine SystemLock check), and
      • run_merger_refill_converge / run_pool_merger_engine (proactive, dual-tick:
        T-2H prep STEP 3b and post-draw T+5M).
    The caller owns the gating decisions and the surrounding transaction; this core
    flushes and commits only when it actually performs transfers.

    Returns {transfers, events, dissolved}.
    """
    phase3_transfers: int        = 0
    phase3_events:    list[dict] = []
    phase3_dissolved: list[str]  = []

    # ── Candidate set: every non-L4-flagged Active/Paused pool, oldest-first ───────
    # Stable sort (created_at, then id) makes the two-pointer sweep deterministic.
    candidates: list[Pool] = (
        db.query(Pool)
        .filter(
            Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]),
            Pool.contains_flagged_l4 == False,   # noqa: E712  (SDE immunity)
        )
        .order_by(Pool.created_at.asc(), Pool.id.asc())
        .all()
    )

    # Live Active-member count per candidate — single pass, no N+1 inside the loop.
    counts: dict[int, int] = {
        p.id: (
            db.query(User)
            .filter(User.current_pool_id == p.id, User.status == UserStatus.Active)
            .count()
        )
        for p in candidates
    }

    # Compactable = under-capacity candidates only (0-member shells included so they
    # are dissolved away).  A full 12/12 pool is excluded → never churned.
    compactable: list[Pool] = [p for p in candidates if counts[p.id] < POOL_CAPACITY]

    if len(compactable) < 2:
        _logger.info(
            "Condensation: %d under-capacity non-flagged pool(s) — nothing to compact "
            "(need ≥2).",
            len(compactable),
        )
        return {"transfers": 0, "events": [], "dissolved": []}

    # Every pool we may touch (for the post-pass total_members re-sync below).
    affected_ids: set[int] = {p.id for p in compactable}

    _logger.info(
        "Condensation (two-pointer compaction): %d under-capacity non-flagged "
        "pool(s): %s",
        len(compactable),
        ", ".join(f"{p.name}({counts[p.id]}/12)" for p in compactable),
    )

    _MAX_P3_ITERS = 10_000          # explicit safety ceiling (#189)
    lo, hi        = 0, len(compactable) - 1
    _p3_iter      = 0               # iteration guard counter

    # ── Two-pointer sweep: pack the oldest pool from the newest, dissolve emptied ──
    while lo < hi and _p3_iter < _MAX_P3_ITERS:
        _p3_iter += 1
        recv  = compactable[lo]     # receiver — oldest under-cap pool
        donor = compactable[hi]     # donor    — newest under-cap pool

        rvac = POOL_CAPACITY - counts[recv.id]
        if rvac <= 0:               # receiver already full → advance receiver
            lo += 1
            continue
        if counts[donor.id] == 0:   # donor already drained → dissolve + advance donor
            donor.status        = PoolStatus.Merged_Dissolved
            donor.total_members = 0
            phase3_dissolved.append(donor.name)
            hi -= 1
            continue

        take = min(rvac, counts[donor.id])

        # FIFO within donor: move the most-senior (oldest join_date) members first.
        transfer_batch: list[User] = (
            db.query(User)
            .filter(
                User.current_pool_id == donor.id,
                User.status == UserStatus.Active,
            )
            .order_by(User.join_date.asc())
            .limit(take)
            .all()
        )

        for member in transfer_batch:
            # ── LEVEL & STATE PRESERVATION (CRITICAL) ──────────────────────────
            # ONLY pool_id and journey counter change.  current_level,
            # weekly_payment_status, join_date, sde_* : NEVER touched.
            member.current_pool_id            = recv.id
            member.dynamic_merges_experienced = (
                (member.dynamic_merges_experienced or 0) + 1
            )
            _logger.info(
                "[MERGE-XFER]  @%-20s  (id=%5d  L%d  %s)  %s → %s",
                member.username,
                member.id,
                member.current_level,
                member.weekly_payment_status.value,
                donor.name,
                recv.name,
            )

        moved = len(transfer_batch)
        counts[recv.id]  += moved
        counts[donor.id] -= moved
        phase3_transfers += moved

        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # MONEY-GRADE ORPHAN-LEAK FIX (Jun-21).  The SessionLocal is autoflush=False
        # (app/database.py:69), so the transfer-batch SELECT above
        # (current_pool_id == donor.id, ORDER BY join_date ASC, LIMIT take) reads the
        # *DB* state, NOT the pending in-session reassignments.  When a single donor
        # feeds MORE THAN ONE receiver across consecutive iterations (receiver fills
        # before the donor empties), the next iteration's SELECT re-reads the donor's
        # rows BEFORE the prior batch's `current_pool_id = recv.id` is visible — so it
        # re-selects the SAME senior members (oldest join_date first) and moves them
        # again, while the donor's *junior* members are never selected.  The Python
        # `counts[donor]` counter still ticks to 0 → the pool is dissolved (lines 777 /
        # 822) while those unselected juniors are STILL physically inside it →
        # permanently ORPHANED Active members (status=Active, current_pool_id → a
        # Merged_Dissolved pool, dynamic_merges_experienced=0), invisible to every
        # pool-based view yet still counted Active.  Flushing the batch NOW makes the
        # reassignments visible to the very next SELECT, so each member is selected and
        # moved exactly once and a pool is dissolved only when it is truly empty.
        # One transaction still (commit stays at the end); flush only pushes the
        # pending pool_id changes so the read-after-write is correct.
        db.flush()

        donor_dissolved = (counts[donor.id] == 0)
        if donor_dissolved:
            donor.status        = PoolStatus.Merged_Dissolved
            donor.total_members = 0
            phase3_dissolved.append(donor.name)

        condensation_msg = (
            f"Condensation Event: Moved {moved} member(s) from "
            f"{donor.name} to {recv.name}."
            + (f" {donor.name} dissolved." if donor_dissolved else "")
        )
        _logger.info("[MERGE] %s", condensation_msg)

        phase3_events.append({
            "from_pool":     donor.name,
            "to_pool":       recv.name,
            "members_moved": moved,
            "dissolved":     donor_dissolved,
        })

        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # FORENSIC — the donor↔receiver merger "trigger moment" the admin asked to
        # see. One event per transfer batch (+ a dissolve event when the donor empties).
        # Toggle-gated + failure-isolated; no-op zero-overhead when the debugger is OFF.
        try:
            from app.services import forensic as _forensic
            _forensic.merger_event(
                "members_merged", pool_id=recv.id, ref=recv.name, severity="notice",
                before={"receiver_count": counts[recv.id] - moved, "donor_count": counts[donor.id] + moved},
                after={"receiver_count": counts[recv.id], "donor_count": counts[donor.id]},
                payload={"from_pool": donor.name, "from_pool_id": donor.id,
                         "to_pool": recv.name, "members_moved": moved,
                         "donor_dissolved": donor_dissolved},
                message=(f"MERGER: {moved} member(s) {donor.name}→{recv.name}"
                         + (f" · {donor.name} DISSOLVED" if donor_dissolved else "")))
            if donor_dissolved:
                _forensic.merger_event(
                    "pool_dissolved", pool_id=donor.id, ref=donor.name, severity="notice",
                    before={"members": moved}, after={"members": 0, "status": "Merged_Dissolved"},
                    payload={"absorbed_into": recv.name, "absorbed_into_id": recv.id},
                    message=f"POOL DISSOLVED: {donor.name} emptied into {recv.name}")
        except Exception:
            pass

        # Advance the pointers that are now exhausted.  At least one always advances
        # (take = min(rvac, donor) ⇒ either recv fills or donor empties), guaranteeing
        # termination independent of the _MAX_P3_ITERS backstop.
        if donor_dissolved:
            hi -= 1
        if counts[recv.id] >= POOL_CAPACITY:
            lo += 1

    if _p3_iter >= _MAX_P3_ITERS:
        _logger.error(
            "Condensation: safety limit reached (%d iterations) — "
            "halted early to prevent runaway loop.",
            _MAX_P3_ITERS,
        )

    # ── Persist + sync all affected pools ─────────────────────────────────────
    if phase3_transfers:
        db.flush()   # push all pool_id changes to DB before counting

        for pid in affected_ids:
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

            # Restore Paused → Active if condensation filled it to capacity.
            if (
                pool_obj.status == PoolStatus.Paused_Awaiting_Members
                and new_actual >= POOL_CAPACITY
            ):
                pool_obj.status = PoolStatus.Active
                _logger.info(
                    "[MERGE] %s restored from Paused_Awaiting_Members → Active (%d/12).",
                    pool_obj.name, new_actual,
                )

        db.commit()

    _logger.info(
        "Condensation COMPLETE — %d member(s) transferred | %d event(s) | "
        "dissolved: [%s]",
        phase3_transfers,
        len(phase3_events),
        ", ".join(phase3_dissolved) if phase3_dissolved else "none",
    )

    return {
        "transfers": phase3_transfers,
        "events":    phase3_events,
        "dissolved": phase3_dissolved,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# DUAL-TICK CONVERGENCE DRIVER (Jun-19 requirement).
# ─────────────────────────────────────────────────────────────────────────────

def run_merger_refill_converge(
    db: Session,
    user_prefix: str | None = None,
    max_rounds: int = 8,
) -> dict:
    """
    Dual-tick convergence driver — loop [compaction → waitlist refill] until no
    further progress, i.e. until every consolidatable pool is full and the single
    remainder pool has been topped up from the waitlist (or the waitlist is drained).
    This is the user's explicit rule: "run the merger until ALL pools are full, then
    run a resync+refill cycle filling the remaining pool(s) from the waitlist."

    Runs at BOTH ticks:
      • T-2H draw preparation (STEP 3b, after flag_l4_members) so pools are packed to
        12 BEFORE the eligibility gate → more 12/12 pools draw that week, and
      • post-draw T+5M (replacing the old single, inert merger call) so the vacancies
        opened by winner ejection are re-compacted and the remainder refilled.

    Each round:
      1. _condense_pools_once(db)            — internal two-pointer compaction.  This
         is lock-INDEPENDENT and does the real consolidation during the draw window.
      2. assign_waitlist_to_pools(db, …)     — Phase 1 refill existing vacancies +
         Phase 2 form new pools from surplus waitlist.  Its OWN Phase-3 condensation
         self-skips here (draw-engine SystemLock is held during both ticks), so there
         is NO double-compaction.

    Convergence: stop as soon as a round moves nobody and assigns/forms nothing
    (normally 1–2 rounds).  max_rounds is a hard backstop.  Failure isolation is the
    caller's responsibility (both call sites wrap this in a non-fatal try/except).

    Returns {transfers, dissolved, rounds, refill} (refill = last assign result).
    """
    rounds:    int       = 0
    tot_xfer:  int       = 0
    dissolved: list[str] = []
    refill:    dict      = {}

    while rounds < max_rounds:
        rounds += 1
        m      = _condense_pools_once(db)
        refill = assign_waitlist_to_pools(db, user_prefix=user_prefix)

        tot_xfer  += m["transfers"]
        dissolved += m["dissolved"]

        progressed = bool(
            m["transfers"]
            or refill["phase1_assigned"]
            or refill["phase2_pools_count"]
            or refill["phase3_transfers"]
        )
        _logger.info(
            "[CONVERGE] round %d — compaction xfers=%d | refill P1=%d P2=%d P3=%d → %s",
            rounds,
            m["transfers"],
            refill["phase1_assigned"],
            refill["phase2_pools_count"],
            refill["phase3_transfers"],
            "progress" if progressed else "CONVERGED",
        )
        if not progressed:
            break

    # ── SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # SINGLE-REMAINDER GUARANTEE (Enhancement 1B — Jun-20).  After a full two-pointer
    # compaction the set of NON-FLAGGED under-capacity pools MUST collapse to AT MOST
    # ONE remainder pool — members are fungible, so ΣM members always pack into
    # floor(ΣM / 12) full pools + exactly one partial of (ΣM mod 12).  If more than
    # one non-flagged partial survives, something blocked the compaction (a flagged
    # pool interleaved — expected & excluded; a refill/lock race; or a regression).
    # We surface it as a forensic ANOMALY so the property is self-diagnosing and never
    # silently violated.  This block is OBSERVATION-ONLY: it moves no members, writes
    # no pool/member state, and therefore cannot affect any payout/level math.
    partial_pools: int = -1
    try:
        non_flagged = (
            db.query(Pool)
            .filter(
                Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]),
                Pool.contains_flagged_l4 == False,   # noqa: E712
            )
            .all()
        )
        partial_names: list[str] = []
        for p in non_flagged:
            cnt = (
                db.query(func.count(User.id))
                .filter(User.current_pool_id == p.id, User.status == UserStatus.Active)
                .scalar() or 0
            )
            if cnt < POOL_CAPACITY:
                partial_names.append(f"{p.name}({cnt}/12)")
        partial_pools = len(partial_names)

        if partial_pools > 1:
            _logger.warning(
                "[CONVERGE] SINGLE-REMAINDER INVARIANT — %d non-flagged partial pool(s) "
                "survived convergence (expected ≤1): %s",
                partial_pools, ", ".join(partial_names),
            )
            try:
                from app.services import forensic as _forensic
                if _forensic.is_on():
                    _forensic.anomaly(
                        "fragmentation_residual",
                        severity="warning",
                        payload={
                            "partial_pool_count": partial_pools,
                            "partial_pools":      partial_names[:50],
                            "rounds":             rounds,
                            "transfers":          tot_xfer,
                        },
                        message=(f"Fragmentation: {partial_pools} non-flagged partial "
                                 f"pools survived convergence (expected ≤1)"),
                    )
            except Exception:
                pass
        else:
            _logger.info(
                "[CONVERGE] single-remainder OK — %d non-flagged partial pool(s) after "
                "%d round(s).",
                partial_pools, rounds,
            )
    except Exception as _verify_exc:   # observation must never break the converge
        _logger.error(
            "[CONVERGE] single-remainder verification failed (non-fatal): %s",
            _verify_exc,
        )

    return {
        "transfers":     tot_xfer,
        "dissolved":     dissolved,
        "rounds":        rounds,
        "refill":        refill,
        "partial_pools": partial_pools,
    }


def run_pool_merger_engine(db: Session, user_prefix: str | None = None) -> dict:
    """
    Lever 3a — Proactive Pool Merger Smart Engine (back-compat thin entry).

    Historically this ran the condensation core ONCE, post-draw.  As of the Jun-19
    dual-tick convergence work it delegates to run_merger_refill_converge, which loops
    compaction + waitlist refill until every consolidatable pool is full (the user's
    "run the merger until all pools are full, then refill the remainder" rule).  The
    name and the {transfers, dissolved} keys are preserved for existing callers; the
    result additionally carries {rounds, refill}.

    L4 immunity is enforced inside the shared core (_condense_pools_once never uses a
    contains_flagged_l4 pool as donor or receiver).
    """
    _logger.info(
        "POOL MERGER ENGINE (proactive, dual-tick convergence) — compacting + "
        "refilling pools to capacity.",
    )
    result = run_merger_refill_converge(db, user_prefix=user_prefix)
    _logger.info(
        "POOL MERGER ENGINE DONE — %d member(s) merged across %d round(s) | "
        "%d pool(s) dissolved.",
        result["transfers"], result["rounds"], len(result["dissolved"]),
    )
    return result


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
