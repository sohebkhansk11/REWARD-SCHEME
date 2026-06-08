import random
import string
from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy.orm import Session

from app.core.config import POOL_CAPACITY, LEVEL_LOW, LEVEL_HIGH, LEVEL_PAYOUTS, PAYOUT_FEE_INR, REFERRAL_REWARD_INR
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


def _unique_token_code(db: Session, prefix: str) -> str:
    while True:
        code = prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not crud_token.get_token_by_code(db, code):
            return code


def _next_paid_waitlist_member(db: Session) -> User | None:
    return (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .order_by(User.join_date)
        .first()
    )


def _issue_referral_token(db: Session, new_active_user: User) -> None:
    """If new_active_user was referred, generate a ₹250 REF token for the referrer."""
    if not new_active_user.referred_by_user_id:
        return
    code = _unique_token_code(db, "REF-")
    crud_token.create_token(
        db,
        TokenCreate(
            code=code,
            type=TokenType.Referral,
            value_inr=Decimal(str(REFERRAL_REWARD_INR)),
            user_id=new_active_user.referred_by_user_id,
            status=TokenStatus.Active,
        ),
    )


def _process_winner(db: Session, winner: User, pool: Pool) -> WinnerResult:
    """
    1. Generate level-based Withdraw token for the winner.
    2. Set winner status → Eliminated_Won, detach from pool.
    3. Pull next paid Waitlist member as replacement at Level 1.
    4. Issue referral token for replacement's referrer (if any).
    """
    gross, net = LEVEL_PAYOUTS.get(winner.current_level, (2500, 2000))
    gross_d = Decimal(str(gross))
    net_d = Decimal(str(net))
    fee_d = Decimal(str(PAYOUT_FEE_INR))

    code = _unique_token_code(db, "WIT-")
    crud_token.create_token(
        db,
        TokenCreate(
            code=code,
            type=TokenType.Withdraw,
            value_inr=net_d,
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
        db.refresh(replacement)
        _issue_referral_token(db, replacement)
    else:
        crud_pool.update_pool(
            db, pool.id, PoolUpdate(total_members=max(0, pool.total_members - 1))
        )

    return WinnerResult(
        winner_id=winner.id,
        winner_username=winner.username,
        winner_level=winner.current_level,
        gross_payout_inr=gross_d,
        fee_inr=fee_d,
        net_payout_inr=net_d,
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
    - Each winner receives a Withdraw token sized to their level.
    - Each winner is replaced by the next paid Waitlist member at Level 1.
    - After both draws: surviving original members advance one level (max 6).
    - After both draws: all active pool members reset to weekly_payment_status=Unpaid.
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

    # Snapshot the original member IDs before any mutations
    original_ids = {m.id for m in members}
    winner_ids = {winner_low.id, winner_high.id}

    result_low = _process_winner(db, winner_low, pool)
    db.refresh(pool)
    result_high = _process_winner(db, winner_high, pool)

    # ── Post-draw maintenance ────────────────────────────────────────────────
    # 1. Advance surviving original members by one level (capped at 6).
    # 2. Reset weekly payment for ALL currently active pool members (new week starts).
    surviving_ids = original_ids - winner_ids
    for member_id in surviving_ids:
        member = crud_user.get_user(db, member_id)
        if member and member.status == UserStatus.Active and member.current_pool_id == pool_id:
            crud_user.update_user(
                db,
                member_id,
                UserUpdate(
                    current_level=min(member.current_level + 1, 6),
                    weekly_payment_status=WeeklyPaymentStatus.Unpaid,
                ),
            )

    # Reset payment for replacement members too — new week begins after the draw
    for rep_id in filter(None, [result_low.replaced_by_user_id, result_high.replaced_by_user_id]):
        member = crud_user.get_user(db, rep_id)
        if member and member.status == UserStatus.Active:
            crud_user.update_user(
                db, rep_id, UserUpdate(weekly_payment_status=WeeklyPaymentStatus.Unpaid)
            )

    return DrawResult(
        pool_id=pool.id,
        pool_name=pool.name,
        winner_low_level=result_low,
        winner_high_level=result_high,
    )
