"""
Admin Data Engine  —  Phase 1
==============================

GET  /admin/users                 Advanced user list with filters + payment timestamps
GET  /admin/users/{user_id}       Comprehensive user profile (tokens, wins, history)
POST /admin/import/users          Bulk CSV user import
GET  /admin/tokens                Full token audit trail with filters
GET  /admin/export/users          Download users as CSV
GET  /admin/export/tokens         Download tokens as CSV

All endpoints require Admin JWT (inherited from router-level dependency).
"""

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserStatus, WeeklyPaymentStatus
from app.models.token import Token, TokenType, TokenStatus
from app.schemas.admin import (
    AdminUserListItem,
    AdminUserDetail,
    AdminTokenSummary,
    AdminTokenAudit,
    ImportSummaryResponse,
    ImportError,
)
from app.crud import user as crud_user
from app.core.security import require_admin_jwt

router = APIRouter(tags=["Admin · Data"], dependencies=[Depends(require_admin_jwt)])


# ── helpers ───────────────────────────────────────────────────────────────────

def _first_payment_map(db: Session) -> dict[int, datetime]:
    """
    Return {user_id: earliest_redeemed_at} for all users who have at least one
    burned Deposit token.  Single query — used by the user list endpoint.
    """
    rows = (
        db.query(Token.user_id, func.min(Token.redeemed_at))
        .filter(Token.type == TokenType.Deposit, Token.status == TokenStatus.Burned)
        .group_by(Token.user_id)
        .all()
    )
    return {uid: ts for uid, ts in rows if uid is not None}


def _build_list_item(user: User, first_payment_map: dict) -> dict:
    return {
        "id":                    user.id,
        "name":                  user.name,
        "mobile":                user.mobile,
        "username":              user.username,
        "status":                user.status,
        "current_level":         user.current_level,
        "current_pool_id":       user.current_pool_id,
        "weekly_payment_status": user.weekly_payment_status,
        "late_fees_inr":         user.late_fees_inr,
        "join_date":             user.join_date,
        "first_payment_at":      first_payment_map.get(user.id),
        "referred_by_user_id":   user.referred_by_user_id,
    }


# ── GET /admin/users ──────────────────────────────────────────────────────────

