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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, insert as sa_insert, text
from sqlalchemy.orm import Session

from app.core.config import DEPOSIT_AMOUNT_INR, NEW_POOL_INTAKE, POOL_CAPACITY
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

    # ── Auto-form pools ───────────────────────────────────────────────────────
    pools_formed = 0
    if body.auto_pool:
        # Step 1: fill existing pool vacancies before creating new pools.
        # This fixes any under-capacity active pools (e.g. after eliminations)
        # regardless of the AUTO_POOL_CREATION_ENABLED toggle state.
        fill_pool_vacancies(db)

        # Step 2: create new pools while ≥ NEW_POOL_INTAKE paid members remain.
        # Use manual_create_pool (ignores the toggle) so this dev tool works
        # whether auto-creation is ON or OFF.
        while True:
            new_pool = manual_create_pool(db)
            if not new_pool:
                break
            pools_formed += 1

    # ── Count remaining waitlist users ────────────────────────────────────────
    waitlist_remaining = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist)
        .count()
    )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    live_threshold = get_pool_threshold(db)
    if pools_formed:
        note = (
            f"{len(user_ids)} users + {len(user_ids)} DEP tokens created "
            f"(sequential join_dates, bcrypt passwords). "
            f"{pools_formed} pool(s) auto-formed. "
            f"{waitlist_remaining} users still on waitlist — "
            f"run POST /dev/force-draw to draw from the new pool(s)."
        )
    else:
        note = (
            f"{len(user_ids)} users + {len(user_ids)} DEP tokens created "
            f"(sequential join_dates, bcrypt passwords). "
            f"No pools formed yet (threshold: {live_threshold} paid waitlist users needed). "
            f"Call POST /admin/waitlist/check when ready."
        )

    return SimulateUsersResult(
        users_created=len(user_ids),
        dep_tokens_created=len(user_ids),
        prefix=prefix,
        pools_formed=pools_formed,
        waitlist_remaining=waitlist_remaining,
        elapsed_ms=elapsed_ms,
        note=note,
    )


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

_S_PAY: dict[int, tuple[Decimal, Decimal]] = {
    1: (Decimal("2500"), Decimal("2000")),
    2: (Decimal("2500"), Decimal("2000")),
    3: (Decimal("2500"), Decimal("2000")),
    4: (Decimal("5000"), Decimal("4000")),
    5: (Decimal("5000"), Decimal("4000")),
    6: (Decimal("10000"), Decimal("8000")),
}


# ── Request schema (strict validation) ───────────────────────────────────────

class AdvancedSimRequest(BaseModel):
    total_cycles: int = Field(
        ..., ge=1, le=1000,
        description="Number of consecutive weekly cycles to simulate (1–1000)",
    )
    late_fee_pct: float = Field(
        5.0, ge=0.0,
        description="Late fee as % of the ₹1,000 weekly installment",
    )
    late_users_ratio_pct: float = Field(
        2.0, ge=0.0, le=100.0,
        description="Percentage of active pool members defaulting on payment each cycle",
    )
    volatility_mode: bool = Field(
        False,
        description="Randomise weekly inflow when True; inject exactly 12 when False",
    )
    volatility_max_inflow: int = Field(
        100, ge=5,
        description="Upper bound for random weekly user injection (volatility mode only)",
    )


# ── Lightweight in-memory state objects ──────────────────────────────────────

