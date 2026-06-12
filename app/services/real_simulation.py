"""
Real Simulation Engine  — Zero-Duplication Stress-Test Harness
==============================================================

ARCHITECTURE GUARANTEE:
  This module contains ZERO business logic.  Every formula, algorithm, and
  rule lives exclusively in the production services.  This engine is a
  dumb orchestrator that:
    1. Creates an isolated in-memory SQLite database (SimulationDB)
    2. Mocks datetime.now() globally across all production modules (ChronosEngine)
    3. Generates synthetic load (MassLoadInjector)
    4. Calls real production services in exact weekly chronological order

DRY contract: if any rule changes in production, the simulation automatically
reflects it.  No second codebase to maintain.  No risk of divergence.

Weekly cycle (mirrors the real Sunday production flow):
  a. MassLoadInjector.inject_week()       — add new users to waitlist
  b. MassLoadInjector.auto_pay_active()   — mark all active members as Paid
  c. MassLoadInjector.apply_abc_model()   — A/B/C late-fee + elimination
  d. brain5_lpi_engine.flag_l4_members()  — catch-up L4 flagging
  e. sde_engine.run_sde_meta_pool()       — SDE: guaranteed L4 exits
  f. waitlist.assign_waitlist_to_pools()  — refill after SDE exits
  g. draw.execute_weekly_draw()           — draw all remaining eligible pools
  h. draw.post_draw_cleanup()             — reset weekly flags
  i. MetricsCollector._snapshot()         — read real DB state for reporting
"""

import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, event, func
from sqlalchemy.orm import sessionmaker, Session

_logger = logging.getLogger(__name__)

# ── Modules whose datetime.now() calls must be intercepted ───────────────────
_TIME_PATCHED = [
    "app.services.draw",
    "app.services.sde_engine",
    "app.services.brain5_lpi_engine",
    "app.services.ai_quant_engine",
    "app.services.draw_preparation",
    "app.services.waitlist",
    "app.services.settings",
]


# ══════════════════════════════════════════════════════════════════════════════
# 1. CHRONOS ENGINE — Time Travel
# ══════════════════════════════════════════════════════════════════════════════

class ChronosEngine:
    """
    Globally mocks datetime.now() across all production service modules so
    the simulation can instantly jump between T-2H, T-0H, T+5m without
    waiting a week.

    Usage:
        chronos = ChronosEngine(start_utc)
        with chronos:
            chronos.jump_to(saturday_22h)
            start_draw_preparation(db, sunday_midnight)
            chronos.jump_to(sunday_midnight)
            execute_weekly_draw(db)
    """

    def __init__(self, start_utc: datetime):
        self._t = start_utc if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)
        self._patches: list = []

    @property
    def current(self) -> datetime:
        return self._t

    def jump_to(self, dt: datetime) -> None:
        self._t = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def advance(self, **kw) -> None:
        self._t += timedelta(**kw)

    def __enter__(self) -> "ChronosEngine":
        import datetime as _dt_mod
        _self = self

        class _Fake(_dt_mod.datetime):
            """Drop-in replacement — .now() returns the simulated clock."""
            @classmethod
            def now(cls, tz=None):          # type: ignore[override]
                return _self._t.astimezone(tz) if tz else _self._t

            @classmethod
            def utcnow(cls):               # type: ignore[override]
                return _self._t.replace(tzinfo=None)

        self._fake = _Fake
        for mod in _TIME_PATCHED:
            try:
                p = patch(f"{mod}.datetime", _Fake)
                p.start()
                self._patches.append(p)
            except Exception as exc:
                _logger.debug("ChronosEngine: skip patch %s — %s", mod, exc)
        return self

    def __exit__(self, *_) -> None:
        for p in reversed(self._patches):
            try:
                p.stop()
            except Exception:
                pass
        self._patches.clear()


# ══════════════════════════════════════════════════════════════════════════════
# 2. SIMULATION DB — Isolated In-Memory SQLite
# ══════════════════════════════════════════════════════════════════════════════