@router.get("/admin/users", response_model=list[AdminUserListItem])
def list_users_admin(
    status:          Optional[str] = Query(None, description="Active|Waitlist|Eliminated|Eliminated_Won"),
    current_pool_id: Optional[int] = Query(None),
    skip:            int           = Query(0, ge=0),
    limit:           int           = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Return all users with optional filters.
    Includes `first_payment_at` derived from their earliest burned Deposit token.
    """
    q = db.query(User)

    if status:
        try:
            q = q.filter(User.status == UserStatus(status))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Valid: Active, Waitlist, Eliminated, Eliminated_Won",
            )

    if current_pool_id is not None:
        q = q.filter(User.current_pool_id == current_pool_id)

    users = q.order_by(User.join_date).offset(skip).limit(limit).all()

    payment_map = _first_payment_map(db)
    return [_build_list_item(u, payment_map) for u in users]


# ── GET /admin/users/{user_id} ────────────────────────────────────────────────

@router.get("/admin/users/{user_id}", response_model=AdminUserDetail)
def get_user_admin(user_id: int, db: Session = Depends(get_db)):
    """
    Comprehensive user profile:
    - Full base data + first_payment_at
    - All tokens ever issued or redeemed (DEP / WIT / REF)
    - total_wins and total_won_inr derived from Withdraw tokens
    """
    user = crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    tokens = (
        db.query(Token)
        .filter(Token.user_id == user_id)
        .order_by(Token.created_at.desc())
        .all()
    )

    win_tokens = [t for t in tokens if t.type == TokenType.Withdraw]
    total_won  = sum(Decimal(str(t.value_inr)) for t in win_tokens)

    payment_map = _first_payment_map(db)

    token_summaries = [
        {
            "id":         t.id,
            "code":       t.code,
            "type":       t.type,
            "value_inr":  t.value_inr,
            "status":     t.status,
            "created_at": t.created_at,
            "redeemed_at":t.redeemed_at,
        }
        for t in tokens
    ]

    return {
        **_build_list_item(user, payment_map),
        "total_wins":    len(win_tokens),
        "total_won_inr": total_won,
        "tokens":        token_summaries,
    }


# ── POST /admin/import/users ──────────────────────────────────────────────────

@router.post("/admin/import/users", response_model=ImportSummaryResponse, status_code=201)
async def import_users_csv(
    file: UploadFile = File(..., description="CSV with columns: name, mobile, username (opt), referred_by_username (opt)"),
    db: Session = Depends(get_db),
):
    """
    Bulk-create users from a CSV upload.

    Required CSV columns : name, mobile
    Optional CSV columns  : username, referred_by_username

    Rows are skipped (not errored) when:
    - mobile already exists in the database
    - username is provided but already taken (a new one is auto-generated)

    Rows produce errors when:
    - name or mobile is blank
    - referred_by_username is given but resolves to no user
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")   # handles UTF-8 with BOM (Excel export)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader     = csv.DictReader(io.StringIO(text))
    headers    = [h.strip().lower() for h in (reader.fieldnames or [])]

    if "name" not in headers or "mobile" not in headers:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain at least 'name' and 'mobile' columns.",
        )

    created_count = 0
    skipped_count = 0
    errors: list[ImportError] = []

    for row_num, raw_row in enumerate(reader, start=2):   # row 1 = header
        # Normalise keys
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}

        name   = row.get("name",   "")
        mobile = row.get("mobile", "")

        if not name or not mobile:
            errors.append(ImportError(row=row_num, mobile=mobile or "—", reason="name and mobile are required"))
            continue

        # Skip existing mobiles
        if crud_user.get_user_by_mobile(db, mobile):
            skipped_count += 1
            continue

        # Resolve optional referred_by
        referred_id: int | None = None
        ref_username = row.get("referred_by_username", "")
        if ref_username:
            ref_user = crud_user.get_user_by_username(db, ref_username)
            if not ref_user:
                errors.append(ImportError(row=row_num, mobile=mobile, reason=f"referred_by_username '{ref_username}' not found"))
                continue
            referred_id = ref_user.id

        # Resolve username (may be blank; auto-generated if taken)
        username = row.get("username", "").strip() or None
        if username and crud_user.get_user_by_username(db, username):
            username = None   # fall back to auto-generate; don't error

        # Create user — Waitlist, Unpaid (no deposit token in bulk import)
        import random, string as _string
        def _gen() -> str:
            return "user_" + "".join(random.choices(_string.ascii_lowercase + _string.digits, k=7))

        final_username = username
        if not final_username:
            final_username = _gen()
            while crud_user.get_user_by_username(db, final_username):
                final_username = _gen()

        new_user = User(
            name=name,
            mobile=mobile,
            username=final_username,
            status=UserStatus.Waitlist,
            weekly_payment_status=WeeklyPaymentStatus.Unpaid,
            current_level=1,
            referred_by_user_id=referred_id,
            hashed_password=None,   # user must set password via app
        )
        db.add(new_user)
        try:
            db.commit()
            created_count += 1
        except Exception as exc:
            db.rollback()
            errors.append(ImportError(row=row_num, mobile=mobile, reason=f"DB error: {exc}"))

    return ImportSummaryResponse(
        total_rows=created_count + skipped_count + len(errors),
        created_count=created_count,
        skipped_count=skipped_count,
        errors=errors,
    )


# ── GET /admin/tokens ─────────────────────────────────────────────────────────

