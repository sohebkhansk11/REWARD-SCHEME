from sqlalchemy.orm import Session

from app.core.config import WAITLIST_TRIGGER, NEW_POOL_INTAKE
from app.crud import user as crud_user, pool as crud_pool
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.pool import Pool, PoolStatus
from app.schemas.pool import PoolCreate, PoolUpdate
from app.schemas.user import UserUpdate
from app.services.draw import _issue_referral_token, _credit_referral_bonus


def _next_pool_name(db: Session) -> str:
    """Generate Pool A, Pool B, …, Pool Z, Pool AA, … based on existing count."""
    count = db.query(Pool).count()
    letters = ""
    n = count
    while True:
        letters = chr(65 + n % 26) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return f"Pool {letters}"


def check_and_scale_waitlist(db: Session) -> Pool | None:
    """
    If there are at least WAITLIST_TRIGGER paid Waitlist members, create a new
    pool and move the earliest NEW_POOL_INTAKE members into it at Level 1.

    Returns the newly created Pool, or None if the threshold wasn't met.
    """
    paid_waitlist: list[User] = (
        db.query(User)
        .filter(User.status == UserStatus.Waitlist, User.weekly_payment_status == WeeklyPaymentStatus.Paid)
        .order_by(User.join_date)
        .all()
    )

    if len(paid_waitlist) < WAITLIST_TRIGGER:
        return None

    pool_name = _next_pool_name(db)
    new_pool = crud_pool.create_pool(
        db,
        PoolCreate(name=pool_name, status=PoolStatus.Active, total_members=NEW_POOL_INTAKE),
    )

    for member in paid_waitlist[:NEW_POOL_INTAKE]:
        crud_user.update_user(
            db,
            member.id,
            UserUpdate(status=UserStatus.Active, current_pool_id=new_pool.id, current_level=1),
        )
        db.refresh(member)
        # Rule 39: credit referral bonus NOW — at Active pool entry, not at registration.
        if member.referred_by_user_id:
            _credit_referral_bonus(db, member.referred_by_user_id)
        _issue_referral_token(db, member)   # no-op kept for backward compat

    db.commit()   # flush the referral bonus updates
    return new_pool
