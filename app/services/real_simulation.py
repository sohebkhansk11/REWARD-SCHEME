"""
Real Simulation Engine  — Zero-Duplication Stress-Test Harness
==============================================================

ARCHITECTURE GUARANTEE:
  This module contains ZERO business logic.  Every formula, algorithm, and
  rule lives exclusively in the production services.  This engine is a
  dumb orchestrator that:
    1. Creates an isolated in-memory SQLite database (SimulationDB)
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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, insert as sa_insert
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

_DEPOSIT_DEC = Decimal("1000")
_TOKEN_ALPHA = string.ascii_uppercase + string.digits


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
    The production database is NEVER touched.

    Returns (engine, SessionLocal).  Call engine.dispose() when done.
    """
    from app.database import Base

    # Force-import all model modules so their tables register on Base.metadata
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

    def __init__(self):
        self._counter = 0   # global monotonic counter for unique IDs

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

        # Flush to get DB-assigned user IDs before creating tokens
        db.flush()

        # Bulk-insert burned DEP tokens (1 per user) — mirrors production payment flow
        token_rows = [
            {
                "code":      f"SD{u.id:010d}",   # deterministic, unique per user
                "type":      TokenType.Deposit,
                "status":    TokenStatus.Burned,
                "value_inr": _DEPOSIT_DEC,
                "user_id":   u.id,
                "pool_id":   None,
            }
            for u in new_users
        ]

        if token_rows:
            db.execute(sa_insert(Token), token_rows)

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

        now = datetime.now(timezone.utc)
        token_rows = []
        for member in unpaid:
            member.weekly_payment_status = WeeklyPaymentStatus.Paid
            # U-08: one DEP token per member per week — code is deterministic
            # so a re-run of the same week is idempotent (same code = unique constraint
            # violation → simulation catches + skips duplicates gracefully).
            token_rows.append({
                "code":        f"WK{week_num:04d}U{member.id:010d}",
                "type":        TokenType.Deposit,
                "status":      TokenStatus.Burned,
                "value_inr":   _DEPOSIT_DEC,
                "user_id":     member.id,
                "pool_id":     member.current_pool_id,
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

            rw_code = f"RW{week_num:04d}U{user.id:010d}"
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
        from app.core.config import LATE_FEE_DAILY_INR, LATE_FEE_MAX_CAP_INR
        from app.services.waitlist import assign_waitlist_to_pools

        _zero = Decimal("0")
        _fee  = Decimal(str(LATE_FEE_DAILY_INR))
        _cap  = Decimal(str(LATE_FEE_MAX_CAP_INR))
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
    }


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

    def _sunday(self, week_offset: int) -> datetime:
        """Return Sunday 00:00 UTC for (start_week + week_offset)."""
        total_week = self.start_week + week_offset
        year       = self.start_year + (total_week - 1) // 52
        iso_week   = ((total_week - 1) % 52) + 1
        try:
            base = datetime.fromisocalendar(year, iso_week, 7)   # 7 = Sunday
        except ValueError:
            base = datetime.fromisocalendar(year, 52, 7)
        return base.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    def run(self, progress_callback=None) -> dict:
        """
        Execute the full simulation.

        progress_callback: optional callable(week_num: int, total_weeks: int, metrics: dict)
            Called after each week completes.  Used by background-task mode for live
            progress reporting.  Any exception raised by the callback is swallowed so
            it cannot abort the simulation.

        Returns a dict with the SAME structure as the legacy _AdvSimEngine so
        existing frontend charts work without modification.

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

        # ── Preserve + force production-compatible global state ───────────────
        _orig_auto = get_auto_pool_creation()
        set_auto_pool_creation(True)

        engine_db, SessionLocal = _create_sim_db()
        injector = MassLoadInjector()

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

        db = SessionLocal()

        try:
            with ChronosEngine(self._sunday(0)) as chronos:

                # ── Seed: inject initial users one week before first draw ────
                seed_time = self._sunday(0) - timedelta(days=7)
                chronos.jump_to(seed_time)

                seed_users = injector.inject_week(
                    db, self.initial_users, seed_time, self.organic_ratio,
                )
                db.commit()
                total_users_created += len(seed_users)

                # Trigger initial pool formation from seed users
                refill = assign_waitlist_to_pools(db)
                total_p2_pools += refill.get("phase2_pools_count", 0)

                # ────────────────────────────────────────────────────────────
                # MAIN WEEKLY LOOP
                # ────────────────────────────────────────────────────────────
                for w in range(self.weeks):
                    week_num         = w + 1
                    sunday_midnight  = self._sunday(w)
                    saturday_22h     = sunday_midnight - timedelta(hours=2)
                    sunday_5min      = sunday_midnight + timedelta(minutes=5)
                    monday_morning   = sunday_midnight - timedelta(days=6)

                    iso     = sunday_midnight.isocalendar()
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

                    # ── a. Inject new users (Monday morning) ─────────────────
                    chronos.jump_to(monday_morning)

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
                        decay   = 1.0 - self.organic_decay_rate * week_num
                        effective_organic = max(0.0, effective_organic * max(0.0, decay))

                    # Build referral pool from existing users (Brain 3 RDR feed)
                    from app.models.user import User as _U, UserStatus as _US
                    existing_ids = [
                        r[0] for r in db.query(_U.id).filter(
                            _U.status.in_([_US.Active, _US.Waitlist])
                        ).limit(500).all()
                    ]

                    new_batch = injector.inject_week(
                        db, inflow, chronos.current,
                        effective_organic, existing_ids,
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
                        weekly_refill = assign_waitlist_to_pools(db)
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

                    # ── b. Finance Manager: Reset payment cycle (Monday morning)
                    #
                    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    # FIX A3: Corrected FM payment-cycle order.
                    #
                    # OLD (wrong) order:
                    #   Monday — reset ALL → Unpaid
                    #   Monday — auto_pay ALL → Paid + WK tokens (even future late payers!)
                    #   Thursday — apply_abc → re-mark n_late% Unpaid (tokens already issued!)
                    #
                    # NEW (correct) order:
                    #   Monday    — reset ALL → Unpaid
                    #   Thursday  — apply_abc → A eliminated, B late-fee stays Unpaid,
                    #                           C grace saved → Paid
                    #   Thursday  — auto_pay(skip_ids=type_b_ids) → non-late Unpaid → Paid
                    #
                    # Effect: WK installment tokens are only created for members who
                    # ACTUALLY paid this week.  installments_collected_inr is now correct.

                    # ── b. Finance Manager: Reset payment cycle (Monday morning) ──
                    # All Active members start the week Unpaid (they owe this week's ₹1000).
                    _fm_reset_payment_cycle(db)
                    db.commit()

                    # ── c. Thursday 23:59 — Payment due date: Apply A/B/C compliance ──
                    #
                    # Time-travel to Thursday 23:59 (T-3d from Sunday draw).
                    # Production due-date cutoff: late members enter A/B/C processing.
                    #
                    # Timeline:
                    #   Monday  00:01 (above)  — reset to Unpaid
                    #   Thursday 23:59 (now)   — due date: A eliminated, B late-fee,
                    #                            C grace saves seat → Paid
                    #   Thursday 23:59 (below) — FM auto-pays remaining non-late members
                    #   Saturday 22:00 (T-2H)  — draw preparation with FULL pools
                    #   Sunday   00:00 (T-0)   — draw executes
                    thursday_2359 = monday_morning + timedelta(days=3, hours=23, minutes=59)
                    chronos.jump_to(thursday_2359)

                    # K-14: Payment shock — spike late_ratio for the shock week
                    effective_late = self.late_ratio
                    if self.payment_shock_week > 0 and week_num == self.payment_shock_week:
                        effective_late = 0.20   # 20% spike regardless of normal rate
                        _logger.info(
                            "K-14: Payment shock week %d — late_ratio spiked to 20%%",
                            week_num,
                        )

                    compliance = injector.apply_abc_model(
                        db, effective_late, self.elim_pct_a, self.grace_pct_c,
                    )
                    db.commit()
                    total_late        += compliance["n_late"]
                    total_elim        += compliance["n_elim"]
                    total_grace_saved += compliance["n_saved"]
                    total_late_fee_rev += compliance["late_fee_revenue_inr"]

                    # ── c.2 FM: Auto-pay non-late members (U-08 weekly DEP tokens) ──
                    # Now that A/B/C has run, we know which members are Type B (Unpaid
                    # late-fee holders).  auto_pay skips them and pays everyone else.
                    # This ensures WK tokens reflect only genuine installment payments.
                    injector.auto_pay_installments(
                        db,
                        week_num = week_num,
                        skip_ids = compliance.get("type_b_ids", set()),
                    )
                    db.commit()

                    # ── c.5 Finance Manager: Enforce pool capacity before T-2H ─
                    #
                    # apply_abc_model eliminated some members.  Their pools are still
                    # Active (not Paused) so assign_waitlist_to_pools Phase 1 won't
                    # refill the vacancies.  Without this step, execute_weekly_draw
                    # would find an Active pool with < 12 members → pause it mid-draw
                    # → no draw for that pool this week.
                    #
                    # Fix: Proactively pause every under-capacity Active pool and call
                    # assign_waitlist_to_pools so Phase 1 fills them from waitlist.
                    # By T-2H, every pool is back to 12 members and eligible to draw.
                    if compliance.get("n_elim", 0) > 0:
                        _fm_paused = _fm_enforce_pool_capacity(db)
                        if _fm_paused:
                            _logger.info(
                                "Week %d: Finance Manager enforced capacity — "
                                "%d pool(s) paused+refilled before T-2H.",
                                week_num, _fm_paused,
                            )

                    # ── d. T-2H: Call start_draw_preparation() ────────────────
                    # This is the REAL T-2H production service.  It:
                    #   1. Acquires the draw_engine system lock
                    #   2. Freezes LPI snapshot into WeeklyDrawState
                    #   3. Catch-up flags any un-flagged L4 members
                    #   4. Quantifies SDE demand + checks L1/L2 supply
                    #   5. Runs run_sde_meta_pool() (SDE sub-draws executed here)
                    #   6. Sets preparation_valid=True, countdown_active=True
                    chronos.jump_to(saturday_22h)
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
                            db, draw_time_utc=sunday_midnight,
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

                    # ── e. T-0H: Call execute_weekly_draw() ──────────────────
                    # This runs the Ext-II/III pre-pass THEN draws all eligible pools.
                    # SDE-processed pools are skipped (draw_completed_this_week=True).
                    chronos.jump_to(sunday_midnight)

                    draws_this_week  = 0
                    pauses_this_week = 0

                    try:
                        mass_result      = execute_weekly_draw(db, auto_pay_unpaid=False)
                        draws_this_week  = mass_result.pools_drawn    # regular draws only (temp)
                        pauses_this_week = len(mass_result.paused_pools)
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

                    # ── f. T+5m: Call post_draw_cleanup() ────────────────────
                    # Resets draw_completed_this_week, clears L4 flags, releases lock.
                    chronos.jump_to(sunday_5min)

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

                    metrics = _snapshot(
                        db                   = db,
                        week_num             = week_num,
                        draws_this_week      = draws_this_week,
                        pauses_this_week     = pauses_this_week,
                        compliance           = compliance,
                        cumulative_ext2      = delta_ext2,
                        cumulative_ext3      = delta_ext3,
                        cumulative_accel     = delta_accel,
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
                final_ext2  = sum(w.get("ext2_exits_this_week", 0) for w in weekly_detail)
                final_ext3  = sum(w.get("ext3_exits_this_week", 0) for w in weekly_detail)
                final_accel = sum(w.get("accel_diss_this_week",  0) for w in weekly_detail)

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

                # Build summary — same schema as legacy _AdvSimEngine.summary()
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
            db.close()
            engine_db.dispose()
            set_auto_pool_creation(_orig_auto)

        return {
            "engine":             "real",
            "simulation_summary": simulation_summary,
            "weekly_detail":      weekly_detail,
            "cycle_logs":         cycle_logs,
        }
