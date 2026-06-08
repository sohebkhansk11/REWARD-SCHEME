import random
import string
from decimal import Decimal
from sqlalchemy.orm import Session

from app.core.config import DEPOSIT_AMOUNT_INR
from app.crud import token as crud_token, user as crud_user
from app.models.token import TokenType, TokenStatus
from app.models.user import UserStatus, WeeklyPaymentStatus
from app.schemas.token import TokenCreate, TokenUpdate
from app.schemas.user import UserUpdate


def _make_code(token_type: TokenType) -> str:
    prefix = {TokenType.Deposit: "DEP", TokenType.Withdraw: "WIT", TokenType.Referral: "REF"}[token_type]
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{suffix}"


def admin_generate_token(
    db: Session,
    token_type: TokenType,
    value_inr: Decimal,
    user_id: int | None = None,
):
    """Admin creates a new token with a unique auto-generated code."""
    code = _make_code(token_type)
    while crud_token.get_token_by_code(db, code):
        code = _make_code(token_type)

    return crud_token.create_token(
        db,
        TokenCreate(code=code, type=token_type, value_inr=value_inr, user_id=user_id),
    )


def redeem_deposit_token(db: Session, code: str, user_id: int):
    """
    User redeems a Deposit token.

    Rules:
    - Token must be Active, type Deposit, and face value = ₹DEPOSIT_AMOUNT_INR.
    - User must not be Eliminated.
    - Marks user's weekly_payment_status = Paid.
    - Moves a bare-registered user (not yet Active) into Waitlist.
    - Burns the token.

    Returns (token, user).
    """
    token = crud_token.get_token_by_code(db, code)
    if not token:
        raise ValueError("Token not found")
    if token.status != TokenStatus.Active:
        raise ValueError("Token has already been used")
    if token.type != TokenType.Deposit:
        raise ValueError("Only Deposit tokens can be redeemed here")
    if Decimal(str(token.value_inr)) != Decimal(str(DEPOSIT_AMOUNT_INR)):
        raise ValueError(f"Token face value must be ₹{DEPOSIT_AMOUNT_INR}")

    user = crud_user.get_user(db, user_id)
    if not user:
        raise ValueError("User not found")
    if user.status in (UserStatus.Eliminated, UserStatus.Eliminated_Won):
        raise ValueError("Eliminated users cannot redeem tokens")
    if user.weekly_payment_status == WeeklyPaymentStatus.Paid:
        raise ValueError("User has already paid for this week")

    # Burn the token and assign to user
    crud_token.update_token(db, token.id, TokenUpdate(user_id=user_id, status=TokenStatus.Burned))

    # Determine new user status: nudge unclassified users to Waitlist
    new_status = user.status if user.status in (UserStatus.Active, UserStatus.Waitlist) else UserStatus.Waitlist
    crud_user.update_user(
        db,
        user_id,
        UserUpdate(weekly_payment_status=WeeklyPaymentStatus.Paid, status=new_status),
    )

    db.refresh(token)
    db.refresh(user)
    return token, user
