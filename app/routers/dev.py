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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# run_merger_refill_converge added for injection-time consolidation (Enhancement 1B).
from app.services.waitlist import (
    assign_waitlist_to_pools, fill_pool_vacancies, manual_create_pool,
    run_merger_refill_converge,
)

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
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Surface a Pool Re-assessor HOLD as a clean 409 (not a 500) so the dev
        # force-draw button reports the block and points to the report.
        from app.services.pool_reassessor import ReassessmentHoldError
        try:
            mass = execute_weekly_draw(
                db,
                auto_pay_unpaid=True,   # always safe-pay before drawing in dev mode
            )
        except ReassessmentHoldError as exc:
            raise HTTPException(status_code=409, detail={
                "error":        "reassessment_hold",
                "message":      "Draw blocked by the Pool Re-assessor — approve the "
                                "corrected plan (Pool Re-assessment panel) before re-running.",
                "week_id":      getattr(exc, "week_id", None),
                "report_id":    getattr(exc, "report_id", None),
                "failed_gates": getattr(exc, "failed_gates", []) or [],
            })
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

                # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                _post_injection_consolidate(bg_db)   # Enhancement 1B (lock-gated)

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
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # COMPREHENSIVE clean slate — truncate ALL transactional/test tables, not just
    # users/pools/tokens. Leftover draw_history, weekly_draw_state, system_locks,
    # SDE sessions and elimination_events from earlier test injections corrupt
    # downstream stats and can interfere with a fresh simulation. We explicitly
    # PRESERVE admins (login accounts) and system_settings (global config).
    _test_tables = [
        "tokens",
        "draw_history",
        "weekly_draw_state",
        "system_locks",
        "sde_checkpoints",
        "sde_sessions",
        "elimination_events",
        "users",
        "pools",
    ]
    try:
        # PostgreSQL: TRUNCATE with RESTART IDENTITY resets sequences to 1.
        # CASCADE handles all FK constraints automatically across the listed tables.
        # The admins and system_settings tables have no FK to any of these and are
        # therefore NOT affected by CASCADE.
        db.execute(text(
            f"TRUNCATE TABLE {', '.join(_test_tables)} RESTART IDENTITY CASCADE"
        ))
        db.commit()
        sequences_reset = True
    except Exception:
        # Fallback for non-PostgreSQL environments (e.g., SQLite in local unit tests).
        # Delete children before parents to respect FK ordering.
        db.rollback()
        for _tbl in _test_tables:
            try:
                db.execute(text(f"DELETE FROM {_tbl}"))
            except Exception:
                pass  # table may not exist on older schemas — skip
        db.commit()

    return ResetDataResult(
        users_deleted=users_count,
        tokens_deleted=tokens_count,
        pools_deleted=pools_count,
        sequences_reset=sequences_reset,
        note=(
            "Clean slate: users, pools, tokens, draw history, weekly draw state, "
            "system locks, SDE sessions and elimination events were all cleared. "
            "Admin accounts and system settings were NOT affected. "
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


# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ───────────────────────────────────────────────────────────────────
# The Fast Preview simulation (POST /dev/advanced-simulation + its in-memory
# _AdvSimEngine, AdvancedSimRequest, _SU/_SP dataclasses, _sim_flush/_sim_cleanup
# helpers, and _SIM_CHUNK/_S_CAP/_S_THR/_S_DEP constants) was REMOVED COMPLETELY
# per directive Point 4 ("fast stress test remove completely that is useless").
# It duplicated production logic in-memory and could drift from the real rules.
# The Real-Engine job API (POST /dev/real-simulation, below) is the ONLY simulation
# path now — it calls the ACTUAL production services (draw, SDE, waitlist, finance
# manager, Brain 2/3/5) on an isolated SQLite DB with Chronos time-travel (zero
# logic duplication).
#
# _logger_sim is RETAINED below: it is SHARED by the inject-timed background task
# and the Real-Engine background job — it is NOT exclusive to the removed Fast sim.
_logger_sim = __import__("logging").getLogger(__name__ + ".advsim")


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
            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Precedence + defensive None-guard. Previously
            # `float(A if c else B or 0)` parsed as `float(A if c else (B or 0))`,
            # so the `or 0` guard covered ONLY slot 2; the slot-1 branch had none.
            # winner_*_net_payout is nullable=False at the DDL level, so well-formed
            # ORM rows are already safe — but a Python-level None reaching this line
            # (a legacy / raw-SQL row that bypassed the ORM constraint, or any non-ORM
            # insert path) would raise float(None) → TypeError → HTTP 500 on the
            # Winners statistics tab. Parenthesising makes the guard symmetric across
            # both slots regardless of insert path. No behaviour change for valid rows.
            pay  = float((dh.winner_1_net_payout if slot == 1 else dh.winner_2_net_payout) or 0)
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


# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# INJECTION-TIME CONSOLIDATION (Enhancement 1B — Jun-20) — "merger should also fire
# at member-join / injection time so fragments never accumulate between draws."
def _post_injection_consolidate(db: Session) -> None:
    """
    After a freshly-injected batch has filled vacancies + formed new full pools, fold
    any pre-existing post-draw partial pods (e.g. 10/12 pools awaiting refill) into the
    single FIFO remainder pool immediately — instead of waiting for the next draw tick.

    MONEY-SAFE LOCK GATE (critical):
      The two-pointer compaction inside run_merger_refill_converge is lock-INDEPENDENT
      (it is designed to run *inside* the draw window at T-2H / T+5M).  Calling it from
      this async injection path WHILE a weekly draw concurrently holds the draw_engine
      lock would race the draw engine moving the very same members — a money-grade
      hazard.  So we SKIP whenever the draw lock is held; the draw's own T+5M
      convergence consolidates in that case.  Failure-isolated: never raises into the
      injection path (a consolidation hiccup must not fail user creation).
    """
    try:
        from app.models.system_lock import SystemLock
        draw_locked = (
            db.query(SystemLock)
            .filter(
                SystemLock.lock_name == "draw_engine",
                SystemLock.expires_at > datetime.now(timezone.utc),
            )
            .first() is not None
        )
        if draw_locked:
            _logger_sim.info(
                "inject consolidate: SKIPPED — draw engine lock active (draw in "
                "flight; its T+5M converge will consolidate).",
            )
            return
        result = run_merger_refill_converge(db)
        _logger_sim.info(
            "inject consolidate: merger convergence in %d round(s) — %d member(s) "
            "compacted, %d pool(s) dissolved, %s partial pool(s) remain.",
            result["rounds"], result["transfers"], len(result["dissolved"]),
            result.get("partial_pools", "?"),
        )
    except Exception as exc:   # consolidation must never break injection
        try:
            db.rollback()
        except Exception:
            pass
        _logger_sim.error("inject consolidate FAILED (non-fatal): %s", exc)


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

        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        _post_injection_consolidate(db)   # Enhancement 1B (lock-gated injection-time converge)

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
            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            _post_injection_consolidate(db)   # Enhancement 1B (lock-gated injection-time converge)
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
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# This endpoint calls the REAL production services on an isolated in-memory SQLite
# database with mocked time — ZERO logic duplication. The former
# /dev/advanced-simulation Fast Preview engine (duplicated in-memory logic) has
# been removed completely; this is now the ONLY simulation path.
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
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # The `from app.services.real_simulation import RealSimEngine` import was
    # MOVED from here (module top of the worker, BEFORE the try) to INSIDE the
    # try block below. Rationale: a pre-existing IndentationError in
    # real_simulation.py made it un-importable; because the import sat before
    # the try, the ImportError killed this daemon thread BEFORE the except
    # handler (which records error_type/line/traceback for the Debugger Panel)
    # could capture anything — so the UI froze at "Week 0 / 0.0%" with NO error
    # shown, for ~10 sessions. With the import inside the try, any future
    # import-time regression surfaces as a visible "error" status with full
    # traceback in the DevTools Debugger Panel instead of a silent freeze.

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
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Import lives HERE (inside try) so an un-importable engine becomes a
        # captured "error" status (visible in the Debugger Panel) rather than a
        # silent daemon-thread death that freezes the UI at 0%. See the comment
        # at the top of this function for the full rationale.
        from app.services.real_simulation import RealSimEngine
        # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Pass job_id as run_id so MassLoadInjector prefixes all usernames/tokens
        # with rsim_{job_id[:8]} — collision-safe on real PostgreSQL.
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
            run_id               = job_id,
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
    # SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # FIX: Refuse a second simulation if one is already running.
    # Concurrent simulations share the same PostgreSQL tables — both call
    # execute_weekly_draw() on the same pools → row-level deadlock → infinite hang.
    with _SIM_LOCK:
        _active_sims = [jid for jid, v in _SIM_STATUS.items() if v.get("status") == "running"]
    if _active_sims:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Simulation {_active_sims[0][:8]}… is already running. "
                "Wait for it to complete, or restart the server to cancel all in-progress jobs."
            ),
        )

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

    The result dict schema is the canonical Stress Test schema (formerly shared
    with the now-removed /dev/advanced-simulation Fast Preview) so the DevTools
    6-tab report sub-nav renders without any frontend changes.
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