@_dc
class _SU:
    """In-memory simulation user — never a SQLAlchemy ORM object."""
    sid:      int
    uname:    str
    mobile:   str
    joined:   datetime
    level:    int  = 1
    paid:     bool = False
    late:     bool = False
    pool_sid: int | None = None   # which _SP this user belongs to
    alive:    bool = True         # False = Eliminated_Won


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
        self._dep  = Decimal("0")
        self._pay  = Decimal("0")
        self._late = Decimal("0")

        self.logs: list[dict] = []
        self._ins:  list[dict] = []   # pending DB-insert buffer

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _mbrs(self, psid: int) -> list[_SU]:
        """Live active members of pool psid."""
        return [u for u in self._users.values()
                if u.pool_sid == psid and u.alive]

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
            "total_referrals_count":         0,
            "accumulated_referral_bonus_inr": Decimal("0"),
            "late_fees_inr":                 Decimal("0"),
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

        return n

    # ── Step B — Ratio Penalty Application ────────────────────────────────────

    def step_b(self, late_fee_pct: float, late_ratio_pct: float) -> int:
        """
        Randomly select late_ratio_pct% of active pool members, mark them
        Late (unpaid this week), and accumulate the virtual penalty.
        """
        pool_mbrs = [u for u in self._users.values()
                     if u.alive and u.pool_sid is not None]
        n_late    = int(len(pool_mbrs) * late_ratio_pct / 100.0)
        if not n_late:
            return 0
        late_sel  = random.sample(pool_mbrs, min(n_late, len(pool_mbrs)))
        fee_each  = _S_DEP * Decimal(str(late_fee_pct)) / Decimal("100")
        for u in late_sel:
            u.late      = True
            self._late += fee_each
        return len(late_sel)

    # ── Step C — Auto Billing ─────────────────────────────────────────────────

    def step_c(self):
        """Mark non-late active members Paid; clear late markers for next cycle."""
        for u in self._users.values():
            if u.alive and u.pool_sid is not None and not u.late:
                u.paid = True
        for u in self._users.values():
            u.late = False

    # ── Step D — Double-FIFO Refill + Condensation ────────────────────────────

    def step_d(self, ts: datetime) -> tuple[int, int]:
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
                uid       = self._wl.pop(0)         # oldest waitlist user (FIFO)
                u         = self._users[uid]
                u.pool_sid = pool.sid
                u.paid    = True
                u.level   = 1
                vac      -= 1
            if pool.paused and len(self._mbrs(pool.sid)) >= _S_CAP:
                pool.paused = False                  # restore Active if now full

        # ── Phase 2 ───────────────────────────────────────────────────────────
        while len(self._wl) >= _S_THR:
            pool = self._mkpool(ts)
            for _ in range(_S_CAP):
                if not self._wl:
                    break
                uid       = self._wl.pop(0)
                u         = self._users[uid]
                u.pool_sid = pool.sid
                u.paid    = True
                u.level   = 1

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
        For each Active pool:
          12 members → Smart Pairing draw (L1-3 vs L4-6; edge-case L1-3 only).
          < 12 members → status = Paused_Awaiting_Members; SKIP draw to
                         protect the L1-L3 / L4-L6 financial mathematics.
        """
        draws = new_pauses = 0

        for pool in sorted(
            [p for p in self._pools.values() if not p.dissolved and not p.paused],
            key=lambda p: p.sid,
        ):
            members = self._mbrs(pool.sid)

            # ── Safestop ──────────────────────────────────────────────────────
            if len(members) != _S_CAP:
                pool.paused = True
                new_pauses += 1
                self.n_paused += 1
                continue

            low  = [m for m in members if 1 <= m.level <= 3]
            high = [m for m in members if 4 <= m.level <= 6]

            if not high:                           # early-pool edge case (weeks 1-3)
                if len(low) < 2:
                    pool.paused = True; new_pauses += 1; self.n_paused += 1
                    continue
                w1, w2 = random.sample(low, 2)
            else:                                  # normal draw (pool has matured)
                if not low:
                    pool.paused = True; new_pauses += 1; self.n_paused += 1
                    continue
                w1 = random.choice(low)
                w2 = random.choice(high)

            # Issue payouts, eliminate winners
            for w in (w1, w2):
                _, net  = _S_PAY.get(w.level, (Decimal("2500"), Decimal("2000")))
                self._pay   += net
                w.alive      = False
                w.pool_sid   = None
                self.n_winners += 1

            # Advance all survivors +1 level (hard-capped at 6); reset payment flag
            winner_sids = {w1.sid, w2.sid}
            for m in members:
                if m.alive and m.sid not in winner_sids:
                    m.level = min(m.level + 1, 6)
                    m.paid  = False                # cleared for the next installment week

            draws += 1

        return draws, new_pauses

    # ── Per-cycle orchestrator ────────────────────────────────────────────────

    def run_cycle(self, cycle: int, req: AdvancedSimRequest,
                  base: datetime, hpw: str):
        ts = base + timedelta(weeks=cycle - 1)
        self.step_a(cycle, req.volatility_mode, req.volatility_max_inflow, base, hpw)
        self.step_b(req.late_fee_pct, req.late_users_ratio_pct)
        self.step_c()
        _, merges  = self.step_d(ts)
        _, pauses  = self.step_e()

        active_n = sum(1 for p in self._pools.values()
                       if not p.dissolved and not p.paused)
        self.logs.append({
            "week":           cycle,
            "active_pools":   active_n,
            "waitlist_count": len(self._wl),
            "pauses":         pauses,
            "merges":         merges,
        })

    # ── Response helpers ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        """
        final_virtual_liquidity_float = (total deposits + total late fees)
                                         − total winner payouts
        """
        return {
            "total_cycles_run":              len(self.logs),
            "total_simulated_users_created": self.n_created,
            "total_winners_drawn":           self.n_winners,
            "total_pools_auto_scaled":       self.n_scaled,
            "total_condensation_events":     self.n_condensed,
            "total_draw_pauses_triggered":   self.n_paused,
            "total_late_fees_collected_inr": float(self._late),
            "final_virtual_liquidity_float": float(
                self._dep + self._late - self._pay
            ),
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
        }

    finally:
        # GUARANTEED cleanup — executes even on unhandled exceptions / timeouts
        _sim_cleanup(db, upfx)
