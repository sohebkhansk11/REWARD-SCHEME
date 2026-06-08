import random
import string
from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy.orm import Session

from app.core.config import POOL_CAPACITY, LEVEL_LOW, LEVEL_HIGH, NET_PAYOUT_INR, PAYOUT_FEE_INR, BASE_PAYOUT_INR
from app.crud import token as crud_token, user as crud_user, pool as crud_pool
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.models.token import TokenType, TokenStatus
from app.schemas.token import TokenCreate
from app.schemas.user import UserUpdate
from app.schemas.pool import PoolUpdate


@dataclass
class WinnerResult:
    winner_id: int
    winner_username: str
    winner_level: int
    gross_payout_inr: Decimal
    fee_inr: Decimal
    net_payout_inr: Decimal
    withdraw_token_code: str
    replaced_by_user_id: int | None
    replaced_by_username: str | None


@dataclass
class DrawResult:
    pool_id: int
    pool_name: str
    winner_low_level: WinnerResult   # selected from Level 1–3
    winner_high_level: WinnerResult  # selected from Level 4–6


def _unique_withdraw_code(db: Session) -> str:
    while True:
        code = "WIT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not crud_token.get_token_by_code(db, code):
            return code


def _next_paid_waitlist_member(db: Session) -> User | None:
    """Return the earliest-joined paid Waitlist member, or None."""
    return (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .order_by(User.join_date)
        .first()
    )


def _process_winner(db: Session, winner: User, pool: Pool) -> WinnerResult:
    """
    For a single winner:
    1. Generate a Withdraw token for the net payout.
    2. Set status → Eliminated_Won and detach from pool.
    3. Replace with the next paid Waitlist member at Level 1.
    """
    code = _unique_withdraw_code(db)
    net = Decimal(str(NET_PAYOUT_INR))

    crud_token.create_token(
        db,
        TokenCreate(
            code=code,
            type=TokenType.Withdraw,
            value_inr=net,
            user_id=winner.id,
            status=TokenStatus.Active,
        ),
    )

    crud_user.update_user(
        db,
        winner.id,
        UserUpdate(status=UserStatus.Eliminated_Won, current_pool_id=None),
    )

    replacement = _next_paid_waitlist_member(db)
    if replacement:
        crud_user.update_user(
            db,
            replacement.id,
            UserUpdate(status=UserStatus.Active, current_pool_id=pool.id, current_level=1),
        )
    else:
        # No one waiting — pool shrinks by one
        crud_pool.update_pool(
            db, pool.id, PoolUpdate(total_members=max(0, pool.total_members - 1))
        )

    return WinnerResult(
        winner_id=winner.id,
        winner_username=winner.username,
        winner_level=winner.current_level,
        gross_payout_inr=Decimal(str(BASE_PAYOUT_INR)),
        fee_inr=Decimal(str(PAYOUT_FEE_INR)),
        net_payout_inr=net,
        withdraw_token_code=code,
        replaced_by_user_id=replacement.id if replacement else None,
        replaced_by_username=replacement.username if replacement else None,
    )


def run_dual_draw(db: Session, pool_id: int) -> DrawResult:
    """
    Dual-Draw Algorithm:
    - Pool must be Active with exactly POOL_CAPACITY members.
    - Winner 1: random pick from members at Level LEVEL_LOW (1–3).
    - Winner 2: random pick from members at Level LEVEL_HIGH (4–6).
    - Each winner receives a Withdraw token for NET_PAYOUT_INR.
    - Each winner is replaced by the next paid Waitlist member at Level 1.
    """
    pool: Pool | None = crud_pool.get_pool(db, pool_id)
    if not pool:
        raise ValueError(f"Pool {pool_id} not found")
    if pool.status != PoolStatus.Active:
        raise ValueError(f"Pool '{pool.name}' is not Active (status={pool.status.value})")

    members: list[User] = (
        db.query(User)
        .filter(User.current_pool_id == pool_id, User.status == UserStatus.Active)
        .all()
    )

    if len(members) != POOL_CAPACITY:
        raise ValueError(
            f"Pool '{pool.name}' has {len(members)} active members; need exactly {POOL_CAPACITY}"
        )

    low_pool = [m for m in members if LEVEL_LOW[0] <= m.current_level <= LEVEL_LOW[1]]
    high_pool = [m for m in members if LEVEL_HIGH[0] <= m.current_level <= LEVEL_HIGH[1]]

    if not low_pool:
        raise ValueError(f"No members at Level {LEVEL_LOW[0]}–{LEVEL_LOW[1]} in pool '{pool.name}'")
    if not high_pool:
        raise ValueError(f"No members at Level {LEVEL_HIGH[0]}–{LEVEL_HIGH[1]} in pool '{pool.name}'")

    winner_low = random.choice(low_pool)
    winner_high = random.choice(high_pool)

    # Process low-level winner first so their slot opens before the high-level
    # winner's replacement is pulled from the waitlist
    result_low = _process_winner(db, winner_low, pool)

    # Re-fetch pool after first replacement (total_members may have changed)
    db.refresh(pool)
    result_high = _process_winner(db, winner_high, pool)

    return DrawResult(
        pool_id=pool.id,
        pool_name=pool.name,
        winner_low_level=result_low,
        winner_high_level=result_high,
    )
