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
  POST /dev/force-draw        Run the Sunday draw immediately on any pool
  POST /dev/simulate-cycle    Generate dummy users + run N consecutive draws
"""

import random
import string
import time
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dev_guard import require_dev_mode
from app.database import get_db
from app.models.pool import Pool, PoolStatus
from app.models.token import Token
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.services.draw import run_dual_draw
from app.services.waitlist import check_and_scale_waitlist

router = APIRouter(
    prefix="/dev",
    tags=["Developer Mode"],
    dependencies=[Depends(require_dev_mode)],
)


# ── Request / response schemas ─────────────────────────────────────────────────

class ForceDrawRequest(BaseModel):
    pool_id: Optional[int] = Field(
        None,
        description="Pool to draw on. Defaults to the first active pool.",
    )


class SimulateCycleRequest(BaseModel):
    n_cycles:  int  = Field(3, ge=1, le=12, description="Number of weekly draws to simulate (1–12)")
    cleanup:   bool = Field(True,  description="Delete all generated dev users and tokens after the run")


class DrawTrace(BaseModel):
    cycle:         int
    winner_1:      str
    winner_2:      str
    level_1:       int
    level_2:       int
    payout_1_inr:  float
    payout_2_inr:  float
    edge_case:     bool


class SimulateResult(BaseModel):
    n_requested:       int
    n_executed:        int
    users_created:     int
    pool_id:           Optional[int]
    draws:             list[DrawTrace]
    total_paid_out_inr: float
    cleanup_done:      bool


# ── POST /dev/force-draw ───────────────────────────────────────────────────────

@router.post("/force-draw")
def force_draw(body: ForceDrawRequest, db: Session = Depends(get_db)):
    """
    Execute the Sunday dual-draw immediately on the specified pool
    (or the first active pool if pool_id is omitted).

    Useful for testing the draw logic without waiting for Sunday.
    """
    if body.pool_id:
        pool = db.query(Pool).filter(Pool.id == body.pool_id).first()
        if not pool:
            raise HTTPException(status_code=404, detail=f"Pool {body.pool_id} not found.")
    else:
        pool = db.query(Pool).filter(Pool.status == PoolStatus.Active).first()
        if not pool:
            raise HTTPException(status_code=404, detail="No active pools found.")

    # Before drawing, ensure members are marked Paid so the draw doesn't fail
    # (in a real Sunday run, payments are verified beforehand; this is dev mode)
    unpaid = (
        db.query(User)
        .filter(
            User.current_pool_id == pool.id,
            User.status == UserStatus.Active,
            User.weekly_payment_status == WeeklyPaymentStatus.Unpaid,
        )
        .all()
    )
    auto_paid = len(unpaid)
    for member in unpaid:
        member.weekly_payment_status = WeeklyPaymentStatus.Paid
    if unpaid:
        db.commit()

    try:
        result = run_dual_draw(db, pool.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    w = result
    return {
        "pool_id":        w.pool_id,
        "pool_name":      w.pool_name,
        "auto_paid_count": auto_paid,
        "winner_1": {
            "username":        w.winner_1.winner_username,
            "level":           w.winner_1.winner_level,
            "net_payout_inr":  float(w.winner_1.net_payout_inr),
            "withdraw_token":  w.winner_1.withdraw_token_code,
            "replaced_by":     w.winner_1.replaced_by_username,
        },
        "winner_2": {
            "username":        w.winner_2.winner_username,
            "level":           w.winner_2.winner_level,
            "net_payout_inr":  float(w.winner_2.net_payout_inr),
            "withdraw_token":  w.winner_2.withdraw_token_code,
            "replaced_by":     w.winner_2.replaced_by_username,
        },
        "edge_case_used": w.edge_case_used,
        "dev_note": "Unpaid members were auto-marked Paid before the draw.",
    }


# ── POST /dev/simulate-cycle ───────────────────────────────────────────────────

@router.post("/simulate-cycle", response_model=SimulateResult)
def simulate_cycle(body: SimulateCycleRequest, db: Session = Depends(get_db)):
    """
    Full end-to-end simulation:
      1. Generate 24 + 2×N dummy users (all Waitlist / Paid).
      2. Trigger waitlist auto-scaling → creates a new pool of 12.
      3. For each of the N cycles:
           a. Mark all pool members Paid.
           b. Run the dual-draw.
           c. Record winners, payouts, level progression.
      4. Optionally delete all generated users and their tokens (cleanup=True).

    Returns a full trace of every draw for inspection.
    """
    N = body.n_cycles

    # ── 1. Create dummy users ─────────────────────────────────────────────────
    ts      = int(time.time())
    prefix  = f"dev_sim_{ts}_"
    n_users = 24 + 2 * N
    created = []

    for i in range(n_users):
        # Use +999 prefix to distinguish from real mobile numbers
        mobile = f"+999{ts % 1_000_000:06d}{i:04d}"
        # Ensure uniqueness in the same second
        while db.query(User).filter(User.mobile == mobile).first():
            mobile += "0"

        username = f"{prefix}{i + 1}"
        user = User(
            name=f"SimUser-{ts % 10000}-{i + 1}",
            mobile=mobile,
            username=username,
            status=UserStatus.Waitlist,
            weekly_payment_status=WeeklyPaymentStatus.Paid,
            current_level=1,
            hashed_password=None,
        )
        db.add(user)
        created.append(username)

    db.commit()

    # ── 2. Trigger pool creation ──────────────────────────────────────────────
    new_pool = check_and_scale_waitlist(db)
    if not new_pool:
        # Cleanup and bail — this should not happen in a fresh DB, but be safe
        _cleanup_dev_users(db, prefix)
        raise HTTPException(
            status_code=500,
            detail="Waitlist scaling did not trigger. Ensure no existing waitlist users exceed the threshold.",
        )

    pool_id = new_pool.id

    # ── 3. Run N draw cycles ──────────────────────────────────────────────────
    traces:     list[DrawTrace] = []
    n_executed  = 0
    total_paid  = 0.0

    for cycle in range(1, N + 1):
        # Mark all active members Paid
        members = (
            db.query(User)
            .filter(
                User.current_pool_id == pool_id,
                User.status == UserStatus.Active,
            )
            .all()
        )
        if not members:
            break  # pool is exhausted

        for m in members:
            m.weekly_payment_status = WeeklyPaymentStatus.Paid
        db.commit()

        try:
            result = run_dual_draw(db, pool_id)
        except ValueError:
            break   # draw failed (e.g., pool too small) — stop here

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
        _cleanup_dev_users(db, prefix)
        cleanup_done = True

    return SimulateResult(
        n_requested=N,
        n_executed=n_executed,
        users_created=n_users,
        pool_id=None if cleanup_done else pool_id,
        draws=traces,
        total_paid_out_inr=round(total_paid, 2),
        cleanup_done=cleanup_done,
    )


# ── cleanup helper ─────────────────────────────────────────────────────────────

def _cleanup_dev_users(db: Session, prefix: str) -> None:
    """Delete all tokens and users whose username starts with `prefix`."""
    dev_users = db.query(User).filter(User.username.like(f"{prefix}%")).all()
    if not dev_users:
        return

    dev_ids = [u.id for u in dev_users]

    # Null out FK references before deleting to avoid constraint errors
    (
        db.query(Token)
        .filter(Token.user_id.in_(dev_ids))
        .update({"user_id": None, "redeemed_by_user_id": None}, synchronize_session=False)
    )
    (
        db.query(Token)
        .filter(Token.redeemed_by_user_id.in_(dev_ids))
        .update({"redeemed_by_user_id": None}, synchronize_session=False)
    )
    db.commit()

    # Now delete users
    db.query(User).filter(User.id.in_(dev_ids)).delete(synchronize_session=False)
    db.commit()