# =============================================================================
# SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
# GET/POST/DELETE /dev/debugger/* — Global System Debugger controls
# =============================================================================
#
# Four endpoints that expose the SystemDebugger toggle and DebugLog table.
# All require ENABLE_DEV_MODE=true (require_dev_mode dependency).
#
# POST /dev/debugger/toggle  {"enabled": true|false}  — flip the toggle
# GET  /dev/debugger/status                           — current state + log count
# GET  /dev/debugger/logs    ?run_id=&limit=&offset=  — paginated log entries
# DELETE /dev/debugger/logs                           — clear all entries
# =============================================================================

class DebuggerToggleRequest(BaseModel):
    enabled: bool = Field(..., description="True to enable the Global System Debugger.")


@router.post("/debugger/toggle")
def toggle_debugger(
    body: DebuggerToggleRequest,
    _: None = Depends(require_dev_mode),
):
    """
    Enable or disable the Global System Debugger.

    When enabled, every @debug_trace-decorated call in RealSimEngine writes
    a DebugLog row (phase, event, duration_ms, error) to the debug_logs table.
    When disabled, all decorators are pure zero-overhead pass-throughs.
    """
    from app.services.system_debugger import enable_debugger, disable_debugger

    if body.enabled:
        enable_debugger()
    else:
        disable_debugger()

    return {
        "enabled": body.enabled,
        "message": f"Global System Debugger {'ENABLED' if body.enabled else 'DISABLED'}.",
    }


@router.get("/debugger/status")
def debugger_status(
    db: Session = Depends(get_db),
    _: None = Depends(require_dev_mode),
):
    """
    Return the current debugger toggle state + count of rows in debug_logs.
    """
    from app.services.system_debugger import get_debug_context
    from app.models.debug_log import DebugLog

    log_count = db.query(func.count(DebugLog.id)).scalar() or 0
    ctx = get_debug_context()
    return {
        "enabled":    ctx["enabled"],
        "run_id":     ctx["run_id"],
        "week":       ctx["week"],
        "log_count":  log_count,
    }