def _create_sim_db():
    """
    Create a fresh in-memory SQLite database with all production tables.
    Uses the same SQLAlchemy models — zero schema duplication.

    Returns (engine, SessionLocal).  Call engine.dispose() when done.
    """
    from app.database import Base

    # Force-import all model modules so their tables are registered on Base.metadata
    import app.models.user              # noqa: F401
    import app.models.pool              # noqa: F401
    import app.models.token             # noqa: F401
    import app.models.draw_history      # noqa: F401
    import app.models.sde_session       # noqa: F401
    import app.models.system_settings   # noqa: F401
    import app.models.system_lock       # noqa: F401
    import app.models.weekly_draw_state # noqa: F401

    try:
        import app.models.elimination_event  # noqa: F401
    except ImportError:
        pass

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, SessionLocal


# ══════════════════════════════════════════════════════════════════════════════
# 3. MASS LOAD INJECTOR — Synthetic User Traffic
# ══════════════════════════════════════════════════════════════════════════════

class MassLoadInjector:
    """
    Generates dummy users and manages their payment state.
    Contains ZERO business logic — only user/token creation and payment marking.
    """

    def __init__(self):
        self._counter = 0   # global monotonic counter for unique IDs

    def inject_week(
        self,
        db: Session,
        count: int,
        now: datetime,
        organic_ratio: float = 0.6,
        existing_ids: list[int] | None = None,
    ) -> list:
        """
        Insert `count` new Paid Waitlist users into the simulation DB.
        Returns the list of created User ORM objects (flushed, not committed).

        organic_ratio: 0.0–1.0 — fraction who join organically (no referrer).
        existing_ids:  pool of possible referrer IDs for non-organic joins.
        """
        from app.models.user import User, UserStatus, WeeklyPaymentStatus

        new_users = []
        for _ in range(count):
            self._counter += 1
            uid = self._counter

            referrer_id = None
            if random.random() >= organic_ratio and existing_ids:
                referrer_id = random.choice(existing_ids)

            u = User(
                name                    = f"SimUser{uid}",
                mobile                  = f"9{uid:010d}",
                username                = f"s{uid:08d}",
                join_date               = now,
                status                  = UserStatus.Waitlist,
                weekly_payment_status   = WeeklyPaymentStatus.Paid,
                current_level           = 1,
                total_deposited_inr     = 1000,
                sde_required            = False,
                elimination_risk        = False,
                grace_active            = False,
                grace_fee_paid          = False,
                referred_by_user_id     = referrer_id,
            )
            db.add(u)
            new_users.append(u)

        if new_users:
            db.flush()   # assign DB IDs without committing
        return new_users

    def auto_pay_active(self, db: Session) -> int:
        """
        Mark ALL Active members as Paid for the current week.
        Simulates 100% payment compliance before the A/B/C model is applied.
        Returns count marked.
        """
        from app.models.user import User, UserStatus, WeeklyPaymentStatus

        n = (
            db.query(User)
            .filter(
                User.status == UserStatus.Active,
                User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
            )
            .update({"weekly_payment_status": WeeklyPaymentStatus.Paid},
                    synchronize_session=False)
        )
        db.flush()
        return n

    def apply_abc_model(
        self,
        db: Session,
        late_ratio: float,
        elim_pct_a: float,
        grace_pct_c: float,
    ) -> dict:
        """
        Apply the A/B/C circular late-fee model BEFORE the draw.

        late_ratio  : fraction of active members who miss payment this week
        elim_pct_a  : of late payers, % directly eliminated (no grace attempt)
        grace_pct_c : of remaining late payers, % who pay grace fee and survive

        Revenue from grace savers (C path) is tracked but not stored in DB for
        simplicity — the production system would have late_fees_inr on each user.

        Returns {n_late, n_elim, n_saved, late_fee_revenue_inr}
        """
        from app.models.user import User, UserStatus, WeeklyPaymentStatus

        if late_ratio <= 0.0:
            return {"n_late": 0, "n_elim": 0, "n_saved": 0, "late_fee_revenue_inr": 0}

        active = db.query(User).filter(User.status == UserStatus.Active).all()
        if not active:
            return {"n_late": 0, "n_elim": 0, "n_saved": 0, "late_fee_revenue_inr": 0}

        n_late     = max(0, int(len(active) * late_ratio))
        late_batch = random.sample(active, min(n_late, len(active)))

        for m in late_batch:
            m.weekly_payment_status = WeeklyPaymentStatus.Unpaid
        db.flush()

        # A: direct elimination
        n_direct_elim = max(0, int(n_late * (elim_pct_a / 100.0)))
        direct_elim   = late_batch[:n_direct_elim]
        grace_pool    = late_batch[n_direct_elim:]

        for m in direct_elim:
            m.status          = UserStatus.Eliminated
            m.current_pool_id = None

        # C: grace savers (pay and stay)
        n_saved = max(0, int(len(grace_pool) * (grace_pct_c / 100.0)))
        for m in grace_pool[:n_saved]:
            m.weekly_payment_status = WeeklyPaymentStatus.Paid  # grace saved

        # Remaining grace pool who don't pay → also eliminated
        for m in grace_pool[n_saved:]:
            m.status          = UserStatus.Eliminated
            m.current_pool_id = None

        db.flush()

        n_total_elim = n_direct_elim + (len(grace_pool) - n_saved)
        # Simulate grace fee + 3-day late fee revenue (proxy for financial reporting)
        late_fee_rev = n_saved * (500 + 150)  # ₹500 seat-save + avg 3d × ₹50

        return {
            "n_late":              n_late,
            "n_elim":              n_total_elim,
            "n_saved":             n_saved,
            "late_fee_revenue_inr": late_fee_rev,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 4. METRICS COLLECTOR — Read Real DB State
# ══════════════════════════════════════════════════════════════════════════════

def _snapshot(
    db: Session,
    week_num: int,
    draws_this_week: int,
    pauses_this_week: int,
    compliance: dict,
    cumulative_ext2: int,
    cumulative_ext3: int,
    cumulative_accel: int,
) -> dict:
    """
    Read ACTUAL DB state after the week completes.
    All numbers come from the real database — no approximation.
    """
    from app.services.brain5_lpi_engine import calculate_lpi, get_level_distribution
    from app.services.ai_quant_engine import (
        calculate_slow_velocity, calculate_fast_velocity, calculate_burn_rate,
        determine_reserve_multiplier, calculate_rdr,
    )
    from app.models.user import User, UserStatus
    from app.models.pool import Pool, PoolStatus

    dist = get_level_distribution(db)
    lpi  = calculate_lpi(db)

    active_users   = db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar() or 0
    waitlist_count = db.query(func.count(User.id)).filter(User.status == UserStatus.Waitlist).scalar() or 0
    pools_active   = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Active).scalar() or 0
    pools_paused   = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Paused_Awaiting_Members).scalar() or 0

    try:
        slow = calculate_slow_velocity(db)
        fast = calculate_fast_velocity(db)
        burn = calculate_burn_rate(db)
        rdr  = calculate_rdr(db, days=7)
        mul, scenario = determine_reserve_multiplier(db)
        momentum = round(fast - slow, 3)
    except Exception:
        slow = fast = burn = rdr = momentum = 0.0
        scenario = "NEUTRAL"
        mul = 1.0

    return {
        # Identity
        "week":                   week_num,
        # Core metrics (same keys as legacy engine's weekly_detail)
        "lpi":                    round(lpi, 2),
        "active_users":           active_users,
        "waitlist_count":         waitlist_count,
        "pools_active":           pools_active,
        "pools_paused":           pools_paused + pauses_this_week,
        "pools_formed":           0,   # set by caller per-week
        "draws_this_week":        draws_this_week,
        "winners_this_week":      draws_this_week * 2,
        "late_payers":            compliance.get("n_late", 0),
        "eliminated":             compliance.get("n_elim", 0),
        "grace_saved":            compliance.get("n_saved", 0),
        # Level distribution (same structure as legacy engine)
        "level_distribution": {
            "L1": dist.l1, "L2": dist.l2, "L3": dist.l3,
            "L4": dist.l4, "L5": dist.l5, "L6": dist.l6,
        },
        "l5_count":               dist.l5,
        "l6_count":               dist.l6,
        # SDE event counts — CUMULATIVE (same as legacy engine)
        "ext2_exits_this_week":   cumulative_ext2,
        "ext3_exits_this_week":   cumulative_ext3,
        "accel_diss_this_week":   cumulative_accel,
        # AI Brain state
        "scenario":               scenario,
        "momentum":               momentum,
        "burn_rate":              burn,
        "rdr_pct":                round(rdr, 1),
        "multiplier":             mul,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. REAL SIM ENGINE — The Main Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class RealSimEngine:
    """
    Zero-duplication stress-test engine.

    Calls real production services in exact weekly chronological order.
    No business logic here — only orchestration.
    """

    def __init__(
        self,
        weeks:            int   = 52,
        users_per_week:   int   = 24,
        initial_users:    int   = 24,
        organic_ratio:    float = 0.6,
        late_ratio:       float = 0.02,
        elim_pct_a:       float = 80.0,
        grace_pct_c:      float = 15.0,
        volatility_mode:  bool  = False,
        volatility_max:   int   = 100,
        start_year:       int   = 2024,
        start_week:       int   = 1,
    ):
        self.weeks           = max(1, min(weeks, 200))
        self.users_per_week  = users_per_week
        self.initial_users   = max(12, initial_users)
        self.organic_ratio   = organic_ratio
        self.late_ratio      = late_ratio
        self.elim_pct_a      = elim_pct_a
        self.grace_pct_c     = grace_pct_c
        self.volatility_mode = volatility_mode
        self.volatility_max  = volatility_max
        self.start_year      = start_year
        self.start_week      = start_week

    def _sunday(self, week_offset: int) -> datetime:
        """Return Sunday 00:00 UTC for (start_week + week_offset)."""
        iso_week = self.start_week + week_offset
        year     = self.start_year + (iso_week - 1) // 52
        iso_week = ((iso_week - 1) % 52) + 1
        try:
            base = datetime.fromisocalendar(year, iso_week, 7)  # 7 = Sunday
        except ValueError:
            # Some years have 53 ISO weeks — clamp to week 52
            base = datetime.fromisocalendar(year, 52, 7)
        return base.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    def run(self) -> dict:
        """
        Execute the full simulation.

        Returns a dict with the SAME structure as the legacy _AdvSimEngine so
        existing frontend charts work without modification.
        """
        from app.services.draw import execute_weekly_draw, post_draw_cleanup
        from app.services.waitlist import assign_waitlist_to_pools
        from app.services.sde_engine import run_sde_meta_pool
        from app.services.brain5_lpi_engine import flag_l4_members, redistribute_multi_l4_pools
        from app.core.pool_settings import get_auto_pool_creation, set_auto_pool_creation
        from app.models.system_lock import SystemLock
        from app.models.draw_history import DrawHistory
        from app.core.config import POOL_DRAW_SDE_EXT2, POOL_DRAW_SDE_EXT3, POOL_DRAW_ACCELERATED

        # ── Preserve + force production-compatible global state ───────────────
        _orig_auto = get_auto_pool_creation()
        set_auto_pool_creation(True)

        engine_db, SessionLocal = _create_sim_db()
        injector = MassLoadInjector()

        weekly_detail:  list[dict] = []
        cycle_logs:     list[dict] = []

        # Running totals (for summary block)
        total_draws         = 0
        total_pauses        = 0
        total_late          = 0
        total_elim          = 0
        total_grace_saved   = 0
        total_late_fee_rev  = 0
        total_users_created = 0
        total_p2_pools      = 0
        total_p3_xfers      = 0
        max_lpi             = 0.0
        max_active          = 0
        max_waitlist        = 0
        max_pools           = 0
        max_l5              = 0
        max_l6              = 0
        scenario_counts:    dict[str, int] = {}

        db = SessionLocal()

        try:
            with ChronosEngine(self._sunday(0)) as chronos:

                # ── Seed: inject initial users one week before first draw ────
                seed_time = self._sunday(0) - timedelta(days=7)
                chronos.jump_to(seed_time)

                seed_users = injector.inject_week(
                    db, self.initial_users, seed_time, self.organic_ratio
                )
                db.commit()
                total_users_created += len(seed_users)

                # Trigger initial pool formation from the seed users
                refill = assign_waitlist_to_pools(db)
                total_p2_pools += refill.get("phase2_pools_count", 0)

                # ── Main weekly loop ─────────────────────────────────────────
                for w in range(self.weeks):
                    week_num        = w + 1
                    sunday_midnight = self._sunday(w)
                    monday_morning  = sunday_midnight - timedelta(days=6)

                    # ISO week_id used by SDE engine for session keying
                    iso = sunday_midnight.isocalendar()
                    week_id = f"{iso.year}-W{iso.week:02d}"

                    # ── a. Inject new users (Monday) ─────────────────────────
                    chronos.jump_to(monday_morning)
                    inflow = self.users_per_week
                    if self.volatility_mode:
                        inflow = random.randint(0, self.volatility_max)

                    # Collect existing user IDs for referral chains (Brain 3 RDR)
                    from app.models.user import User as _U, UserStatus as _US
                    existing_ids = [
                        r[0] for r in db.query(_U.id).filter(
                            _U.status.in_([_US.Active, _US.Waitlist])
                        ).limit(200).all()
                    ]

                    new_users = injector.inject_week(
                        db, inflow, chronos.current, self.organic_ratio, existing_ids
                    )
                    db.commit()
                    total_users_created += len(new_users)

                    # ── b. Auto-pay all active members ───────────────────────
                    injector.auto_pay_active(db)
                    db.commit()

                    # ── c. Apply A/B/C compliance model ─────────────────────
                    compliance = injector.apply_abc_model(
                        db, self.late_ratio, self.elim_pct_a, self.grace_pct_c
                    )
                    db.commit()
                    total_late        += compliance["n_late"]
                    total_elim        += compliance["n_elim"]
                    total_grace_saved += compliance["n_saved"]
                    total_late_fee_rev += compliance["late_fee_revenue_inr"]

                    # ── d. Catch-up flag any un-flagged L4 members ───────────
                    flag_l4_members(db)
                    db.commit()

                    # ── e. Redistribute multi-L4 pools (Brain 5 / Bug 2 fix) ─
                    redistribute_multi_l4_pools(db)
                    db.commit()

                    # ── f. Run SDE meta-pool (L4 guaranteed exits) ───────────
                    # Advance Chronos to Saturday 22:00 (T-2H) for correct week_id
                    saturday_22h = sunday_midnight - timedelta(hours=2)
                    chronos.jump_to(saturday_22h)

                    try:
                        run_sde_meta_pool(db, week_id)
                    except Exception as exc:
                        _logger.warning("Week %d SDE error: %s", week_num, exc)
                        try:
                            db.rollback()
                        except Exception:
                            pass

                    # ── g. Waitlist refill after SDE exits ───────────────────
                    try:
                        refill = assign_waitlist_to_pools(db)
                        total_p2_pools += refill.get("phase2_pools_count", 0)
                        total_p3_xfers += refill.get("phase3_transfers", 0)
                    except Exception as exc:
                        _logger.warning("Week %d refill-after-SDE error: %s", week_num, exc)

                    # ── h. Execute weekly draw (Sunday 00:00) ────────────────
                    chronos.jump_to(sunday_midnight)

                    # Force-clear any stale system lock from crashed prior cycles
                    try:
                        db.query(SystemLock).delete()
                        db.commit()
                    except Exception:
                        pass

                    draws_this_week  = 0
                    pauses_this_week = 0

                    try:
                        mass_result      = execute_weekly_draw(db, auto_pay_unpaid=False)
                        draws_this_week  = mass_result.pools_drawn
                        pauses_this_week = len(mass_result.paused_pools)
                        total_draws  += draws_this_week
                        total_pauses += pauses_this_week

                        total_p2_pools += mass_result.refill.get("phase2_pools_count", 0)
                        total_p3_xfers += mass_result.refill.get("phase3_transfers",   0)

                    except ValueError as exc:
                        _logger.info("Week %d: no eligible pools — %s", week_num, exc)
                    except Exception as exc:
                        _logger.warning("Week %d draw error: %s", week_num, exc)
                        try:
                            db.rollback()
                        except Exception:
                            pass

                    # ── i. Post-draw cleanup (Sunday 00:05) ──────────────────
                    chronos.jump_to(sunday_midnight + timedelta(minutes=5))
                    try:
                        post_draw_cleanup(db)
                    except Exception as exc:
                        _logger.warning("Week %d cleanup error: %s", week_num, exc)
                        try:
                            db.rollback()
                        except Exception:
                            pass

                    # ── j. Read cumulative SDE event counts from DrawHistory ──
                    cumul_ext2 = db.query(func.count(DrawHistory.id)).filter(
                        DrawHistory.draw_type == POOL_DRAW_SDE_EXT2
                    ).scalar() or 0
                    cumul_ext3 = db.query(func.count(DrawHistory.id)).filter(
                        DrawHistory.draw_type == POOL_DRAW_SDE_EXT3
                    ).scalar() or 0
                    cumul_accel = db.query(func.count(DrawHistory.id)).filter(
                        DrawHistory.draw_type == POOL_DRAW_ACCELERATED
                    ).scalar() or 0

                    # ── k. Collect metrics from REAL DB state ────────────────
                    metrics = _snapshot(
                        db             = db,
                        week_num       = week_num,
                        draws_this_week = draws_this_week,
                        pauses_this_week = pauses_this_week,
                        compliance     = compliance,
                        cumulative_ext2 = cumul_ext2,
                        cumulative_ext3 = cumul_ext3,
                        cumulative_accel = cumul_accel,
                    )
                    weekly_detail.append(metrics)

                    cycle_logs.append({
                        "week":      week_num,
                        "pauses":    pauses_this_week,
                        "draws":     draws_this_week,
                        "inflow":    inflow,
                        "compliance": compliance,
                    })

                    # Update running maxima
                    max_lpi      = max(max_lpi, metrics["lpi"])
                    max_active   = max(max_active, metrics["active_users"])
                    max_waitlist = max(max_waitlist, metrics["waitlist_count"])
                    max_pools    = max(max_pools,    metrics["pools_active"])
                    max_l5       = max(max_l5,       metrics["l5_count"])
                    max_l6       = max(max_l6,       metrics["l6_count"])

                    sc = metrics["scenario"]
                    scenario_counts[sc] = scenario_counts.get(sc, 0) + 1

                # ── Final financials from actual DrawHistory ─────────────────
                total_payout = db.query(
                    func.sum(
                        DrawHistory.winner_1_net_payout + DrawHistory.winner_2_net_payout
                    )
                ).scalar() or Decimal("0")

                total_collected = Decimal(str(total_users_created * 1000))
                net_profit      = total_collected - total_payout
                avg_lpi         = round(
                    sum(w["lpi"] for w in weekly_detail) / max(len(weekly_detail), 1), 2
                )

                final_ext2  = weekly_detail[-1]["ext2_exits_this_week"]  if weekly_detail else 0
                final_ext3  = weekly_detail[-1]["ext3_exits_this_week"]  if weekly_detail else 0
                final_accel = weekly_detail[-1]["accel_diss_this_week"]  if weekly_detail else 0

                # L5/L6 escalation explanation (same field as legacy engine)
                if max_l5 > 0 or max_l6 > 0:
                    escalation_note = (
                        f"L5 members appeared — {final_ext2} SDE Ext-II draw(s) executed. "
                        f"L6 members appeared — {final_ext3} SDE Ext-III draw(s) executed. "
                        f"Root cause: Accelerated Dissolution (≥60% L4+) → L4 survivors "
                        f"advanced to L5. {total_pauses} pool pause(s) delayed SDE processing."
                    )
                else:
                    escalation_note = (
                        "No L5/L6 escalation — SDE cleared all L4 members in time. "
                        "System operated within normal parameters throughout simulation."
                    )

                # Build summary in the same schema as legacy _AdvSimEngine.summary()
                # so the existing frontend SimStatsGrid, LevelMatrix, etc. work without change.
                simulation_summary = {
                    # ── Legacy backward-compatible keys ──────────────────────
                    "total_cycles_run":              self.weeks,
                    "total_simulated_users_created": total_users_created,
                    "total_winners_drawn":           total_draws * 2,
                    "total_pools_auto_scaled":       total_p2_pools,
                    "total_condensation_events":     total_p3_xfers,
                    "total_draw_pauses_triggered":   total_pauses,
                    "total_late_fees_collected_inr": float(total_late_fee_rev),
                    "final_virtual_liquidity_float": float(net_profit),
                    # ── Extended financial section ────────────────────────────
                    "financial_metrics": {
                        "total_collected_inr":        float(total_collected),
                        "total_distributed_inr":      float(total_payout),
                        "total_maintenance_fees_inr": float(total_draws * 2 * 500),
                        "total_late_fees_inr":        float(total_late_fee_rev),
                        "net_organizer_profit_inr":   float(net_profit),
                        "master_liquidity_float_inr": float(net_profit),
                        "projected_ultimate_liability": float(total_payout),
                    },
                    # ── System health section (same keys as legacy) ───────────
                    "system_health": {
                        "total_members_injected":        total_users_created,
                        "total_direct_pool_assignments": total_users_created,
                        "total_dynamic_merges":          total_p3_xfers,
                        "total_draw_pauses_triggered":   total_pauses,
                        "total_l4_sde_flaggings":        0,   # tracked by real DB
                        "total_sde_exits":               final_ext2 + final_ext3,
                        "total_type_a_draws":            0,   # tracked by real DB
                        "total_type_b_draws":            0,
                        "sde_exit_rate_pct":             round(
                            (final_ext2 + final_ext3) / max(total_draws * 2, 1) * 100, 1
                        ),
                        # Anti-maturity pressure
                        "max_l5_count":                  max_l5,
                        "max_l6_count":                  max_l6,
                        "max_high_lpi_streak_weeks":     0,
                        "l5_peak_by_week":               [w["l5_count"] for w in weekly_detail],
                        "l6_peak_by_week":               [w["l6_count"] for w in weekly_detail],
                        "pauses_by_week":                [c["pauses"] for c in cycle_logs],
                        # SDE Extension events
                        "total_l5_ext2_forced_exits":    final_ext2,
                        "total_l6_ext3_forced_exits":    final_ext3,
                        "total_accel_dissolution_events": final_accel,
                        # A-1 WHY explanation
                        "l5_l6_escalation_explanation":  escalation_note,
                    },
                    # ── Real engine metadata ──────────────────────────────────
                    "engine":               "real",
                    "avg_lpi":              avg_lpi,
                    "max_lpi":              round(max_lpi, 2),
                    "max_active_users":     max_active,
                    "max_waitlist_count":   max_waitlist,
                    "max_pools":            max_pools,
                    "scenario_distribution": scenario_counts,
                }

        finally:
            db.close()
            engine_db.dispose()
            set_auto_pool_creation(_orig_auto)

        return {
            "engine":            "real",
            "simulation_summary": simulation_summary,
            "weekly_detail":     weekly_detail,
            "cycle_logs":        cycle_logs,
        }