@router.get("/admin/tokens", response_model=list[AdminTokenAudit])
def list_tokens_admin(
    type:    Optional[str] = Query(None, description="Deposit|Withdraw|Referral"),
    status:  Optional[str] = Query(None, description="Active|Burned"),
    user_id: Optional[int] = Query(None, description="Filter by owning user"),
    skip:    int           = Query(0, ge=0),
    limit:   int           = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Full token audit trail.  Each row includes the owner username and the
    username of the user who redeemed it (if applicable).
    """
    # Build owner alias
    OwnerUser    = db.query(User).subquery()
    RedeemerUser = db.query(User).subquery()

    q = db.query(Token)

    if type:
        try:
            q = q.filter(Token.type == TokenType(type))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid type '{type}'.")

    if status:
        try:
            q = q.filter(Token.status == TokenStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status '{status}'.")

    if user_id is not None:
        q = q.filter(Token.user_id == user_id)

    tokens = q.order_by(Token.created_at.desc()).offset(skip).limit(limit).all()

    # Bulk-fetch usernames to avoid N+1
    user_ids = set()
    for t in tokens:
        if t.user_id:             user_ids.add(t.user_id)
        if t.redeemed_by_user_id: user_ids.add(t.redeemed_by_user_id)

    user_map: dict[int, User] = {}
    if user_ids:
        user_map = {
            u.id: u
            for u in db.query(User).filter(User.id.in_(user_ids)).all()
        }

    result = []
    for t in tokens:
        owner    = user_map.get(t.user_id)
        redeemer = user_map.get(t.redeemed_by_user_id)
        result.append({
            "id":                    t.id,
            "code":                  t.code,
            "type":                  t.type,
            "value_inr":             t.value_inr,
            "status":                t.status,
            "created_at":            t.created_at,
            "redeemed_at":           t.redeemed_at,
            "user_id":               t.user_id,
            "user_username":         owner.username    if owner    else None,
            "user_name":             owner.name        if owner    else None,
            "redeemed_by_user_id":   t.redeemed_by_user_id,
            "redeemed_by_username":  redeemer.username if redeemer else None,
        })
    return result


# ── GET /admin/export/users ───────────────────────────────────────────────────

@router.get("/admin/export/users")
def export_users_csv(db: Session = Depends(get_db)):
    """
    Download the complete Users table as a UTF-8 CSV.
    Filename: users_<timestamp>.csv
    """
    users = db.query(User).order_by(User.join_date).all()

    payment_map = _first_payment_map(db)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "mobile", "username", "status",
        "current_level", "current_pool_id", "weekly_payment_status",
        "late_fees_inr", "join_date", "first_payment_at", "referred_by_user_id",
    ])
    for u in users:
        writer.writerow([
            u.id, u.name, u.mobile, u.username, u.status.value,
            u.current_level, u.current_pool_id, u.weekly_payment_status.value,
            u.late_fees_inr, u.join_date.isoformat() if u.join_date else "",
            payment_map.get(u.id, "").isoformat() if isinstance(payment_map.get(u.id), datetime) else "",
            u.referred_by_user_id or "",
        ])

    output.seek(0)
    filename = f"users_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── GET /admin/export/tokens ──────────────────────────────────────────────────

@router.get("/admin/export/tokens")
def export_tokens_csv(db: Session = Depends(get_db)):
    """
    Download the complete Tokens table as a UTF-8 CSV (includes audit columns).
    Filename: tokens_<timestamp>.csv
    """
    tokens = db.query(Token).order_by(Token.created_at.desc()).all()

    # Bulk-load usernames
    user_ids = {t.user_id for t in tokens if t.user_id} | \
               {t.redeemed_by_user_id for t in tokens if t.redeemed_by_user_id}
    user_map: dict[int, User] = {}
    if user_ids:
        user_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "code", "type", "value_inr", "status",
        "user_id", "user_username", "user_name",
        "created_at", "redeemed_at",
        "redeemed_by_user_id", "redeemed_by_username",
    ])
    for t in tokens:
        owner    = user_map.get(t.user_id)
        redeemer = user_map.get(t.redeemed_by_user_id)
        writer.writerow([
            t.id, t.code, t.type.value, t.value_inr, t.status.value,
            t.user_id or "",
            owner.username    if owner    else "",
            owner.name        if owner    else "",
            t.created_at.isoformat()   if t.created_at   else "",
            t.redeemed_at.isoformat()  if t.redeemed_at  else "",
            t.redeemed_by_user_id or "",
            redeemer.username if redeemer else "",
        ])

    output.seek(0)
    filename = f"tokens_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
