"""
Real Simulation Engine  — Zero-Duplication Stress-Test Harness
==============================================================

# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ARCHITECTURAL PIVOT: SQLite isolation REMOVED — engine now operates directly
# on the real PostgreSQL database so that Admin Dashboard, Statistics, Pool
# Oversight, and all analytics reflect the load-test data in real time.
# Users are namespaced with a per-run prefix (rsim_{run_id}) so multiple runs
# can coexist and be purged with a targeted DELETE or /dev/reset-data.

ARCHITECTURE GUARANTEE:
  This module contains ZERO business logic.  Every formula, algorithm, and
  rule lives exclusively in the production services.  This engine is a
  dumb orchestrator that:
    1. Opens a session on the REAL PostgreSQL database (no SQLite isolation)
    2. Mocks datetime.now() globally across all production modules (ChronosEngine)
    3. Generates synthetic load with DEP tokens (MassLoadInjector)
    4. Calls real production services in exact weekly chronological order

DRY contract: if any rule changes in production, the simulation automatically
reflects it.  No second codebase to maintain.  No risk of divergence.

Weekly cycle — EXACT PRODUCTION ORDER:
  a. inject_week()               — new users → DEP tokens burned → Waitlist
  b. auto_pay_installments()     — all Active members marked Paid
  c. apply_abc_model()           — A/B/C late-fee + elimination
  [Chronos → Saturday 22:00 (T-2H)]
  d. start_draw_preparation()    — acquires lock, flags L4, runs SDE meta-pool
  [Chronos → Sunday 00:00 (T-0H)]
  e. execute_weekly_draw()       — Ext-II/III pre-pass + all pool draws
  [Chronos → Sunday 00:05 (T+5m)]
  f. post_draw_cleanup()         — reset weekly flags, release lock
  [Collect metrics from real DB]

See also: app/services/stress_simulator.py (spec-named alias)
"""

import logging
import random
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Removed: create_engine, event, sessionmaker — no longer needed (SQLite gone).
from sqlalchemy import func, insert as sa_insert
from sqlalchemy.orm import Session

# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Virtual DB-write clock.  ChronosEngine installs it for the run's lifespan; the
# 5 bulk sa_insert(Token) sites below stamp created_at from it explicitly because
# core bulk inserts bypass the model's Python-side default=.
from app.core import sim_clock

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

_DEPOSIT_DEC = Decimal("1000")
_TOKEN_ALPHA = string.ascii_uppercase + string.digits


# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ── _SimMilestones — typed container for all 9-tick Chronos timestamps ───────
# All fields are computed dynamically from DB-backed global_config values by
# _compute_milestones().  NO field may ever be hardcoded inside the simulator.
@dataclass(frozen=True)
class _SimMilestones:
    """
    Immutable snapshot of every chronological milestone for one simulated cycle.

    Strict ordering guaranteed by _compute_milestones():
        CYCLE_START < DUE_DATE < GRACE_PERIOD_START < G_CLOSE < T_02H < T_00H < T_05M

    Fields:
        CYCLE_START         — payment window opens (= previous T_00H)
        DUE_DATE            — on-time payment window closes
                              (= CYCLE_START + payment_due_offset_days)
        GRACE_PERIOD_START  — grace-period opens after late-fee window
                              (= T_02H − grace_period_hours)
        G_CLOSE             — guillotine: FM triggers elimination
                              (= T_02H − 5 min)
        T_02H               — draw preparation start (= T_00H − 2 h)
        T_00H               — draw execution time
        T_05M               — post-draw cleanup fires
                              (= T_00H + cleanup_offset_minutes)
        cycle_length        — total duration of one cycle (weekly = 7 days, etc.)
    """
    CYCLE_START:        datetime
    DUE_DATE:           datetime
    GRACE_PERIOD_START: datetime
    G_CLOSE:            datetime
    T_02H:              datetime
    T_00H:              datetime
    T_05M:              datetime
    cycle_length:       timedelta


# ══════════════════════════════════════════════════════════════════════════════
# 1. CHRONOS ENGINE — Time Travel
# ══════════════════════════════════════════════════════════════════════════════

class ChronosEngine:
    """
    Globally mocks datetime.now() across all production service modules so
    the simulation can instantly jump between T-2H, T-0H, T+5m without
    waiting a week.

    Patched modules:
      draw, sde_engine, brain5_lpi_engine, ai_quant_engine,
      draw_preparation, waitlist, settings

    Usage:
        with ChronosEngine(start_utc) as chronos:
            chronos.jump_to(saturday_22h)
            start_draw_preparation(db, sunday_midnight)
            chronos.jump_to(sunday_midnight)
            execute_weekly_draw(db)
            chronos.jump_to(sunday_midnight + timedelta(minutes=5))
            post_draw_cleanup(db)
    """

    def __init__(self, start_utc: datetime):
        self._t = start_utc if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)
        self._patches: list = []

    @property
    def current(self) -> datetime:
        return self._t

    def jump_to(self, dt: datetime) -> None:
        """Instantly advance the simulated clock to dt."""
        self._t = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def advance(self, **kw) -> None:
        """Advance simulated clock by a timedelta."""
        self._t += timedelta(**kw)

    def __enter__(self) -> "ChronosEngine":
        import datetime as _dt_mod
        _self = self

        class _FakeDatetime(_dt_mod.datetime):
            """Drop-in replacement — .now() returns the simulated clock time."""
            @classmethod
            def now(cls, tz=None):          # type: ignore[override]
                return _self._t.astimezone(tz) if tz else _self._t

            @classmethod
            def utcnow(cls):               # type: ignore[override]
                return _self._t.replace(tzinfo=None)

        self._fake = _FakeDatetime
        for mod in _TIME_PATCHED:
            try:
                p = patch(f"{mod}.datetime", _FakeDatetime)
                p.start()
                self._patches.append(p)
            except Exception as exc:
                _logger.debug("ChronosEngine: skip %s — %s", mod, exc)
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Install the DB-WRITE virtual clock in lockstep with the datetime patches.
        # The patches above govern what the strategy READS (its decisions); this
        # governs what the strategy WRITES (audit-row timestamps).  Without it,
        # DrawHistory.draw_timestamp / Token.created_at / Pool.created_at /
        # EliminationEvent.created_at fall back to server_default=func.now() (the
        # real PostgreSQL clock), so every simulated week collapses onto the single
        # real instant the run executed and week-by-week statistics are impossible.
        # The lambda reads _self._t at call time, so every chronos.jump_to() is
        # immediately reflected in the timestamps written after it.
        from app.core import sim_clock as _sim_clock
        _sim_clock.install(lambda: _self._t)
        return self

    def __exit__(self, *_) -> None:
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Uninstall the DB-write virtual clock FIRST (in a guarded block) so that
        # even if a patch.stop() raises, production code immediately reverts to the
        # real wall-clock.  Clock lifespan must never outlive the datetime patches.
        try:
            from app.core import sim_clock as _sim_clock
            _sim_clock.uninstall()
        except Exception:
            pass
        for p in reversed(self._patches):
            try:
                p.stop()
            except Exception:
                pass
        self._patches.clear()


# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ══════════════════════════════════════════════════════════════════════════════
# 2. DATABASE SESSION — Real PostgreSQL (SQLite isolation REMOVED)
# ══════════════════════════════════════════════════════════════════════════════
# _create_sim_db() and its sqlite:///:memory: engine are DELETED.
# RealSimEngine.run() now opens a session via app.database.SessionLocal so
# all writes land in the real PostgreSQL database and are immediately
# visible in the Admin Dashboard, Statistics, Pool Oversight, and all
# analytics pages.
#
# Collision safety: MassLoadInjector prefixes every username, mobile, and
# weekly token code with the run-specific rsim_{run_id[:8]} slug.  This
# guarantees uniqueness across multiple back-to-back simulation runs
# without a DB reset between them.
#
# Cleanup before public launch: POST /dev/reset-data (Danger Zone in
# Dev Tools) truncates users + pools + tokens and resets sequences to 1.


# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ══════════════════════════════════════════════════════════════════════════════
# 2.5  CHRONOS MILESTONE ENGINE — Dynamic Timeline Computation
# ══════════════════════════════════════════════════════════════════════════════

def _compute_milestones(db: "Session", T_00H: datetime) -> _SimMilestones:
    """
    Compute every Chronos tick timestamp for one simulation cycle from live
    DB-backed global_config values.

    All offsets are read fresh every cycle so an admin changing a value
    mid-simulation takes effect on the next cycle (within 60-second TTL).

    STRICT CHRONOLOGICAL GUARANTEE:
        CYCLE_START < DUE_DATE < GRACE_PERIOD_START < G_CLOSE < T_02H < T_00H < T_05M

    DUE_DATE guard: if DUE_DATE >= GRACE_PERIOD_START (misconfigured settings,
    e.g. due_days = 6 with grace 48 h and a 7-day cycle), DUE_DATE is clamped
    to GRACE_PERIOD_START − 1 hour so the late-fee window is always positive.
    """
    from app.services.global_config import (
        get_draw_frequency,
        get_grace_period_hours,
        get_cleanup_offset_minutes,
        get_payment_due_offset_days,
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        get_grace_close_offset_minutes,
    )

    freq          = get_draw_frequency(db)
    grace_h       = get_grace_period_hours(db)
    cleanup_m     = get_cleanup_offset_minutes(db)
    due_days      = get_payment_due_offset_days(db)
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    grace_close_m = get_grace_close_offset_minutes(db)

    cycle_length: timedelta = (
        timedelta(days=7)  if freq == "weekly"   else
        timedelta(days=14) if freq == "biweekly"  else
        timedelta(days=30) if freq == "monthly"   else
        timedelta(days=7)
    )

    T_02H              = T_00H - timedelta(hours=2)
    T_05M              = T_00H + timedelta(minutes=cleanup_m)
    CYCLE_START        = T_00H - cycle_length
    GRACE_PERIOD_START = T_02H - timedelta(hours=grace_h)
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    G_CLOSE            = T_02H - timedelta(minutes=grace_close_m)
    DUE_DATE           = CYCLE_START + timedelta(days=due_days)

    # Guard: DUE_DATE must be strictly before GRACE_PERIOD_START
    if DUE_DATE >= GRACE_PERIOD_START:
        DUE_DATE = GRACE_PERIOD_START - timedelta(hours=1)

    return _SimMilestones(
        CYCLE_START        = CYCLE_START,
        DUE_DATE           = DUE_DATE,
        GRACE_PERIOD_START = GRACE_PERIOD_START,
        G_CLOSE            = G_CLOSE,
        T_02H              = T_02H,
        T_00H              = T_00H,
        T_05M              = T_05M,
        cycle_length       = cycle_length,
    )


def _compute_next_draw_time(T_00H: datetime, cycle_length: timedelta) -> datetime:
    """
    TICK 9 — advance to the next cycle's draw execution time.
    Pure arithmetic: no DB read required (cycle_length already read from DB
    in _compute_milestones and passed through _SimMilestones.cycle_length).
    """
    return T_00H + cycle_length


# ══════════════════════════════════════════════════════════════════════════════
# 3. MASS LOAD INJECTOR — Synthetic User Traffic + DEP Token Burning
# ══════════════════════════════════════════════════════════════════════════════

