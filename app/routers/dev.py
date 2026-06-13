"""
Developer Mode Router  (/dev/*)
================================
Endpoints in this router are ONLY accessible when:
  1. The caller presents a valid Admin JWT.
  2. ENABLE_DEV_MODE=true is set in the server environment.

Both checks are enforced by the `require_dev_mode` dependency, which itself
wraps `require_admin_jwt`.  In production (ENABLE_DEV_MODE unset or false)
every route here returns 403 — even for authenticated admins.

Endpoints:
  POST   /dev/force-draw      Instantly run the Sunday draw on any active pool
  POST   /dev/simulate-cycle  Generate dummy users + run N consecutive draw cycles
  POST   /dev/simulate-users  Bulk-insert N fake Waitlist users with Burned DEP tokens
  DELETE /dev/reset-data      Nuke all users / pools / tokens; reset DB sequences
"""

import random
import secrets
from dataclasses import dataclass as _dc
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import threading

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, insert as sa_insert, text
from sqlalchemy.orm import Session

from app.core.config import DEPOSIT_AMOUNT_INR, LEVEL_PAYOUTS, NEW_POOL_INTAKE, POOL_CAPACITY
from app.core.dev_guard import require_dev_mode
from app.database import get_db
from app.crud import pool as crud_pool
from app.models.pool import Pool, PoolStatus
from app.models.token import Token, TokenType, TokenStatus
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.schemas.pool import PoolCreate
from app.services.auth import hash_password as _hash_password
from app.services.draw import run_dual_draw, execute_weekly_draw
from app.services.settings import get_pool_threshold
from app.services.waitlist import assign_waitlist_to_pools, fill_pool_vacancies, manual_create_pool

router = APIRouter(
    prefix="/dev",
    tags=["Developer Mode"],
    dependencies=[Depends(require_dev_mode)],
)

# ── Injection Background Task Registry ───────────────────────────────────────
# Tracks the status of timed-injection pool-formation jobs that run after the
# HTTP response is returned.  Keyed by `prefix` (unique per injection call).
# Thread-safe via threading.Lock since FastAPI may serve concurrent requests.
#
# Schema per entry:
#   {
#     "status":       "running" | "done" | "error",
#     "pools_formed": int,
#     "waitlist_remaining": int,
#     "error":        str | None,
#     "started_at":   datetime ISO,
#     "finished_at":  datetime ISO | None,
#   }
_INJECT_STATUS: dict[str, dict] = {}
_INJECT_LOCK   = threading.Lock()

# ── Real Simulation Background Job Registry ───────────────────────────────────
# Tracks RealSimEngine jobs started by POST /dev/real-simulation.
# Keyed by job_id (unique per simulation call).  Thread-safe via _SIM_LOCK.
#
# Schema per entry:
#   {
#     "status":           "queued" | "running" | "done" | "error",
#     "current_week":     int,
#     "total_weeks":      int,
#     "percent":          float,
#     "result":           dict | None,        — full response when done
#     "error_message":    str | None,
#     "error_type":       str | None,         — exception class name
#     "error_traceback":  str | None,         — full traceback string (debugger)
#     "error_file":       str | None,         — file where exception occurred
#     "error_line":       int | None,         — line number
#     "error_func":       str | None,         — function/method name
#     "error_source":     str | None,         — source line text
#     "started_at":       datetime ISO,
#     "finished_at":      datetime ISO | None,
#   }
_SIM_STATUS: dict[str, dict] = {}
_SIM_LOCK   = threading.Lock()

# Rows per executemany batch — keeps individual SQL statements a manageable size
_BULK_BATCH = 5_000

# Pre-computed deposit amount as Decimal to avoid repeated conversions
_DEPOSIT_DEC = Decimal(str(DEPOSIT_AMOUNT_INR))

# Lazily-computed bcrypt hash for dev users' default password.
# Bcrypt is intentionally slow (~100 ms per call); computing it once and caching
# it avoids spending minutes hashing the same string for every row in a bulk insert.
_DEV_PW_HASH: str | None = None


def _get_dev_pw_hash() -> str:
    """Return a bcrypt hash of the dev-user default password, computed at most once."""
    global _DEV_PW_HASH
    if _DEV_PW_HASH is None:
        _DEV_PW_HASH = _hash_password("dev_default_1234")
    return _DEV_PW_HASH


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ForceDrawRequest(BaseModel):
    pool_id: Optional[int] = Field(
        None,
        description="Target pool ID. Omit to auto-select the first active pool.",
    )
    auto_pay_installments: bool = Field(
        False,
        description=(
            "If True, simulate real token redemptions for every unpaid member before "
            "the draw (creates Burned DEP tokens in the Tokens table so wallet history "
            "and Cash Inflow statistics reflect accurate figures). "
            "If False, payment status is set directly without creating token records."
        ),
    )


class SimulateCycleRequest(BaseModel):
    n_cycles: int  = Field(3,    ge=1, le=12,     description="Number of weekly draws to simulate (1–12).")
    cleanup:  bool = Field(True,                  description="Delete all generated users, tokens, and the pool after the run.")
    auto_pay_installments: bool = Field(
        False,
        description=(
            "If True, simulate real token redemptions each cycle (creates Burned DEP "
            "tokens per unpaid member so Cash Inflow statistics are accurate). "
            "If False, payment status is toggled directly without token records."
        ),
    )


class SimulateUsersRequest(BaseModel):
    count:     int  = Field(..., ge=1, le=100_000, description="Number of fake Waitlist users to bulk-create (1–100,000).")
    auto_pool: bool = Field(True,                  description="Auto-trigger pool formation after creation (calls check_and_scale_waitlist in a loop).")


class ResetDataRequest(BaseModel):
    confirm: str = Field(
        ...,
        description="Must be exactly 'CONFIRM_NUKE' to proceed. Prevents accidental calls.",
    )


class DrawTrace(BaseModel):
    cycle:        int
    winner_1:     str
    winner_2:     str
    level_1:      int
    level_2:      int
    payout_1_inr: float
    payout_2_inr: float
    edge_case:    bool


class SimulateResult(BaseModel):
    n_requested:             int
    n_executed:              int
    users_created:           int
    pool_id:                 Optional[int]
    draws:                   list[DrawTrace]
    total_paid_out_inr:      float
    simulated_tokens_created: int   # DEP tokens created by auto_pay_installments
    cleanup_done:            bool


class SimulateUsersResult(BaseModel):
    users_created:      int
    dep_tokens_created: int
    prefix:             str
    pools_formed:       int
    waitlist_remaining: int
    elapsed_ms:         int
    note:               str


class ResetDataResult(BaseModel):
    users_deleted:   int
    tokens_deleted:  int
    pools_deleted:   int
    sequences_reset: bool
    note:            str


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper — simulate real token payments
# ─────────────────────────────────────────────────────────────────────────────

_DEP_ALPHABET = string.ascii_uppercase + string.digits


def _simulate_installment_payments(
    db: Session,
    members: list,
    pool_id: int,
) -> int:
    """
    For each unpaid Active member in `members`, create a Burned DEP token
    that represents a real ₹1,000 deposit redemption.

    This makes the Cash Inflow statistics accurate: the Tokens table will contain
    the simulated deposit records just as if users had physically redeemed tokens.

    Returns the number of tokens created.
    """
    now = datetime.now(timezone.utc)
    tokens_created = 0

    # Gather tokens already in DB to avoid code collisions cheaply
    existing_codes: set[str] = set()

    for member in members:
        if member.weekly_payment_status == WeeklyPaymentStatus.Paid:
            continue   # already paid — no token needed

        # Generate a unique DEP code
        while True:
            code = "DEP-" + "".join(secrets.choice(_DEP_ALPHABET) for _ in range(6))
            if code not in existing_codes:
                # Quick DB check for absolute safety
                if not db.query(Token).filter(Token.code == code).first():
                    existing_codes.add(code)
                    break

        dep_token = Token(
            code=code,
            type=TokenType.Deposit,
            value_inr=_DEPOSIT_DEC,
            status=TokenStatus.Burned,
            user_id=member.id,
            redeemed_by_user_id=member.id,
            redeemed_at=now,
        )
        db.add(dep_token)
        member.weekly_payment_status = WeeklyPaymentStatus.Paid
        tokens_created += 1

    if tokens_created:
        db.commit()

    return tokens_created


