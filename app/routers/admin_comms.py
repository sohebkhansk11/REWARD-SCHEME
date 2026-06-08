"""
Admin Communications Router  (/admin/broadcast)
================================================
Sends a message to a target audience via WhatsApp and/or Telegram.

Audience types:
  all       — every non-eliminated user (Active + Waitlist + Winners)
  active    — all Active pool members
  waitlist  — users with status = Waitlist
  winners   — users with status = Eliminated_Won
  pool      — members of a specific pool (requires pool_id param)

Channels:
  whatsapp  — via Twilio or Meta Cloud API (see app/services/broadcast.py)
  telegram  — via Telegram Bot API (requires user.telegram_chat_id to be set)

All HTTP calls are made concurrently, so latency scales with the slowest
individual message, not with the number of recipients.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_admin_jwt
from app.database import get_db
from app.models.user import User, UserStatus
from app.schemas.admin import BroadcastRequest, BroadcastResponse, BroadcastChannelResult
from app.services import broadcast as svc_broadcast

router = APIRouter(tags=["Admin · Communications"], dependencies=[Depends(require_admin_jwt)])


def _resolve_audience(db: Session, req: BroadcastRequest) -> list[User]:
    """Return the list of User objects that match the requested audience."""
    q = db.query(User)

    if req.audience_type == "all":
        q = q.filter(User.status.in_([
            UserStatus.Active, UserStatus.Waitlist, UserStatus.Eliminated_Won,
        ]))

    elif req.audience_type == "active":
        q = q.filter(User.status == UserStatus.Active)

    elif req.audience_type == "waitlist":
        q = q.filter(User.status == UserStatus.Waitlist)

    elif req.audience_type == "winners":
        q = q.filter(User.status == UserStatus.Eliminated_Won)

    elif req.audience_type == "pool":
        if req.pool_id is None:
            raise HTTPException(
                status_code=400,
                detail="pool_id is required when audience_type is 'pool'.",
            )
        q = q.filter(
            User.current_pool_id == req.pool_id,
            User.status == UserStatus.Active,
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown audience_type '{req.audience_type}'.")

    return q.all()


@router.post("/admin/broadcast", response_model=BroadcastResponse)
async def broadcast_message(body: BroadcastRequest, db: Session = Depends(get_db)):
    """
    Dispatch a message to the target audience via the specified channel(s).

    Notes:
    - `telegram` channel requires users to have `telegram_chat_id` set.
      Users without it are automatically skipped and counted in `skipped`.
    - `whatsapp` uses the mobile number already stored on each user.
    - All sends run concurrently — a 500-user broadcast typically completes
      in under a second (limited by the slowest external API call, not count).
    - WhatsApp requires either Twilio or Meta credentials in env vars.
      Telegram requires TELEGRAM_BOT_TOKEN in env vars.
      Missing credentials produce a `skipped` result, not a 500 error.
    """
    users = _resolve_audience(db, body)

    if not users:
        return BroadcastResponse(
            audience_type=body.audience_type,
            total_targeted=0,
            channels={ch: BroadcastChannelResult(sent=0, failed=0, skipped=0) for ch in body.channels},
        )

    raw_results = await svc_broadcast.dispatch(
        users=users,
        message=body.message,
        channels=body.channels,
    )

    return BroadcastResponse(
        audience_type=body.audience_type,
        total_targeted=len(users),
        channels={
            ch: BroadcastChannelResult(**raw_results[ch])
            for ch in body.channels
            if ch in raw_results
        },
    )
