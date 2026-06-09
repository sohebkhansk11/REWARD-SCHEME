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
import string
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import insert as sa_insert, text
from sqlalchemy.orm import Session

from app.core.config import DEPOSIT_AMOUNT_INR
from app.core.dev_guard import require_dev_mode
from app.database import get_db
from app.models.pool import Pool, PoolStatus
from app.models.token import Token, TokenType, TokenStatus
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.services.draw import run_dual_draw
from app.services.waitlist import check_and_scale_waitlist

router = APIRouter(
    prefix="/dev",
    tags=["Developer Mode"],
    dependencies=[Depends(require_dev_mode)],
)

# Rows per executemany batch — keeps individual SQL statements a manageable size
_BULK_BATCH = 5_000

# Pre-computed deposit amount as Decimal to avoid repeated conversions
_DEPOSIT_DEC = Decimal(str(DEPOSIT_AMOUNT_INR))


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
    Execute the Sunday dual-draw immediately on the specified pool
    (or the first Active pool when pool_id is omitted).

    auto_pay_installments=False (default):
      Unpaid members are marked Paid directly — no token records created.

    auto_pay_installments=True:
      A real Burned DEP token is created per unpaid member and logged in the
      Tokens table.  This keeps Cash Inflow statistics accurate.
    """
    # ── Resolve target pool ───────────────────────────────────────────────────
    if body.pool_id:
        pool = db.query(Pool).filter(Pool.id == body.pool_id).first()
        if not pool:
            raise HTTPException(status_code=404, detail=f"Pool {body.pool_id} not found.")
    else:
        pool = db.query(Pool).filter(Pool.status == PoolStatus.Active).first()
        if not pool:
            raise HTTPException(status_code=404, detail="No active pools found.")

    # ── Pay unpaid members ────────────────────────────────────────────────────
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
        # Create real Burned DEP tokens so Tokens table reflects cash inflow
        tokens_made = _simulate_installment_payments(db, unpaid, pool.id)
    else:
        # Fast-path: set payment flag directly without token records
        for member in unpaid:
            member.weekly_payment_status = WeeklyPaymentStatus.Paid
        if unpaid:
            db.commit()

    # ── Run draw ──────────────────────────────────────────────────────────────
    try:
        result = run_dual_draw(db, pool.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    w = result
    return {
        "pool_id":                    w.pool_id,
        "pool_name":                  w.pool_name,
        "auto_paid_count":            auto_paid,
        "simulated_tokens_created":   tokens_made,
        "winner_1": {
            "username":       w.winner_1.winner_username,
            "level":          w.winner_1.winner_level,
            "net_payout_inr": float(w.winner_1.net_payout_inr),
            "withdraw_token": w.winner_1.withdraw_token_code,
            "replaced_by":    w.winner_1.replaced_by_username,
        },
        "winner_2": {
            "username":       w.winner_2.winner_username,
            "level":          w.winner_2.winner_level,
            "net_payout_inr": float(w.winner_2.net_payout_inr),
            "withdraw_token": w.winner_2.withdraw_token_code,
            "replaced_by":    w.winner_2.replaced_by_username,
        },
        "edge_case_used": w.edge_case_used,
        "dev_note": (
            "Real DEP tokens created for each unpaid member (auto_pay_installments=True)."
            if body.auto_pay_installments else
            "Payment status set directly without token records (auto_pay_installments=False)."
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
    n_users = 24 + 2 * N

    # ── 1. Bulk-insert dummy users ────────────────────────────────────────────
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
            "username":              f"{prefix}{i + 1}",
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

    # ── 2. Trigger pool creation ──────────────────────────────────────────────
    new_pool = check_and_scale_waitlist(db)
    if not new_pool:
        _cleanup_dev_users(db, prefix, pool_id=None)
        raise HTTPException(
            status_code=500,
            detail=(
                "Waitlist scaling did not trigger. "
                "Combined real + fake waitlist count may still be below the 24-user threshold."
            ),
        )

    pool_id = new_pool.id

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

    # ── Build user rows ───────────────────────────────────────────────────────
    # Pre-generate unique referral codes for all dev users in Python to avoid
    # individual DB round-trips inside the bulk insert.
    _ref_codes: set[str] = set()
    while len(_ref_codes) < count:
        _ref_codes.update(
            "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            for _ in range(count - len(_ref_codes))
        )
    _ref_list = list(_ref_codes)

    user_rows = [
        {
            "name":                  f"DevUser-{i + 1}",
            "mobile":                f"+99{ts:010d}{nonce:06d}{i:05d}",
            "username":              f"{prefix}{i + 1}",
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
        while True:
            new_pool = check_and_scale_waitlist(db)
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

    if pools_formed:
        note = (
            f"{len(user_ids)} users + {len(user_ids)} DEP tokens created. "
            f"{pools_formed} pool(s) auto-formed. "
            f"{waitlist_remaining} users still on waitlist — "
            f"run POST /dev/force-draw to draw from the new pool(s)."
        )
    else:
        note = (
            f"{len(user_ids)} users + {len(user_ids)} DEP tokens created. "
            f"No pools formed yet (need ≥24 total paid waitlist users). "
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