@router.get("/debugger/logs")
def get_debugger_logs(
    run_id:   str | None = Query(None, description="Filter by simulation run_id."),
    week_num: int | None = Query(None, description="Filter by simulated week number."),
    phase:    str | None = Query(None, description="Substring filter on phase tag."),
    limit:    int        = Query(100,  ge=1, le=1000),
    offset:   int        = Query(0,    ge=0),
    db: Session = Depends(get_db),
    _: None     = Depends(require_dev_mode),
):
    """
    Return paginated DebugLog entries, newest-first.

    Filters are additive (AND).  All filters are optional.
    """
    from app.models.debug_log import DebugLog

    q = db.query(DebugLog)
    if run_id   is not None: q = q.filter(DebugLog.run_id   == run_id)
    if week_num is not None: q = q.filter(DebugLog.week_num == week_num)
    if phase    is not None: q = q.filter(DebugLog.phase.contains(phase))

    total = q.count()
    rows  = q.order_by(DebugLog.id.desc()).offset(offset).limit(limit).all()

    return {
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "logs": [
            {
                "id":          r.id,
                "run_id":      r.run_id,
                "week_num":    r.week_num,
                "phase":       r.phase,
                "event":       r.event,
                "data_json":   r.data_json,
                "duration_ms": r.duration_ms,
                "lpi":         r.lpi,
                "error":       r.error,
                "created_at":  r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.delete("/debugger/logs")
def clear_debugger_logs(
    db: Session = Depends(get_db),
    _: None     = Depends(require_dev_mode),
):
    """
    Delete all rows from the debug_logs table.
    Use before a new load-test run to get a clean log.
    """
    from app.models.debug_log import DebugLog

    count = db.query(func.count(DebugLog.id)).scalar() or 0
    db.query(DebugLog).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted": count,
        "message": f"Cleared {count} debug log entries from debug_logs.",
    }


# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# =============================================================================
# FORENSIC DEBUGGER — event-level audit API ("every breath of the system")
# -----------------------------------------------------------------------------
# Finer-grained than the function-LEVEL Global System Debugger above: this
# records every DOMAIN event (member join/win, level advance, elimination,
# pool create/merge/dissolve, SDE flag / meta-pool / Case-E, draw executed,
# posture decision, per-week heartbeat, anomalies) into the forensic_events
# table via app.services.forensic.
#
# POST   /dev/forensic/toggle                          — enable/disable recorder
# GET    /dev/forensic/status                          — toggle state + row count
# GET    /dev/forensic/events   ?filters&limit&offset  — paginated, newest-first
# GET    /dev/forensic/summary  ?run_id&week_id        — aggregate counts
# GET    /dev/forensic/export   ?format=csv|json       — full filtered dump
# DELETE /dev/forensic/events   ?run_id                — clear (optionally scoped)
# =============================================================================

class ForensicToggleRequest(BaseModel):
    enabled: bool   = Field(..., description="True to enable the Forensic Debugger.")
    run_id:  str | None = Field(None, description="Optional run tag for captured events.")


@router.post("/forensic/toggle")
def toggle_forensic(
    body: ForensicToggleRequest,
    _: None = Depends(require_dev_mode),
):
    """
    Enable or disable the Forensic Debugger (event-level recorder).

    When enabled, every instrumented domain event in the engine is buffered and
    bulk-flushed (per Chronos tick / per week) into forensic_events via an
    independent session — engine payout/draw transactions are never touched.
    When disabled, every recorder call is a single boolean check (zero overhead);
    disabling first flushes any pending buffered events.
    """
    from app.services import forensic as _forensic

    if body.enabled:
        _forensic.enable_forensic(body.run_id or "live")
    else:
        _forensic.disable_forensic()

    return {
        "enabled": body.enabled,
        "context": _forensic.get_context(),
        "message": f"Forensic Debugger {'ENABLED' if body.enabled else 'DISABLED'}.",
    }


@router.get("/forensic/status")
def forensic_status(
    db: Session = Depends(get_db),
    _: None = Depends(require_dev_mode),
):
    """Return the current forensic toggle state + total rows in forensic_events."""
    from app.services import forensic as _forensic
    from app.models.forensic_event import ForensicEvent

    event_count = db.query(func.count(ForensicEvent.id)).scalar() or 0
    ctx = _forensic.get_context()
    return {
        "enabled":     ctx["enabled"],
        "run_id":      ctx["run_id"],
        "week":        ctx["week"],
        "tick":        ctx["tick"],
        "buffered":    ctx["buffered"],
        "event_count": event_count,
    }


def _forensic_apply_filters(q, *, run_id, week_id, category, event_type,
                            severity, entity_id, search):
    """Shared additive (AND) filter builder for events/summary/export."""
    from app.models.forensic_event import ForensicEvent
    if run_id     is not None: q = q.filter(ForensicEvent.run_id     == run_id)
    if week_id    is not None: q = q.filter(ForensicEvent.week_id    == week_id)
    if category   is not None: q = q.filter(ForensicEvent.category   == category)
    if event_type is not None: q = q.filter(ForensicEvent.event_type == event_type)
    if severity   is not None: q = q.filter(ForensicEvent.severity   == severity)
    if entity_id  is not None: q = q.filter(ForensicEvent.entity_id  == entity_id)
    if search     is not None: q = q.filter(ForensicEvent.message.contains(search))
    return q


def _forensic_row_dict(r) -> dict:
    return {
        "id":          r.id,
        "run_id":      r.run_id,
        "seq":         r.seq,
        "week_id":     r.week_id,
        "tick":        r.tick,
        "category":    r.category,
        "event_type":  r.event_type,
        "severity":    r.severity,
        "actor":       r.actor,
        "entity_type": r.entity_type,
        "entity_id":   r.entity_id,
        "entity_ref":  r.entity_ref,
        "amount_inr":  r.amount_inr,
        "before_json":  r.before_json,
        "after_json":   r.after_json,
        "payload_json": r.payload_json,
        "message":      r.message,
        "created_at":   r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/forensic/events")
def get_forensic_events(
    run_id:     str | None = Query(None, description="Filter by capture run_id."),
    week_id:    int | None = Query(None, description="Filter by simulated week number."),
    category:   str | None = Query(None, description="Exact category (DRAW, SDE, MERGER, ...)."),
    event_type: str | None = Query(None, description="Exact event_type (member_won, ...)."),
    severity:   str | None = Query(None, description="Exact severity (info/notice/warning/critical)."),
    entity_id:  int | None = Query(None, description="Filter by entity_id (user/pool id)."),
    search:     str | None = Query(None, description="Substring filter on the message field."),
    order:      str        = Query("desc", regex="^(asc|desc)$",
                                   description="Timeline order by (seq within run, id overall)."),
    limit:      int        = Query(200, ge=1, le=2000),
    offset:     int        = Query(0,   ge=0),
    db: Session = Depends(get_db),
    _: None     = Depends(require_dev_mode),
):
    """
    Return paginated forensic_events. Filters are additive (AND); all optional.

    Default order is newest-first (descending id). Pass order=asc to replay the
    timeline forward (chronological). Within a single run, `seq` is a strict
    monotonic tiebreaker so same-millisecond events stay correctly ordered.
    """
    from app.models.forensic_event import ForensicEvent

    q = db.query(ForensicEvent)
    q = _forensic_apply_filters(
        q, run_id=run_id, week_id=week_id, category=category,
        event_type=event_type, severity=severity, entity_id=entity_id, search=search,
    )

    total = q.count()
    if order == "asc":
        q = q.order_by(ForensicEvent.id.asc())
    else:
        q = q.order_by(ForensicEvent.id.desc())
    rows = q.offset(offset).limit(limit).all()

    return {
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "order":  order,
        "events": [_forensic_row_dict(r) for r in rows],
    }


@router.get("/forensic/summary")
def forensic_summary(
    run_id:  str | None = Query(None, description="Scope the summary to one run."),
    week_id: int | None = Query(None, description="Scope the summary to one week."),
    db: Session = Depends(get_db),
    _: None     = Depends(require_dev_mode),
):
    """
    Aggregate counts of forensic events — by category, event_type, severity, and
    week — for the operator dashboard. Anomalies (category=ANOMALY) and
    warning/critical severities are surfaced separately as a quick health gauge.
    """
    from app.models.forensic_event import ForensicEvent

    def _scoped():
        q = db.query(ForensicEvent)
        if run_id  is not None: q = q.filter(ForensicEvent.run_id  == run_id)
        if week_id is not None: q = q.filter(ForensicEvent.week_id == week_id)
        return q

    total = _scoped().count()

    by_category = (
        _scoped().with_entities(ForensicEvent.category, func.count(ForensicEvent.id))
        .group_by(ForensicEvent.category)
        .order_by(func.count(ForensicEvent.id).desc()).all()
    )
    by_event = (
        _scoped().with_entities(ForensicEvent.event_type, func.count(ForensicEvent.id))
        .group_by(ForensicEvent.event_type)
        .order_by(func.count(ForensicEvent.id).desc()).all()
    )
    by_severity = (
        _scoped().with_entities(ForensicEvent.severity, func.count(ForensicEvent.id))
        .group_by(ForensicEvent.severity).all()
    )
    by_week = (
        _scoped().with_entities(ForensicEvent.week_id, func.count(ForensicEvent.id))
        .group_by(ForensicEvent.week_id)
        .order_by(ForensicEvent.week_id.asc()).all()
    )

    anomaly_count = _scoped().filter(ForensicEvent.category == "ANOMALY").count()
    alert_count   = _scoped().filter(
        ForensicEvent.severity.in_(["warning", "critical"])
    ).count()

    runs = (
        db.query(ForensicEvent.run_id, func.count(ForensicEvent.id))
        .group_by(ForensicEvent.run_id)
        .order_by(func.max(ForensicEvent.id).desc()).limit(50).all()
    )

    return {
        "total":         total,
        "anomaly_count": anomaly_count,
        "alert_count":   alert_count,
        "by_category":   [{"category": c or "?", "count": n} for c, n in by_category],
        "by_event_type": [{"event_type": e or "?", "count": n} for e, n in by_event],
        "by_severity":   [{"severity": s or "?", "count": n} for s, n in by_severity],
        "by_week":       [{"week_id": w, "count": n} for w, n in by_week],
        "runs":          [{"run_id": r or "?", "count": n} for r, n in runs],
    }


@router.get("/forensic/export")
def export_forensic_events(
    fmt:        str        = Query("csv", regex="^(csv|json)$", alias="format"),
    run_id:     str | None = Query(None),
    week_id:    int | None = Query(None),
    category:   str | None = Query(None),
    event_type: str | None = Query(None),
    severity:   str | None = Query(None),
    entity_id:  int | None = Query(None),
    search:     str | None = Query(None),
    max_rows:   int        = Query(50000, ge=1, le=500000),
    db: Session = Depends(get_db),
    _: None     = Depends(require_dev_mode),
):
    """
    Stream the full filtered forensic timeline (chronological) as CSV or JSON.
    Used by the dashboard "Export" button to pull an auditable event log.
    """
    import csv as _csv
    import io as _io
    import json as _json
    from fastapi.responses import Response
    from app.models.forensic_event import ForensicEvent

    q = db.query(ForensicEvent)
    q = _forensic_apply_filters(
        q, run_id=run_id, week_id=week_id, category=category,
        event_type=event_type, severity=severity, entity_id=entity_id, search=search,
    )
    rows = q.order_by(ForensicEvent.id.asc()).limit(max_rows).all()
    dicts = [_forensic_row_dict(r) for r in rows]

    if fmt == "json":
        return Response(
            content=_json.dumps({"count": len(dicts), "events": dicts}, default=str),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="forensic_events.json"'},
        )

    # CSV
    cols = [
        "id", "run_id", "seq", "week_id", "tick", "category", "event_type",
        "severity", "actor", "entity_type", "entity_id", "entity_ref",
        "amount_inr", "before_json", "after_json", "payload_json", "message",
        "created_at",
    ]
    buf = _io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for d in dicts:
        writer.writerow(d)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="forensic_events.csv"'},
    )


@router.delete("/forensic/events")
def clear_forensic_events(
    run_id: str | None = Query(None, description="If set, only clear this run's events."),
    db: Session = Depends(get_db),
    _: None     = Depends(require_dev_mode),
):
    """
    Delete forensic_events rows. With run_id, scope the purge to a single run;
    without it, clear the whole table (use before a fresh forensic-capture run).
    """
    from app.models.forensic_event import ForensicEvent

    q = db.query(ForensicEvent)
    if run_id is not None:
        q = q.filter(ForensicEvent.run_id == run_id)
    count = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return {
        "deleted": count,
        "scope":   run_id or "ALL",
        "message": f"Cleared {count} forensic event(s)"
                   + (f" for run '{run_id}'." if run_id else " (entire table)."),
    }


# =============================================================================
# Manual Event-Timeline Simulator — "Time Machine"   (/dev/manual-sim/*)
# =============================================================================
# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
# A MANUAL counterpart to the automated /dev/real-simulation engine.  Where that
# engine races the clock through every weekly cycle in one synchronous run, the
# Time Machine lets a developer jump event → event along the SAME milestone spine
# (CYCLE_START → DUE_DATE → GRACE_PERIOD_START → G_CLOSE → T_02H → T_00H → T_05M)
# across separate requests, surfacing only the actions valid at each instant.
#
# All clock + event-state logic lives in app/services/manual_sim.py.  These
# endpoints are a thin transport layer; they inherit the router's
# require_dev_mode gate, so every route here is 403 in production.  The action
# endpoints that actually mutate money state (Phase 3) wrap the SAME production
# services in a request-scoped ChronosEngine (manual_sim.manual_clock) so reads
# and writes observe the simulated instant — zero business-logic duplication.
# =============================================================================


class ManualSimStartRequest(BaseModel):
    draw_anchor: Optional[str] = Field(
        None,
        description=(
            "ISO-8601 timestamp for cycle 1's draw (T_00H). Omit to default to "
            "the next Sunday 00:00 UTC. The simulated clock starts one cycle "
            "before this, at the computed CYCLE_START."
        ),
    )
    link_global: bool = Field(
        False,
        description="Link the global watch to the simulation watch (display + "
                    "request-scoped clock). Gated by ENABLE_DEV_MODE.",
    )
    ttl_hours: int = Field(
        6, ge=1, le=72,
        description="Session auto-expiry window. A forgotten session reverts "
                    "after this many hours.",
    )


class ManualSimJumpToRequest(BaseModel):
    event: str = Field(
        ...,
        description="Target event name from the spine. Must be strictly ahead "
                    "of the current event (time only moves forward).",
    )


@router.post("/manual-sim/start")
def manual_sim_start(body: ManualSimStartRequest, db: Session = Depends(get_db)):
    """
    Start (or replace) a Time Machine session.

    Anchors cycle 1 at ``draw_anchor`` (defaults to next Sunday 00:00 UTC) and
    positions the simulated clock at that cycle's CYCLE_START.  Returns the full
    state (watch, timeline, current event, available actions, snapshot).
    """
    from app.services import manual_sim

    anchor_dt = None
    if body.draw_anchor:
        try:
            anchor_dt = datetime.fromisoformat(body.draw_anchor)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid draw_anchor '{body.draw_anchor}'. Use ISO-8601, "
                       "e.g. 2026-03-22T00:00:00+00:00.",
            )
    try:
        return manual_sim.start_session(
            db,
            draw_anchor=anchor_dt,
            link_global=body.link_global,
            ttl_hours=body.ttl_hours,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/manual-sim/state")
def manual_sim_state(db: Session = Depends(get_db)):
    """
    Current Time Machine state — the panel's single source of truth.

    Returns ``{"active": false}`` when no session is live (or after TTL expiry,
    which auto-clears the stale session).  Otherwise returns the watch
    (sim time / day / date), cycle number, current event, the seven-node
    timeline with past/current flags, the actions available now, and a real-DB
    snapshot.
    """
    from app.services import manual_sim
    return manual_sim.compute_state(db)


@router.post("/manual-sim/jump-next")
def manual_sim_jump_next(db: Session = Depends(get_db)):
    """
    Advance the simulated clock to the next event on the spine.

    Moves the clock only — runs no business logic.  At T_05M (cleanup) it rolls
    into the next cycle and lands on DUE_DATE (the draw event doubles as the new
    cycle's start, keeping simulated time strictly forward).
    """
    from app.services import manual_sim
    try:
        return manual_sim.jump_next(db)
    except manual_sim.ManualSimError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/manual-sim/jump-to")
def manual_sim_jump_to(body: ManualSimJumpToRequest, db: Session = Depends(get_db)):
    """
    Forward-only jump to a named event within the current cycle.

    The target must be strictly ahead of the current event; backward jumps are
    rejected (409) because the timeline only moves forward.
    """
    from app.services import manual_sim
    try:
        return manual_sim.jump_to(db, body.event)
    except manual_sim.ManualSimError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/manual-sim/stop")
def manual_sim_stop(db: Session = Depends(get_db)):
    """
    Tear down the Time Machine session and guarantee no simulated clock remains
    installed.  Idempotent — safe to call when no session is active.
    """
    from app.services import manual_sim
    return manual_sim.stop_session(db)


class ManualSimLinkRequest(BaseModel):
    link_global: bool = Field(
        ...,
        description="When true, the frontend mirrors the global watch to the "
                    "simulated instant while a session is live. The simulated "
                    "clock itself stays request-scoped regardless.",
    )


@router.post("/manual-sim/link")
def manual_sim_link(body: ManualSimLinkRequest, db: Session = Depends(get_db)):
    """
    Toggle the global-watch link on the active Time Machine session.

    Display/intent switch only — the simulated write-clock is always installed
    just for the duration of an action request and never held open, so concurrent
    real traffic is never exposed to simulated time.  409 if no session is active.
    """
    from app.services import manual_sim
    try:
        return manual_sim.set_link(db, body.link_global)
    except manual_sim.ManualSimError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ── Per-event actions (Phase 3) ──────────────────────────────────────────────
# SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Each action runs the SAME production service the live app / RealSimEngine call,
# wrapped in manual_sim.manual_clock(sim_now) so every READ (datetime in the
# strategy modules) and every WRITE (token / elimination / draw timestamps via
# sim_clock) observes the simulated instant.  There is NO second financial
# implementation here — the Time Machine only chooses WHEN, not HOW.
#
# The event→action guard (manual_sim.assert_action) is the server-side authority:
# an action is rejected (409) unless it is offered at the event the clock is
# currently standing on, so the draw can never be executed before its −2h prep,
# etc.  The dev-mode gate is enforced twice (router dependency + manual_clock).

class ManualSimInjectRequest(BaseModel):
    count: int = Field(..., ge=1, le=20000,
                       description="Number of synthetic Paid-Waitlist users to inject.")
    organic_ratio: float = Field(0.6, ge=0.0, le=1.0,
                                 description="Fraction joining organically (rest via referral).")


class ManualSimSetLateRequest(BaseModel):
    late_pct: float = Field(..., ge=0.0, le=100.0,
                            description="Percentage of active members to treat as late this "
                                        "cycle. Stored as the grace-settlement late-ratio knob.")


class ManualSimGraceRequest(BaseModel):
    late_pct: Optional[float] = Field(None, ge=0.0, le=100.0,
                                      description="Override the stored late-ratio (else uses the "
                                                  "value set at the due-date event).")
    elim_pct_a: Optional[float] = Field(None, ge=0.0, le=100.0,
                                        description="A — % of late directly eliminated (skip grace).")
    grace_pct_c: Optional[float] = Field(None, ge=0.0, le=100.0,
                                         description="C — % of grace-eligible late who pay and survive.")


def _manual_sim_run(db: Session, action_key: str, runner):
    """Guard, time-travel, run, commit — the shared spine of every action route.

    1. Enforce the dev-mode gate and the event→action guard.
    2. Resolve the simulated instant from the persisted session.
    3. Run ``runner(manual_sim, sim_now)`` INSIDE manual_clock(sim_now) so the
       production service it calls reads + writes the simulated time.
    4. Commit, then return ``{action, result, state}`` (fresh full Time Machine
       state so the panel re-renders the watch, timeline and snapshot in one round
       trip).  On any service failure the transaction is rolled back (no partial
       money mutation) and surfaced as HTTP 400.
    """
    from app.services import manual_sim

    if not manual_sim._dev_mode_enabled():
        raise HTTPException(status_code=403, detail="ENABLE_DEV_MODE is not true.")
    try:
        manual_sim.assert_action(db, action_key)          # 409 if not allowed here
    except manual_sim.ManualSimError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    sim_now = manual_sim.sim_now(db)
    cur_event = manual_sim.current_event(db)
    try:
        with manual_sim.manual_clock(sim_now):
            result = runner(manual_sim, sim_now)
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:                               # any production-service failure
        try:
            db.rollback()
        except Exception:
            pass
        _logger_sim.error("manual-sim action '%s' FAILED: %s", action_key, exc)
        raise HTTPException(status_code=400, detail=f"{action_key} failed: {exc}")

    # Always-on audit + sliding TTL (post-commit so a failed action leaves no trail
    # and never extends the session).
    try:
        st = manual_sim.load_state(db) or {}
        manual_sim._audit(
            db, f"action:{action_key}", event=cur_event,
            cycle_num=st.get("cycle_num"), sim_now=sim_now,
            payload=(result if isinstance(result, dict) else None),
            message=f"{action_key} @ {cur_event}",
        )
        manual_sim.touch_session(db)
    except Exception:
        pass

    return {
        "action": action_key,
        "result": result,
        "state":  manual_sim.compute_state(db),
    }


@router.post("/manual-sim/action/inject")
def manual_sim_action_inject(body: ManualSimInjectRequest, db: Session = Depends(get_db)):
    """
    Inject synthetic users at the simulated instant (available at EVERY event).

    Re-uses the production MassLoadInjector + the exact pool-formation pipeline the
    live injection path uses (fill vacancies → form full pools → lock-gated merger
    convergence).  Pool formation runs synchronously here — Time-Machine batches are
    developer-driven and small — but is the SAME code as the background path.
    """
    from app.services.real_simulation import MassLoadInjector

    def runner(ms, sim_now):
        prefix, base = ms.reserve_inject_counter(db, body.count)
        injector = MassLoadInjector(run_prefix=prefix)
        injector._counter = base                            # continue this session's id block
        created = injector.inject_week(
            db, body.count, now=sim_now, organic_ratio=body.organic_ratio,
        )
        db.commit()                                         # persist users before forming pools

        # Net pool delta captures BOTH paths: assign_waitlist_to_pools auto-creates
        # full pools internally, and the manual_create_pool loop drains any remainder.
        pools_before = db.query(func.count(Pool.id)).scalar() or 0
        fill_pool_vacancies(db)
        while True:
            new_pool = manual_create_pool(db)
            if not new_pool:
                break
        _post_injection_consolidate(db)                     # lock-gated injection-time converge
        pools_after = db.query(func.count(Pool.id)).scalar() or 0

        return {
            "injected":     len(created),
            "pools_formed": max(0, pools_after - pools_before),
            "prefix":       prefix,
        }

    return _manual_sim_run(db, "inject_users", runner)


@router.post("/manual-sim/action/pay-all")
def manual_sim_action_pay_all(db: Session = Depends(get_db)):
    """
    DUE_DATE — everyone pays on time.  Marks every Unpaid Active member Paid and
    writes one weekly DEP installment token per member, timestamped at the
    simulated instant (production MassLoadInjector.auto_pay_installments).
    """
    from app.services.real_simulation import MassLoadInjector

    def runner(ms, sim_now):
        st = ms._require_active(db)
        injector = MassLoadInjector(run_prefix=st.get("inject_prefix", "msim0000"))
        paid = injector.auto_pay_installments(db, week_num=int(st.get("cycle_num", 1)))
        return {"installments_paid": paid}

    return _manual_sim_run(db, "pay_all_installments", runner)


@router.post("/manual-sim/action/set-late")
def manual_sim_action_set_late(body: ManualSimSetLateRequest, db: Session = Depends(get_db)):
    """
    DUE_DATE — choose how many members are late this cycle.

    Stores the late-ratio knob (fed to the grace-window settlement) and returns a
    projection.  Deliberately does NOT pre-mark members: the production
    apply_abc_model samples the late cohort itself at the grace event, so marking
    here would double-count.
    """
    def runner(ms, sim_now):
        knobs  = ms.set_settlement(db, late_ratio=body.late_pct / 100.0)
        active = db.query(func.count(User.id)).filter(
            User.status == UserStatus.Active
        ).scalar() or 0
        return {
            "late_ratio":     knobs["late_ratio"],
            "active_members": active,
            "projected_late": int(active * knobs["late_ratio"]),
        }

    return _manual_sim_run(db, "set_late_pct", runner)


@router.post("/manual-sim/action/pay-remaining")
def manual_sim_action_pay_remaining(db: Session = Depends(get_db)):
    """
    DUE_DATE — the stragglers settle.  Pays every still-Unpaid Active member at
    the simulated instant (same production auto-pay as pay-all; idempotent and
    collision-safe on re-run).
    """
    from app.services.real_simulation import MassLoadInjector

    def runner(ms, sim_now):
        st = ms._require_active(db)
        injector = MassLoadInjector(run_prefix=st.get("inject_prefix", "msim0000"))
        paid = injector.auto_pay_installments(db, week_num=int(st.get("cycle_num", 1)))
        return {"remaining_paid": paid}

    return _manual_sim_run(db, "pay_remaining", runner)


@router.post("/manual-sim/action/grace-settle")
def manual_sim_action_grace_settle(body: ManualSimGraceRequest, db: Session = Depends(get_db)):
    """
    GRACE_PERIOD_START — the authoritative A/B/C grace-window settlement.

    Runs the production apply_abc_model at the simulated instant: it marks the
    late cohort, accrues real Late_Fee tokens, splits them into
      • B — paid the late fee and stay in (Unpaid by design this week),
      • C — entered the grace window and paid the grace fee → survive,
      • A / failed-C — eliminated (real EliminationEvent rows written),
    then refills the vacancies.  The response is framed exactly as the panel asks:
    of those who were late, how many paid late fees (B) versus how many entered the
    grace window (C survivors + the eliminated who could not pay).
    """
    from app.services.real_simulation import MassLoadInjector

    def runner(ms, sim_now):
        st    = ms._require_active(db)
        knobs = ms.set_settlement(
            db,
            late_ratio=(None if body.late_pct is None else body.late_pct / 100.0),
            elim_pct_a=body.elim_pct_a,
            grace_pct_c=body.grace_pct_c,
        )
        injector = MassLoadInjector(run_prefix=st.get("inject_prefix", "msim0000"))
        res = injector.apply_abc_model(
            db,
            late_ratio=knobs["late_ratio"],
            elim_pct_a=knobs["elim_pct_a"],
            grace_pct_c=knobs["grace_pct_c"],
        )
        n_late = int(res.get("n_late", 0))
        n_b    = int(res.get("n_type_b", 0))
        n_c    = int(res.get("n_saved", 0))
        n_elim = int(res.get("n_elim", 0))
        return {
            "late_payers":              n_late,
            "paid_late_fee_B":          n_b,
            "grace_survivors_C":        n_c,
            "entered_grace_no_fee":     max(0, n_late - n_b),  # B paid; the rest go to grace
            "eliminated_A_or_failed":   n_elim,
            "late_fee_revenue_inr":     res.get("late_fee_revenue_inr", 0),
            "grace_fee_revenue_inr":    res.get("grace_fee_revenue_inr", 0),
            "total_compliance_revenue_inr": res.get("total_compliance_revenue_inr", 0),
            "knobs":                    knobs,
        }

    return _manual_sim_run(db, "grace_settlement", runner)


@router.post("/manual-sim/action/finalize-eliminations")
def manual_sim_action_finalize_eliminations(db: Session = Depends(get_db)):
    """
    G_CLOSE — the guillotine confirmation.

    Read-only: the eliminations were written atomically by the grace settlement
    (production apply_abc_model eliminates A + failed-C in one settlement, exactly
    as the live engine does).  This surfaces the EliminationEvent rows finalized in
    THIS cycle — count, split by reason, and total forfeited — so the developer can
    confirm the guillotine before the draw prepares.  It mutates nothing.
    """
    from app.models.elimination_event import EliminationEvent, EliminationReason

    def runner(ms, sim_now):
        cycle_start, cycle_end = ms.cycle_window(db)
        rows = (
            db.query(EliminationEvent)
            .filter(
                EliminationEvent.created_at >= cycle_start,
                EliminationEvent.created_at <= cycle_end,
            )
            .all()
        )
        non_payment = sum(1 for r in rows if r.reason == EliminationReason.non_payment)
        grace_exp   = sum(1 for r in rows if r.reason == EliminationReason.grace_expired)
        total_forfeited = sum(float(r.total_forfeited or 0) for r in rows)
        return {
            "eliminations_this_cycle": len(rows),
            "reason_non_payment":      non_payment,
            "reason_grace_expired":    grace_exp,
            "total_forfeited_inr":     round(total_forfeited, 2),
            "read_only":               True,
        }

    return _manual_sim_run(db, "finalize_eliminations", runner)


@router.post("/manual-sim/action/prepare-draw")
def manual_sim_action_prepare_draw(db: Session = Depends(get_db)):
    """
    T_02H — run the production draw preparation at the simulated instant.

    Acquires the draw-engine lock, flags L4 members, plans SDE meta-pools, freezes
    the Brain-5 LPI snapshot and runs the re-assessor — scoped to this session's
    injected users.  Surfaces whether an admin override is required before the draw.
    """
    from app.services.draw_preparation import start_draw_preparation

    def runner(ms, sim_now):
        st     = ms._require_active(db)
        prefix = st.get("inject_prefix", "msim0000")
        prep   = start_draw_preparation(db, draw_time_utc=sim_now, user_prefix=prefix)
        return {
            "week_id":                 prep.week_id,
            "preparation_valid":       bool(prep.preparation_valid),
            "countdown_active":        bool(prep.countdown_active),
            "admin_override_required": bool(prep.admin_override_required),
            "sde_sessions_planned":    int(prep.sde_sessions_planned or 0),
            "total_l4_count":          int(prep.total_l4_count or 0),
            "total_active_count":      int(prep.total_active_count or 0),
            "float_projection_inr":    int(prep.float_projection_inr or 0),
        }

    return _manual_sim_run(db, "prepare_draw", runner)


@router.post("/manual-sim/action/execute-draw")
def manual_sim_action_execute_draw(db: Session = Depends(get_db)):
    """
    T_00H — execute the global weekly draw at the simulated instant.

    Runs the production execute_weekly_draw (SDE pre-passes, all pool draws,
    refill) scoped to this session's users.  ``auto_pay_unpaid`` is False — payment
    is the developer's explicit choice at the due-date / grace events, never an
    implicit side-effect of the draw.
    """
    def runner(ms, sim_now):
        st     = ms._require_active(db)
        prefix = st.get("inject_prefix", "msim0000")
        res    = execute_weekly_draw(db, auto_pay_unpaid=False, user_prefix=prefix)
        return {
            "pools_drawn":        int(res.pools_drawn),
            "winners":            len(res.draw_results),
            "total_auto_paid":    int(res.total_auto_paid),
            "sde_draws":          int(res.sde_draws_this_week),
            "ext_draws":          int(res.ext_draws_this_week),
            "preventive_l3_draws": int(res.preventive_l3_draws_this_week),
            "accel_draws":        int(res.accel_draws_this_week),
            "paused_pools":       len(res.paused_pools),
            "skipped_pools":      len(res.skipped_pools),
            "draw_posture":       res.draw_posture,
        }

    return _manual_sim_run(db, "execute_draw", runner)


@router.post("/manual-sim/action/cleanup")
def manual_sim_action_cleanup(db: Session = Depends(get_db)):
    """
    T_05M — post-draw cleanup at the simulated instant.

    Resets weekly draw flags, releases the draw-engine lock and auto-settles
    referral-withdraw tokens (production post_draw_cleanup + auto_settle_referral_rw).
    Moves NO clock — after cleanup the developer uses jump-next to roll into the
    next cycle (landing on its DUE_DATE), keeping clock-moves and money-mutations
    strictly separate operations.
    """
    from app.services.draw import post_draw_cleanup
    from app.services.real_simulation import MassLoadInjector

    def runner(ms, sim_now):
        st       = ms._require_active(db)
        summary  = post_draw_cleanup(db)
        injector = MassLoadInjector(run_prefix=st.get("inject_prefix", "msim0000"))
        rw_settled = injector.auto_settle_referral_rw(db, week_num=int(st.get("cycle_num", 1)))
        return {"cleanup": summary, "rw_settled": rw_settled}

    return _manual_sim_run(db, "run_cleanup", runner)