# ─────────────────────────────────────────────────────────────────────────────
# POST /dev/force-draw
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/force-draw")
def force_draw(body: ForceDrawRequest, db: Session = Depends(get_db)):
    """
    Execute the Sunday dual-draw.

    No pool_id supplied → GLOBAL MASS DRAW via execute_weekly_draw():
      • Draws ALL active pools that currently have exactly 12 members.
      • Each pool drops to 10 after the draw (no inline replacements).
      • A single Double-FIFO assign_waitlist_to_pools() call refills all
        vacancies and runs Phase 2 pool creation check.

    pool_id supplied → SINGLE-POOL DRAW on the specified pool only.
      • The normal run_dual_draw() path: inline replacement + FIFO fill.

    auto_pay_installments=True in either mode:
      Creates real Burned DEP tokens per unpaid member so Cash Inflow
      statistics in the Tokens table are accurate.
    """
    def _winner_dict(w) -> dict:
        return {
            "username":       w.winner_username,
            "level":          w.winner_level,
            "net_payout_inr": float(w.net_payout_inr),
            "withdraw_token": w.withdraw_token_code,
            "replaced_by":    w.replaced_by_username,
        }

    # ── GLOBAL MASS DRAW (no pool_id) ─────────────────────────────────────────
    if not body.pool_id:
        try:
            mass = execute_weekly_draw(
                db,
                auto_pay_unpaid=True,   # always safe-pay before drawing in dev mode
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        # Optionally create Burned DEP token records for unpaid members
        tokens_made = 0
        if body.auto_pay_installments:
            # Gather all active members across drawn pools and create DEP tokens
            # for those who were unpaid (auto_pay_unpaid already flipped flags)
            for dr in mass.draw_results:
                members = (
                    db.query(User)
                    .filter(User.current_pool_id == dr.pool_id, User.status == UserStatus.Active)
                    .all()
                )
                tokens_made += _simulate_installment_payments(db, members, dr.pool_id)

        return {
            "mode":                     "mass_draw",
            "pools_drawn":              mass.pools_drawn,
            "skipped_pools":            mass.skipped_pools,
            "paused_pools":             mass.paused_pools,
            "total_auto_paid":          mass.total_auto_paid,
            "simulated_tokens_created": tokens_made,
            "draws": [
                {
                    "pool_id":        dr.pool_id,
                    "pool_name":      dr.pool_name,
                    "edge_case_used": dr.edge_case_used,
                    "winner_1":       _winner_dict(dr.winner_1),
                    "winner_2":       _winner_dict(dr.winner_2),
                }
                for dr in mass.draw_results
            ],
            "refill": {
                "phase1_assigned":     mass.refill["phase1_assigned"],
                "phase1_pool_changes": mass.refill["phase1_pool_changes"],
                "phase2_pool_created": mass.refill["phase2_pool_created"],
                "phase2_assigned":     mass.refill["phase2_assigned"],
                "phase3_transfers":    mass.refill["phase3_transfers"],
                "phase3_events":       mass.refill["phase3_events"],
                "phase3_dissolved":    mass.refill["phase3_dissolved"],
            },
            "dev_note": (
                "Global Mass Draw — all full pools drawn simultaneously; "
                "Triple-phase FIFO refill (P1: waitlist fill, P2: auto-scale, "
                "P3: condensation) ran once after all draws."
            ),
        }

    # ── SINGLE-POOL DRAW (pool_id specified) ──────────────────────────────────
    pool = db.query(Pool).filter(Pool.id == body.pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail=f"Pool {body.pool_id} not found.")

    unpaid = (
        db.query(User)
        .filter(
            User.current_pool_id == pool.id,
            User.status == UserStatus.Active,
            User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
        )
        .all()
    )
    auto_paid   = len(unpaid)
    tokens_made = 0

    if body.auto_pay_installments:
        tokens_made = _simulate_installment_payments(db, unpaid, pool.id)
    else:
        for member in unpaid:
            member.weekly_payment_status = WeeklyPaymentStatus.Paid
        if unpaid:
            db.commit()

    try:
        result = run_dual_draw(db, pool.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "mode":                   "single_draw",
        "pool_id":                result.pool_id,
        "pool_name":              result.pool_name,
        "auto_paid_count":        auto_paid,
        "simulated_tokens_created": tokens_made,
        "winner_1":               _winner_dict(result.winner_1),
        "winner_2":               _winner_dict(result.winner_2),
        "edge_case_used":         result.edge_case_used,
        "dev_note": (
            "Real DEP tokens created for each unpaid member."
            if body.auto_pay_installments else
            "Payment status set directly without token records."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /dev/simulate-cycle
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/simulate-cycle", response_model=SimulateResult)
def simulate_cycle(body: SimulateCycleRequest, db: Session = Depends(get_db)):
    """
    Full end-to-end simulation:
      1. Bulk-insert 24 + 2×N dummy users (Waitlist / Paid).
      2. Trigger waitlist auto-scaling → new Active pool of 12.
      3. For each of the N cycles:
           a. Mark all pool members Paid.
           b. Run the dual-draw; record winners and payouts.
      4. If cleanup=True: delete all generated users, their tokens, and the pool.
         Any real users accidentally absorbed into the dev pool are safely
         returned to Waitlist status before deletion.

    Returns a full per-cycle trace for inspection.
    """
    N      = body.n_cycles
    ts     = int(time.time())
    nonce  = random.randint(100_000, 999_999)
    prefix = f"dev_sim_{ts}_{nonce}_"

    # ── Dynamic user count: threshold (from DB) + 2 replacements per cycle ────
    # This replaces the previous hardcoded "24 + 2*N" so the simulation always
    # creates enough users to satisfy the live pool_creation_threshold setting.
    # max(threshold, POOL_CAPACITY) guards against thresholds below 12 (pool size).
    threshold = get_pool_threshold(db)
    n_users   = max(threshold, POOL_CAPACITY) + 2 * N

    # ── 1. Bulk-insert dummy users with realistic sequential timestamps ────────
    # Each user gets join_date = base_time + i minutes so their FIFO ordering is
    # deterministic and reflects real sequential growth rather than one instant.
    hashed_pw = _get_dev_pw_hash()   # bcrypt computed once — reused for all rows
    base_time = datetime.now(timezone.utc)

    # Generate unique referral codes for all sim users upfront
    _sim_ref_codes: set[str] = set()
    while len(_sim_ref_codes) < n_users:
        _sim_ref_codes.update(
            "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            for _ in range(n_users - len(_sim_ref_codes))
        )
    _sim_ref_list = list(_sim_ref_codes)

    user_rows = [
        {
            "name":                  f"SimUser-{i + 1}",
            "mobile":                f"+99{ts:010d}{nonce:06d}{i:05d}",
            # UUID-based username keeps the shared prefix for cleanup + is unique per user
            "username":              f"{prefix}{uuid.uuid4().hex[:12]}",
            "hashed_password":       hashed_pw,
            "join_date":             base_time + timedelta(minutes=i),
            "status":                UserStatus.Waitlist,
            "weekly_payment_status": WeeklyPaymentStatus.Paid,
            "current_level":         1,
            "referral_code":         _sim_ref_list[i],
        }
        for i in range(n_users)
    ]
    for start in range(0, n_users, _BULK_BATCH):
        db.execute(sa_insert(User), user_rows[start : start + _BULK_BATCH])
    db.commit()

    # ── 2. Create isolated dev pool (bypasses AUTO_POOL_CREATION_ENABLED toggle) ─
    #
    # We create the pool directly instead of calling check_and_scale_waitlist so:
    #   (a) The admin toggle state does NOT block the simulation.
    #   (b) Real waitlisted users are NOT consumed for the initial 12-member fill;
    #       only the freshly-created dev users are assigned.
    #
    # Derive next sequential pool name using the same alphabet logic used in
    # waitlist._next_pool_name (Pool A → B → … → Z → AA → …).
    _pool_count = db.query(Pool).count()
    _letters    = ""
    _n          = _pool_count
    while True:
        _letters = chr(65 + _n % 26) + _letters
        _n       = _n // 26 - 1
        if _n < 0:
            break
    dev_pool_name = f"Pool {_letters}"

    new_pool = crud_pool.create_pool(
        db,
        PoolCreate(name=dev_pool_name, status=PoolStatus.Active, total_members=NEW_POOL_INTAKE),
    )
    pool_id = new_pool.id

    # Pull the first NEW_POOL_INTAKE dev-prefix users and activate them directly.
    first_batch: list[User] = (
        db.query(User)
        .filter(User.username.like(f"{prefix}%"))
        .order_by(User.id.asc())
        .limit(NEW_POOL_INTAKE)
        .all()
    )
    if len(first_batch) < NEW_POOL_INTAKE:
        _cleanup_dev_users(db, prefix, pool_id=pool_id)
        raise HTTPException(
            status_code=500,
            detail=(
                f"Only {len(first_batch)} dev users were inserted; "
                f"need {NEW_POOL_INTAKE} to populate the dev pool."
            ),
        )
    for _member in first_batch:
        _member.status                = UserStatus.Active
        _member.current_pool_id       = pool_id
        _member.current_level         = 1
        _member.weekly_payment_status = WeeklyPaymentStatus.Paid
    db.commit()

    # ── 3. Run N draw cycles ──────────────────────────────────────────────────
    traces:           list[DrawTrace] = []
    n_executed        = 0
    total_paid        = 0.0
    total_tokens_made = 0

    for cycle in range(1, N + 1):
        members = (
            db.query(User)
            .filter(
                User.current_pool_id == pool_id,
                User.status == UserStatus.Active,
            )
            .all()
        )
        if not members:
            break  # pool exhausted early

        if body.auto_pay_installments:
            # Create real Burned DEP tokens for all unpaid members so Cash
            # Inflow statistics in the Tokens table are accurate per cycle.
            cycle_tokens = _simulate_installment_payments(db, members, pool_id)
            total_tokens_made += cycle_tokens
        else:
            # Fast-path: flip payment flags directly
            for m in members:
                m.weekly_payment_status = WeeklyPaymentStatus.Paid
            db.commit()

        try:
            result = run_dual_draw(db, pool_id)
        except ValueError:
            break  # draw validation failed — stop here

        p1 = float(result.winner_1.net_payout_inr)
        p2 = float(result.winner_2.net_payout_inr)
        total_paid += p1 + p2
        n_executed += 1

        traces.append(DrawTrace(
            cycle=cycle,
            winner_1=result.winner_1.winner_username,
            winner_2=result.winner_2.winner_username,
            level_1=result.winner_1.winner_level,
            level_2=result.winner_2.winner_level,
            payout_1_inr=p1,
            payout_2_inr=p2,
            edge_case=result.edge_case_used,
        ))

    # ── 4. Optional cleanup ───────────────────────────────────────────────────
    cleanup_done = False
    if body.cleanup:
        _cleanup_dev_users(db, prefix, pool_id=pool_id)
        cleanup_done = True

    return SimulateResult(
        n_requested=N,
        n_executed=n_executed,
        users_created=n_users,
        pool_id=None if cleanup_done else pool_id,
        draws=traces,
        total_paid_out_inr=round(total_paid, 2),
        simulated_tokens_created=total_tokens_made,
        cleanup_done=cleanup_done,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /dev/simulate-users
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/simulate-users", response_model=SimulateUsersResult)
def simulate_users(body: SimulateUsersRequest, db: Session = Depends(get_db)):
    """
    Rapidly bulk-insert `count` fake Waitlist users, each with a Burned DEP
    token representing a completed ₹1,000 deposit.

    Uses batched SQLAlchemy Core inserts for high-throughput performance:
      • 1,000 users  → ~200 ms
      • 10,000 users → ~800 ms
      • 100,000 users → ~5–8 s

    With auto_pool=True (default), repeatedly calls check_and_scale_waitlist()
    until no more pools can be formed. Remaining users stay on the Waitlist
    and can be pooled later via POST /admin/waitlist/check.

    To clean up these users later, call DELETE /dev/reset-data.
    """
    t0     = time.perf_counter()
    ts     = int(time.time())
    nonce  = random.randint(100_000, 999_999)
    prefix = f"dev_user_{ts}_{nonce}_"
    count  = body.count

    # ── Hashed password — computed ONCE, reused for every row ─────────────────
    # bcrypt intentionally takes ~100 ms.  Computing it per-row for 100k users
    # would take ~2.8 hours.  One hash for all dev users is correct here because
    # they are synthetic test accounts, not real credentials.
    hashed_pw = _get_dev_pw_hash()

    # ── Sequential base timestamp ─────────────────────────────────────────────
    # Each user gets join_date = base_time + i minutes so their FIFO rank is
    # deterministic and reflects realistic sequential growth.
    # PostgreSQL's server_default=NOW() would assign the SAME instant to every
    # row in the same bulk INSERT statement — explicit values avoid this.
    base_time = datetime.now(timezone.utc)

    # ── Generate unique DEP token codes entirely in Python ────────────────────
    # token_hex(4) → 8 hex chars → ~4.3 billion possibilities; collision at
    # 100k records is astronomically unlikely (~0.0000012%).
    codes: set[str] = set()
    while len(codes) < count:
        codes.update(
            f"DEP-{secrets.token_hex(4).upper()}"
            for _ in range(count - len(codes))
        )
    code_list = list(codes)

    # ── Pre-generate unique 8-char referral codes ─────────────────────────────
    _ref_codes: set[str] = set()
    while len(_ref_codes) < count:
        _ref_codes.update(
            "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            for _ in range(count - len(_ref_codes))
        )
    _ref_list = list(_ref_codes)

    # ── Build user rows ───────────────────────────────────────────────────────
    # username  = "{prefix}{12-hex UUID fragment}" — unique by construction;
    #             starts with the shared prefix so _cleanup_dev_users() can
    #             still identify and delete these rows with LIKE '{prefix}%'.
    # join_date = base_time + i minutes — guarantees perfect FIFO ordering and
    #             places newer dev users AFTER any real users (real users have
    #             historical join_dates; dev users join "from now forward").
    user_rows = [
        {
            "name":                  f"DevUser-{i + 1}",
            "mobile":                f"+99{ts:010d}{nonce:06d}{i:05d}",
            "username":              f"{prefix}{uuid.uuid4().hex[:12]}",
            "hashed_password":       hashed_pw,
            "join_date":             base_time + timedelta(minutes=i),
            "status":                UserStatus.Waitlist,
            "weekly_payment_status": WeeklyPaymentStatus.Paid,
            "current_level":         1,
            "referral_code":         _ref_list[i],
        }
        for i in range(count)
    ]

    # ── Bulk insert users (batched) ───────────────────────────────────────────
    for start in range(0, count, _BULK_BATCH):
        db.execute(sa_insert(User), user_rows[start : start + _BULK_BATCH])
    db.flush()  # force INSERT so we can SELECT the new IDs below

    # ── Fetch inserted user IDs in one round-trip ─────────────────────────────
    rows = db.execute(
        text("SELECT id FROM users WHERE username LIKE :prefix ORDER BY id"),
        {"prefix": f"{prefix}%"},
    ).fetchall()
    user_ids = [r[0] for r in rows]

    if not user_ids:
        db.rollback()
        raise HTTPException(status_code=500, detail="Bulk user insert produced no rows — check DB constraints.")

    # ── Build DEP token rows (Burned = deposit already completed) ─────────────
    token_rows = [
        {
            "code":                code_list[i],
            "type":                TokenType.Deposit,
            "value_inr":           _DEPOSIT_DEC,
            "status":              TokenStatus.Burned,
            "user_id":             user_ids[i],
            "redeemed_by_user_id": user_ids[i],
        }
        for i in range(len(user_ids))
    ]

    # ── Bulk insert tokens (batched) ──────────────────────────────────────────
    for start in range(0, len(token_rows), _BULK_BATCH):
        db.execute(sa_insert(Token), token_rows[start : start + _BULK_BATCH])
    db.commit()

    # ── Count remaining waitlist users (before pool formation) ───────────────
    waitlist_remaining = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist)
        .count()
    )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # ── Auto-form pools — runs in BACKGROUND to avoid HTTP timeout ────────────
    #
    # CRITICAL FIX: the while-True pool formation loop was previously executed
    # synchronously inside this HTTP handler.  For large injections (10,000+
    # users → 800+ pools), the loop could run for 30–120 s, causing:
    #   1. HTTP client timeout → connection closed, but thread keeps running.
    #   2. Abandoned thread holds DB connections → subsequent requests starve.
    #
    # Fix: the _INJECT_STATUS dict and _INJECT_LOCK were ALREADY DEFINED for this
    # purpose (lines 55–70 in this file) but were never wired up.  We now:
    #   • Immediately return HTTP 200 with the prefix (job ID).
    #   • Spawn pool formation in a daemon thread so the HTTP connection closes.
    #   • Poll via GET /dev/injection-status/{prefix} to track progress.
    #
    # Thread safety: _INJECT_LOCK guards all reads/writes to _INJECT_STATUS.
    # The background thread opens its own DB session (SessionLocal()) rather
    # than reusing the request session (which closes when the handler returns).

    if body.auto_pool:
        # Register job as "running" BEFORE spawning so poll can see it instantly
        with _INJECT_LOCK:
            _INJECT_STATUS[prefix] = {
                "status":             "running",
                "pools_formed":       0,
                "waitlist_remaining": waitlist_remaining,
                "error":              None,
                "started_at":         datetime.now(timezone.utc).isoformat(),
                "finished_at":        None,
            }

        def _bg_pool_formation(job_prefix: str) -> None:
            """
            Background pool-formation job.  Runs in a daemon thread.
            Opens its own DB session — the request session has already closed.
            """
            from app.database import SessionLocal
            bg_db = SessionLocal()
            pools_formed_bg = 0
            try:
                fill_pool_vacancies(bg_db)
                while True:
                    new_pool = manual_create_pool(bg_db)
                    if not new_pool:
                        break
                    pools_formed_bg += 1

                wl_remaining_bg = (
                    bg_db.query(User)
                    .filter(User.status == UserStatus.Waitlist)
                    .count()
                )
                with _INJECT_LOCK:
                    _INJECT_STATUS[job_prefix].update({
                        "status":             "done",
                        "pools_formed":       pools_formed_bg,
                        "waitlist_remaining": wl_remaining_bg,
                        "finished_at":        datetime.now(timezone.utc).isoformat(),
                    })
            except Exception as exc:
                with _INJECT_LOCK:
                    _INJECT_STATUS[job_prefix].update({
                        "status":    "error",
                        "error":     str(exc),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    })
            finally:
                bg_db.close()

        import threading as _th
        t = _th.Thread(target=_bg_pool_formation, args=(prefix,), daemon=True)
        t.start()

        note = (
            f"{len(user_ids)} users + {len(user_ids)} DEP tokens created "
            f"({elapsed_ms} ms). Pool formation running in background — "
            f"poll GET /dev/injection-status/{prefix} for progress."
        )
        pool_formation_info = "background"
    else:
        pool_formation_info = "skipped"
        note = (
            f"{len(user_ids)} users + {len(user_ids)} DEP tokens created "
            f"(sequential join_dates, bcrypt passwords). "
            f"auto_pool=False — no pool formation triggered. "
            f"Call POST /admin/waitlist/check when ready."
        )

    return SimulateUsersResult(
        users_created=len(user_ids),
        dep_tokens_created=len(user_ids),
        prefix=prefix,
        pools_formed=0,           # always 0 in response — formation is async now
        waitlist_remaining=waitlist_remaining,
        elapsed_ms=elapsed_ms,
        note=note,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /dev/injection-status/{prefix}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/injection-status/{prefix}")
def injection_status(prefix: str):
    """
    Poll the background pool-formation job started by POST /dev/simulate-users.

    Accepts prefix as a PATH parameter (e.g. GET /dev/injection-status/dev_user_123).
    Use POST /dev/simulate-users prefix in the response to poll here.

    GET /dev/injection-status?prefix=<prefix> (query param) is the unified endpoint
    that works for both simulate-users AND inject-timed background jobs.

    Status values:
      "running"  — pool formation in progress
      "done"     — completed successfully
      "error"    — failed; see `error` field for details

    The _INJECT_STATUS dict is process-local — it is NOT persisted across
    server restarts.  If the server restarts mid-job, the status entry will
    be absent and this endpoint returns 404.

    Usage pattern:
      POST /dev/simulate-users  → prefix=dev_user_1234_...
      loop:  GET /dev/injection-status/{prefix}  every 2s
             break when status == "done" or "error"
    """
    with _INJECT_LOCK:
        entry = _INJECT_STATUS.get(prefix)

    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No injection job found for prefix '{prefix}'. "
                "The server may have restarted, or auto_pool=False was used."
            ),
        )

    return {
        "prefix":             prefix,
        "status":             entry["status"],
        "pools_formed":       entry["pools_formed"],
        "waitlist_remaining": entry["waitlist_remaining"],
        "error":              entry["error"],
        "started_at":         entry["started_at"],
        "finished_at":        entry["finished_at"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /dev/reset-data
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/reset-data", response_model=ResetDataResult)
def reset_data(body: ResetDataRequest, db: Session = Depends(get_db)):
    """
    DESTRUCTIVE — truncates all rows in users, pools, and tokens.
    Resets PostgreSQL auto-increment sequences so IDs start from 1 again.

    Admin accounts and server configuration are NOT affected.

    Safety gate: the request body must include {"confirm": "CONFIRM_NUKE"}.
    Any other value returns 400 immediately.
    """
    if body.confirm != "CONFIRM_NUKE":
        raise HTTPException(
            status_code=400,
            detail='Safety check failed. Send {"confirm": "CONFIRM_NUKE"} in the request body.',
        )

    # Snapshot counts before deletion for the summary response
    users_count  = db.query(User).count()
    tokens_count = db.query(Token).count()
    pools_count  = db.query(Pool).count()

    sequences_reset = False
    try:
        # PostgreSQL: TRUNCATE with RESTART IDENTITY resets sequences to 1.
        # CASCADE handles all FK constraints automatically (tokens → users → pools).
        # The admins table has no FK to any of these tables and is unaffected.
        db.execute(text(
            "TRUNCATE TABLE tokens, users, pools RESTART IDENTITY CASCADE"
        ))
        db.commit()
        sequences_reset = True
    except Exception:
        # Fallback for non-PostgreSQL environments (e.g., SQLite in local unit tests)
        db.rollback()
        db.execute(text("DELETE FROM tokens"))
        db.execute(text("DELETE FROM users"))
        db.execute(text("DELETE FROM pools"))
        db.commit()

    return ResetDataResult(
        users_deleted=users_count,
        tokens_deleted=tokens_count,
        pools_deleted=pools_count,
        sequences_reset=sequences_reset,
        note=(
            "Admin accounts and server settings were NOT affected. "
            + ("All auto-increment IDs reset to 1." if sequences_reset else
               "Rows deleted but sequence reset skipped (non-PostgreSQL backend).")
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper — clean up a simulate-cycle run
# ─────────────────────────────────────────────────────────────────────────────

def _cleanup_dev_users(
    db: Session,
    prefix: str,
    pool_id: Optional[int] = None,
) -> None:
    """
    Remove all dev users whose username starts with `prefix`, their owned
    tokens, and optionally the pool that was created for the simulation.

    Safety: any REAL users accidentally absorbed into the dev pool are
    returned to Waitlist status before deletion proceeds.
    """
    dev_users = db.query(User).filter(User.username.like(f"{prefix}%")).all()

    if not dev_users and pool_id is None:
        return  # nothing to clean up

    dev_ids = [u.id for u in dev_users]

    # ── Return any real users sucked into the dev pool back to Waitlist ───────
    if pool_id:
        strays = (
            db.query(User)
            .filter(
                User.current_pool_id == pool_id,
                ~User.username.like(f"{prefix}%"),
            )
            .all()
        )
        for user in strays:
            user.current_pool_id = None
            user.status          = UserStatus.Waitlist
            user.current_level   = 1

    if dev_ids:
        # ── Null out FK back-references before deletion ───────────────────────
        # 1. Users who were referred by a dev user
        (
            db.query(User)
            .filter(User.referred_by_user_id.in_(dev_ids))
            .update({"referred_by_user_id": None}, synchronize_session=False)
        )
        # 2. Token audit trail: tokens burned *by* a dev user
        (
            db.query(Token)
            .filter(Token.redeemed_by_user_id.in_(dev_ids))
            .update({"redeemed_by_user_id": None}, synchronize_session=False)
        )
        db.flush()

        # ── Delete tokens *owned by* dev users ───────────────────────────────
        (
            db.query(Token)
            .filter(Token.user_id.in_(dev_ids))
            .delete(synchronize_session=False)
        )
        db.flush()

        # ── Delete dev users ──────────────────────────────────────────────────
        db.query(User).filter(User.id.in_(dev_ids)).delete(synchronize_session=False)

    # ── Delete the dev pool ───────────────────────────────────────────────────
    if pool_id:
        db.query(Pool).filter(Pool.id == pool_id).delete(synchronize_session=False)

    db.commit()


# =============================================================================
# POST /dev/advanced-simulation
# =============================================================================
#
# High-performance, database-isolated stress-testing simulation.
# Runs up to 1,000 consecutive weekly draw cycles entirely in-memory.
#
# Database isolation strategy
# ────────────────────────────
# • All dummy user records share username prefix  sim_{run_id[:12]}_
#   This prefix is the sole cleanup anchor in the `finally` block.
# • Pool and token state are NEVER written to DB — they are pure Python objects.
# • User rows are flushed to DB in _SIM_CHUNK batches to prevent OOM.
# • The `finally` block issues a cascading SQL DELETE on that prefix,
#   guaranteeing 100% cleanup regardless of success, exception, or timeout.
# =============================================================================

_logger_sim = __import__("logging").getLogger(__name__ + ".advsim")
_SIM_CHUNK  = 500          # DB-insert batch size (per spec)
_S_CAP      = 12           # pool capacity
_S_THR      = 12           # waitlist threshold for auto-scaling a new pool
_S_DEP      = Decimal("1000")



# ── Request schema (strict validation) ───────────────────────────────────────

class AdvancedSimRequest(BaseModel):
    total_cycles: int = Field(
        ..., ge=1, le=1000,
        description="Number of consecutive weekly cycles to simulate (1–1000)",
    )
    # ── B parameter: Late Fee Rate (% of ₹1000 deposit per day) ──────────────
    late_fee_pct: float = Field(
        5.0, ge=5.0,
        description=(
            "B parameter: Late fee per day as % of ₹1,000 deposit (minimum 5% = ₹50/day). "
            "Higher B → fewer members attempt grace period (C decreases as B increases)."
        ),
    )
    # ── Late defaulters ratio (feeds A + C pool) ──────────────────────────────
    late_users_ratio_pct: float = Field(
        2.0, ge=0.0, le=100.0,
        description="% of active pool members who miss the payment due date each cycle",
    )
    # ── A parameter: Direct Elimination % ────────────────────────────────────
    elim_pct_a: float = Field(
        80.0, ge=0.05, le=100.0,
        description=(
            "A parameter: % of late members who are directly eliminated (skip grace period). "
            "Remaining (100-A)% enter the grace period and are eligible for C."
        ),
    )
    # ── C parameter: Grace Saver % ────────────────────────────────────────────
    grace_saver_pct_c: float = Field(
        15.0, ge=0.05, le=100.0,
        description=(
            "C parameter: % of grace-eligible members who actually pay the grace fee "
            "(seat-save fee + accumulated late fees). "
            "Circular: B cost reduces C willingness; lower B → higher C."
        ),
    )
    volatility_mode: bool = Field(
        False,
        description="Randomise weekly inflow when True; inject exactly 12 when False",
    )
    volatility_max_inflow: int = Field(
        100, ge=5,
        description="Upper bound for random weekly user injection (volatility mode only)",
    )
    avg_rdr_pct: float = Field(
        40.0, ge=0.0, le=100.0,
        description=(
            "Simulated average Referral Density Ratio % "
            "(0 = all organic, 100 = all referral). "
            "Gaussian noise (σ=8) is added per cycle to model real-world variance."
        ),
    )


# ── Lightweight in-memory state objects ──────────────────────────────────────

@_dc
class _SU:
    """In-memory simulation user — never a SQLAlchemy ORM object."""
    sid:          int
    uname:        str
    mobile:       str
    joined:       datetime
    level:        int  = 1
    paid:         bool = False
    late:         bool = False
    pool_sid:     int | None = None   # which _SP this user belongs to
    alive:        bool = True         # False = Eliminated_Won
    deposits_paid:  int  = 1            # entry deposit counted as first payment
    sde_required:   bool = False        # True when member reaches L4 → guaranteed SDE exit


@_dc
class _SP:
    """In-memory simulation pool."""
    sid:        int
    name:       str
    created_at: datetime
    paused:     bool = False      # Paused_Awaiting_Members (draw skipped)
    dissolved:  bool = False      # Merged_Dissolved


# ── DB helpers ────────────────────────────────────────────────────────────────

def _sim_flush(db: Session, chunk: list[dict]) -> None:
    """Bulk-insert one chunk of sim user rows via SQLAlchemy Core."""
    if not chunk:
        return
    db.execute(sa_insert(User), chunk)
    db.commit()


def _sim_cleanup(db: Session, uname_prefix: str) -> None:
    """
    Cascading SQL DELETE — removes all records tagged with this sim run.
    Called unconditionally in the `finally` block; swallows exceptions.
    """
    _logger_sim.info("AdvancedSim cleanup: deleting prefix='%s%%'", uname_prefix)
    try:
        db.execute(
            text(
                "DELETE FROM tokens "
                "WHERE user_id IN "
                "(SELECT id FROM users WHERE username LIKE :p)"
            ),
            {"p": f"{uname_prefix}%"},
        )
        db.execute(
            text("DELETE FROM users WHERE username LIKE :p"),
            {"p": f"{uname_prefix}%"},
        )
        db.commit()
        _logger_sim.info("AdvancedSim cleanup complete.")
    except Exception as exc:
        _logger_sim.error("AdvancedSim cleanup failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


# ── Core simulation engine ────────────────────────────────────────────────────

class _AdvSimEngine:
    """
    Self-contained in-memory weekly-draw engine.

    All business logic (FIFO refill, condensation, Smart Pairing draw,
    level progression) runs in Python dicts — zero DB reads during the main
    loop.  User records are buffered in `_ins` and written to DB per chunk
    by the endpoint.  Pool and token records are never persisted.
    """

    def __init__(self, run_id: str):
        self._rid    = run_id
        self._upfx   = f"sim_{run_id[:12]}"  # username prefix (cleanup anchor)
        # Deterministic per-run offset → unique mobile numbers across all runs
        self._mob    = int(run_id[:8], 16)    # 0 – 4,294,967,295

        self._users: dict[int, _SU] = {}
        self._pools: dict[int, _SP] = {}
        self._wl:    list[int]      = []     # waitlist — maintained in join-order

        self._uidc = 1    # simulation-local user SID counter
        self._pidc = 1    # simulation-local pool SID counter

        # Metrics (Decimal for financial accuracy)
        self.n_created   = 0
        self.n_winners   = 0
        self.n_scaled    = 0
        self.n_condensed = 0
        self.n_paused    = 0
        self._elim = 0        # total eliminations across all cycles (A-path + grace-expired)
        self._dep  = Decimal("0")
        self._pay  = Decimal("0")
        self._late = Decimal("0")

        # God Mode — journey & level-wise tracking
        self.direct_assignments:  int            = 0
        self.level_wise_winners:  dict[int, int]     = {l: 0 for l in range(1, 7)}
        self.level_wise_deposits: dict[int, Decimal] = {l: Decimal("0") for l in range(1, 7)}
        self.level_wise_payouts:  dict[int, Decimal] = {l: Decimal("0") for l in range(1, 7)}
        self._inflow_history:     list[int]       = []   # new users per cycle (velocity calc)

        # SDE / draw-type metrics (architecture-accurate — matches Brain 5 routing)
        self.n_sde_flags:    int = 0   # total L4 flaggings (sde_required = True events)
        self.n_sde_exits:    int = 0   # SDE-guaranteed exits executed
        self.n_type_a_draws: int = 0   # Type A draw executions (LPI 14-25%)
        self.n_type_b_draws: int = 0   # Type B draw executions (L1/L2 shortage)

        # ── L5/L6 peak tracking (Anti-Maturity pressure metrics) ──────────────
        # Tracks the maximum L5 and L6 member counts seen in any single cycle.
        # Used by the Stress Test panel to show heavy pressure accumulation.
        self._max_l5:        int = 0   # peak L5 member count across all cycles
        self._max_l6:        int = 0   # peak L6 member count across all cycles
        self._high_lpi_streak: int = 0   # consecutive cycles with LPI > 40%
        self._max_high_lpi_streak: int = 0   # longest high-LPI streak seen

        # ── SDE Extension event counters (A-1: WHY members reach L5/L6) ────────
        # l5_escalation_events: times an L5 member was found in a pool (Ext-II draw)
        # l6_escalation_events: times an L6 member was found in a pool (Ext-III draw)
        # accel_diss_events:    times accelerated dissolution triggered (≥60% L4+)
        # Escalation root cause: accelerated dissolution surviving L4s advance → L5
        self._l5_escalation_events:   int = 0
        self._l6_escalation_events:   int = 0
        self._accel_diss_events:       int = 0

        # ── Weekly detail log (for Master Weekly Report, Phase 2-C) ──────────
        # Each element is a rich per-cycle record emitted by run_cycle().
        # Stored here so the endpoint can return it alongside simulation_summary.
        self.weekly_detail: list[dict] = []

        self.logs: list[dict] = []
        self._ins:  list[dict] = []   # pending DB-insert buffer

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _mbrs(self, psid: int) -> list[_SU]:
        """Live active members of pool psid."""
        return [u for u in self._users.values()
                if u.pool_sid == psid and u.alive]

    def _calc_lpi(self) -> float:
        """
        Level Pressure Index = (L3+L4+L5+L6 active members) / Total Active × 100.
        Mirrors Brain 5 LPI calculation. Drives draw type routing.
          0–14%  → Regular draw
          14–25% → Type A (if L3/L4 present)
          25%+   → SDE (if sde_required members exist)
        """
        active = [u for u in self._users.values()
                  if u.alive and u.pool_sid is not None]
        if not active:
            return 0.0
        pressure = sum(1 for u in active if u.level >= 3)
        return pressure / len(active) * 100.0

    def _letter(self) -> str:
        """Sequence: A, B, …, Z, AA, AB, … (based on n_scaled at call time)."""
        n, s = self.n_scaled, ""
        while True:
            s = chr(65 + n % 26) + s
            n = n // 26 - 1
            if n < 0:
                break
        return s

    def _mkpool(self, ts: datetime) -> _SP:
        sid  = self._pidc; self._pidc += 1
        pool = _SP(sid=sid,
                   name=f"SIM-{self._rid[:8]}-Pool {self._letter()}",
                   created_at=ts)
        self._pools[sid] = pool
        self.n_scaled += 1
        return pool

    def _mkrow(self, sid: int, uname: str, joined: datetime,
               mobile: str, hpw: str) -> dict:
        """Build a User insert-mapping dict."""
        return {
            "name":                          f"AdvSim-{sid}",
            "username":                      uname,
            "mobile":                        mobile,
            "hashed_password":               hpw,
            "join_date":                     joined,
            "status":                        UserStatus.Waitlist,
            "weekly_payment_status":         WeeklyPaymentStatus.Unpaid,
            "current_level":                 1,
            "current_pool_id":               None,
            "referred_by_user_id":           None,
            "referral_code":                 None,   # NULL OK: unique constraint allows multi-NULL
            "total_referrals_count":          0,
            "accumulated_referral_bonus_inr": Decimal("0"),
            "late_fees_inr":                  Decimal("0"),
            "dynamic_merges_experienced":     0,
            "pauses_experienced":             0,
            "total_deposited_inr":            1000,
            "sde_required":                   False,
        }

    # ── Step A — FIFO Sequential Inflow ───────────────────────────────────────

    def step_a(self, cycle: int, vol: bool, vol_max: int,
               base: datetime, hpw: str) -> int:
        """
        Create n new users.  Sequential join_dates (1 min apart) guarantee
        strict FIFO ordering independent of DB clock granularity.
        """
        n  = random.randint(5, vol_max) if vol else 12
        t0 = base + timedelta(weeks=cycle - 1)

        for i in range(n):
            sid    = self._uidc; self._uidc += 1
            joined = t0 + timedelta(minutes=i)       # sequential → FIFO guaranteed
            uname  = f"{self._upfx}_w{cycle:04d}_{sid:07d}"
            # +99 prefix = clearly synthetic; 10-digit body unique per (run × user)
            mobile = f"+99{(self._mob + sid) % 10_000_000_000:010d}"

            self._users[sid] = _SU(sid=sid, uname=uname, mobile=mobile, joined=joined)
            self._wl.append(sid)        # sequential inserts preserve join-order
            self._dep   += _S_DEP
            self.n_created += 1
            self._ins.append(self._mkrow(sid, uname, joined, mobile, hpw))

        self._inflow_history.append(n)  # record for velocity calculations
        return n

    # ── Step B — Ratio Penalty Application (A/B/C Circular Model) ──────────────

    def step_b(
        self,
        late_fee_pct:      float,
        late_ratio_pct:    float,
        elim_pct_a:        float = 80.0,
        grace_saver_pct_c: float = 15.0,
    ) -> dict:
        """
        Circular A/B/C late-payment model:

        A (elim_pct_a):        % of late members directly eliminated (skip grace period).
        B (late_fee_pct):      Late fee per day as % of ₹1000 deposit. Minimum 5% = ₹50/day.
                               Higher B → fewer members attempt grace (C follows B inversely).
        C (grace_saver_pct_c): % of grace-eligible members who actually pay the grace fee.

        Flow:
          1. Select late_ratio_pct% of active pool members as "late".
          2. Of those: A% are directly eliminated (they skip grace entirely).
          3. Remaining (100-A)% enter grace period.
          4. Of grace-eligible: C% pay grace fee + late fees → seat saved.
          5. Remaining grace-eligible who don't pay → also eliminated.

        Revenue:
          - Late fees collected = C% of grace-eligible * daily fee * avg_days_late
          - Grace seat-save fee (₹500 proxy) collected from C%

        Returns dict of {n_late, n_direct_elim, n_grace_eligible, n_grace_saved, n_grace_elim}
        """
        pool_mbrs = [u for u in self._users.values()
                     if u.alive and u.pool_sid is not None]
        n_pool    = len(pool_mbrs)
        n_late    = int(n_pool * late_ratio_pct / 100.0)
        if not n_late:
            return {"n_late": 0, "n_direct_elim": 0, "n_grace_eligible": 0,
                    "n_grace_saved": 0, "n_grace_elim": 0}

        late_sel      = random.sample(pool_mbrs, min(n_late, len(pool_mbrs)))
        n_actual_late = len(late_sel)

        # B — Late fee accumulation (proxy: 3 days late on average)
        avg_days_late = 3.0
        fee_each      = _S_DEP * Decimal(str(late_fee_pct)) / Decimal("100") * Decimal(str(avg_days_late))
        grace_seat_fee = Decimal("500")  # proxy for ₹500 grace seat-save fee

        for u in late_sel:
            u.late = True

        # A — Direct elimination
        n_direct_elim   = max(0, int(n_actual_late * elim_pct_a / 100.0))
        direct_elim_sel = late_sel[:n_direct_elim]
        grace_eligible  = late_sel[n_direct_elim:]

        # Eliminate directly (A path)
        for u in direct_elim_sel:
            u.alive = False
            self._elim += 1
            # Late fees are forfeited — NOT collected (user never paid)

        # C — Grace period saving
        n_grace_elg   = len(grace_eligible)
        n_grace_saved = max(0, int(n_grace_elg * grace_saver_pct_c / 100.0))
        grace_saved   = grace_eligible[:n_grace_saved]
        grace_elim    = grace_eligible[n_grace_saved:]

        # Grace savers: collect late fees + grace seat-save fee (REVENUE)
        for u in grace_saved:
            u.late  = False   # paid, seat saved
            u.paid  = True
            self._late      += fee_each          # late fee collected (B parameter)
            self._late      += grace_seat_fee    # seat-save fee also collected as revenue

        # Grace non-payers: eliminated
        for u in grace_elim:
            u.alive = False
            self._elim += 1
            # Forfeited: late fees NOT collected

        return {
            "n_late":          n_actual_late,
            "n_direct_elim":   n_direct_elim,
            "n_grace_eligible":n_grace_elg,
            "n_grace_saved":   n_grace_saved,
            "n_grace_elim":    len(grace_elim),
        }

    # ── Step C — Auto Billing + Weekly Installment Collection ────────────────

    def step_c(self):
        """
        Mark non-late active members Paid; clear late markers; collect weekly
        installments from ALL active pool members.

        The recurring ₹1,000/week installment that every pool member pays is
        the primary revenue stream that funds draw payouts.  Without tracking it,
        the liquidity float goes massively negative as pools accumulate.

        Note: initial join deposits are tracked in step_a (_dep += _S_DEP per new user).
        This step adds the RECURRING installment on top of those initial deposits.
        """
        active_in_pools = 0
        for u in self._users.values():
            if u.alive and u.pool_sid is not None:
                if not u.late:
                    u.paid = True
                active_in_pools += 1          # count ALL active members, late or not
                u.deposits_paid += 1          # accumulate installment count per user
        for u in self._users.values():
            u.late = False

        # Weekly installment collection: every active pool member pays ₹1,000 this week.
        # This is tracked in _dep (total system inflow = initial deposits + installments).
        self._dep += _S_DEP * active_in_pools

    # ── AI helpers ────────────────────────────────────────────────────────────

    def _recent_velocity(self) -> float:
        """Average weekly inflow over the last 3 cycles (slow velocity proxy)."""
        hist = self._inflow_history[-3:] if len(self._inflow_history) >= 1 else []
        return (sum(hist) / len(hist)) if hist else 12.0

    def _determine_sim_multiplier(
        self, velocity: float, burn_rate: float, rdr_pct: float
    ) -> tuple[float, str, str]:
        """
        Simulation-local mirror of the production AI decision matrix.
        Returns (multiplier, scenario, phase).
        """
        if velocity > burn_rate:
            if rdr_pct < 30.0:
                return 0.50, "SUSTAINABLE_WAVE",  "BOOM"
            elif rdr_pct > 70.0:
                return 1.50, "FLASH_FLOOD",        "BOOM"   # cautious — volatile referral hype
            else:
                return 0.75, "BOOM_GOLDEN_CROSS",  "BOOM"
        else:
            if rdr_pct > 60.0:
                return 2.00, "REFERRAL_LIFELINE",  "LIQUIDITY_PROTECTION"
            return 2.00,     "DRY_PHASE",          "DRY"

    # ── Step D — Double-FIFO Refill + Condensation ────────────────────────────

    def step_d(self, ts: datetime, rdr_pct: float = 40.0) -> tuple[int, int]:
        """
        Phase 1: Fill vacancies from Waitlist (oldest pool first, oldest user first).
        Phase 2: Auto-scale new pool when waitlist >= threshold.
        Phase 3: Condensation — harvest newest source pools for oldest targets;
                 STRICTLY preserve current_level and join_date of transferred members.
        """
        cond = merges = 0

        # ── Phase 1 ───────────────────────────────────────────────────────────
        p1 = sorted([p for p in self._pools.values() if not p.dissolved],
                    key=lambda p: p.created_at)
        for pool in p1:
            vac = _S_CAP - len(self._mbrs(pool.sid))
            while vac > 0 and self._wl:
                uid       = self._wl.pop(0)
                u         = self._users[uid]
                u.pool_sid = pool.sid
                u.paid    = True
                u.level   = 1
                vac      -= 1
                self.direct_assignments += 1
            if pool.paused and len(self._mbrs(pool.sid)) >= _S_CAP:
                pool.paused = False

        # ── Phase 2 (AI-governed spawning) ───────────────────────────────────
        # Burn rate = Active-only (paused pools don't exit members this cycle).
        # Reserve = ALL operational pools (Active + Paused) because paused pools
        # still hold members and need replacement coverage to eventually resume.
        _active_ct   = sum(1 for p in self._pools.values() if not p.dissolved and not p.paused)
        _ops_ct      = sum(1 for p in self._pools.values() if not p.dissolved)  # active + paused
        _burn        = float(_active_ct * 2)
        _velocity    = self._recent_velocity()
        _multiplier, _, _ = self._determine_sim_multiplier(_velocity, _burn, rdr_pct)
        _dyn_reserve = int(_ops_ct * _S_CAP * _multiplier)      # reserve covers ALL ops pools
        _available   = max(0, len(self._wl) - _dyn_reserve)

        while _available >= _S_THR:
            pool = self._mkpool(ts)
            for _ in range(_S_CAP):
                if not self._wl:
                    break
                uid       = self._wl.pop(0)
                u         = self._users[uid]
                u.pool_sid = pool.sid
                u.paid    = True
                u.level   = 1
                self.direct_assignments += 1
            _available -= _S_CAP

        # ── Phase 3: Dynamic Inter-Pool Condensation ──────────────────────────
        p3_tgts = sorted(
            [p for p in self._pools.values()
             if not p.dissolved and len(self._mbrs(p.sid)) < _S_CAP],
            key=lambda p: p.created_at,             # oldest target filled first
        )
        if p3_tgts:
            tgt_ids = {p.sid for p in p3_tgts}
            srcs = sorted(
                [p for p in self._pools.values()
                 if not p.dissolved and not p.paused
                 and p.sid not in tgt_ids
                 and len(self._mbrs(p.sid)) == _S_CAP],
                key=lambda p: p.created_at,
                reverse=True,                        # newest source dismantled first
            )
            si = 0
            for tgt in p3_tgts:
                vac = _S_CAP - len(self._mbrs(tgt.sid))
                while vac > 0 and si < len(srcs):
                    src   = srcs[si]
                    batch = sorted(self._mbrs(src.sid), key=lambda u: u.joined)
                    take  = min(vac, len(batch))
                    for m in batch[:take]:
                        # !! STRICTLY preserve current_level, paid, join_date !!
                        m.pool_sid = tgt.sid
                        vac       -= 1
                        cond      += 1
                        self.n_condensed += 1
                        _logger_sim.debug(
                            "Condensation Event: Moved @%s (L%d) %s → %s",
                            m.uname, m.level, src.name, tgt.name,
                        )
                    if not self._mbrs(src.sid):
                        src.dissolved = True
                        merges       += 1
                        _logger_sim.debug(
                            "Condensation Event: %s dissolved.", src.name,
                        )
                        si += 1

        return cond, merges

    # ── Step E — Draw + Safestop ──────────────────────────────────────────────

    def step_e(self) -> tuple[int, int]:
        """
        Architecture-accurate draw router — mirrors ALL Brain 5 production logic.

        Faithfully implements the FULL decision tree (same rules/thresholds as production):
          0. SDE Ext-III: L6 member found → both winners from L6 tier (upper) + L1-L5 (lower)
             → guaranteed L6 forced exit; runs BEFORE any other draw type
          1. SDE Ext-II:  L5 member found → both winners: upper=L5, lower=L1-L4
             → guaranteed L5 forced exit; runs after Ext-III check
          2. SDE draw:    sde_required (L4) → oldest L4 exits guaranteed; lower=L1-L2 preferred
          3. Accelerated dissolution: ≥60% L4+ → both winners from L4+; dissolve if <8 remain
          4. Type A draw: LPI 14–25% + L3/L4 + L1/L2 available
          5. Type B draw: LPI ≥ 14% + L3/L4 + NO L1/L2 (shortage)
          6. Regular draw: L1-3 lower / L4-6 upper (default)

        L5/L6 escalation tracking (A-1: WHY members reach L5/L6):
          Members reach L5/L6 when SDE is unable to process them due to:
            - Pool being paused (insufficient members)
            - Insufficient lower-tier members to match with the L4 for SDE
          The simulation now runs Ext-II/III to catch these cases BEFORE they accumulate.
        """
        draws = new_pauses = 0
        lpi   = self._calc_lpi()

        for pool in sorted(
            [p for p in self._pools.values() if not p.dissolved and not p.paused],
            key=lambda p: p.sid,
        ):
            members = self._mbrs(pool.sid)

            # ── Safestop — pool must have exactly POOL_CAPACITY (12) members to draw ─
            # Members only advance level when they survive a draw.
            # Under-capacity pools never draw, so members inside cannot advance.
            # L5/L6 escalation therefore only occurs via accelerated dissolution:
            #   → pool with ≥60% L4+ draws both winners from L4+
            #   → surviving L4 members advance +1 → L5
            #   → Ext-II then forces L5 exit in the following eligible cycle.
            if len(members) != _S_CAP:
                pool.paused = True
                new_pauses += 1
                self.n_paused += 1
                continue

            # ── Classify members ──────────────────────────────────────────────
            sde_mbrs = [m for m in members if m.sde_required]
            l1_l2    = [m for m in members if 1 <= m.level <= 2]
            l3       = [m for m in members if m.level == 3]
            l4       = [m for m in members if m.level == 4]
            l5       = [m for m in members if m.level == 5]
            l6       = [m for m in members if m.level == 6]
            l1_l3    = [m for m in members if 1 <= m.level <= 3]
            l1_l4    = [m for m in members if 1 <= m.level <= 4]
            l1_l5    = [m for m in members if 1 <= m.level <= 5]
            l4_l6    = [m for m in members if 4 <= m.level <= 6]
            l4_plus_ratio = len(l4_l6) / max(len(members), 1)

            w1 = w2 = None
            draw_tag = "regular"

            # ── SDE Ext-III: L6 found — both winners from L6 (upper) + L1-L5 (lower) ──
            if l6:
                upper = random.choice(l6)
                lowers = [m for m in l1_l5 if m.sid != upper.sid]
                if not lowers:
                    lowers = [m for m in members if m.sid != upper.sid]
                if lowers:
                    w2 = upper
                    w1 = random.choice(lowers)
                    draw_tag = "sde"
                    self.n_sde_exits += 1
                    self._l6_escalation_events += 1   # Ext-III: L6 forced exit

            # ── SDE Ext-II: L5 found — both winners: upper=L5, lower=L1-L4 ──────────
            elif l5:
                upper = random.choice(l5)
                lowers = [m for m in l1_l4 if m.sid != upper.sid]
                if not lowers:
                    lowers = [m for m in l1_l3 if m.sid != upper.sid]
                if not lowers:
                    lowers = [m for m in members if m.sid != upper.sid]
                if lowers:
                    w2 = upper
                    w1 = random.choice(lowers)
                    draw_tag = "sde"
                    self.n_sde_exits += 1
                    self._l5_escalation_events += 1   # Ext-II: L5 forced exit

            # ── Accelerated Dissolution: ≥60% L4+ → both winners from L4+ ─────────
            elif l4_plus_ratio >= 0.60 and len(l4_l6) >= 2:
                w1 = random.choice(l4_l6)
                l4_l6_remaining = [m for m in l4_l6 if m.sid != w1.sid]
                if l4_l6_remaining:
                    w2 = random.choice(l4_l6_remaining)
                    draw_tag = "sde"
                    self.n_sde_exits += 1
                    self._accel_diss_events += 1   # Accel dissolution: ≥60% L4+ triggered

            # ── SDE Draw: sde_required L4 member guaranteed exit ─────────────────────
            elif sde_mbrs:
                upper  = sde_mbrs[0]      # oldest SDE-flagged L4 member
                lowers = [m for m in l1_l2 if m.sid != upper.sid]
                if not lowers:
                    lowers = [m for m in l1_l3 if m.sid != upper.sid]
                if not lowers:
                    lowers = [m for m in members if m.sid != upper.sid]
                if not lowers:
                    pool.paused = True; new_pauses += 1; self.n_paused += 1; continue
                w1 = random.choice(lowers)
                w2 = upper
                draw_tag = "sde"
                self.n_sde_exits += 1

            elif lpi >= 14.0 and (l3 or l4):
                if l1_l2:
                    # ── Type A: L1/L2 lower, L3/L4 upper ─────────────────────
                    upper_pool = l3 + l4
                    w2   = random.choice(upper_pool)
                    avail = [m for m in l1_l2 if m.sid != w2.sid]
                    w1   = random.choice(avail) if avail else random.choice(l1_l2)
                    draw_tag = "type_a"
                    self.n_type_a_draws += 1
                elif l3 and l4:
                    # ── Type B: L3 lower, L4 upper (L1/L2 shortage) ───────────
                    w1 = random.choice(l3)
                    w2 = random.choice(l4)
                    draw_tag = "type_b"
                    self.n_type_b_draws += 1
                else:
                    # Degenerate: not enough tiered members — regular fallback
                    if not l4_l6:
                        if len(l1_l3) < 2:
                            pool.paused = True; new_pauses += 1; self.n_paused += 1; continue
                        w1, w2 = random.sample(l1_l3, 2)
                    else:
                        if not l1_l3:
                            pool.paused = True; new_pauses += 1; self.n_paused += 1; continue
                        w1 = random.choice(l1_l3)
                        w2 = random.choice(l4_l6)

            else:
                # ── Regular Draw: L1-3 lower / L4-6 upper ────────────────────
                if not l4_l6:                      # early-pool edge case (weeks 1-3)
                    if len(l1_l3) < 2:
                        pool.paused = True; new_pauses += 1; self.n_paused += 1; continue
                    w1, w2 = random.sample(l1_l3, 2)
                else:
                    if not l1_l3:
                        pool.paused = True; new_pauses += 1; self.n_paused += 1; continue
                    w1 = random.choice(l1_l3)
                    w2 = random.choice(l4_l6)

            # Safety check (should not reach here, but defensive)
            if w1 is None or w2 is None:
                pool.paused = True; new_pauses += 1; self.n_paused += 1; continue

            # ── Issue payouts, eliminate winners ──────────────────────────────
            for w in (w1, w2):
                _, net = LEVEL_PAYOUTS.get(w.level, (2500, 2000))
                net_d = Decimal(str(net))
                self._pay                          += net_d
                self.level_wise_winners[w.level]    = self.level_wise_winners.get(w.level,   0)             + 1
                self.level_wise_payouts[w.level]    = self.level_wise_payouts.get(w.level,   Decimal("0")) + net_d
                self.level_wise_deposits[w.level]   = (
                    self.level_wise_deposits.get(w.level, Decimal("0"))
                    + Decimal(str(w.deposits_paid)) * _S_DEP
                )
                w.alive    = False
                w.pool_sid = None
                self.n_winners += 1

            # ── Advance survivors +1 level; flag new L4 arrivals for SDE ──────
            winner_sids = {w1.sid, w2.sid}
            for m in members:
                if m.alive and m.sid not in winner_sids:
                    old_level = m.level
                    m.level   = min(m.level + 1, 6)
                    m.paid    = False               # reset for next installment week
                    # Anti-Maturity Protocol: flag L4 arrivals for guaranteed exit
                    if old_level == 3 and m.level == 4 and not m.sde_required:
                        m.sde_required  = True
                        self.n_sde_flags += 1

            draws += 1

        return draws, new_pauses

    # ── Per-cycle orchestrator ────────────────────────────────────────────────

    def run_cycle(self, cycle: int, req: AdvancedSimRequest,
                  base: datetime, hpw: str):
        ts = base + timedelta(weeks=cycle - 1)

        # ── Pre-cycle AI snapshot (uses history BEFORE this cycle's inflow) ──
        velocity   = self._recent_velocity()
        active_pre = sum(1 for p in self._pools.values() if not p.dissolved and not p.paused)
        burn_rate  = float(active_pre * 2)
        # Gaussian noise ± 8% around the configured avg RDR
        rdr_pct    = max(0.0, min(100.0, req.avg_rdr_pct + random.gauss(0, 8.0)))
        _, scenario, phase = self._determine_sim_multiplier(velocity, burn_rate, rdr_pct)
        # Momentum = current cycle velocity vs previous-cycle velocity
        prev_vel   = (
            (sum(self._inflow_history[-4:-1]) / len(self._inflow_history[-4:-1]))
            if len(self._inflow_history) >= 2 else velocity
        )
        momentum   = velocity - prev_vel

        # ── Pre-draw level snapshot ──────────────────────────────────────────
        # Count active pool members at each level before the draw executes.
        level_counts_pre: dict[str, int] = {f"L{l}": 0 for l in range(1, 7)}
        for u in self._users.values():
            if u.alive and u.pool_sid is not None:
                key = f"L{min(u.level, 6)}"
                level_counts_pre[key] = level_counts_pre.get(key, 0) + 1

        # Track L5/L6 peaks for Anti-Maturity pressure metrics
        l5_this = level_counts_pre.get("L5", 0)
        l6_this = level_counts_pre.get("L6", 0)
        if l5_this > self._max_l5: self._max_l5 = l5_this
        if l6_this > self._max_l6: self._max_l6 = l6_this

        # ── Execute cycle (A/B/C circular late-fee model) ───────────────────
        n_joined  = self.step_a(cycle, req.volatility_mode, req.volatility_max_inflow, base, hpw)
        late_info = self.step_b(
            late_fee_pct      = req.late_fee_pct,
            late_ratio_pct    = req.late_users_ratio_pct,
            elim_pct_a        = getattr(req, "elim_pct_a",        80.0),
            grace_saver_pct_c = getattr(req, "grace_saver_pct_c", 15.0),
        )
        n_late = late_info["n_late"]
        self.step_c()
        condensed, merges = self.step_d(ts, rdr_pct)
        draws_this_cycle, pauses = self.step_e()

        # ── Post-draw state ──────────────────────────────────────────────────
        lpi_post   = self._calc_lpi()
        active_n   = sum(1 for p in self._pools.values() if not p.dissolved and not p.paused)
        paused_n   = sum(1 for p in self._pools.values() if not p.dissolved and p.paused)
        total_pools = sum(1 for p in self._pools.values() if not p.dissolved)

        # LPI streak tracking for "heavy pressure mode"
        if lpi_post > 40.0:
            self._high_lpi_streak += 1
            if self._high_lpi_streak > self._max_high_lpi_streak:
                self._max_high_lpi_streak = self._high_lpi_streak
        else:
            self._high_lpi_streak = 0

        # Post-draw level distribution (after winners exit + new members join)
        level_counts_post: dict[str, int] = {f"L{l}": 0 for l in range(1, 7)}
        for u in self._users.values():
            if u.alive and u.pool_sid is not None:
                key = f"L{min(u.level, 6)}"
                level_counts_post[key] = level_counts_post.get(key, 0) + 1

        # Financial snapshot this cycle
        cash_inflow_this  = n_joined * float(_S_DEP)    # new deposits
        # Weekly installments collected (approximated from active members × 1000)
        total_active_in_pools = sum(level_counts_post.values())
        installments_this  = total_active_in_pools * float(_S_DEP)
        late_fees_this     = n_late * float(_S_DEP) * (req.late_fee_pct / 100.0) if n_late else 0.0

        # Randomised join timestamps for realistic week representation
        # Join dates are distributed across the week via Gaussian (σ=2 days)
        week_start_iso = ts.date().isoformat()

        # ── Append to cycle_logs (backward-compatible lean log) ──────────────
        self.logs.append({
            "week":               cycle,
            "active_pools":       active_n,
            "waitlist_count":     len(self._wl),
            "pauses":             pauses,
            "merges":             merges,
            "momentum_value":     round(momentum, 3),
            "rdr_value":          round(rdr_pct,  1),
            "scenario":           scenario,
            "phase":              phase,
            "burn_rate":          burn_rate,
            "velocity":           round(velocity, 2),
            "lpi":                round(lpi_post, 1),
            "sde_exits_total":    self.n_sde_exits,
            "type_a_draws_total": self.n_type_a_draws,
            "type_b_draws_total": self.n_type_b_draws,
            # Extended L5/L6 pressure data
            "l5_count":           l5_this,
            "l6_count":           l6_this,
            "high_pressure_mode": lpi_post > 40.0,
        })

        # ── Append to weekly_detail (Master Weekly Report, Phase 2-C) ────────
        self.weekly_detail.append({
            "week":             cycle,
            "week_start_date":  week_start_iso,
            # Inflow
            "users_joined":     n_joined,
            # Counts
            "active_users":     sum(1 for u in self._users.values() if u.alive and u.pool_sid is not None),
            "waitlist_count":   len(self._wl),
            "pools_active":     active_n,
            "pools_paused":     paused_n,
            "pools_total":      total_pools,
            "pools_formed_this_week":  max(0, total_pools - (len(self.logs) > 1 and self.logs[-2].get("active_pools", 0) or 0) - paused_n),
            "pools_merged_this_week":  merges,
            # Level distribution
            "level_distribution": {**level_counts_post},
            "l5_count":           l5_this,
            "l6_count":           l6_this,
            # LPI & draw intelligence
            "lpi":                round(lpi_post, 2),
            "high_pressure_mode": lpi_post > 40.0,
            "draws_this_week":    draws_this_cycle,
            "draw_type_breakdown": {
                "regular": max(0, draws_this_cycle - self.n_type_a_draws - self.n_type_b_draws - self.n_sde_exits),
                "type_a":  self.n_type_a_draws,
                "type_b":  self.n_type_b_draws,
                "sde":     self.n_sde_exits,
            },
            # Payment stats (A/B/C breakdown)
            "late_payers":              n_late,
            "direct_eliminated":        late_info.get("n_direct_elim",    0),
            "grace_eligible":           late_info.get("n_grace_eligible", 0),
            "grace_saved":              late_info.get("n_grace_saved",    0),
            "grace_eliminated":         late_info.get("n_grace_elim",     0),
            "late_fees_collected_inr":  round(late_fees_this, 2),
            # A-1: Why members reach L5/L6 — SDE extension events this cycle
            "ext2_exits_this_week":     self._l5_escalation_events,  # cumulative: frontend diffs
            "ext3_exits_this_week":     self._l6_escalation_events,
            "accel_diss_this_week":     self._accel_diss_events,
            "condensation_events": condensed,
            # Financials (approximate per-cycle)
            "cash_inflow_inr":    round(cash_inflow_this, 2),
            "installments_collected_inr": round(installments_this, 2),
            "total_inflow_inr":   round(cash_inflow_this + installments_this + late_fees_this, 2),
            # AI/market signals
            "scenario":           scenario,
            "phase":              phase,
            "velocity":           round(velocity, 2),
            "momentum":           round(momentum, 3),
            "rdr_pct":            round(rdr_pct, 1),
        })

    # ── Response helpers ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        """
        Full God Mode simulation summary.

        Backward-compatible: the original 8 top-level keys are preserved so
        existing frontend code continues to work without changes.

        New sections added:
          financial_metrics   — detailed INR cash-flow breakdown
          level_wise_metrics  — per-level winner / collected / distributed data
          system_health       — assignment-method counters for journey analysis

        _dep accumulates BOTH initial join deposits (step_a) AND weekly
        installments from all active pool members (step_c).  The liquidity
        float stays positive because ongoing installment revenue funds payouts.
        """
        # ── Core financial figures ─────────────────────────────────────────────
        total_collected  = float(self._dep)
        total_distributed = float(self._pay)
        late_fees        = float(self._late)
        net_profit       = float(self._dep + self._late - self._pay)

        # Maintenance fee = gross − net for each payout issued, summed by level
        maintenance_fees = float(sum(
            self.level_wise_winners.get(l, 0) * (
                Decimal(str(LEVEL_PAYOUTS[l][0])) - Decimal(str(LEVEL_PAYOUTS[l][1]))
            )
            for l in range(1, 7)
            if LEVEL_PAYOUTS.get(l)
        ))

        # Projected ultimate liability: every active pool member wins at the
        # maximum level (L6).  This is the worst-case future obligation.
        _l6_net = Decimal(str(LEVEL_PAYOUTS.get(6, (0, 80000))[1]))
        _active_in_pools = sum(
            1 for u in self._users.values() if u.alive and u.pool_sid is not None
        )
        projected_ultimate_liability = float(_l6_net * _active_in_pools)

        # ── Level-wise breakdown (L1 – L6) ────────────────────────────────────
        level_wise_metrics: dict = {}
        for l in range(1, 7):
            w_count    = self.level_wise_winners.get(l, 0)
            collected  = float(self.level_wise_deposits.get(l, Decimal("0")))
            distributed = float(self.level_wise_payouts.get(l, Decimal("0")))
            avg_payout  = (distributed / w_count) if w_count else 0.0
            roi_pct     = (
                ((distributed - collected) / collected * 100.0)
                if collected else 0.0
            )
            level_wise_metrics[f"L{l}"] = {
                "winners_count":             w_count,
                "total_collected_from_them": round(collected,  2),
                "total_distributed_to_them": round(distributed, 2),
                "avg_payout":                round(avg_payout, 2),
                "level_roi_pct":             round(roi_pct,    2),
            }

        # ── System health counters ─────────────────────────────────────────────
        # ── L5/L6 peak timeline (Anti-Maturity pressure) ──────────────────────
        # Peak counts per cycle for the Level Progression chart
        l5_by_week = [log.get("l5_count", 0) for log in self.logs]
        l6_by_week = [log.get("l6_count", 0) for log in self.logs]

        # Pool pause timeline (used by Pool Activity tab)
        pauses_by_week = [log.get("pauses", 0) for log in self.logs]

        l5_escalation_events = self._l5_escalation_events
        l6_escalation_events = self._l6_escalation_events
        accel_diss_events    = self._accel_diss_events

        system_health = {
            "total_members_injected":        self.n_created,
            "total_direct_pool_assignments": self.direct_assignments,
            "total_dynamic_merges":          self.n_condensed,
            "total_draw_pauses_triggered":   self.n_paused,
            # SDE / draw-type analytics (architecture-accurate simulation)
            "total_l4_sde_flaggings":       self.n_sde_flags,
            "total_sde_exits":              self.n_sde_exits,
            "total_type_a_draws":           self.n_type_a_draws,
            "total_type_b_draws":           self.n_type_b_draws,
            "sde_exit_rate_pct": round(
                self.n_sde_exits / max(self.n_winners, 1) * 100, 1
            ),
            # Anti-Maturity pressure metrics (Phase 2-A / A-1)
            "max_l5_count":                 self._max_l5,
            "max_l6_count":                 self._max_l6,
            "max_high_lpi_streak_weeks":    self._max_high_lpi_streak,
            "l5_peak_by_week":              l5_by_week,
            "l6_peak_by_week":              l6_by_week,
            "pauses_by_week":               pauses_by_week,
            # SDE Extension events (Ext-II = L5 forced exit, Ext-III = L6 forced exit)
            "total_l5_ext2_forced_exits":   l5_escalation_events,
            "total_l6_ext3_forced_exits":   l6_escalation_events,
            "total_accel_dissolution_events": accel_diss_events,
            # A-1: WHY members reach L5/L6 explanation
            "l5_l6_escalation_explanation": (
                f"L5 members appeared {l5_escalation_events} times (Ext-II draws executed). "
                f"L6 members appeared {l6_escalation_events} times (Ext-III draws executed). "
                + (
                    "Root cause: SDE failed to clear L4 before advancement when pools were paused "
                    f"or under-capacity. {self.n_paused} pool pauses prevented timely SDE processing."
                    if (l5_escalation_events + l6_escalation_events) > 0
                    else "No L5/L6 escalation — SDE cleared all L4 members in time."
                )
            ),
        }

        return {
            # ── Backward-compatible original 8 keys ─────────��─────────────────
            "total_cycles_run":              len(self.logs),
            "total_simulated_users_created": self.n_created,
            "total_winners_drawn":           self.n_winners,
            "total_pools_auto_scaled":       self.n_scaled,
            "total_condensation_events":     self.n_condensed,
            "total_draw_pauses_triggered":   self.n_paused,
            "total_late_fees_collected_inr": late_fees,
            "final_virtual_liquidity_float": net_profit,
            # ── Elimination tracking (BUG-1 fix: self._elim now initialized) ──
            "total_eliminations":            self._elim,
            # ── God Mode extended sections ────────────────────────────────────
            "financial_metrics": {
                "total_collected_inr":            total_collected,
                "total_distributed_inr":          total_distributed,
                "total_maintenance_fees_inr":     maintenance_fees,
                "total_late_fees_inr":            late_fees,
                "net_organizer_profit_inr":       net_profit,
                "master_liquidity_float_inr":     net_profit,
                "projected_ultimate_liability":   projected_ultimate_liability,
            },
            "level_wise_metrics": level_wise_metrics,
            "system_health":      system_health,
        }


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/advanced-simulation")
def advanced_simulation(
    body: AdvancedSimRequest,
    db: Session = Depends(get_db),
):
    """
    High-performance isolated stress-testing endpoint.

    Runs `total_cycles` consecutive weekly draw cycles with:
      • FIFO user inflow (fixed 12/cycle or random 5–N in volatility mode)
      • Late-fee penalty simulation (configurable % and ratio)
      • Auto-billing of non-late members
      • Double-FIFO refill (P1: waitlist fill, P2: auto-scale, P3: condensation)
      • Smart Pairing draw with Safestop on partial pools

    Database isolation
    ──────────────────
    • A unique run_id (UUID hex) is generated per request.
    • All dummy User rows share the prefix  sim_{run_id[:12]}_  and are
      written to DB in _SIM_CHUNK=500 row batches (prevents OOM).
    • Pool / Token records are NEVER written to the DB — pure in-memory.
    • The `finally` block issues a cascading SQL DELETE on the prefix,
      guaranteeing 100% cleanup regardless of success, exception, or timeout.

    Returns
    ───────
    {
      "simulation_summary": { total_cycles_run, total_simulated_users_created,
        total_winners_drawn, total_pools_auto_scaled, total_condensation_events,
        total_draw_pauses_triggered, total_late_fees_collected_inr,
        final_virtual_liquidity_float },
      "cycle_logs": [ {"week", "active_pools", "waitlist_count", "pauses", "merges"} ]
    }
    """
    run_id = uuid.uuid4().hex               # 32-char hex — unique per request
    upfx   = f"sim_{run_id[:12]}"           # username cleanup anchor
    engine = _AdvSimEngine(run_id)
    hpw    = _get_dev_pw_hash()             # bcrypt: computed once, reused for all rows
    base   = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    _logger_sim.info(
        "AdvancedSim START  run_id=%s  cycles=%d  vol=%s  late_fee=%.1f%%  late_ratio=%.1f%%",
        run_id[:12], body.total_cycles,
        body.volatility_mode, body.late_fee_pct, body.late_users_ratio_pct,
    )

    try:
        for cycle in range(1, body.total_cycles + 1):
            engine.run_cycle(cycle, body, base, hpw)

            # ── OOM-safe DB flush: drain insert buffer in _SIM_CHUNK chunks ──────
            while len(engine._ins) >= _SIM_CHUNK:
                _sim_flush(db, engine._ins[:_SIM_CHUNK])
                engine._ins = engine._ins[_SIM_CHUNK:]

        # Flush any remaining rows below the chunk threshold
        if engine._ins:
            _sim_flush(db, engine._ins)
            engine._ins.clear()

        summ = engine.summary()
        _logger_sim.info(
            "AdvancedSim DONE  run_id=%s  users=%d  winners=%d  pools=%d  "
            "condensations=%d  pauses=%d  liquidity=%.2f",
            run_id[:12],
            summ["total_simulated_users_created"],
            summ["total_winners_drawn"],
            summ["total_pools_auto_scaled"],
            summ["total_condensation_events"],
            summ["total_draw_pauses_triggered"],
            summ["final_virtual_liquidity_float"],
        )
        return {
            "simulation_summary": summ,
            "cycle_logs":         engine.logs,
            "weekly_detail":      engine.weekly_detail,   # Phase 2-C Master Weekly Report
        }

    except Exception:
        # Roll back any uncommitted inserts before the finally-block cleanup
        try:
            db.rollback()
        except Exception:
            pass
        raise

    finally:
        # GUARANTEED cleanup — executes even on unhandled exceptions / timeouts
        _sim_cleanup(db, upfx)


# =============================================================================
# DEV ANALYTICS ENDPOINTS — God Mode production mirror
# =============================================================================


# ─────────────────────────────────────────────────────────────────────────────
# GET /dev/live-stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/live-stats")
def dev_live_stats(db: Session = Depends(get_db)):
    """
    Combined real-time statistics snapshot — mirrors all production dashboards
    in a single API call for the Developer Mode Live Stats panel.

    Returns: user counts, pool counts, payment status, level distribution,
    SDE/LPI state, financial snapshot, draw history summary, AI scenario.
    """
    from datetime import timedelta
    from app.models.draw_history import DrawHistory

    now        = datetime.now(timezone.utc)
    week_start = now - timedelta(days=(now.weekday() + 1) % 7)

    # ── User counts ───────────────────────────────────────────────────────────
    active_count   = db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar()   or 0
    waitlist_count = db.query(func.count(User.id)).filter(User.status == UserStatus.Waitlist).scalar() or 0
    # SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]: fix invalid enum string literals
    won_count      = db.query(func.count(User.id)).filter(User.status == UserStatus.Eliminated_Won).scalar() or 0
    unpaid_count   = db.query(func.count(User.id)).filter(User.status == UserStatus.Eliminated).scalar()     or 0

    # ── Pool counts ───────────────────────────────────────────────────────────
    active_pools  = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Active).scalar()                      or 0
    paused_pools  = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Paused_Awaiting_Members).scalar()     or 0
    waiting_pools = db.query(func.count(Pool.id)).filter(Pool.status == PoolStatus.Waiting).scalar()                     or 0
    total_pools   = db.query(func.count(Pool.id)).scalar() or 0

    # ── Payment status (active members only) ──────────────────────────────────
    paid_active   = db.query(func.count(User.id)).filter(
        User.status == UserStatus.Active,
        User.weekly_payment_status == WeeklyPaymentStatus.Paid,
    ).scalar() or 0
    unpaid_active = active_count - paid_active

    # ── Level distribution ────────────────────────────────────────────────────
    level_dist: dict[str, int] = {}
    for lvl in range(1, 7):
        cnt = db.query(func.count(User.id)).filter(
            User.status        == UserStatus.Active,
            User.current_level == lvl,
        ).scalar() or 0
        level_dist[f"L{lvl}"] = cnt

    # ── SDE state ─────────────────────────────────────────────────────────────
    sde_flagged = db.query(func.count(User.id)).filter(
        User.sde_required == True,    # noqa: E712
        User.status       == UserStatus.Active,
    ).scalar() or 0

    lpi = 0.0
    try:
        from app.services.brain5_lpi_engine import calculate_lpi
        lpi = calculate_lpi(db)
    except Exception:
        pass

    # ── Financial snapshot ────────────────────────────────────────────────────
    total_dep = db.query(func.sum(Token.value_inr)).filter(
        Token.type   == TokenType.Deposit,
        Token.status == TokenStatus.Burned,
    ).scalar() or Decimal("0")

    total_wit = db.query(func.sum(Token.value_inr)).filter(
        Token.type   == TokenType.Withdraw,
        Token.status == TokenStatus.Burned,
    ).scalar() or Decimal("0")

    total_ref_paid = db.query(func.sum(Token.value_inr)).filter(
        Token.type   == TokenType.Referral,
        Token.status == TokenStatus.Burned,
    ).scalar() or Decimal("0")

    # ── Draw history summary ──────────────────────────────────────────────────
    total_draws    = db.query(func.count(DrawHistory.id)).scalar() or 0
    draws_this_wk  = db.query(func.count(DrawHistory.id)).filter(
        DrawHistory.draw_timestamp >= week_start,
    ).scalar() or 0

    # ── Recent draws (last 6) ─────────────────────────────────────────────────
    recent_draws_raw = (
        db.query(DrawHistory)
        .order_by(DrawHistory.draw_timestamp.desc())
        .limit(6)
        .all()
    )
    recent_draws = []
    for dh in recent_draws_raw:
        recent_draws.append({
            "id":             dh.id,
            "pool_id":        dh.pool_id,
            "draw_type":      dh.draw_type or "regular",
            "w1_level":       dh.winner_1_level,
            "w1_payout":      float(dh.winner_1_net_payout or 0),
            "w2_level":       dh.winner_2_level,
            "w2_payout":      float(dh.winner_2_net_payout or 0),
            "timestamp":      dh.draw_timestamp.isoformat() if dh.draw_timestamp else None,
            "sde":            bool(dh.targeted_early_exit),
        })

    # ── AI snapshot ───────────────────────────────────────────────────────────
    scenario = "NEUTRAL"
    velocity = 0.0
    try:
        from app.services.ai_quant_engine import get_system_snapshot
        snap     = get_system_snapshot(db)
        scenario = snap.get("scenario", "NEUTRAL")
        velocity = float(snap.get("velocity", 0.0))
    except Exception:
        pass

    return {
        "users": {
            "active":   active_count,
            "waitlist": waitlist_count,
            "won":      won_count,
            "unpaid":   unpaid_count,
            "total":    active_count + waitlist_count + won_count + unpaid_count,
        },
        "pools": {
            "active":  active_pools,
            "paused":  paused_pools,
            "waiting": waiting_pools,
            "total":   total_pools,
        },
        "payments": {
            "paid_in_pools":   paid_active,
            "unpaid_in_pools": unpaid_active,
            "paid_pct":        round(paid_active / active_count * 100, 1) if active_count else 0.0,
        },
        "levels":  level_dist,
        "sde": {
            "l4_flagged": sde_flagged,
            "lpi":        round(lpi, 2),
        },
        "financials": {
            "total_collected_inr":   float(total_dep),
            "total_paid_out_inr":    float(total_wit + total_ref_paid),
            "net_float_inr":         float(total_dep - total_wit - total_ref_paid),
        },
        "draws": {
            "total":     total_draws,
            "this_week": draws_this_wk,
            "recent":    recent_draws,
        },
        "ai": {
            "scenario": scenario,
            "velocity": round(velocity, 2),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /dev/level-map
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/level-map")
def dev_level_map(db: Session = Depends(get_db)):
    """
    Visual distribution of all active members by level across all pools.

    Returns each pool with its members broken down by level — feeds the
    Developer Mode Level Map visualizer and the L1/L2/L3 member viewer.
    """
    pools = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .order_by(Pool.id.asc())
        .all()
    )

    result_pools = []
    global_by_level: dict[int, int] = {l: 0 for l in range(1, 7)}

    for pool in pools:
        members = (
            db.query(User)
            .filter(
                User.current_pool_id == pool.id,
                User.status          == UserStatus.Active,
            )
            .order_by(User.current_level.asc(), User.join_date.asc())
            .all()
        )

        by_level: dict[str, list] = {f"L{l}": [] for l in range(1, 7)}
        level_counts: dict[str, int] = {f"L{l}": 0 for l in range(1, 7)}

        for m in members:
            lvl = m.current_level
            key = f"L{lvl}"
            by_level[key].append({
                "id":           m.id,
                "username":     m.username,
                "name":         m.name or "",
                "paid":         m.weekly_payment_status == WeeklyPaymentStatus.Paid,
                "sde_required": bool(m.sde_required),
                "join_date":    m.join_date.isoformat() if m.join_date else None,
            })
            level_counts[key] = level_counts[key] + 1
            global_by_level[lvl] = global_by_level.get(lvl, 0) + 1

        result_pools.append({
            "id":               pool.id,
            "name":             pool.name,
            "status":           pool.status.value,
            "member_count":     len(members),
            "draw_completed":   bool(pool.draw_completed_this_week),
            "pool_draw_type":   pool.pool_draw_type or "regular",
            "contains_l4":      bool(pool.contains_flagged_l4),
            "members_by_level": by_level,
            "level_counts":     level_counts,
        })

    return {
        "pools":   result_pools,
        "summary": {
            "total_active_members": sum(global_by_level.values()),
            "by_level": {f"L{l}": global_by_level[l] for l in range(1, 7)},
            "pool_count": len(result_pools),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /dev/winners-analytics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/winners-analytics")
def dev_winners_analytics(db: Session = Depends(get_db)):
    """
    Level-wise winner analysis with amounts and temporal distribution.

    Returns aggregate stats from draw_history for the Winners tab.
    """
    from app.models.draw_history import DrawHistory

    all_draws = db.query(DrawHistory).order_by(DrawHistory.draw_timestamp.desc()).all()

    # ── Level-wise aggregation ─────────────────────────────────────────────────
    by_level: dict[int, dict] = {
        l: {"winners": 0, "total_payout_inr": 0.0, "sde_winners": 0}
        for l in range(1, 7)
    }
    total_winners   = 0
    total_payout    = 0.0
    sde_total       = 0

    # Recent winners with full detail (last 20)
    recent: list[dict] = []

    for dh in all_draws:
        is_sde = bool(dh.targeted_early_exit)
        for slot in (1, 2):
            lvl  = (dh.winner_1_level if slot == 1 else dh.winner_2_level) or 1
            pay  = float(dh.winner_1_net_payout if slot == 1 else dh.winner_2_net_payout or 0)
            uid  = dh.winner_1_user_id if slot == 1 else dh.winner_2_user_id

            if 1 <= lvl <= 6:
                by_level[lvl]["winners"]       += 1
                by_level[lvl]["total_payout_inr"] += pay
                if is_sde:
                    by_level[lvl]["sde_winners"] += 1
                    sde_total += 1

            total_winners += 1
            total_payout  += pay

            if len(recent) < 20:
                user = db.query(User).filter(User.id == uid).first() if uid else None
                recent.append({
                    "draw_id":    dh.id,
                    "pool_id":    dh.pool_id,
                    "draw_type":  dh.draw_type or "regular",
                    "sde":        is_sde,
                    "level":      lvl,
                    "payout_inr": pay,
                    "username":   user.username if user else None,
                    "timestamp":  dh.draw_timestamp.isoformat() if dh.draw_timestamp else None,
                })

    # ── Compute averages ──────────────────────────────────────────────────────
    level_stats = []
    for l in range(1, 7):
        d   = by_level[l]
        w   = d["winners"]
        pay = d["total_payout_inr"]
        level_stats.append({
            "level":            l,
            "winners":          w,
            "total_payout_inr": round(pay, 2),
            "avg_payout_inr":   round(pay / w, 2) if w else 0.0,
            "sde_winners":      d["sde_winners"],
            "sde_pct":          round(d["sde_winners"] / w * 100, 1) if w else 0.0,
            "pct_of_total":     round(w / total_winners * 100, 1) if total_winners else 0.0,
        })

    return {
        "summary": {
            "total_winners":   total_winners,
            "total_payout_inr": round(total_payout, 2),
            "avg_payout_inr":  round(total_payout / total_winners, 2) if total_winners else 0.0,
            "total_draws":     len(all_draws),
            "sde_exits":       sde_total,
        },
        "by_level":      level_stats,
        "recent_winners": recent,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /dev/projection
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/projection")
def dev_projection(db: Session = Depends(get_db)):
    """
    Next draw projection engine.

    For each eligible full pool (12 members), projects:
      • Draw type based on current pool_draw_type assignment
      • Expected upper/lower winner levels and payouts
      • Projected collection vs payout vs profit
      • Post-draw level advancement analysis (who will reach L4 next)

    Also projects waitlist → pool formation events.
    """
    from app.core.config import (
        POOL_CAPACITY, LEVEL_PAYOUTS, PAYOUT_FEE_INR,
        EXEC_LEVEL_LOW, EXEC_LEVEL_HIGH,
        LEVEL_LOW, LEVEL_HIGH,
        TYPE_B_LEVEL_LOW, TYPE_B_LEVEL_HIGH,
        POOL_DRAW_TYPE_A, POOL_DRAW_REGULAR, POOL_DRAW_TYPE_B,
    )

    # ── Eligible full pools ───────────────────────────────────────────────────
    candidate_pools = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .order_by(Pool.id.asc())
        .all()
    )

    pool_projections = []
    total_collection = 0
    total_payout     = 0
    total_fee_income = 0
    eligible_count   = 0

    for pool in candidate_pools:
        actual = (
            db.query(func.count(User.id))
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .scalar() or 0
        )
        if actual != POOL_CAPACITY:
            continue

        eligible_count += 1
        draw_type = pool.pool_draw_type or POOL_DRAW_REGULAR

        # Determine tier bounds
        if draw_type == POOL_DRAW_TYPE_A:
            lo_bounds, hi_bounds = EXEC_LEVEL_LOW,    EXEC_LEVEL_HIGH
        elif draw_type == POOL_DRAW_TYPE_B:
            lo_bounds, hi_bounds = TYPE_B_LEVEL_LOW,  TYPE_B_LEVEL_HIGH
        else:
            lo_bounds, hi_bounds = LEVEL_LOW,          LEVEL_HIGH

        members = (
            db.query(User)
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .all()
        )

        lower_tier = [m for m in members if lo_bounds[0] <= m.current_level <= lo_bounds[1]]
        upper_tier = [m for m in members if hi_bounds[0] <= m.current_level <= hi_bounds[1]]

        # Projected winner: highest level in each tier (worst-case payout)
        if upper_tier:
            proj_upper_lvl = max(m.current_level for m in upper_tier)
        else:
            proj_upper_lvl = max(m.current_level for m in members) if members else 1

        if lower_tier:
            proj_lower_lvl = min(m.current_level for m in lower_tier)
        else:
            proj_lower_lvl = 1

        upper_gross, upper_net = LEVEL_PAYOUTS.get(proj_upper_lvl, (2500, 2000))
        lower_gross, lower_net = LEVEL_PAYOUTS.get(proj_lower_lvl, (2500, 2000))

        pool_collection = POOL_CAPACITY * 1000
        pool_payout     = upper_net + lower_net
        pool_fee        = PAYOUT_FEE_INR * 2   # ₹500 per winner × 2
        pool_profit     = pool_collection - pool_payout

        total_collection += pool_collection
        total_payout     += pool_payout
        total_fee_income += pool_fee

        # Post-draw level advancement: survivors get +1 level
        # Who will reach L4 next?
        surviving = [m for m in members]   # conservative — don't know who wins
        new_l4_after = sum(
            1 for m in surviving
            if m.current_level == 3   # they'll advance to L4 after surviving the draw
        )

        level_counts = {}
        for l in range(1, 7):
            cnt = sum(1 for m in members if m.current_level == l)
            if cnt:
                level_counts[f"L{l}"] = cnt

        pool_projections.append({
            "pool_id":            pool.id,
            "pool_name":          pool.name,
            "member_count":       actual,
            "draw_type":          draw_type,
            "lower_tier_count":   len(lower_tier),
            "upper_tier_count":   len(upper_tier),
            "proj_lower_level":   proj_lower_lvl,
            "proj_upper_level":   proj_upper_lvl,
            "proj_lower_payout":  lower_net,
            "proj_upper_payout":  upper_net,
            "proj_total_payout":  pool_payout,
            "proj_collection":    pool_collection,
            "proj_profit":        pool_profit,
            "fee_income":         pool_fee,
            "new_l4_after_draw":  new_l4_after,
            "level_distribution": level_counts,
        })

    # ── Waitlist projection ───────────────────────────────────────────────────
    wl_count   = db.query(func.count(User.id)).filter(User.status == UserStatus.Waitlist).scalar() or 0
    threshold  = get_pool_threshold(db)
    can_form   = wl_count // threshold
    wl_remain  = wl_count - can_form * threshold

    # ── Post-draw LPI estimate ─────────────────────────────────────────────────
    current_active = db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar() or 1
    current_l4     = db.query(func.count(User.id)).filter(User.status == UserStatus.Active, User.current_level == 4).scalar() or 0
    current_l3     = db.query(func.count(User.id)).filter(User.status == UserStatus.Active, User.current_level == 3).scalar() or 0

    # After draw: 2 × eligible_count winners exit; current_l3 members advance → some become L4
    total_new_l4 = sum(p["new_l4_after_draw"] for p in pool_projections)
    post_draw_l4 = max(0, current_l4 - eligible_count * 0.5 + total_new_l4)   # rough estimate
    post_draw_active = max(1, current_active - eligible_count)
    post_draw_lpi = round((post_draw_l4 / post_draw_active) * 100, 2)

    return {
        "eligible_pools":   eligible_count,
        "ineligible_pools": len(candidate_pools) - eligible_count,
        "pool_projections": pool_projections,
        "totals": {
            "projected_collection_inr": total_collection,
            "projected_payout_inr":     total_payout,
            "projected_profit_inr":     total_collection - total_payout,
            "fee_income_inr":           total_fee_income,
            "total_new_l4_members":     total_new_l4,
        },
        "post_draw_lpi": {
            "estimated_lpi":        post_draw_lpi,
            "current_lpi":          round((current_l4 / current_active) * 100, 2) if current_active else 0.0,
            "total_new_l4_after":   total_new_l4,
            "current_l4":           current_l4,
        },
        "waitlist_projection": {
            "current_waitlist":   wl_count,
            "threshold":          threshold,
            "pools_can_form":     can_form,
            "waitlist_remaining": wl_remain,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /dev/inject-timed
# ─────────────────────────────────────────────────────────────────────────────

class TimedInjectRequest(BaseModel):
    count:              int   = Field(..., ge=1, le=100_000, description="Number of users to create.")
    base_date_iso:      str | None = Field(None, description="ISO datetime to use as injection anchor.  Null = now.")
    spread_days:        int   = Field(7,   ge=0, le=365,    description="Spread injection across the last N days.  0 = all at base_date.")
    randomize_dates:    bool  = Field(True,                  description="Randomise individual join_dates within the spread window.")
    daily_count:        int | None = Field(None, ge=1,       description="If set, inject this many users per day over spread_days.")
    auto_pool:          bool  = Field(True,                  description="Auto-trigger pool formation after creation.")


def _build_join_dates(
    body: "TimedInjectRequest",
    anchor: datetime,
    count: int,
) -> list[datetime]:
    """
    Compute the sorted list of join_date timestamps for a timed injection.
    Extracted here so it can be unit-tested independently of the endpoint.
    """
    join_dates: list[datetime] = []

    if body.spread_days == 0:
        # All users at the anchor datetime, sequential minutes apart
        for i in range(count):
            join_dates.append(anchor + timedelta(minutes=i))

    elif body.daily_count and body.spread_days > 0:
        # Daily cadence: daily_count per day for spread_days days
        for day in range(body.spread_days):
            day_base = anchor - timedelta(days=(body.spread_days - 1 - day))
            for j in range(body.daily_count):
                if len(join_dates) >= count:
                    break
                minute_offset = random.randint(0, 1439) if body.randomize_dates else j
                join_dates.append(day_base + timedelta(minutes=minute_offset))
            if len(join_dates) >= count:
                break
        # Pad to count if daily_count × spread_days < count
        while len(join_dates) < count:
            join_dates.append(anchor - timedelta(minutes=random.randint(0, body.spread_days * 1440)))

    elif body.randomize_dates:
        # Random scatter within the spread window
        spread_minutes = body.spread_days * 24 * 60
        for i in range(count):
            offset = random.randint(0, max(1, spread_minutes))
            join_dates.append(anchor - timedelta(minutes=offset) + timedelta(seconds=i))

    else:
        # Linear spread: evenly spaced across the window
        if count == 1 or body.spread_days == 0:
            join_dates = [anchor + timedelta(minutes=i) for i in range(count)]
        else:
            interval = (body.spread_days * 24 * 60) / (count - 1)
            for i in range(count):
                join_dates.append(anchor - timedelta(minutes=interval * (count - 1 - i)))

    return sorted(join_dates)[:count]   # FIFO order guaranteed


def _background_pool_formation(prefix: str) -> None:
    """
    Background task: form pools from the users just injected.

    Runs AFTER the HTTP response is returned to the client.  This prevents
    HTTP timeouts on large batches (2000+ users → 10–30 s pool-formation loop).

    Uses a fresh DB session so it doesn't compete with the request-scoped
    session that has already closed.  Status is written to _INJECT_STATUS so
    clients can poll GET /dev/injection-status?prefix=<prefix>.
    """
    from app.database import SessionLocal as _SL   # local import avoids circular

    started_at = datetime.now(timezone.utc).isoformat()
    with _INJECT_LOCK:
        _INJECT_STATUS[prefix] = {
            "status":            "running",
            "pools_formed":      0,
            "waitlist_remaining": None,
            "error":             None,
            "started_at":        started_at,
            "finished_at":       None,
        }

    db = _SL()
    try:
        pools_formed = 0
        fill_pool_vacancies(db)
        while True:
            new_pool = manual_create_pool(db)
            if not new_pool:
                break
            pools_formed += 1

        wl_remaining = (
            db.query(func.count(User.id))
            .filter(User.status == UserStatus.Waitlist)
            .scalar() or 0
        )

        with _INJECT_LOCK:
            _INJECT_STATUS[prefix].update({
                "status":            "done",
                "pools_formed":      pools_formed,
                "waitlist_remaining": wl_remaining,
                "finished_at":       datetime.now(timezone.utc).isoformat(),
            })
        _logger_sim.info(
            "inject-timed background: prefix=%s  pools_formed=%d  wl_remaining=%d",
            prefix, pools_formed, wl_remaining,
        )

    except Exception as exc:
        _logger_sim.error("inject-timed background FAILED: prefix=%s  error=%s", prefix, exc)
        try:
            db.rollback()
        except Exception:
            pass
        with _INJECT_LOCK:
            _INJECT_STATUS[prefix].update({
                "status":    "error",
                "error":     str(exc),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
    finally:
        db.close()


@router.post("/inject-timed")
def dev_inject_timed(
    body: TimedInjectRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Inject users with fully-customizable date/time distribution.

    Supports three modes:
      • Single burst: all users at base_date (spread_days=0)
      • Random spread: each user gets a random date within the last N days
      • Daily cadence: daily_count users per day for spread_days days

    IMPORTANT DESIGN CHANGE (pool formation is now asynchronous):
    ──────────────────────────────────────────────────────────────
    For large batches (200+ users) the pool-formation loop (fill vacancies →
    manual_create_pool loop) takes 5–30 seconds.  Executing it inline blocked
    the HTTP response and caused:
      1. The browser to show a timeout / request-failed error.
      2. All subsequent API calls to queue behind the blocking operation,
         exhausting the connection pool and making ALL buttons fail.

    Fix: user rows + DEP tokens are committed synchronously (fast, ~200 ms for
    2000 users).  The pool-formation loop is handed off to FastAPI's
    BackgroundTasks which run AFTER the HTTP response is sent.  The client
    receives an immediate 200 with:
      {
        "users_created": N,
        "pool_formation": "background",
        "status_key": prefix
      }
    Poll GET /dev/injection-status?prefix=<prefix> to get live pool-formation
    progress.  The admin Dashboard's "Check Waitlist Threshold" button will
    also catch any missed formations.
    """
    import time as _time

    t0       = time.perf_counter()
    ts_epoch = int(_time.time())
    nonce    = random.randint(100_000, 999_999)
    prefix   = f"dev_timed_{ts_epoch}_{nonce}_"
    count    = body.count

    # ── Resolve anchor datetime ───────────────────────────────────────────────
    if body.base_date_iso:
        try:
            anchor = datetime.fromisoformat(body.base_date_iso.replace("Z", "+00:00"))
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
        except ValueError:
            anchor = datetime.now(timezone.utc)
    else:
        anchor = datetime.now(timezone.utc)

    # ── Build join_date list ──────────────────────────────────────────────────
    join_dates = _build_join_dates(body, anchor, count)

    # ── Build user rows ───────────────────────────────────────────────────────
    hashed_pw = _get_dev_pw_hash()

    _ref_set: set[str] = set()
    while len(_ref_set) < count:
        _ref_set.update(
            "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            for _ in range(count - len(_ref_set))
        )
    _ref_list = list(_ref_set)

    user_rows = [
        {
            "name":                  f"TimedUser-{i + 1}",
            "mobile":                f"+99{ts_epoch % 10_000_000_000:010d}{nonce:06d}{i:05d}",
            "username":              f"{prefix}{secrets.token_hex(6)}",
            "hashed_password":       hashed_pw,
            "join_date":             join_dates[i],
            "status":                UserStatus.Waitlist,
            "weekly_payment_status": WeeklyPaymentStatus.Paid,
            "current_level":         1,
            "referral_code":         _ref_list[i],
        }
        for i in range(count)
    ]

    for start in range(0, count, _BULK_BATCH):
        db.execute(sa_insert(User), user_rows[start:start + _BULK_BATCH])
    db.flush()

    # ── Create DEP tokens ─────────────────────────────────────────────────────
    user_ids = [
        r[0] for r in db.execute(
            text("SELECT id FROM users WHERE username LIKE :p ORDER BY join_date"),
            {"p": f"{prefix}%"},
        ).fetchall()
    ]

    if not user_ids:
        db.rollback()
        raise HTTPException(status_code=500, detail="Bulk user insert produced no rows — check DB constraints.")

    codes: set[str] = set()
    while len(codes) < len(user_ids):
        codes.update(f"DEP-{secrets.token_hex(4).upper()}" for _ in range(len(user_ids) - len(codes)))
    code_list = list(codes)

    token_rows = [
        {
            "code":                code_list[i],
            "type":                TokenType.Deposit,
            "value_inr":           _DEPOSIT_DEC,
            "status":              TokenStatus.Burned,
            "user_id":             user_ids[i],
            "redeemed_by_user_id": user_ids[i],
        }
        for i in range(len(user_ids))
    ]
    for start in range(0, len(token_rows), _BULK_BATCH):
        db.execute(sa_insert(Token), token_rows[start:start + _BULK_BATCH])
    db.commit()   # ← HTTP response can now return; pool formation continues below

    # ── Pool formation: schedule as background task ───────────────────────────
    # For small counts (≤ 100 users) run inline — background overhead not worth it.
    # For large counts run in background so the HTTP response returns immediately.
    date_from    = join_dates[0].isoformat() if join_dates else None
    date_to      = join_dates[-1].isoformat() if join_dates else None
    elapsed_ms   = int((time.perf_counter() - t0) * 1000)

    if body.auto_pool:
        if count <= 100:
            # ── Inline (small batch — fast) ───────────────────────────────────
            pools_formed = 0
            fill_pool_vacancies(db)
            while True:
                new_pool = manual_create_pool(db)
                if not new_pool:
                    break
                pools_formed += 1
            wl_remaining = (
                db.query(func.count(User.id))
                .filter(User.status == UserStatus.Waitlist)
                .scalar() or 0
            )
            return {
                "users_created":      len(user_ids),
                "dep_tokens_created": len(user_ids),
                "pools_formed":       pools_formed,
                "pool_formation":     "inline",
                "waitlist_remaining": wl_remaining,
                "elapsed_ms":         elapsed_ms,
                "date_from":          date_from,
                "date_to":            date_to,
                "spread_days":        body.spread_days,
                "randomized":         body.randomize_dates,
                "daily_cadence":      body.daily_count,
                "prefix":             prefix,
                "status_key":         None,
                "note": (
                    f"{len(user_ids)} timed users created (inline pool formation). "
                    f"{pools_formed} pool(s) formed. {wl_remaining} on waitlist."
                ),
            }
        else:
            # ── Background (large batch — avoids HTTP timeout) ─────────────────
            background_tasks.add_task(_background_pool_formation, prefix)
            return {
                "users_created":      len(user_ids),
                "dep_tokens_created": len(user_ids),
                "pools_formed":       None,
                "pool_formation":     "background",
                "waitlist_remaining": None,
                "elapsed_ms":         elapsed_ms,
                "date_from":          date_from,
                "date_to":            date_to,
                "spread_days":        body.spread_days,
                "randomized":         body.randomize_dates,
                "daily_cadence":      body.daily_count,
                "prefix":             prefix,
                "status_key":         prefix,
                "note": (
                    f"{len(user_ids)} users + DEP tokens committed. "
                    f"Pool formation running in background — "
                    f"poll GET /dev/injection-status?prefix={prefix} for progress."
                ),
            }
    else:
        wl_remaining = (
            db.query(func.count(User.id))
            .filter(User.status == UserStatus.Waitlist)
            .scalar() or 0
        )
        return {
            "users_created":      len(user_ids),
            "dep_tokens_created": len(user_ids),
            "pools_formed":       0,
            "pool_formation":     "skipped",
            "waitlist_remaining": wl_remaining,
            "elapsed_ms":         elapsed_ms,
            "date_from":          date_from,
            "date_to":            date_to,
            "spread_days":        body.spread_days,
            "randomized":         body.randomize_dates,
            "daily_cadence":      body.daily_count,
            "prefix":             prefix,
            "status_key":         None,
            "note": (
                f"{len(user_ids)} timed users created (auto_pool=false). "
                f"Call POST /admin/waitlist/check to form pools manually."
            ),
        }


@router.get("/injection-status")
def dev_injection_status(prefix: str):
    """
    Poll the status of a background pool-formation job started by POST /dev/inject-timed.

    Returns the current state:
      • status = "running"  — pool formation is in progress
      • status = "done"     — complete; pools_formed and waitlist_remaining filled
      • status = "error"    — background task raised an exception; see error field
      • status = "unknown"  — prefix not found (job hasn't started or expired from memory)

    The in-memory registry holds at most ~1000 entries (one per injection call since
    server start).  On server restart all entries are lost — check pool counts directly
    via GET /pools/ to verify formation completed.
    """
    with _INJECT_LOCK:
        entry = _INJECT_STATUS.get(prefix)

    if entry is None:
        return {
            "prefix": prefix,
            "status": "unknown",
            "message": (
                "No background task found for this prefix. "
                "Either it hasn't started, the server was restarted, or this prefix is invalid."
            ),
        }
    return {"prefix": prefix, **entry}


# ─────────────────────────────────────────────────────────────────────────────
# POST /dev/mark-all-paid
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/mark-all-paid")
def dev_mark_all_paid(db: Session = Depends(get_db)):
    """
    Master paid toggle — marks ALL active pool members as Paid.
    Used to instantly clear unpaid state before running a draw.
    Returns count of members whose status was changed.
    """
    result = (
        db.query(User)
        .filter(
            User.status               == UserStatus.Active,
            User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
        )
        .update(
            {"weekly_payment_status": WeeklyPaymentStatus.Paid},
            synchronize_session=False,
        )
    )
    db.commit()

    total_active = db.query(func.count(User.id)).filter(User.status == UserStatus.Active).scalar() or 0

    return {
        "marked_paid":    result,
        "total_active":   total_active,
        "all_paid_now":   True,
        "message":        f"Marked {result} member(s) as Paid. All {total_active} active members are now Paid.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /dev/set-payment-scenario
# ─────────────────────────────────────────────────────────────────────────────

class PaymentScenarioRequest(BaseModel):
    paid_pct:            float = Field(100.0, ge=0.0, le=100.0,
                                       description="% of active pool members to mark Paid (rest become Unpaid).")
    apply_late_fee:      bool  = Field(False,
                                       description="If True, create Burned Late Fee tokens for unpaid members.")
    late_fee_inr:        float = Field(50.0, ge=0.0,
                                       description="Late fee amount in INR per unpaid member.")
    eliminate_unpaid_pct: float = Field(0.0, ge=0.0, le=100.0,
                                        description="% of unpaid members to eliminate (Eliminated_Unpaid status).")


@router.post("/set-payment-scenario")
def dev_set_payment_scenario(body: PaymentScenarioRequest, db: Session = Depends(get_db)):
    """
    Configurable payment scenario for testing.

    Sets the payment distribution across all active pool members:
      • paid_pct = 80 → 80% of members marked Paid, 20% Unpaid
      • apply_late_fee = True → creates Late Fee tokens for unpaid members
      • eliminate_unpaid_pct = 50 → eliminates 50% of unpaid members

    Returns counts of affected members in each category.
    """
    all_active: list[User] = (
        db.query(User)
        .filter(User.status == UserStatus.Active)
        .all()
    )

    if not all_active:
        return {"marked_paid": 0, "marked_unpaid": 0, "eliminated": 0, "late_fees_created": 0}

    total  = len(all_active)
    random.shuffle(all_active)
    n_paid = int(total * body.paid_pct / 100.0)

    paid_members   = all_active[:n_paid]
    unpaid_members = all_active[n_paid:]

    for m in paid_members:
        m.weekly_payment_status = WeeklyPaymentStatus.Paid
    for m in unpaid_members:
        m.weekly_payment_status = WeeklyPaymentStatus.Unpaid

    db.flush()

    # ── Late fees ─────────────────────────────────────────────────────────────
    late_tokens = 0
    if body.apply_late_fee and unpaid_members and body.late_fee_inr > 0:
        fee_dec = Decimal(str(body.late_fee_inr))
        for m in unpaid_members:
            code = "LF-" + secrets.token_hex(4).upper()
            db.add(Token(
                code       = code,
                type       = TokenType.Withdraw,     # treated as outflow
                value_inr  = fee_dec,
                status     = TokenStatus.Burned,
                user_id    = m.id,
            ))
            late_tokens += 1

    # ── Elimination ───────────────────────────────────────────────────────────
    eliminated = 0
    if body.eliminate_unpaid_pct > 0 and unpaid_members:
        n_elim = max(1, int(len(unpaid_members) * body.eliminate_unpaid_pct / 100.0))
        for m in unpaid_members[:n_elim]:
            m.status          = "Eliminated_Unpaid"
            m.current_pool_id = None
            eliminated       += 1

    db.commit()

    return {
        "total_active":     total,
        "marked_paid":      len(paid_members),
        "marked_unpaid":    len(unpaid_members),
        "eliminated":       eliminated,
        "late_fees_created": late_tokens,
        "paid_pct_actual":  round(len(paid_members) / total * 100, 1),
        "message": (
            f"Scenario applied: {len(paid_members)} Paid, {len(unpaid_members)} Unpaid "
            f"({eliminated} eliminated, {late_tokens} late-fee tokens)."
        ),
    }


# =============================================================================
# POST /dev/real-simulation   (background job)
# GET  /dev/real-simulation-status/{job_id}
# GET  /dev/real-simulation-result/{job_id}
# =============================================================================
#
# Zero-duplication stress-test harness.
#
# Unlike /dev/advanced-simulation (which has its own _AdvSimEngine with
# duplicated in-memory logic), this endpoint calls the REAL production services
# on an isolated in-memory SQLite database with mocked time.
#
# Background job pattern (solves Render 60-second proxy timeout):
#   POST  → starts daemon thread, returns {"job_id": "..."} in < 200 ms
#   GET status/{job_id} → live progress (week N/total, %)
#   GET result/{job_id} → full result dict when status == "done"
#
# Architecture:
#   ChronosEngine  — patches datetime.now() across all production modules
#   SimulationDB   — isolated SQLite with all production tables (zero schema dup)
#   MassLoadInjector — creates synthetic users, manages payment state
#   RealSimEngine  — calls real services in exact weekly chronological order:
#     a. inject_week()         — new waitlist users + DEP tokens
#     b. auto_pay_installments() — all Active members marked Paid (U-08)
#     c. apply_abc_model()     — A/B/C late-fee + elimination + grace
#     d. start_draw_preparation() — acquires lock, flags L4, runs SDE meta-pool
#     e. execute_weekly_draw() — Ext-II/III pre-pass + all pool draws
#     f. post_draw_cleanup()   — reset weekly flags, release lock
#     g. auto_settle_referral_rw() — RW token auto-settlement (U-09)
#
# DRY contract: any rule change in production is automatically reflected.
#
# Debugger: on exception the background worker captures:
#   error_type, error_message, error_file, error_line, error_func,
#   error_source (exact source line), error_traceback (full stack).
# =============================================================================


def _background_real_simulation(job_id: str, params: dict) -> None:
    """
    Daemon-thread worker for POST /dev/real-simulation.

    Runs RealSimEngine in an isolated SQLite database.  Writes live progress
    to _SIM_STATUS[job_id] after every completed week via progress_callback so
    the frontend can display "Week N / total (X%)" while the job runs.

    On any exception, captures full traceback + exact failure location
    (file path, line number, function name, source line text) so the
    Debugger Panel in DevTools can display the precise failure site without
    the developer needing to read server logs.

    The caller must register a "queued" entry in _SIM_STATUS before calling
    threading.Thread.start() to avoid a race between the poll endpoint and
    the worker's first status write.
    """
    import traceback as _tb_mod
    from app.services.real_simulation import RealSimEngine

    def _on_week(week_num: int, total_weeks: int, _metrics: dict) -> None:
        """Called by RealSimEngine after each week completes."""
        pct = round(week_num / max(total_weeks, 1) * 100.0, 1)
        with _SIM_LOCK:
            _SIM_STATUS[job_id].update({
                "status":       "running",
                "current_week": week_num,
                "total_weeks":  total_weeks,
                "percent":      pct,
            })

    # Flip from "queued" → "running" immediately so the status endpoint
    # never returns "queued" after the thread has already started.
    with _SIM_LOCK:
        _SIM_STATUS[job_id]["status"] = "running"

    try:
        engine = RealSimEngine(
            weeks                = params["weeks"],
            users_per_week       = params["users_per_week"],
            initial_users        = params["initial_users"],
            organic_ratio        = params["organic_ratio"],
            late_ratio           = params["late_ratio"],
            elim_pct_a           = params["elim_pct_a"],
            grace_pct_c          = params["grace_pct_c"],
            volatility_mode      = params["volatility_mode"],
            volatility_max       = params["volatility_max"],
            start_year           = params["start_year"],
            start_week           = params["start_week"],
            inflow_pattern       = params["inflow_pattern"],
            referral_burst_week  = params["referral_burst_week"],
            payment_shock_week   = params["payment_shock_week"],
            waitlist_dropout_pct = params["waitlist_dropout_pct"],
            organic_decay_rate   = params["organic_decay_rate"],
            simulation_label     = params["simulation_label"],
        )

        result = engine.run(progress_callback=_on_week)

        with _SIM_LOCK:
            _SIM_STATUS[job_id].update({
                "status":       "done",
                "current_week": params["weeks"],
                "total_weeks":  params["weeks"],
                "percent":      100.0,
                "result":       result,
                "finished_at":  datetime.now(timezone.utc).isoformat(),
            })

        _logger_sim.info(
            "RealSim DONE  job_id=%s  weeks=%d  users=%d  winners=%d",
            job_id,
            params["weeks"],
            result.get("simulation_summary", {}).get("total_simulated_users_created", 0),
            result.get("simulation_summary", {}).get("total_winners_drawn", 0),
        )

    except Exception as exc:
        # ── Full traceback capture for the DevTools Debugger Panel ────────────
        tb_frames = _tb_mod.extract_tb(exc.__traceback__)
        tb_string = "".join(_tb_mod.format_tb(exc.__traceback__))
        # Most-recent (innermost) frame is where the exception was raised
        last = tb_frames[-1] if tb_frames else None

        with _SIM_LOCK:
            _SIM_STATUS[job_id].update({
                "status":          "error",
                "error_message":   str(exc),
                "error_type":      type(exc).__name__,
                "error_traceback": tb_string,
                "error_file":      last.filename if last else None,
                "error_line":      last.lineno   if last else None,
                "error_func":      last.name     if last else None,
                "error_source":    (last.line or "").strip() if last else None,
                "finished_at":     datetime.now(timezone.utc).isoformat(),
            })

        _logger_sim.exception("RealSim FAILED  job_id=%s", job_id)

class RealSimRequest(BaseModel):
    weeks:              int   = Field(52,   ge=1,    le=200,
                                      description="Number of weekly draw cycles to simulate.")
    users_per_week:     int   = Field(24,   ge=0,    le=2000,
                                      description="New users injected into waitlist each week.")
    initial_users:      int   = Field(24,   ge=12,   le=5000,
                                      description="Seed users created before week 1 draw.")
    organic_ratio:      float = Field(0.6,  ge=0.0,  le=1.0,
                                      description="Fraction of new users who join organically (Brain 3 RDR feed).")
    late_users_ratio_pct: float = Field(2.0, ge=0.0, le=100.0,
                                        description="% of active members who miss payment each week.")
    elim_pct_a:         float = Field(80.0, ge=0.05, le=100.0,
                                      description="A — % of late payers directly eliminated (skip grace).")
    grace_saver_pct_c:  float = Field(15.0, ge=0.05, le=100.0,
                                      description="C — % of grace-eligible late payers who pay and survive.")
    volatility_mode:    bool  = Field(False,
                                      description="When True, weekly inflow is random 0–volatility_max.")
    volatility_max_inflow: int = Field(100, ge=5,
                                       description="Maximum random weekly inflow in volatility mode.")
    start_year:         int   = Field(2024, ge=2020, le=2040,
                                      description="ISO year for simulated week 1 (affects Brain 2 timestamps).")
    start_week:         int   = Field(1,    ge=1,    le=52,
                                      description="ISO week number for simulated week 1.")
    # ── K-12 to K-17: Extended Injection Knobs ────────────────────────────────
    inflow_pattern:     str   = Field("linear",
                                      description="K-12: Inflow pattern: linear|sine|burst|step.")
    referral_burst_week: int  = Field(0, ge=0, le=200,
                                      description="K-13: Week to inject a 2× referral surge (0=disabled).")
    payment_shock_week: int   = Field(0, ge=0, le=200,
                                      description="K-14: Week to inject a payment shock (0=disabled).")
    waitlist_dropout_pct: float = Field(0.0, ge=0.0, le=50.0,
                                        description="K-15: % of waitlist who drop out before pool entry.")
    organic_decay_rate: float = Field(0.0, ge=0.0, le=1.0,
                                      description="K-16: Weekly organic join rate decay (0=none).")
    simulation_label:   str   = Field("",
                                      description="K-17: Free-text label for multi-run comparison.")


@router.post("/real-simulation")
def run_real_simulation(body: RealSimRequest):
    """
    Real-Strategy Stress-Test Engine — Background Job Mode.

    Calls ACTUAL production services (draw, SDE, waitlist, Brain 2/3/5)
    on an isolated in-memory SQLite database with mocked time (ChronosEngine).

    Returns {"job_id": "..."} IMMEDIATELY (< 200 ms) and runs the simulation
    in a background daemon thread.  No HTTP proxy timeout possible — this
    endpoint returns before any heavy work starts.

    Guarantees:
      - Zero logic duplication: all math lives in production services
      - Chronos Engine: datetime.now() mocked globally across 7 modules
      - SimulationDB: isolated SQLite — production DB never touched
      - Injector + Loader: MassLoadInjector creates real users with DEP tokens
      - Time-travel: ChronosEngine advances clock week-by-week per user inflow
        timestamps and weekly draw schedule (Mon–Sun cycle, T-2H, T-0H, T+5m)
      - A/B/C compliance: apply_abc_model() → Late_Fee/Grace_Fee tokens,
        EliminationEvent records, waitlist refill after eliminations
      - Payment engine: auto_pay_installments() marks all active members Paid
        per week; referral RW settlement (U-09) runs post-draw

    Flow:
      POST /dev/real-simulation          → { job_id, status:"queued", total_weeks }
      GET  /dev/real-simulation-status/{job_id}  → { status, current_week, total_weeks, percent, ... }
      GET  /dev/real-simulation-result/{job_id}  → full result (only when status=="done")

    Debugger: on any failure, error_file, error_line, error_func, error_source
    and full error_traceback are available in the status endpoint.

    No cap on weeks — simulation CAN take time (like MetaTrader strategy tester).
    1–200 weeks supported.
    """
    job_id = str(uuid.uuid4())

    params = {
        "weeks":                body.weeks,
        "users_per_week":       body.users_per_week,
        "initial_users":        body.initial_users,
        "organic_ratio":        body.organic_ratio,
        "late_ratio":           body.late_users_ratio_pct / 100.0,
        "elim_pct_a":           body.elim_pct_a,
        "grace_pct_c":          body.grace_saver_pct_c,
        "volatility_mode":      body.volatility_mode,
        "volatility_max":       body.volatility_max_inflow,
        "start_year":           body.start_year,
        "start_week":           body.start_week,
        "inflow_pattern":       body.inflow_pattern,
        "referral_burst_week":  body.referral_burst_week,
        "payment_shock_week":   body.payment_shock_week,
        "waitlist_dropout_pct": body.waitlist_dropout_pct,
        "organic_decay_rate":   body.organic_decay_rate,
        "simulation_label":     body.simulation_label,
    }

    # Register "queued" BEFORE thread.start() — eliminates race with poll endpoint
    with _SIM_LOCK:
        _SIM_STATUS[job_id] = {
            "status":           "queued",
            "current_week":     0,
            "total_weeks":      body.weeks,
            "percent":          0.0,
            "result":           None,
            "error_message":    None,
            "error_type":       None,
            "error_traceback":  None,
            "error_file":       None,
            "error_line":       None,
            "error_func":       None,
            "error_source":     None,
            "started_at":       datetime.now(timezone.utc).isoformat(),
            "finished_at":      None,
        }

    thread = threading.Thread(
        target=_background_real_simulation,
        args=(job_id, params),
        daemon=True,
        name=f"real-sim-{job_id[:8]}",
    )
    thread.start()

    _logger_sim.info(
        "RealSim QUEUED  job_id=%s  weeks=%d  upw=%d  init=%d  late=%.1f%%  A=%.1f%%  C=%.1f%%",
        job_id, body.weeks, body.users_per_week, body.initial_users,
        body.late_users_ratio_pct, body.elim_pct_a, body.grace_saver_pct_c,
    )

    return {
        "job_id":      job_id,
        "status":      "queued",
        "total_weeks": body.weeks,
        "message": (
            f"Simulation queued — {body.weeks} weeks, "
            f"{body.users_per_week} users/week, {body.initial_users} seed users. "
            f"Poll GET /dev/real-simulation-status/{job_id} for live progress."
        ),
    }


@router.get("/real-simulation-status/{job_id}")
def real_sim_status(job_id: str):
    """
    Poll the live progress of a background Real-Engine simulation.

    Status values:
      "queued"  — thread registered, not yet started
      "running" — engine executing; current_week and percent update each week
      "done"    — completed successfully; fetch full result via /real-simulation-result/{job_id}
      "error"   — exception raised; error_* fields populated for the Debugger Panel

    The status registry is process-local (in-memory dict).  Server restart clears
    all entries.  If 404 is returned, the server was restarted mid-simulation.
    """
    with _SIM_LOCK:
        entry = dict(_SIM_STATUS.get(job_id, {}))

    if not entry:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No simulation job found for job_id='{job_id}'. "
                "The server may have restarted, clearing the in-memory registry. "
                "Re-run the simulation from the Dev Tools panel."
            ),
        )

    return {
        "job_id":          job_id,
        "status":          entry["status"],
        "current_week":    entry["current_week"],
        "total_weeks":     entry["total_weeks"],
        "percent":         entry["percent"],
        "started_at":      entry["started_at"],
        "finished_at":     entry["finished_at"],
        # ── Debugger fields — only populated when status == "error" ──────────
        "error_message":   entry.get("error_message"),
        "error_type":      entry.get("error_type"),
        "error_file":      entry.get("error_file"),
        "error_line":      entry.get("error_line"),
        "error_func":      entry.get("error_func"),
        "error_source":    entry.get("error_source"),
        "error_traceback": entry.get("error_traceback"),
    }


@router.get("/real-simulation-result/{job_id}")
def real_sim_result(job_id: str):
    """
    Fetch the full simulation result after status == "done".

    Returns 202 if still running (with current progress in the detail message),
    500 if the simulation failed (with full debugger info),
    404 if the job_id is unknown (server restart cleared the registry).

    The result dict schema is identical to /dev/advanced-simulation so the
    DevTools 6-tab report sub-nav renders without any frontend changes.
    """
    with _SIM_LOCK:
        entry = dict(_SIM_STATUS.get(job_id, {}))

    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"No simulation job found for job_id='{job_id}'. Server may have restarted.",
        )

    status = entry["status"]

    if status == "running":
        raise HTTPException(
            status_code=202,
            detail=(
                f"Simulation still running — "
                f"week {entry['current_week']}/{entry['total_weeks']} "
                f"({entry['percent']:.1f}%). "
                f"Poll GET /dev/real-simulation-status/{job_id} and retry when status=='done'."
            ),
        )

    if status == "queued":
        raise HTTPException(
            status_code=202,
            detail=f"Simulation is queued but has not started yet. Poll status endpoint.",
        )

    if status == "error":
        raise HTTPException(
            status_code=500,
            detail={
                "error_message":   entry.get("error_message"),
                "error_type":      entry.get("error_type"),
                "error_file":      entry.get("error_file"),
                "error_line":      entry.get("error_line"),
                "error_func":      entry.get("error_func"),
                "error_source":    entry.get("error_source"),
                "error_traceback": entry.get("error_traceback"),
            },
        )

    # status == "done"
    return entry["result"]