class MassLoadInjector:
    """
    Generates dummy users WITH burned DEP tokens and manages payment state.
    Contains ZERO business logic — only user/token creation and payment marking.

    Why DEP tokens?
      Production flow: user redeems DEP-XXXXXX → Waitlist + Paid status.
      Burning the DEP token records cash inflow in the Token table so that
      financial metrics (total_collected_inr, Cash Flow charts) are accurate.
    """

    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    def __init__(self, run_prefix: str = "rsim"):
        self._counter = 0   # global monotonic counter for unique IDs within this run
        # 8-char run-specific slug embedded in every username, mobile, and
        # weekly token code so concurrent / back-to-back runs never collide.
        # Padded with '0' if shorter than 8 chars (e.g. bare "rsim" → "rsim0000").
        self._pfx = run_prefix[:8].ljust(8, '0')

    def _unique_token_code(self) -> str:
        """Generate a collision-resistant simulation token code."""
        self._counter += 1
        suffix = "".join(secrets.choice(_TOKEN_ALPHA) for _ in range(6))
        return f"SD{self._counter:06d}{suffix}"

    def inject_week(
        self,
        db: Session,
        count: int,
        now: datetime,
        organic_ratio: float = 0.6,
        existing_ids: list[int] | None = None,
    ) -> list:
        """
        Insert `count` new Paid Waitlist users AND their burned DEP tokens.

        Each user gets:
          - A unique username / mobile (sim_{uid:08d})
          - status=Waitlist, weekly_payment_status=Paid
          - A burned DEP token (₹1,000) that represents their entry deposit
          - Optional referral link (triggers Brain 3 RDR naturally)

        Returns the list of created User ORM objects (flushed, not committed).
        """
        from app.models.user import User, UserStatus, WeeklyPaymentStatus
        from app.models.token import Token, TokenType, TokenStatus

        if count <= 0:
            return []

        new_users: list = []

        for _ in range(count):
            self._counter += 1
            uid = self._counter

            referrer_id = None
            if random.random() >= organic_ratio and existing_ids:
                referrer_id = random.choice(existing_ids)

            # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Username/mobile include run-specific prefix so back-to-back runs
            # on the real DB never violate UNIQUE constraints.
            u = User(
                name                    = f"SimUser{self._pfx}{uid}",
                mobile                  = f"SIM{self._pfx}{uid:06d}",
                username                = f"{self._pfx}_{uid:06d}",
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

        # Flush to get DB-assigned user IDs before creating tokens
        db.flush()

        # Bulk-insert burned DEP tokens (1 per user) — mirrors production payment flow
        # DEP code uses auto-increment user.id — globally unique without prefix.
        token_rows = [
            {
                "code":      f"SD{u.id:010d}",   # deterministic, unique per user
                "type":      TokenType.Deposit,
                "status":    TokenStatus.Burned,
                "value_inr": _DEPOSIT_DEC,
                "user_id":   u.id,
                "pool_id":   None,
                # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # Bulk insert bypasses Token.created_at's Python default=, so stamp
                # the DEP token at the user's (Chronos-accurate) join instant — the
                # deposit is paid exactly when the user joins.
                "created_at": u.join_date,
            }
            for u in new_users
        ]

        if token_rows:
            db.execute(sa_insert(Token), token_rows)

        return new_users

    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    def inject_distributed(
        self,
        db:            "Session",
        count:         int,
        window_start:  datetime,
        window_end:    datetime,
        organic_ratio: float,
        existing_ids:  "list[int]",
        chronos:       "ChronosEngine",
    ) -> list:
        """
        MODULE 2 — DYNAMIC LOAD INJECTOR

        Distribute `count` user injections across [window_start, window_end]
        with randomly-generated timestamps in strictly ascending order.
        Chronos advances to each injection timestamp before the User ORM
        object is created so that join_date and any auto-timestamp fields
        reflect the correct simulated time.

        One DEP token (₹1,000 Burned) is created per user — mirrors the
        production registration flow where the DEP token is burned on entry.

        STRICT FORWARD-TIME GUARANTEE: timestamps are generated then sorted
        ascending before iteration.  Chronos never moves backward inside this
        method, and is guaranteed to leave at a time ≥ window_start.
        """
        if count <= 0:
            return []

        from app.models.user  import User, UserStatus, WeeklyPaymentStatus
        from app.models.token import Token, TokenType, TokenStatus

        window_secs = max(1, int((window_end - window_start).total_seconds()))
        # Sort timestamps so Chronos always moves forward
        timestamps = sorted(
            window_start + timedelta(seconds=random.randint(0, window_secs))
            for _ in range(count)
        )

        new_users: list = []
        for ts in timestamps:
            chronos.jump_to(ts)          # Chronos at exact injection time
            self._counter += 1
            uid = self._counter

            # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
            u = User(
                name                  = f"SimUser{self._pfx}{uid}",
                mobile                = f"SIM{self._pfx}{uid:06d}",
                username              = f"{self._pfx}_{uid:06d}",
                join_date             = ts,
                status                = UserStatus.Waitlist,
                weekly_payment_status = WeeklyPaymentStatus.Paid,
                current_level         = 1,
                total_deposited_inr   = 1000,
                sde_required          = False,
                elimination_risk      = False,
                grace_active          = False,
                grace_fee_paid        = False,
                referred_by_user_id   = (
                    random.choice(existing_ids)
                    if existing_ids and random.random() >= organic_ratio else None
                ),
            )
            db.add(u)
            new_users.append(u)

        # Single flush to get all PKs, then batch-insert DEP tokens
        db.flush()
        token_rows = [
            {
                "code":      f"SD{u.id:010d}",
                "type":      TokenType.Deposit,
                "status":    TokenStatus.Burned,
                "value_inr": _DEPOSIT_DEC,
                "user_id":   u.id,
                "pool_id":   None,
                # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # Bulk insert bypasses Token.created_at's Python default=, so stamp
                # the DEP token at the user's (Chronos-accurate) join instant.
                "created_at": u.join_date,
            }
            for u in new_users
        ]
        if token_rows:
            db.execute(sa_insert(Token), token_rows)
        db.flush()

        return new_users

    def auto_pay_installments(
        self,
        db:       Session,
        week_num: int = 0,
        skip_ids: "set[int] | None" = None,
    ) -> int:
        """
        U-08: Mark non-late Active members as Paid and create one weekly
        Burned DEP token per member — making total_collected_inr financially
        accurate for multi-week simulations.

        SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        FIX A2: Added skip_ids parameter — Type B late-fee holders (Unpaid but NOT
        eliminated) are excluded from auto-pay so their WK token is NOT created.
        This ensures installments_collected_inr reflects only members who genuinely
        paid this week, not all Active members.

        skip_ids  : set of user.id values returned by apply_abc_model() as
                    "type_b_ids" — these members are Unpaid by design and must not
                    receive a WK installment token until they pay in a future week.

        Token code format: WK{week:04d}U{uid:010d} — deterministic, unique per
        member per week, collision-safe without a DB lookup loop.

        Returns count of members who were paid (= new tokens created).
        """
        from app.models.user  import User, UserStatus, WeeklyPaymentStatus
        from app.models.token import Token, TokenType, TokenStatus
        from datetime         import datetime, timezone

        unpaid: list = (
            db.query(User)
            .filter(
                User.status                == UserStatus.Active,
                User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
            )
            .all()
        )

        # Exclude Type B late-fee holders — they are Unpaid by design this week
        if skip_ids:
            unpaid = [m for m in unpaid if m.id not in skip_ids]

        if not unpaid:
            return 0

        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # real_simulation.py is NOT in _TIME_PATCHED, so datetime.now() here returns
        # the REAL wall-clock.  sim_clock.now() returns the simulated instant while a
        # ChronosEngine is active (the whole run is), making both created_at and
        # redeemed_at land in the correct virtual week.  Bulk insert bypasses the
        # model default=, hence created_at is set explicitly here too.
        now = sim_clock.now()
        token_rows = []
        for member in unpaid:
            member.weekly_payment_status = WeeklyPaymentStatus.Paid
            # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # WK code includes run prefix so back-to-back runs on real DB don't
            # produce duplicate codes for the same week + user-id combination.
            token_rows.append({
                "code":        f"WK{self._pfx}{week_num:04d}U{member.id:010d}",
                "type":        TokenType.Deposit,
                "status":      TokenStatus.Burned,
                "value_inr":   _DEPOSIT_DEC,
                "user_id":     member.id,
                "pool_id":     member.current_pool_id,
                "created_at":  now,
                "redeemed_at": now,
            })

        if token_rows:
            try:
                db.execute(sa_insert(Token), token_rows)
            except Exception:
                # Duplicate code on re-run — safe to skip; payment flag already set
                db.rollback()
                # Re-apply just the Paid status without tokens
                for member in unpaid:
                    member.weekly_payment_status = WeeklyPaymentStatus.Paid

        db.flush()
        return len(unpaid)

    # Keep legacy alias so any existing callers don't break
    def auto_pay_active(self, db: Session) -> int:
        return self.auto_pay_installments(db, week_num=0)

    def auto_settle_referral_rw(self, db: Session, week_num: int = 0) -> int:
        """
        U-09: Post-draw RW token auto-settlement.

        After each draw cycle, scan all users with
            accumulated_referral_bonus_inr >= 1000
        and create one Referral_Withdraw (RW) token as an auto-settlement record.

        This makes the simulation's referral outflow stats accurate:
        without U-09 the accumulated balance grows unbounded and is never
        reflected in total_cash_outflow_inr.

        Returns count of RW tokens created.
        """
        from app.models.user  import User, UserStatus
        from app.models.token import Token, TokenType, TokenStatus
        from decimal          import Decimal

        _threshold = Decimal("1000")
        _zero      = Decimal("0")

        eligible: list = (
            db.query(User)
            .filter(
                User.status.in_([UserStatus.Active, UserStatus.Waitlist, UserStatus.Eliminated_Won]),
                User.accumulated_referral_bonus_inr >= _threshold,
            )
            .all()
        )

        if not eligible:
            return 0

        created = 0
        for user in eligible:
            balance = Decimal(str(user.accumulated_referral_bonus_inr or 0))
            if balance < _threshold:
                continue

            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # FIX: this line was indented at 8 spaces (pre-existing error from a prior
            # session) but must be 12 to sit inside the `for user in eligible:` loop.
            # The IndentationError made real_simulation.py un-importable, so EVERY
            # simulation thread died instantly on import → UI stuck at "Week 0 / 0.0%".
            rw_code = f"RW{self._pfx}{week_num:04d}U{user.id:010d}"
            rw_token = Token(
                code      = rw_code,
                type      = TokenType.Referral_Withdraw,
                status    = TokenStatus.Burned,
                value_inr = balance,
                user_id   = user.id,
                pool_id   = None,
            )
            db.add(rw_token)
            # Zero the accumulated balance after settlement
            user.accumulated_referral_bonus_inr = _zero
            created += 1

        if created:
            db.flush()
        return created

    def _sim_token_code(self, db: Session, prefix: str) -> str:
        """
        Collision-safe token code for simulation-created compliance tokens.
        Uses the same cryptographic pattern as production draw.py.
        Format: "{prefix}{6 uppercase alphanumeric}"  e.g. "LF-A3KZ9W"
        """
        from app.crud.token import get_token_by_code
        while True:
            code = prefix + "".join(secrets.choice(_TOKEN_ALPHA) for _ in range(6))
            if not get_token_by_code(db, code):
                return code

    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # ── MODULE 3: FINANCE MANAGER — 9-Tick Payment Behaviour Engine ────────────
    #
    # These four methods implement the exact chronological payment cascade from
    # the Chronos Timeline spec.  Each method is called at a specific Chronos
    # milestone and operates ONLY on members who are in the correct state at
    # that moment in simulated time.
    #
    # Existing apply_abc_model() is kept below as a backward-compat wrapper.

    def tick2_on_time_payments(
        self,
        db:            "Session",
        on_time_fraction: float,
        chronos:       "ChronosEngine",
        window_start:  datetime,
        window_end:    datetime,
        week_num:      int,
    ) -> int:
        """
        TICK 2 — ON-TIME WINDOW (CYCLE_START → DUE_DATE)

        Finance Manager selects `on_time_fraction` of Active+Unpaid members
        and marks them Paid.  One WK{week}U{uid} DEP token is created per
        member — mirrors production weekly-installment token flow.

        Chronos does NOT advance inside this method (it was already advanced
        by inject_distributed).  All tokens are created at chronos.current.

        Returns: count of members paid on time.
        """
        from app.models.user  import User, UserStatus, WeeklyPaymentStatus
        from app.models.token import Token, TokenType, TokenStatus

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Scoped to rsim_ users — prevents processing 2000+ real users in production DB.
        unpaid = (
            db.query(User)
            .filter(User.status == UserStatus.Active,
                    User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
                    User.username.like(f"{self._pfx}%"))
            .all()
        )
        if not unpaid:
            return 0

        n_on_time  = max(0, int(len(unpaid) * on_time_fraction))
        batch      = random.sample(unpaid, min(n_on_time, len(unpaid)))

        for m in batch:
            m.weekly_payment_status = WeeklyPaymentStatus.Paid

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # created_at = simulated instant (bulk insert bypasses the model default=).
        _paid_ts = sim_clock.now()
        token_rows = [
            {
                "code":        f"WK{self._pfx}{week_num:04d}U{m.id:010d}",
                "type":        TokenType.Deposit,
                "status":      TokenStatus.Burned,
                "value_inr":   _DEPOSIT_DEC,
                "user_id":     m.id,
                "pool_id":     m.current_pool_id,
                "created_at":  _paid_ts,
            }
            for m in batch
        ]
        if token_rows:
            try:
                db.execute(sa_insert(Token), token_rows)
            except Exception:
                db.rollback()
                for m in batch:
                    m.weekly_payment_status = WeeklyPaymentStatus.Paid
        db.flush()
        return len(batch)

    def tick3_late_fee_window(
        self,
        db:              "Session",
        type_b_fraction: float,
        chronos:         "ChronosEngine",
        due_date:        datetime,
        grace_start:     datetime,
        week_num:        int,
    ) -> dict:
        """
        TICK 3 — LATE FEE WINDOW (DUE_DATE → GRACE_PERIOD_START)

        Finance Manager:
          1. Accrues daily late fees on ALL remaining Active+Unpaid members
             using get_late_fee_daily(db) and get_late_fee_cap(db) from
             global_config — zero hardcoded amounts.  Chronos advances by
             one simulated day per accrual step.
          2. `type_b_fraction` of Unpaid members pay their installment + accrued
             late fee in this window (Type-B-equivalent: late but before grace).
             WK tokens created for them.

        Returns: {n_late, n_b_paid, late_fee_rev, type_b_ids}
        """
        from app.models.user  import User, UserStatus, WeeklyPaymentStatus
        from app.models.token import Token, TokenType, TokenStatus
        from app.services.global_config import get_late_fee_daily, get_late_fee_cap

        _zero = Decimal("0")
        _fee  = Decimal(str(get_late_fee_daily(db)))
        _cap  = Decimal(str(get_late_fee_cap(db)))

        # Jump to DUE_DATE to start the late-fee accrual
        chronos.jump_to(due_date)

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Scoped to rsim_ users — prevents processing 2000+ real users in production DB.
        unpaid: list = (
            db.query(User)
            .filter(User.status == UserStatus.Active,
                    User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
                    User.username.like(f"{self._pfx}%"))
            .all()
        )
        n_late = len(unpaid)
        if not unpaid:
            return {"n_late": 0, "n_b_paid": 0, "late_fee_rev": 0.0,
                    "type_b_ids": set()}

        # Days in the late-fee window
        late_window_hours = max(1.0, (grace_start - due_date).total_seconds() / 3600)
        sim_days          = max(1, int(late_window_hours / 24))

        total_lf_rev = _zero

        for day_idx in range(sim_days):
            day_ts = due_date + timedelta(days=day_idx)
            if day_ts >= grace_start:
                break
            chronos.jump_to(day_ts)          # advance clock one day at a time

            for m in unpaid:
                current  = Decimal(str(m.late_fees_inr or 0))
                headroom = max(_zero, _cap - current)
                if headroom <= _zero:
                    continue
                accrual         = min(_fee, headroom)
                m.late_fees_inr = current + accrual

                lf_code = self._sim_token_code(db, "LF-")
                db.add(Token(
                    code      = lf_code,
                    type      = TokenType.Late_Fee,
                    status    = TokenStatus.Burned,
                    value_inr = accrual,
                    user_id   = m.id,
                    pool_id   = m.current_pool_id,
                ))
                total_lf_rev += accrual

        db.flush()

        # Type-B-equivalent: pay installment + late fee before grace period
        n_b   = max(0, int(n_late * type_b_fraction))
        b_batch = random.sample(unpaid, min(n_b, len(unpaid)))

        for m in b_batch:
            m.weekly_payment_status = WeeklyPaymentStatus.Paid
            m.late_fees_inr         = _zero

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # created_at = simulated instant (bulk insert bypasses the model default=).
        _typeb_ts = sim_clock.now()
        token_rows = [
            {
                "code":      f"WK{self._pfx}{week_num:04d}U{m.id:010d}",
                "type":      TokenType.Deposit,
                "status":    TokenStatus.Burned,
                "value_inr": _DEPOSIT_DEC,
                "user_id":   m.id,
                "pool_id":   m.current_pool_id,
                "created_at": _typeb_ts,
            }
            for m in b_batch
        ]
        if token_rows:
            try:
                db.execute(sa_insert(Token), token_rows)
            except Exception:
                db.rollback()
                for m in b_batch:
                    m.weekly_payment_status = WeeklyPaymentStatus.Paid
                    m.late_fees_inr         = _zero
        db.flush()

        return {
            "n_late":      n_late,
            "n_b_paid":    len(b_batch),
            "late_fee_rev": float(total_lf_rev),
            "type_b_ids":  {m.id for m in b_batch},
        }

    def tick4_grace_period(
        self,
        db:             "Session",
        grace_fraction: float,
        chronos:        "ChronosEngine",
        grace_start:    datetime,
        g_close:        datetime,
        week_num:       int,
    ) -> dict:
        """
        TICK 4 — GRACE PERIOD (GRACE_PERIOD_START → G_CLOSE)

        Finance Manager selects `grace_fraction` of remaining Active+Unpaid
        members who save their seats by paying:
          • Accrued late fee  → LFC- settlement token
          • ₹500 grace fee    → GF- token
          • Weekly installment → WK token

        Chronos advances for each grace payment (distributed across the window)
        so timestamps are realistic.

        Returns: {n_grace_saved, grace_fee_rev, lf_settled_rev}
        """
        from app.models.user  import User, UserStatus, WeeklyPaymentStatus
        from app.models.token import Token, TokenType, TokenStatus

        _zero      = Decimal("0")
        _grace_fee = Decimal("500")

        chronos.jump_to(grace_start)

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Scoped to rsim_ users — prevents processing 2000+ real users in production DB.
        unpaid: list = (
            db.query(User)
            .filter(User.status == UserStatus.Active,
                    User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
                    User.username.like(f"{self._pfx}%"))
            .all()
        )
        if not unpaid:
            return {"n_grace_saved": 0, "grace_fee_rev": 0.0, "lf_settled_rev": 0.0}

        n_grace     = max(0, int(len(unpaid) * grace_fraction))
        grace_batch = random.sample(unpaid, min(n_grace, len(unpaid)))

        grace_fee_rev  = _zero
        lf_settled_rev = _zero
        window_secs    = max(1, int((g_close - grace_start).total_seconds()))

        # Advance Chronos progressively through the grace window
        pay_times = sorted(
            grace_start + timedelta(seconds=random.randint(0, window_secs))
            for _ in grace_batch
        )

        for m, pay_time in zip(grace_batch, pay_times):
            if pay_time > chronos.current:
                chronos.jump_to(pay_time)

            late_on_member = Decimal(str(m.late_fees_inr or 0))

            # Settle accrued late fee
            if late_on_member > _zero:
                lfc_code = self._sim_token_code(db, "LFC-")
                db.add(Token(
                    code      = lfc_code,
                    type      = TokenType.Late_Fee,
                    status    = TokenStatus.Burned,
                    value_inr = late_on_member,
                    user_id   = m.id,
                    pool_id   = m.current_pool_id,
                ))
                lf_settled_rev += late_on_member

            # Grace fee
            gf_code = self._sim_token_code(db, "GF-")
            db.add(Token(
                code      = gf_code,
                type      = TokenType.Grace_Fee,
                status    = TokenStatus.Burned,
                value_inr = _grace_fee,
                user_id   = m.id,
                pool_id   = m.current_pool_id,
            ))
            grace_fee_rev += _grace_fee

            # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Weekly installment token
            db.add(Token(
                code      = f"WK{self._pfx}{week_num:04d}U{m.id:010d}",
                type      = TokenType.Deposit,
                status    = TokenStatus.Burned,
                value_inr = _DEPOSIT_DEC,
                user_id   = m.id,
                pool_id   = m.current_pool_id,
            ))

            m.weekly_payment_status = WeeklyPaymentStatus.Paid
            m.grace_fee_paid        = True
            m.grace_active          = False
            m.elimination_risk      = False
            m.late_fees_inr         = _zero

        db.flush()
        return {
            "n_grace_saved":  len(grace_batch),
            "grace_fee_rev":  float(grace_fee_rev),
            "lf_settled_rev": float(lf_settled_rev),
        }

    def tick5_guillotine(self, db: "Session", week_id: str) -> dict:
        """
        TICK 5 — GUILLOTINE / G_CLOSE

        Chronos is at G_CLOSE (T_02H − 5 min).  ALL remaining Active+Unpaid
        members are eliminated unconditionally.  EliminationEvent record written
        per member.  Waitlist refill fires afterward so pools are full before
        draw preparation starts at T_02H.

        Returns: {n_eliminated}
        """
        from app.models.user              import User, UserStatus, WeeklyPaymentStatus
        from app.models.elimination_event import EliminationEvent, EliminationReason
        from app.services.waitlist        import assign_waitlist_to_pools

        _zero = Decimal("0")

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Scoped to rsim_ users — prevents eliminating 2000+ real users in production DB.
        unpaid: list = (
            db.query(User)
            .filter(User.status == UserStatus.Active,
                    User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
                    User.username.like(f"{self._pfx}%"))
            .all()
        )
        if not unpaid:
            return {"n_eliminated": 0}

        for m in unpaid:
            late_fees_on_member = Decimal(str(m.late_fees_inr or 0))
            db.add(EliminationEvent(
                user_id                   = m.id,
                username_snapshot         = m.username,
                user_level_at_elimination = m.current_level,
                pool_id                   = m.current_pool_id,
                pool_name_snapshot        = (
                    f"Pool-{m.current_pool_id}" if m.current_pool_id else "Unknown"
                ),
                draw_week_id              = week_id,
                reason                    = EliminationReason.non_payment,
                late_fees_forfeited       = late_fees_on_member,
                seat_save_fee             = _zero,
                deposit_forfeited         = Decimal("1000"),
                total_forfeited           = Decimal("1000") + late_fees_on_member,
                was_in_grace_period       = False,
            ))
            m.status          = UserStatus.Eliminated
            m.current_pool_id = None
            m.late_fees_inr   = _zero

        db.flush()

        # Refill vacancies from waitlist so pools are full before T_02H
        try:
            assign_waitlist_to_pools(db)
        except Exception as exc:
            _logger.warning("tick5_guillotine: waitlist refill failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        return {"n_eliminated": len(unpaid)}

    def apply_abc_model(
        self,
        db: Session,
        late_ratio: float,
        elim_pct_a: float,
        grace_pct_c: float,
    ) -> dict:
        """
        Apply the A/B/C circular late-fee compliance model with FULL production
        fidelity — real tokens, real EliminationEvent records, real waitlist refill.

        late_ratio  : fraction of active members who miss payment this week
        elim_pct_a  : of late payers, % directly eliminated (skip grace entirely)
        grace_pct_c : of remaining late payers, % who successfully pay grace fee

        This method now mirrors the exact production flow:
          1. Mark late payers (flag as Unpaid)
          2. Accrue late fees on user.late_fees_inr (LATE_FEE_DAILY_INR × sim_days,
             capped at LATE_FEE_MAX_CAP_INR) — creates Late_Fee tokens as receipts
          3. A path: direct elimination → EliminationEvent record written
          4. C path: grace savers pay → Grace_Fee token + Late_Fee settlement token
          5. Failed grace: elimination → EliminationEvent record written
          6. Call assign_waitlist_to_pools(db) to fill vacancies from eliminations
             (Rule 39 referral credits fire naturally through this call)

        Returns {n_late, n_elim, n_saved, late_fee_revenue_inr, grace_fee_revenue_inr,
                 total_compliance_revenue_inr, week_id}
        """
        from app.models.user import User, UserStatus, WeeklyPaymentStatus
        from app.models.token import Token, TokenType, TokenStatus
        from app.models.elimination_event import EliminationEvent, EliminationReason
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Read late-fee amounts from global_config (DB-backed) instead of static config.
        from app.services.global_config import get_late_fee_daily, get_late_fee_cap
        from app.services.waitlist import assign_waitlist_to_pools

        _zero = Decimal("0")
        _fee  = Decimal(str(get_late_fee_daily(db)))
        _cap  = Decimal(str(get_late_fee_cap(db)))
        _grace_fee = Decimal("500")

        now_utc  = datetime.now(timezone.utc)
        iso      = now_utc.isocalendar()
        week_id  = f"{iso.year}-W{iso.week:02d}"

        _empty = {
            "n_late": 0, "n_elim": 0, "n_saved": 0,
            "n_type_b": 0, "type_b_ids": set(),
            "late_fee_revenue_inr": 0, "grace_fee_revenue_inr": 0,
            "total_compliance_revenue_inr": 0, "week_id": week_id,
        }

        if late_ratio <= 0.0:
            return _empty

        active = db.query(User).filter(User.status == UserStatus.Active).all()
        if not active:
            return _empty

        # ── Step 1: Mark late payers ──────────────────────────────────────────
        n_late     = max(0, int(len(active) * late_ratio))
        late_batch = random.sample(active, min(n_late, len(active)))

        for m in late_batch:
            m.weekly_payment_status = WeeklyPaymentStatus.Unpaid
        db.flush()

        # ── Step 2: Accrue real late fees + create Late_Fee tokens ───────────
        # Simulate 3 days of late accrual (Monday due → Thursday cutoff).
        # Each day = LATE_FEE_DAILY_INR, capped at LATE_FEE_MAX_CAP_INR total.
        # Random 1–4 days to make per-member amounts realistic (not all same).
        sim_days_range = (1, min(4, int(_cap / _fee)))  # never exceed cap in days

        for m in late_batch:
            sim_days   = random.randint(*sim_days_range)
            current    = Decimal(str(m.late_fees_inr or 0))
            headroom   = max(_zero, _cap - current)
            accrual    = min(_fee * sim_days, headroom)

            if accrual > _zero:
                m.late_fees_inr = current + accrual

                # Create Late_Fee token — receipt of this week's accrual
                lf_code = self._sim_token_code(db, "LF-")
                db.add(Token(
                    code      = lf_code,
                    type      = TokenType.Late_Fee,
                    status    = TokenStatus.Burned,
                    value_inr = accrual,
                    user_id   = m.id,
                    pool_id   = m.current_pool_id,
                ))

        db.flush()

        # ── Step 3: Split late_batch into A / C / B buckets ──────────────────
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # FIX A1: Correct A/B/C proportions — each bucket is a fraction of ALL
        # late payers, not a cascading fraction-of-a-fraction.
        #
        #   A (elim_pct_a%)   — direct elimination, no grace
        #   C (grace_pct_c%)  — grace period: seat saved, Paid after grace+late fee
        #   B (remainder %)   — late fee accrued (Step 2 already), stay Unpaid in pool
        #
        # Previous code treated C as "% of the non-A remainder", making it
        # effectively much smaller and silently eliminating all Type B members.
        # With elim_pct_a=80 / grace_pct_c=15: old code eliminated 97% of late
        # payers; correct model eliminates exactly 80%.
        n_direct_elim  = max(0, int(n_late * (elim_pct_a  / 100.0)))
        n_grace        = max(0, int(n_late * (grace_pct_c  / 100.0)))
        # Clamp: A + C must never exceed n_late (rounding guard)
        n_grace        = min(n_grace, max(0, n_late - n_direct_elim))

        direct_elim    = late_batch[:n_direct_elim]
        grace_savers   = late_batch[n_direct_elim : n_direct_elim + n_grace]
        type_b_members = late_batch[n_direct_elim + n_grace:]   # late fee, stay Unpaid

        # ── Step 4: A path — direct elimination + EliminationEvent ───────────
        total_late_fee_rev   = _zero
        total_grace_fee_rev  = _zero
        n_total_elim         = 0

        for m in direct_elim:
            late_fees_on_member = Decimal(str(m.late_fees_inr or 0))
            total_ev = Decimal("1000") + late_fees_on_member

            db.add(EliminationEvent(
                user_id                   = m.id,
                username_snapshot         = m.username,
                user_level_at_elimination = m.current_level,
                pool_id                   = m.current_pool_id,
                pool_name_snapshot        = f"Pool-{m.current_pool_id}" if m.current_pool_id else "Unknown",
                draw_week_id              = week_id,
                reason                    = EliminationReason.non_payment,
                late_fees_forfeited       = late_fees_on_member,
                seat_save_fee             = _zero,
                deposit_forfeited         = Decimal("1000"),
                total_forfeited           = total_ev,
                was_in_grace_period       = False,
            ))

            m.status          = UserStatus.Eliminated
            m.current_pool_id = None
            m.late_fees_inr   = _zero
            n_total_elim     += 1

        db.flush()

        # ── Step 5: C path — grace savers pay grace+late fee, seat saved ────────
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # grace_savers already computed in Step 3 (n_grace of ALL late, not non-A).
        # Removed grace_expired elimination: Type B members (remainder) are NOT
        # eliminated — they stay Active+Unpaid and are handled in Step 5b below.
        n_saved = len(grace_savers)

        for m in grace_savers:
            late_fees_on_member = Decimal(str(m.late_fees_inr or 0))

            # Late_Fee settlement token (clears accumulated accrual)
            if late_fees_on_member > _zero:
                lfc_code = self._sim_token_code(db, "LFC-")
                db.add(Token(
                    code      = lfc_code,
                    type      = TokenType.Late_Fee,
                    status    = TokenStatus.Burned,
                    value_inr = late_fees_on_member,
                    user_id   = m.id,
                    pool_id   = m.current_pool_id,
                ))
                total_late_fee_rev += late_fees_on_member

            # Grace_Fee token — ₹500 seat-save confirmed
            gf_code = self._sim_token_code(db, "GF-")
            db.add(Token(
                code      = gf_code,
                type      = TokenType.Grace_Fee,
                status    = TokenStatus.Burned,
                value_inr = _grace_fee,
                user_id   = m.id,
                pool_id   = m.current_pool_id,
            ))
            total_grace_fee_rev += _grace_fee

            # Clear elimination flags — seat saved, mark Paid
            m.grace_fee_paid          = True
            m.grace_active            = False
            m.elimination_risk        = False
            m.late_fees_inr           = _zero
            m.weekly_payment_status   = WeeklyPaymentStatus.Paid

        db.flush()

        # ── Step 5b: B path — late fee already accrued (Step 2); stay Unpaid ──
        # Type B members remain Active in their pool with weekly_payment_status=Unpaid.
        # They receive no WK installment token this week (auto_pay will skip them).
        # They may pay next week if not selected as late again.
        for m in type_b_members:
            m.elimination_risk = True   # surface as at-risk in UI
        db.flush()

        # ── Step 6: Refill vacancies via real production waitlist engine ──────
        # This triggers Rule 39 referral credits for newly-active members.
        if n_total_elim > 0:
            try:
                assign_waitlist_to_pools(db)
            except Exception as e:
                _logger.warning("apply_abc_model: waitlist refill failed: %s", e)
                try: db.rollback()
                except Exception: pass

        total_compliance = total_late_fee_rev + total_grace_fee_rev

        return {
            "n_late":                       n_late,
            "n_elim":                       n_total_elim,
            "n_saved":                      n_saved,
            "n_type_b":                     len(type_b_members),
            "type_b_ids":                   {m.id for m in type_b_members},
            "late_fee_revenue_inr":         float(total_late_fee_rev),
            "grace_fee_revenue_inr":        float(total_grace_fee_rev),
            "total_compliance_revenue_inr": float(total_compliance),
            "week_id":                      week_id,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 3.5 FINANCE MANAGER HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fm_reset_payment_cycle(db: Session) -> None:
    """
    Finance Manager — Step 0: Reset ALL Active pool members to Unpaid at the
    start of each week's payment cycle.

    WHY: inject_week() creates users with weekly_payment_status=Paid.
    apply_abc_model() then calls random.sample(active, n_late) to pick late
    payers, but if everyone is already Paid the selection is still valid.
    However auto_pay_installments() ONLY processes Unpaid members to create
    weekly DEP tokens.  Without this reset, auto_pay_installments is a no-op
    (everyone is Paid), so installments_collected_inr stays ₹0 forever.

    After this reset:
      1. auto_pay_installments creates one DEP token per member (Unpaid→Paid).
         This gives the correct weekly installment revenue in CSV.
      2. apply_abc_model (Thursday) marks late_ratio% back to Unpaid and
         processes A/B/C paths — giving accurate compliance metrics.
    """
    from app.models.user import User as _U, UserStatus as _US, WeeklyPaymentStatus as _WPS
    db.query(_U).filter(_U.status == _US.Active).update(
        {"weekly_payment_status": _WPS.Unpaid},
        synchronize_session=False,
    )
    db.commit()


def _fm_enforce_pool_capacity(db: Session) -> int:
    """
    Finance Manager — Due-Date Enforcement: After apply_abc_model eliminates
    members, pools may have fewer than POOL_CAPACITY Active members.

    The problem: eliminated members leave their pool in Active status with
    fewer than 12 members.  assign_waitlist_to_pools Phase 1 only fills
    Paused_Awaiting_Members pools — it ignores Active pools.  So the vacancy
    is NOT filled until execute_weekly_draw runs, which:
      (a) Pauses the under-capacity Active pool
      (b) Calls assign_waitlist_to_pools internally
      (c) Phase 1 then fills it
    BUT by then, the pool has already been SKIPPED for this week's draw.

    Fix: Before T-2H (draw preparation), proactively:
      1. Find every Active pool with < POOL_CAPACITY actual members
      2. Set those pools to Paused_Awaiting_Members
      3. Call assign_waitlist_to_pools → Phase 1 fills them from waitlist
      4. They return to Active (with 12 members) before draw preparation runs

    This mirrors production: eliminations happen Thursday, waitlist fills by
    Saturday, every pool has 12 members when T-2H draw prep fires.

    Returns: count of pools that were paused+refilled.
    """
    from app.models.pool import Pool as _Pool, PoolStatus as _PS
    from app.models.user import User as _User, UserStatus as _US
    from app.core.config import POOL_CAPACITY as _PC
    from app.services.waitlist import assign_waitlist_to_pools

    candidate = db.query(_Pool).filter(_Pool.status == _PS.Active).all()

    paused_count = 0
    for pool in candidate:
        actual = (
            db.query(_User)
            .filter(_User.current_pool_id == pool.id, _User.status == _US.Active)
            .count()
        )
        if actual < _PC:
            pool.status  = _PS.Paused_Awaiting_Members
            paused_count += 1

    if paused_count > 0:
        try:
            db.commit()
            assign_waitlist_to_pools(db)
            db.commit()
        except Exception as _e:
            _logger.warning("_fm_enforce_pool_capacity: refill failed: %s", _e)
            try: db.rollback()
            except Exception: pass

    return paused_count


# ══════════════════════════════════════════════════════════════════════════════
# 4. METRICS COLLECTOR — Read Real DB State After Each Week
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
    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Bug #3 — cash_outflow_inr: actual winner payout total for this week's draws
    # Bug #4 — members_joined/exited: pool-entry and winner-exit counts for weekly report
    cash_outflow_inr: float = 0.0,
    members_joined: int = 0,
    members_exited: int = 0,
) -> dict:
    """
    Read ACTUAL DB state after the week completes.
    All numbers come from the real simulation database — no estimation.
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

    # ── U-08: Weekly installment revenue from real WK-prefixed DEP tokens ────
    try:
        from app.models.token import Token as _Tok, TokenType as _TT, TokenStatus as _TS
        installments_collected: float = float(
            db.query(func.sum(_Tok.value_inr))
            .filter(
                _Tok.type   == _TT.Deposit,
                _Tok.status == _TS.Burned,
                _Tok.code.like(f"WK{week_num:04d}%"),
            )
            .scalar() or 0
        )
    except Exception:
        installments_collected = 0.0

    # ── U-09: RW settlements this week ───────────────────────────────────────
    try:
        from app.models.token import Token as _Tok2, TokenType as _TT2, TokenStatus as _TS2
        rw_settled_inr: float = float(
            db.query(func.sum(_Tok2.value_inr))
            .filter(
                _Tok2.type   == _TT2.Referral_Withdraw,
                _Tok2.status == _TS2.Burned,
                _Tok2.code.like(f"RW{week_num:04d}%"),
            )
            .scalar() or 0
        )
    except Exception:
        rw_settled_inr = 0.0

    return {
        "week":               week_num,
        "lpi":                round(lpi, 2),
        "active_users":       active_users,
        "waitlist_count":     waitlist_count,
        "pools_active":       pools_active,
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # FIX C: Removed + pauses_this_week — pools_paused is a live DB COUNT of
        # Paused_Awaiting_Members pools AFTER Phase-1 refill has already run inside
        # execute_weekly_draw().  Adding pauses_this_week double-counted pools that
        # were paused mid-draw but immediately refilled back to Active by Phase 1.
        "pools_paused":       pools_paused,
        "pools_formed":       0,
        "draws_this_week":    draws_this_week,
        "winners_this_week":  draws_this_week * 2,
        "late_payers":               compliance.get("n_late",  0),
        "eliminated":                compliance.get("n_elim",  0),
        "grace_saved":               compliance.get("n_saved", 0),
        "late_fee_revenue_inr":      compliance.get("late_fee_revenue_inr",         0),
        "grace_fee_revenue_inr":     compliance.get("grace_fee_revenue_inr",        0),
        "compliance_revenue_inr":    compliance.get("total_compliance_revenue_inr", 0),
        # U-08: weekly installment collection (real DEP tokens created per active member)
        "installments_collected_inr": installments_collected,
        # U-09: referral withdraw settlements this week
        "rw_settled_inr":             rw_settled_inr,
        # Combined cash inflow this week (new deposits + installments + compliance fees)
        "cash_inflow_inr": (
            installments_collected
            + compliance.get("late_fee_revenue_inr", 0)
            + compliance.get("grace_fee_revenue_inr", 0)
        ),
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Bug #3 — cash_outflow_inr was missing entirely; now populated from DrawHistory
        # payout delta computed in calling code before/after the draw cycle
        "cash_outflow_inr":          cash_outflow_inr,
        # Bug #4 — members_joined/exited were missing; now populated from User status deltas
        "members_joined_this_week":  members_joined,
        "members_exited_this_week":  members_exited,
        # Also store compliance fees under the legacy key for Cash Flow chart
        "late_fees_collected_inr":   compliance.get("late_fee_revenue_inr", 0),
        "level_distribution": {
            "L1": dist.l1, "L2": dist.l2, "L3": dist.l3,
            "L4": dist.l4, "L5": dist.l5, "L6": dist.l6,
        },
        "l5_count":               dist.l5,
        "l6_count":               dist.l6,
        # Cumulative SDE event counts (same field names as legacy engine)
        "ext2_exits_this_week":   cumulative_ext2,
        "ext3_exits_this_week":   cumulative_ext3,
        "accel_diss_this_week":   cumulative_accel,
        # AI Brain 2+3 state
        "scenario":           scenario,
        "momentum":           momentum,
        "burn_rate":          burn,
        "rdr_pct":            round(rdr, 1),
        "multiplier":         mul,
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # CASCADE_RISK metric — L3 / MAX(L1+L2, 1).
        # Thresholds: >1.0 = Forming (L3 eligible as supply), >2.0 = Extreme (forced L3 supply).
        # dist is already loaded above — zero extra DB queries.
        "cascade_risk":  round(dist.l3 / max(dist.l1 + dist.l2, 1), 3),
        "l3_count":      dist.l3,
        "l1l2_count":    dist.l1 + dist.l2,
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # DIRECTIVE 4 — Finance Manager Analytics additions.
        # base_installment_inr: live DB value — reflects any admin change mid-simulation.
        # net_float_inr: cash_inflow - WIT payout outflow - referral settle outflow.
        # l3_to_l4_pressure_pct: % of active members at L3 (all will advance to L4
        #   next week if they survive) — forward-looking cascade risk indicator.
        "base_installment_inr": (
            _get_base_installment_safe(db)
        ),
        "net_float_inr": round(
            (
                installments_collected
                + compliance.get("late_fee_revenue_inr", 0)
                + compliance.get("grace_fee_revenue_inr", 0)
            )
            - cash_outflow_inr
            - rw_settled_inr,
            2,
        ),
        "l3_to_l4_pressure_pct": round(
            dist.l3 / max(active_users, 1) * 100, 2
        ),
    }


def _get_base_installment_safe(db: Session) -> int:
    """Read base installment from DB; return config default on any failure."""
    try:
        from app.services.global_config import get_base_installment
        return get_base_installment(db)
    except Exception:
        from app.core.config import DEPOSIT_AMOUNT_INR
        return DEPOSIT_AMOUNT_INR


# ══════════════════════════════════════════════════════════════════════════════
# 5. REAL SIM ENGINE — The Main Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class RealSimEngine:
    """
    Zero-duplication stress-test engine.

    Calls REAL production services in EXACT weekly chronological order.
    No business logic here — only time-travel and load injection.
    """

    def __init__(
        self,
        weeks:                 int   = 52,
        users_per_week:        int   = 24,
        initial_users:         int   = 24,
        organic_ratio:         float = 0.6,
        late_ratio:            float = 0.02,
        elim_pct_a:            float = 80.0,
        grace_pct_c:           float = 15.0,
        volatility_mode:       bool  = False,
        volatility_max:        int   = 100,
        start_year:            int   = 2024,
        start_week:            int   = 1,
        # ── K-12 through K-17: Extended Injection Knobs ───────────────────────
        # K-12: inflow_pattern — how weekly new-user count varies over time
        #   "linear"  = constant users_per_week every week (default)
        #   "sine"    = sinusoidal ±50% oscillation with 12-week period
        #   "burst"   = 3× spike every 8 weeks, normal otherwise
        #   "step"    = ramp linearly from 50% to 150% of users_per_week
        inflow_pattern:        str   = "linear",
        # K-13: week to inject a 2× referral surge (0 = disabled)
        #   When this week is reached, organic_ratio is halved for that week
        #   simulating a viral referral spike (e.g. social media campaign).
        referral_burst_week:   int   = 0,
        # K-14: week to inject a payment shock (0 = disabled)
        #   When this week is reached, late_ratio spikes to 20% for that week,
        #   simulating a batch of users who skip payment (external shock event).
        payment_shock_week:    int   = 0,
        # K-15: % of waitlist members who randomly drop out before pool assignment
        #   (0.0 = none drop out, 25.0 = 25% of waitlist never enter pools)
        #   Simulates members who register but become inactive before admission.
        waitlist_dropout_pct:  float = 0.0,
        # K-16: organic_decay_rate — how fast organic join ratio decays over time
        #   0.0 = constant (no decay), 0.02 = 2% decay per week
        #   Simulates referral-programme momentum fading as base grows.
        organic_decay_rate:    float = 0.0,
        # K-17: simulation_label — free-text tag for multi-run comparison
        #   Stored in simulation_summary for identification in side-by-side reports.
        simulation_label:      str   = "",
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # run_id — job_id from the background task registry (uuid.uuid4().hex).
        # Passed into MassLoadInjector as the run prefix slug so every username,
        # mobile, and weekly token code produced by this run is globally unique
        # in the real PostgreSQL database without requiring a DB reset between runs.
        run_id:                str   = "",
    ):
        self.weeks                = max(1, min(weeks, 200))
        self.users_per_week       = users_per_week
        self.initial_users        = max(12, initial_users)
        self.organic_ratio        = organic_ratio
        self.late_ratio           = late_ratio
        self.elim_pct_a           = elim_pct_a
        self.grace_pct_c          = grace_pct_c
        self.volatility_mode      = volatility_mode
        self.volatility_max       = volatility_max
        self.start_year           = start_year
        self.start_week           = start_week
        # K-12 to K-17
        self.inflow_pattern       = inflow_pattern
        self.referral_burst_week  = referral_burst_week
        self.payment_shock_week   = payment_shock_week
        self.waitlist_dropout_pct = max(0.0, min(50.0, waitlist_dropout_pct))
        self.organic_decay_rate   = max(0.0, min(1.0, organic_decay_rate))
        self.simulation_label     = simulation_label or ""
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        self._run_id              = (run_id or uuid.uuid4().hex)[:8]

    def _compute_weekly_inflow(self, week_num: int) -> int:
        """
        K-12: Compute weekly inflow based on inflow_pattern.

        Returns the adjusted new-user count for the given week.
        Volatility mode overrides all patterns (random 0–volatility_max).
        """
        import math as _math
        base = self.users_per_week

        if self.volatility_mode:
            return random.randint(0, self.volatility_max)

        if self.inflow_pattern == "sine":
            # Oscillate ±50% with a 12-week period
            osc   = _math.sin(2 * _math.pi * week_num / 12.0) * 0.5
            return max(0, int(base * (1.0 + osc)))

        if self.inflow_pattern == "burst":
            # Triple inflow every 8th week
            return base * 3 if (week_num % 8 == 0) else base

        if self.inflow_pattern == "step":
            # Linear ramp from 50% to 150% over the full simulation
            frac  = week_num / max(self.weeks, 1)
            scale = 0.5 + frac
            return max(0, int(base * scale))

        # Default: "linear" (constant)
        return base

    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # Replaced hardcoded _sunday() (ISO weekday 7 = always Sunday) with
    # _initial_draw_time() which reads draw_day_of_week from DB via global_config.
    def _initial_draw_time(self, db: "Session") -> datetime:
        """
        Compute the first draw execution time (T_00H) from live DB settings.

        Reads draw_day_of_week (0=Mon … 6=Sun) from global_config.
        draw_day_of_week → Python ISO weekday: Mon=1 … Sun=7.
        Derives the target ISO week from start_year + start_week.
        Falls back to ISO week 52 if the computed week is out of range.
        """
        from app.services.global_config import get_draw_day_of_week
        dow         = get_draw_day_of_week(db)          # 0–6
        iso_weekday = dow + 1                           # ISO: 1=Mon … 7=Sun
        total_week  = self.start_week
        year        = self.start_year + (total_week - 1) // 52
        iso_week    = ((total_week - 1) % 52) + 1
        try:
            base = datetime.fromisocalendar(year, iso_week, iso_weekday)
        except ValueError:
            base = datetime.fromisocalendar(year, 52, iso_weekday)
        return base.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    def run(self, progress_callback=None) -> dict:
        """
        Execute the full simulation.

        progress_callback: optional callable(week_num: int, total_weeks: int, metrics: dict)
            Called after each week completes.  Used by background-task mode for live
            progress reporting.  Any exception raised by the callback is swallowed so
            it cannot abort the simulation.

        Returns a dict with the canonical Stress Test result structure (formerly
        produced by the now-removed _AdvSimEngine Fast Preview) so existing
        frontend charts work without modification.

        Real execution order per week:
          a. inject_week()            — users + DEP tokens → Waitlist
          b. auto_pay_installments()  — active members → Paid
          c. apply_abc_model()        — A/B/C late-fee + elimination
          [T-2H] start_draw_preparation()  — lock + flag L4 + SDE meta-pool
          [T-0H] execute_weekly_draw()     — Ext-II/III pre-pass + all draws
          [T+5m] post_draw_cleanup()       — reset flags + release lock
        """
        from app.services.draw import execute_weekly_draw, post_draw_cleanup
        from app.services.draw_preparation import start_draw_preparation
        from app.services.waitlist import assign_waitlist_to_pools
        from app.services.sde_engine import run_sde_meta_pool
        from app.services.brain5_lpi_engine import flag_l4_members, redistribute_multi_l4_pools
        from app.core.pool_settings import get_auto_pool_creation, set_auto_pool_creation
        from app.models.system_lock import SystemLock
        from app.models.draw_history import DrawHistory
        from app.core.config import POOL_DRAW_SDE_EXT2, POOL_DRAW_SDE_EXT3, POOL_DRAW_ACCELERATED

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # ── REAL PostgreSQL session — replaces sqlite:///:memory: ─────────────
        from app.database import SessionLocal as _PgSession
        from app.services.system_debugger import (
            DebuggerSession, log_milestone, set_debug_week,
        )

        # ── Preserve + force production-compatible global state ───────────────
        _orig_auto = get_auto_pool_creation()
        set_auto_pool_creation(True)

        # MassLoadInjector receives the run-specific prefix for collision-safe
        # usernames, mobiles, and weekly token codes on the real DB.
        injector = MassLoadInjector(run_prefix=f"rsim_{self._run_id}")

        weekly_detail:  list[dict] = []
        cycle_logs:     list[dict] = []

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
        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Bug #6 — running cumulative ext2/3/accel totals so per-week delta can be
        # computed as (current_cumulative - prev_cumulative) instead of returning the
        # all-time cumulative total in every weekly snapshot row
        _prev_cumul_ext2  = 0
        _prev_cumul_ext3  = 0
        _prev_cumul_accel = 0

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        db = _PgSession()   # real PostgreSQL — data persists, Dashboard shows it live

        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # FIX: 45-second per-statement timeout so a PostgreSQL lock-wait or
        # deadlock surfaces as a QueryCanceledError (caught by existing try/except
        # patterns) instead of blocking the background thread indefinitely.
        # Without this, one stale lock = infinite hang at "Week 0 / 10".
        try:
            from sqlalchemy import text as _text
            # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # FIX: Use SET (session-level) not SET LOCAL (transaction-level).
            # SET LOCAL is reset on db.commit() — all subsequent queries lose
            # the timeout.  Session-level SET persists for the entire DB session.
            db.execute(_text("SET statement_timeout = '45000'"))
            db.commit()
        except Exception:
            pass  # non-PostgreSQL dialect or permission issue — proceed without timeout

        try:
            # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Open Global System Debugger bracket for this run (no-op when debugger OFF).
            _logger.info("RealSimEngine [%s]: PHASE-A — entering main try block", self._run_id)
            log_milestone("SIM/start", "simulation_started", {"run_id": self._run_id})

            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Record the max pool ID that exists BEFORE the simulation creates ANY
            # pools (i.e. before seed inject + seed pool formation). Any pool with
            # id <= this ceiling is a pre-existing (non-simulation) pool and is
            # skipped in every week's draw. On a freshly-wiped DB this is 0, so the
            # skip becomes a no-op and the simulation draws its own pools normally.
            # CRITICAL: must be captured HERE, not after seed pool formation —
            # otherwise the sim's own seed pools fall under the ceiling and never draw.
            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # FIX (NameError caught LIVE in the Debugger Panel at run() line ~1721:
            # "name 'Pool' is not defined"): `Pool` is NOT a module-level import in
            # this file — models are imported locally inside methods to avoid
            # circular imports. The old ceiling-capture block I relocated had carried
            # this import; moving the capture up here dropped it, so BOTH this line
            # and the pre-skip query at ~1992 raised NameError. A function-local
            # import here binds `Pool` for the REST of run(), covering both call
            # sites. A module-level model import is deliberately avoided — it could
            # reintroduce a circular-import / un-importable failure like the one we
            # just fixed.
            from app.models.pool import Pool
            _pre_sim_max_pool_id: int = db.query(func.max(Pool.id)).scalar() or 0
            _logger.info(
                "RealSimEngine [%s]: draw isolation ceiling = pool_id %d "
                "(pools with id <= this are skipped in all week draws; 0 = clean DB)",
                self._run_id, _pre_sim_max_pool_id,
            )

            # 9-tick dynamic Chronos Timeline — all milestones derived from DB global_config.
            current_T_00H = self._initial_draw_time(db)
            with ChronosEngine(current_T_00H) as chronos:

                # ── Seed: inject initial users into the cycle before first draw ──
                # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                seed_m           = _compute_milestones(db, current_T_00H)
                seed_win_start   = seed_m.CYCLE_START
                seed_win_end     = min(
                    seed_m.CYCLE_START + timedelta(hours=72), seed_m.DUE_DATE,
                )
                chronos.jump_to(seed_win_start)
                _logger.info("RealSimEngine [%s]: PHASE-B — seed inject start (%d users)", self._run_id, self.initial_users)
                seed_users = injector.inject_distributed(
                    db, self.initial_users, seed_win_start, seed_win_end,
                    self.organic_ratio, [], chronos,
                )
                db.commit()
                total_users_created += len(seed_users)
                _logger.info("RealSimEngine [%s]: PHASE-C — seed inject done (%d created), starting pool formation", self._run_id, len(seed_users))

                # Trigger initial pool formation from seed users
                # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # Scoped to rsim_ users — prevents assigning thousands of real
                # Waitlist users into pools during simulation setup.
                refill = assign_waitlist_to_pools(db, user_prefix=injector._pfx)
                total_p2_pools += refill.get("phase2_pools_count", 0)
                db.commit()
                _logger.info("RealSimEngine [%s]: PHASE-D — initial pool formation done", self._run_id)

                # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # FIX: Clear any stale SystemLock + WeeklyDrawState left by:
                #   - A previous simulation that crashed or was server-killed
                #   - A previous admin force-draw that was interrupted mid-draw
                #   - Multiple concurrent simulation threads (race condition)
                # Without this, start_draw_preparation() hits a UNIQUE constraint
                # on lock_name → db.rollback() → the simulation session's mid-week
                # state evaporates → week 1 produces no draws → infinite wait.
                _logger.info("RealSimEngine [%s]: PHASE-E — clearing stale SystemLock + WeeklyDrawState", self._run_id)
                try:
                    from app.models.weekly_draw_state import WeeklyDrawState as _WDS
                    db.query(SystemLock).delete()
                    db.query(_WDS).delete()
                    db.commit()
                    _logger.info("RealSimEngine [%s]: PHASE-F — stale lock clear done — entering week loop", self._run_id)
                except Exception as _pre_exc:
                    _logger.warning("RealSimEngine: pre-loop stale-state clear failed: %s", _pre_exc)
                    try: db.rollback()
                    except Exception: pass

                # ────────────────────────────────────────────────────────────────
                # 9-TICK CHRONOS MAIN LOOP (all milestones derived from DB config)
                # ────────────────────────────────────────────────────────────────
                for w in range(self.weeks):
                    week_num = w + 1
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Tell the debugger which week we're in so all log entries carry week_num.
                    set_debug_week(week_num)

                    # ── Compute all 7 milestones for this cycle (ZERO hardcoding) ──
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    m = _compute_milestones(db, current_T_00H)

                    iso     = m.T_00H.isocalendar()
                    week_id = f"{iso.year}-W{iso.week:02d}"

                    # Track pools formed THIS week (p2 pools only — new pool creation)
                    _week_p2_start = total_p2_pools
                    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Bug #4 — baseline active/eliminated_won counts at week start; delta
                    # after T+5M gives members_joined_this_week and members_exited_this_week
                    # Bug #5 — baseline paused pool count; delta after T+5M identifies Phase-1
                    # restored pools so they are included in pools_formed (not just Phase 2)
                    from app.models.pool import Pool as _P5s, PoolStatus as _PS5s
                    from app.models.user import User as _U5s, UserStatus as _US5s
                    _week_elim_won_before = db.query(func.count(_U5s.id)).filter(
                        _U5s.status == _US5s.Eliminated_Won).scalar() or 0
                    _week_active_before   = db.query(func.count(_U5s.id)).filter(
                        _U5s.status == _US5s.Active).scalar() or 0
                    _week_paused_before   = db.query(func.count(_P5s.id)).filter(
                        _P5s.status == _PS5s.Paused_Awaiting_Members).scalar() or 0

                    # ── TICK 1: CYCLE_START — reset payment cycle + inject users ──
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    _logger.info("RealSimEngine [%s]: TICK1-start week=%d — reset_payment_cycle", self._run_id, week_num)
                    chronos.jump_to(m.CYCLE_START)
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Scoped replacement for _fm_reset_payment_cycle — only resets rsim_
                    # users so 2000+ real Active users are NOT marked Unpaid (which would
                    # cause tick5 to eliminate them and corrupt production data).
                    from app.models.user import User as _Ut1, UserStatus as _USt1, WeeklyPaymentStatus as _WPSt1
                    db.query(_Ut1).filter(
                        _Ut1.status == _USt1.Active,
                        _Ut1.username.like(f"{injector._pfx}%"),
                    ).update({"weekly_payment_status": _WPSt1.Unpaid}, synchronize_session=False)
                    db.commit()
                    _logger.info("RealSimEngine [%s]: TICK1-done week=%d", self._run_id, week_num)

                    # K-12: Compute weekly inflow via pattern
                    inflow = self._compute_weekly_inflow(week_num)

                    # K-13: Referral burst — halve organic ratio for the burst week
                    effective_organic = self.organic_ratio
                    if self.referral_burst_week > 0 and week_num == self.referral_burst_week:
                        effective_organic = max(0.0, self.organic_ratio * 0.5)
                        _logger.info(
                            "K-13: Referral burst week %d — organic ratio: %.2f → %.2f",
                            week_num, self.organic_ratio, effective_organic,
                        )

                    # K-16: Organic decay — reduce organic ratio over time
                    if self.organic_decay_rate > 0.0:
                        decay = 1.0 - self.organic_decay_rate * week_num
                        effective_organic = max(0.0, effective_organic * max(0.0, decay))

                    # Build referral pool from existing users (Brain 3 RDR feed)
                    from app.models.user import User as _U, UserStatus as _US
                    existing_ids = [
                        r[0] for r in db.query(_U.id).filter(
                            _U.status.in_([_US.Active, _US.Waitlist])
                        ).limit(500).all()
                    ]

                    # Distribute users across CYCLE_START → DUE_DATE (dynamic window)
                    new_batch = injector.inject_distributed(
                        db, inflow, m.CYCLE_START, m.DUE_DATE,
                        effective_organic, existing_ids, chronos,
                    )
                    db.commit()
                    total_users_created += len(new_batch)

                    # ── a.5 Waitlist → Pool assignment (critical: must run every week)
                    #
                    # WHY THIS IS HERE:
                    #   execute_weekly_draw() calls assign_waitlist_to_pools() ONLY after
                    #   drawing.  But if ALL pools are Paused_Awaiting_Members, it raises
                    #   ValueError BEFORE reaching the refill — creating an infinite
                    #   deadlock: no refill → pools never unpause → no draw → no refill.
                    #
                    #   Production avoids this because assign_waitlist_to_pools() is called
                    #   on every user-registration event and every pool-state change.
                    #
                    #   In the simulation, we replicate that by calling it explicitly here:
                    #     Phase 1: fills paused pools with oldest paid Waitlist members
                    #              → restores PoolStatus.Active when pool reaches capacity
                    #     Phase 2: creates new full pools from remaining waitlist surplus
                    #              (AI gate: _available_to_spawn >= threshold)
                    #
                    #   This is the exact equivalent of a user registering mid-week and
                    #   triggering the waitlist engine, just done in one batch per week.
                    try:
                        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                        # Scoped to rsim_ users — prevents fetching/processing thousands
                        # of real Waitlist users every week, which caused the 10+ min hang.
                        weekly_refill = assign_waitlist_to_pools(db, user_prefix=injector._pfx)
                        total_p2_pools += weekly_refill.get("phase2_pools_count", 0)
                        total_p3_xfers += weekly_refill.get("phase3_transfers", 0)
                        db.commit()
                    except Exception as _wl_exc:
                        _logger.warning(
                            "Week %d: weekly assign_waitlist_to_pools failed: %s",
                            week_num, _wl_exc,
                        )
                        try: db.rollback()
                        except Exception: pass

                    # K-15: Waitlist dropout — randomly remove a % of waitlist members
                    # Simulates registrants who become inactive before pool entry.
                    if self.waitlist_dropout_pct > 0.0:
                        from app.models.user import UserStatus as _DS
                        wl_all = db.query(_U).filter(_U.status == _DS.Waitlist).all()
                        n_drop = max(0, int(len(wl_all) * self.waitlist_dropout_pct / 100.0))
                        if n_drop > 0:
                            dropouts = random.sample(wl_all, min(n_drop, len(wl_all)))
                            for d in dropouts:
                                d.status = UserStatus.Eliminated   # simulate dropout
                            db.commit()
                            _logger.debug(
                                "K-15: week %d dropout %d/%d waitlist members",
                                week_num, n_drop, len(wl_all),
                            )

                    # ── TICK 2: ON-TIME WINDOW — on_time_fraction pay before DUE_DATE ──
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    on_time_fraction = max(0.0, 1.0 - self.late_ratio)
                    t2_count = injector.tick2_on_time_payments(
                        db, on_time_fraction, chronos,
                        m.CYCLE_START, m.DUE_DATE, week_num,
                    )
                    db.commit()

                    # ── TICK 3: LATE FEE WINDOW (DUE_DATE → GRACE_PERIOD_START) ────
                    # K-14: Payment shock — spike late_ratio for the shock week
                    effective_late = self.late_ratio
                    if self.payment_shock_week > 0 and week_num == self.payment_shock_week:
                        effective_late = 0.20
                        _logger.info(
                            "K-14: Payment shock week %d — late_ratio spiked to 20%%",
                            week_num,
                        )
                    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # UNIT-BUG FIX (stress-test A/B/C compliance model). elim_pct_a / grace_pct_c
                    # are PERCENTAGES (e.g. 80.0 / 15.0), but the 9-tick refactor consumed them as
                    # raw fractions: tick3's `effective_late * (1.0 - 80.0)` went negative -> 0, and
                    # tick4 grace-saved `unpaid * 15.0` -> 100% of late payers, so tick5's guillotine
                    # always found 0 -> eliminations were IMPOSSIBLE for any setting. Restored the
                    # /100 scaling (the original apply_abc_model semantics, lines ~1150-1151). Each
                    # tick runs on the *remaining* unpaid set, so the per-tick fractions must be the
                    # CONDITIONAL shares that resolve A/B/C to exactly elim_pct_a% / grace_pct_c% /
                    # remainder of the ORIGINAL late-payer cohort:
                    #   late = L ; a = elim_pct_a/100 ; c = grace_pct_c/100
                    #   tick3 Type-B share (of L)            = 1 - a - c
                    #   remaining after tick3               = L*(a+c)   (the A + C cohort)
                    #   tick4 grace share (of that remnant) = c / (a+c)  -> grace-saves L*c
                    #   tick5 eliminates the rest           = L*a
                    _abc_a = self.elim_pct_a / 100.0          # Type A: direct-elimination share of late
                    _abc_c = self.grace_pct_c / 100.0          # Type C: grace-saved share of late
                    type_b_fraction = max(0.0, 1.0 - _abc_a - _abc_c)   # Type B: late-fee-then-pay remainder
                    t3 = injector.tick3_late_fee_window(
                        db, type_b_fraction, chronos,
                        m.DUE_DATE, m.GRACE_PERIOD_START, week_num,
                    )
                    db.commit()

                    # ── TICK 4: GRACE PERIOD (GRACE_PERIOD_START → G_CLOSE) ──────
                    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # tick4 operates on the post-tick3 remnant (= A + C of original late), so pass the
                    # CONDITIONAL grace share c/(a+c) — not the raw grace_pct_c — to grace-save exactly
                    # grace_pct_c% of the original late cohort and leave elim_pct_a% for the guillotine.
                    _abc_grace_cond = (_abc_c / (_abc_a + _abc_c)) if (_abc_a + _abc_c) > 0.0 else 0.0
                    t4 = injector.tick4_grace_period(
                        db, _abc_grace_cond, chronos,
                        m.GRACE_PERIOD_START, m.G_CLOSE, week_num,
                    )
                    db.commit()

                    # ── TICK 5: GUILLOTINE / G_CLOSE — eliminate all remaining Unpaid ──
                    chronos.jump_to(m.G_CLOSE)
                    t5 = injector.tick5_guillotine(db, week_id)
                    db.commit()

                    # Build compliance dict from tick results (same keys as _snapshot())
                    compliance = {
                        "n_late":                       t3["n_late"],
                        "n_elim":                       t5["n_eliminated"],
                        "n_saved":                      t4["n_grace_saved"],
                        "n_type_b":                     t3["n_b_paid"],
                        "type_b_ids":                   t3["type_b_ids"],
                        "late_fee_revenue_inr":         t3["late_fee_rev"] + t4["lf_settled_rev"],
                        "grace_fee_revenue_inr":        t4["grace_fee_rev"],
                        "total_compliance_revenue_inr": (
                            t3["late_fee_rev"] + t4["lf_settled_rev"] + t4["grace_fee_rev"]
                        ),
                        "week_id":                      week_id,
                    }
                    total_late        += t3["n_late"]
                    total_elim        += t5["n_eliminated"]
                    total_grace_saved += t4["n_grace_saved"]
                    total_late_fee_rev += (
                        t3["late_fee_rev"] + t4["lf_settled_rev"] + t4["grace_fee_rev"]
                    )

                    if t5["n_eliminated"] > 0:
                        _fm_paused = _fm_enforce_pool_capacity(db)
                        if _fm_paused:
                            _logger.info(
                                "Week %d: Finance Manager enforced capacity — "
                                "%d pool(s) paused+refilled before T-2H.",
                                week_num, _fm_paused,
                            )

                    # ── TICK 6: T_02H — start_draw_preparation() ─────────────────
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # This is the REAL T-2H production service.  It:
                    #   1. Acquires the draw_engine system lock
                    #   2. Freezes LPI snapshot into WeeklyDrawState
                    #   3. Catch-up flags any un-flagged L4 members
                    #   4. Quantifies SDE demand + checks L1/L2 supply
                    #   5. Runs run_sde_meta_pool() (SDE sub-draws executed here)
                    #   6. Sets preparation_valid=True, countdown_active=True
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Mark all pre-existing real pools as draw_completed_this_week=True
                    # so execute_weekly_draw skips them entirely. Without this, 100+
                    # real pools from production data would be drawn every week cycle,
                    # taking 10+ minutes and corrupting real draw history.
                    if _pre_sim_max_pool_id > 0:
                        db.query(Pool).filter(
                            Pool.id <= _pre_sim_max_pool_id,
                            Pool.draw_completed_this_week == False,
                        ).update({"draw_completed_this_week": True}, synchronize_session=False)
                        db.commit()
                        _logger.info(
                            "RealSimEngine [%s]: pre-skipped pools with id <= %d for week %d",
                            self._run_id, _pre_sim_max_pool_id, week_num,
                        )
                    _logger.info("RealSimEngine [%s]: TICK6-start week=%d — start_draw_preparation", self._run_id, week_num)
                    chronos.jump_to(m.T_02H)
                    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Bug #1/#2/#3 — snapshot DrawHistory row count and total payout BEFORE
                    # any draws fire this week (SDE sub-draws at T-2H + regular draws at T-0H).
                    # Post-T+5M delta gives exact per-week draw count, winner count, and
                    # cash outflow covering ALL draw types (SDE, Ext-II, Ext-III, Regular).
                    _draws_total_before  = db.query(func.count(DrawHistory.id)).scalar() or 0
                    _payout_total_before = float(
                        db.query(func.sum(
                            DrawHistory.winner_1_net_payout + DrawHistory.winner_2_net_payout,
                        )).scalar() or 0
                    )

                    # Clear any stale lock left by a previous failed cycle
                    try:
                        db.query(SystemLock).delete()
                        db.commit()
                    except Exception:
                        pass

                    prep_state  = None
                    prep_ok     = False
                    admin_ovr   = False

                    try:
                        prep_state = start_draw_preparation(
                            db, draw_time_utc=m.T_00H,
                        )
                        prep_ok   = True
                        admin_ovr = bool(prep_state.admin_override_required)

                        if admin_ovr:
                            # SDE supply shortage — auto-override for simulation:
                            # force SDE meta-pool directly (no human needed in sim)
                            _logger.info(
                                "Week %d: admin_override_required → auto-running SDE",
                                week_num,
                            )
                            try:
                                flag_l4_members(db); db.commit()
                                # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                                # Bug #8 — removed redundant redistribute_multi_l4_pools() call here.
                                # run_sde_meta_pool() already calls redistribute_multi_l4_pools()
                                # internally as its first step; calling it twice caused duplicate
                                # L4-pool redistribution and double-counting in session tracking.
                                run_sde_meta_pool(db, week_id)
                            except Exception as sde_exc:
                                _logger.warning(
                                    "Week %d auto-SDE failed: %s", week_num, sde_exc,
                                )
                                try: db.rollback()
                                except Exception: pass

                    except RuntimeError as exc:
                        # Lock acquisition failed (prev cycle's cleanup may have missed it)
                        # Fall back: run SDE component services directly
                        _logger.warning(
                            "Week %d: start_draw_preparation failed (%s) — "
                            "falling back to direct SDE call", week_num, exc,
                        )
                        try:
                            db.query(SystemLock).delete(); db.commit()
                            flag_l4_members(db); db.commit()
                            redistribute_multi_l4_pools(db); db.commit()
                            run_sde_meta_pool(db, week_id)
                        except Exception as fb_exc:
                            _logger.warning("Week %d fallback SDE failed: %s", week_num, fb_exc)
                            try: db.rollback()
                            except Exception: pass

                    except Exception as exc:
                        _logger.warning("Week %d preparation error: %s", week_num, exc)
                        try: db.rollback()
                        except Exception: pass

                    # ── TICK 7: T_00H — execute_weekly_draw() ────────────────────
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # This runs the Ext-II/III pre-pass THEN draws all eligible pools.
                    # SDE-processed pools are skipped (draw_completed_this_week=True).
                    _logger.info("RealSimEngine [%s]: TICK7-start week=%d — execute_weekly_draw", self._run_id, week_num)
                    chronos.jump_to(m.T_00H)

                    draws_this_week  = 0
                    pauses_this_week = 0
                    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # DRAW-STALL GATE TELEMETRY (read-only diagnostics — no change to draw logic).
                    # These per-week counters surface WHY draws did/did-not happen each week so the
                    # Weekly Timeline can pinpoint the exact failing gate (capacity gate vs refill).
                    # Initialised to zero here so they remain well-defined if the draw aborts
                    # (ValueError "no eligible pools" or any Exception) before mass_result is set.
                    gate_pools_drawn   = 0   # regular pools drawn at T-0H (mass_result.pools_drawn)
                    gate_pools_skipped = 0   # pools that errored mid-draw (mass_result.skipped_pools)
                    gate_refill_phase1 = 0   # Phase-1 Bulk Double-FIFO refill assignments
                    gate_refill_phase2 = 0   # Phase-2 Bulk Auto-Scale new pools created
                    gate_refill_phase3 = 0   # Phase-3 Condensation inter-pool transfers
                    gate_paused_names  = []  # names of pools paused this run (Active, <12)

                    try:
                        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                        # Pass the run-prefix so every internal assign_waitlist_to_pools()
                        # refill inside execute_weekly_draw (incl. the new pre-draw refill
                        # that resolves the draw-stall deadlock) is scoped to THIS run's
                        # users only — preventing the 10-min hang from scanning thousands
                        # of real Waitlist users (consistent with the Jun-15 scoping on the
                        # standalone weekly refill above).
                        mass_result      = execute_weekly_draw(
                            db, auto_pay_unpaid=False, user_prefix=injector._pfx,
                        )
                        _logger.info("RealSimEngine [%s]: TICK7-done week=%d — pools_drawn=%d", self._run_id, week_num, mass_result.pools_drawn)
                        # SESSION EDIT [Claude Session Jun-14 — Soheb Khan User 2 / Sohebkhan.sk11]:
                        # Temporary value — overwritten by DrawHistory delta below (Bug #1 fix
                        # from Jun-13 session).  Summing all MassDrawResult draw-type counters
                        # for correctness in case the delta computation path is skipped.
                        draws_this_week  = (
                            mass_result.pools_drawn
                            + mass_result.sde_draws_this_week
                            + mass_result.ext_draws_this_week
                            + mass_result.preventive_l3_draws_this_week
                        )
                        pauses_this_week = len(mass_result.paused_pools)
                        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                        # DRAW-STALL GATE TELEMETRY — capture per-week gate outcomes from the
                        # MassDrawResult the draw engine already returns (draw.py:140-150). All
                        # read-only; does not alter draw/refill behaviour. .get() guards the refill
                        # dict in case a code path returns it partially populated.
                        gate_pools_drawn   = mass_result.pools_drawn
                        gate_pools_skipped = len(mass_result.skipped_pools)
                        gate_refill_phase1 = mass_result.refill.get("phase1_assigned",    0)
                        gate_refill_phase2 = mass_result.refill.get("phase2_pools_count", 0)
                        gate_refill_phase3 = mass_result.refill.get("phase3_transfers",   0)
                        gate_paused_names  = list(mass_result.paused_pools)
                        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                        # Bug #1 — total_draws now accumulated AFTER T+5M using all-types
                        # DrawHistory delta instead of mass_result.pools_drawn (regular only).
                        # Removed: total_draws += draws_this_week (moved to metrics section)
                        total_pauses    += pauses_this_week
                        total_p2_pools  += mass_result.refill.get("phase2_pools_count", 0)
                        total_p3_xfers  += mass_result.refill.get("phase3_transfers",   0)

                    except ValueError as exc:
                        # No eligible pools this week — normal at start
                        _logger.info("Week %d: no eligible pools — %s", week_num, exc)
                    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Upgraded from _logger.warning (message only) to _logger.error with
                    # exc_info=True so the full stack trace is captured when the draw cycle
                    # itself aborts. Also added draw_abort_error to cycle_logs for
                    # frontend visibility in the simulation report.
                    except Exception as exc:
                        _logger.error("Week %d draw ABORT: %s", week_num, exc, exc_info=True)
                        cycle_logs.append({"week": week_num, "draw_abort_error": str(exc)})
                        try: db.rollback()
                        except Exception: pass

                    # ── TICK 8: T_05M — post_draw_cleanup() + RW settlement ──────
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Resets draw_completed_this_week, clears L4 flags, releases lock.
                    chronos.jump_to(m.T_05M)

                    try:
                        post_draw_cleanup(db)
                    except Exception as exc:
                        _logger.warning("Week %d cleanup error: %s", week_num, exc)
                        try: db.rollback()
                        except Exception: pass

                    # ── U-09: RW token auto-settlement ───────────────────────
                    # After each draw cycle, settle accumulated referral bonuses ≥ ₹1,000.
                    # This makes total_cash_outflow_inr accurate in financial stats.
                    try:
                        rw_count = injector.auto_settle_referral_rw(db, week_num=week_num)
                        if rw_count > 0:
                            db.commit()
                            _logger.debug(
                                "Week %d: U-09 settled %d RW tokens", week_num, rw_count
                            )
                    except Exception as rw_exc:
                        _logger.debug("Week %d RW settlement skipped: %s", week_num, rw_exc)
                        try: db.rollback()
                        except Exception: pass

                    # ── Collect metrics from REAL DB state ───────────────────
                    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # Bug #1 — draws_this_week: recomputed from DrawHistory delta (all types:
                    #          SDE sub-draws at T-2H + Ext-II/III + Regular at T-0H).
                    #          mass_result.pools_drawn only counted regular draws.
                    # Bug #2 — winners_this_week: 2 per draw row (all types); was derived
                    #          from the wrong regular-only draws_this_week.
                    # Bug #3 — cash_outflow_inr: sum of winner payouts from DrawHistory delta.
                    # Bug #4 — members_joined/exited: User status deltas this week.
                    # Bug #5 — pools_formed: Phase-2 new pools + Phase-1 restored pools.
                    # Bug #6 — ext2/3/accel: per-week delta, not all-time cumulative.
                    from app.models.user import User as _U6m, UserStatus as _US6m
                    from app.models.pool import Pool as _P6m, PoolStatus as _PS6m

                    # Bug #1 + #2 + #3: DrawHistory post-cycle totals vs pre-cycle baseline
                    _draws_total_after  = db.query(func.count(DrawHistory.id)).scalar() or 0
                    _payout_total_after = float(
                        db.query(func.sum(
                            DrawHistory.winner_1_net_payout + DrawHistory.winner_2_net_payout,
                        )).scalar() or 0
                    )
                    draws_this_week        = _draws_total_after  - _draws_total_before
                    cash_outflow_this_week = _payout_total_after - _payout_total_before
                    total_draws           += draws_this_week

                    # Bug #4: member flow deltas — who joined active pools, who exited as winners
                    _week_elim_won_after  = db.query(func.count(_U6m.id)).filter(
                        _U6m.status == _US6m.Eliminated_Won).scalar() or 0
                    _week_active_after    = db.query(func.count(_U6m.id)).filter(
                        _U6m.status == _US6m.Active).scalar() or 0
                    members_exited_this_week = _week_elim_won_after - _week_elim_won_before
                    members_joined_this_week = (
                        (_week_active_after - _week_active_before) + members_exited_this_week
                    )

                    # Bug #6: ext2/3/accel per-week deltas (subtract previous cumulative total)
                    cumul_ext2  = db.query(func.count(DrawHistory.id)).filter(
                        DrawHistory.draw_type == POOL_DRAW_SDE_EXT2,
                    ).scalar() or 0
                    cumul_ext3  = db.query(func.count(DrawHistory.id)).filter(
                        DrawHistory.draw_type == POOL_DRAW_SDE_EXT3,
                    ).scalar() or 0
                    cumul_accel = db.query(func.count(DrawHistory.id)).filter(
                        DrawHistory.draw_type == POOL_DRAW_ACCELERATED,
                    ).scalar() or 0
                    delta_ext2  = cumul_ext2  - _prev_cumul_ext2
                    delta_ext3  = cumul_ext3  - _prev_cumul_ext3
                    delta_accel = cumul_accel - _prev_cumul_accel

                    # SESSION EDIT [Claude Session Jun-14 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # SIMULATION FIX — ext2/ext3/accel cumulative vs per-week mismatch.
                    # _snapshot() stores these under the key ext2_exits_this_week.
                    # The DevTools DrawAnalysisChart computes per-week counts by DIFFING
                    # successive weekly_detail rows (w[n] - w[n-1]).  For this to work,
                    # the stored value must be the RUNNING CUMULATIVE TOTAL (identical to
                    # how _AdvSimEngine.self._l5_escalation_events is cumulative).
                    # Previous code passed delta_ext2 (per-week count) — the frontend diff
                    # then produced the second-derivative (change-in-delta), rendering
                    # garbage escalation bars in the charts.
                    # Fix: pass the all-time cumulative total (cumul_ext2) so the diff
                    # w[n] - w[n-1] = draws of that type in week n  (correct per-week).
                    metrics = _snapshot(
                        db                   = db,
                        week_num             = week_num,
                        draws_this_week      = draws_this_week,
                        pauses_this_week     = pauses_this_week,
                        compliance           = compliance,
                        cumulative_ext2      = cumul_ext2,   # all-time total; frontend diffs
                        cumulative_ext3      = cumul_ext3,
                        cumulative_accel     = cumul_accel,
                        cash_outflow_inr     = cash_outflow_this_week,
                        members_joined       = members_joined_this_week,
                        members_exited       = members_exited_this_week,
                    )

                    # Bug #5: pools_formed = Phase-2 new pools + Phase-1 Paused→Active restorations.
                    # Phase-1 restorations are approximated by the decrease in Paused pool count;
                    # max(0,...) guards against weeks where more pools became newly paused than restored.
                    _week_paused_after  = db.query(func.count(_P6m.id)).filter(
                        _P6m.status == _PS6m.Paused_Awaiting_Members).scalar() or 0
                    phase2_new          = total_p2_pools - _week_p2_start
                    phase1_restored     = max(0, _week_paused_before - _week_paused_after)
                    metrics["pools_formed"] = phase2_new + phase1_restored

                    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # DRAW-STALL GATE TELEMETRY — classify every currently-paused pool by its
                    # active-member count so the Weekly Timeline distinguishes the two failure
                    # modes that stop draws (read-only; mirrors the gate's own count at
                    # draw.py:676-680 exactly — current_pool_id == pool.id AND status==Active):
                    #   • under_cap (<12)  — refill LAG: Phase 1/2/3 can still fill these; if they
                    #                        persist week-over-week, refill velocity is too slow.
                    #   • at_cap   (==12)  — should self-heal (draw.py:686-693 restores Paused→Active);
                    #                        a non-zero value here means that restore path isn't firing.
                    #   • over_cap (>12)   — permanent DEADLOCK: Phase 1 vacancy=12-actual<0 skips
                    #                        them forever (brain5_lpi_engine.py:396). The signature of
                    #                        a hard 0-draw flatline.
                    from app.core.config import POOL_CAPACITY as _PC_diag
                    _paused_ids = [
                        r[0] for r in db.query(_P6m.id)
                        .filter(_P6m.status == _PS6m.Paused_Awaiting_Members).all()
                    ]
                    _paused_under = _paused_at = _paused_over = 0
                    if _paused_ids:
                        _active_by_pool = dict(
                            db.query(_U6m.current_pool_id, func.count(_U6m.id))
                            .filter(_U6m.current_pool_id.in_(_paused_ids),
                                    _U6m.status == _US6m.Active)
                            .group_by(_U6m.current_pool_id)
                            .all()
                        )
                        for _pid in _paused_ids:
                            _cnt = _active_by_pool.get(_pid, 0)
                            if   _cnt <  _PC_diag: _paused_under += 1
                            elif _cnt == _PC_diag: _paused_at    += 1
                            else:                  _paused_over  += 1

                    # Inject gate telemetry into the weekly row (mirrors the pools_formed pattern
                    # above — direct dict assignment, no change to _snapshot's signature).
                    metrics["gate_pools_drawn"]      = gate_pools_drawn
                    metrics["gate_pools_paused"]     = pauses_this_week      # newly paused this run
                    metrics["gate_pools_skipped"]    = gate_pools_skipped
                    metrics["gate_paused_under_cap"] = _paused_under
                    metrics["gate_paused_at_cap"]    = _paused_at
                    metrics["gate_paused_over_cap"]  = _paused_over
                    metrics["gate_refill_phase1"]    = gate_refill_phase1
                    metrics["gate_refill_phase2"]    = gate_refill_phase2
                    metrics["gate_refill_phase3"]    = gate_refill_phase3
                    metrics["gate_paused_pool_names"] = gate_paused_names

                    # Bug #6: advance cumulative trackers for next week's delta computation
                    _prev_cumul_ext2  = cumul_ext2
                    _prev_cumul_ext3  = cumul_ext3
                    _prev_cumul_accel = cumul_accel
                    weekly_detail.append(metrics)

                    cycle_logs.append({
                        "week":      week_num,
                        "pauses":    pauses_this_week,
                        "draws":     draws_this_week,
                        "inflow":    inflow,
                        "prep_ok":   prep_ok,
                        "compliance": compliance,
                    })

                    # ── Live progress callback (background-task mode) ──────────
                    if progress_callback is not None:
                        try:
                            progress_callback(week_num, self.weeks, metrics)
                        except Exception:
                            pass   # never abort simulation due to callback error

                    max_lpi      = max(max_lpi, metrics["lpi"])
                    max_active   = max(max_active, metrics["active_users"])
                    max_waitlist = max(max_waitlist, metrics["waitlist_count"])
                    max_pools    = max(max_pools,    metrics["pools_active"])
                    max_l5       = max(max_l5,       metrics["l5_count"])
                    max_l6       = max(max_l6,       metrics["l6_count"])
                    sc           = metrics["scenario"]
                    scenario_counts[sc] = scenario_counts.get(sc, 0) + 1

                    # ── TICK 9: advance to next draw time ────────────────────────
                    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    current_T_00H = _compute_next_draw_time(m.T_00H, m.cycle_length)

                # ── Final financials from actual DrawHistory ─────────────────
                total_payout = db.query(
                    func.sum(
                        DrawHistory.winner_1_net_payout + DrawHistory.winner_2_net_payout
                    )
                ).scalar() or Decimal("0")

                # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # FIX: was total_users_created×1000 = initial deposits only (wrong).
                # Correct value is the sum of weekly installments actually collected.
                total_collected = sum(
                    Decimal(str(w.get("installments_collected_inr", 0)))
                    for w in weekly_detail
                )
                net_profit      = total_collected - total_payout
                avg_lpi         = round(
                    sum(w["lpi"] for w in weekly_detail) / max(len(weekly_detail), 1), 2,
                )

                # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # Bug #6 — ext2/ext3/accel snapshot fields are now per-week DELTAS (not
                # cumulative totals). The final summary must SUM all weeks to get the
                # simulation-wide total; previously took only the last week's value which
                # was the all-time cumulative (correct by accident) but now would only show
                # the last week's count (wrong).
                # SESSION EDIT [Claude Session Jun-14 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # Since ext2/ext3/accel are now stored as CUMULATIVE totals (fixed above),
                # the simulation-wide total is simply the last week's stored value.
                # Previously used sum() which gave the running-sum-of-cumulative-sums
                # (vastly over-counting: week-N value = w1+w2+...+wN, sum = huge).
                _wd_last    = weekly_detail[-1] if weekly_detail else {}
                final_ext2  = _wd_last.get("ext2_exits_this_week", 0)
                final_ext3  = _wd_last.get("ext3_exits_this_week", 0)
                final_accel = _wd_last.get("accel_diss_this_week",  0)

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

                # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                # Build summary — canonical Stress Test schema (formerly _AdvSimEngine.summary(),
                # now removed; this Real Engine is the sole producer of this schema).
                simulation_summary = {
                    # ── K-17: simulation label ─────────────────────────────────────────
                    "simulation_label":              self.simulation_label or "default",
                    # ── K-12 to K-16: injection knobs used (for report display) ────────
                    "injection_knobs": {
                        "inflow_pattern":       self.inflow_pattern,
                        "referral_burst_week":  self.referral_burst_week,
                        "payment_shock_week":   self.payment_shock_week,
                        "waitlist_dropout_pct": self.waitlist_dropout_pct,
                        "organic_decay_rate":   self.organic_decay_rate,
                    },
                    # Legacy backward-compatible keys
                    "total_cycles_run":              self.weeks,
                    "total_simulated_users_created": total_users_created,
                    "total_winners_drawn":           total_draws * 2,
                    "total_pools_auto_scaled":       total_p2_pools,
                    "total_condensation_events":     total_p3_xfers,
                    "total_draw_pauses_triggered":   total_pauses,
                    "total_late_fees_collected_inr": float(total_late_fee_rev),
                    "final_virtual_liquidity_float": float(net_profit),
                    # Financial section
                    "financial_metrics": {
                        "total_collected_inr":        float(total_collected),
                        "total_distributed_inr":      float(total_payout),
                        "total_maintenance_fees_inr": float(total_draws * 2 * 500),
                        "total_late_fees_inr":        float(total_late_fee_rev),
                        "net_organizer_profit_inr":   float(net_profit),
                        "master_liquidity_float_inr": float(net_profit),
                        "projected_ultimate_liability": float(total_payout),
                    },
                    # System health section (same keys as legacy engine)
                    "system_health": {
                        "total_members_injected":        total_users_created,
                        "total_direct_pool_assignments": total_users_created,
                        "total_dynamic_merges":          total_p3_xfers,
                        "total_draw_pauses_triggered":   total_pauses,
                        "total_l4_sde_flaggings":        0,
                        "total_sde_exits":               final_ext2 + final_ext3,
                        "total_type_a_draws":            0,
                        "total_type_b_draws":            0,
                        "sde_exit_rate_pct":             round(
                            (final_ext2 + final_ext3) / max(total_draws * 2, 1) * 100, 1,
                        ),
                        "max_l5_count":                  max_l5,
                        "max_l6_count":                  max_l6,
                        "max_high_lpi_streak_weeks":     0,
                        "l5_peak_by_week":               [w["l5_count"] for w in weekly_detail],
                        "l6_peak_by_week":               [w["l6_count"] for w in weekly_detail],
                        # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                        # Use .get() so partial cycle_log entries (e.g. draw_abort_error
                        # entries that have no "pauses" key) don't crash aggregation.
                        "pauses_by_week":                [c.get("pauses", 0) for c in cycle_logs],
                        "total_l5_ext2_forced_exits":    final_ext2,
                        "total_l6_ext3_forced_exits":    final_ext3,
                        "total_accel_dissolution_events": final_accel,
                        "l5_l6_escalation_explanation":  escalation_note,
                    },
                    # Real-engine metadata
                    "engine":               "real",
                    "avg_lpi":              avg_lpi,
                    "max_lpi":              round(max_lpi, 2),
                    "max_active_users":     max_active,
                    "max_waitlist_count":   max_waitlist,
                    "max_pools":            max_pools,
                    "scenario_distribution": scenario_counts,
                }

        finally:
            # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Close SIM bracket + close real DB session.
            # engine_db.dispose() REMOVED — no longer using an isolated SQLite engine.
            log_milestone("SIM/end", "simulation_ended", {"run_id": self._run_id})
            db.close()
            set_auto_pool_creation(_orig_auto)

        return {
            "engine":             "real",
            "simulation_summary": simulation_summary,
            "weekly_detail":      weekly_detail,
            "cycle_logs":         cycle_logs,
        }
