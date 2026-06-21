# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
Admin — Master Pool Re-assessment Manager Router
================================================
REST endpoints backing the "Pool Re-assessment" review panel in the Admin
dashboard.  They expose the verdict produced by the VIRTUAL PRE-DEPLOYMENT
INTEGRITY GATE (app/services/pool_reassessor.py) and let an admin clear a HOLD.

The re-assessor runs at T-2H (STEP 8b of draw preparation): it virtually
dissolves every pool, projects the full week's winner set, cross-verifies the
"purity of the draw" against five financial-grade checks, and persists a
ReassessmentReport row.  On HOLD the real draw is refused at T-0H until an admin
acts here (locked decision #1 — hold + propose corrected plan for password
approval).

Endpoint map
------------
  GET  /admin/reassessment/{week_id}          — latest report for the week (full, deserialized)
  GET  /admin/reassessment/{week_id}/history  — every report row for the week (audit trail)
  POST /admin/reassessment/{week_id}/approve  — clear the HOLD (password-gated)

Two ways to clear a HOLD (the approve endpoint):
  • RE-ASSESS (default, `override=false`): the admin has fixed the underlying
    issue (e.g. re-ran preparation, rebalanced, topped up float).  We run a FRESH
    assessment on the CURRENT data and append a new report.  The hold clears ONLY
    if that fresh report is PASS — i.e. the data must actually support deployment.
    This is the safe path: approval is not a rubber stamp, it is re-verification.
  • OVERRIDE (`override=true`): the admin explicitly ACCEPTS the risk and clears
    the hold as-prepared (e.g. they judge a purity/level diagnostic acceptable for
    this week).  Requires a non-empty admin_note justifying the override.  Marks
    the current report approved=True so the T-0H gate lets the prepared draw run.

Security model:
  - Router-level: require_admin_jwt (JWT must be present and valid).
  - approve: admin_password verified against the stored bcrypt hash before any
    mutation — same pattern as admin_financial_config.py.

This router NEVER auto-mutates token / pool / member state.  Operational fixes
(deferring SDE, re-running preparation, admitting L1 members, topping up float)
are applied by the admin through the existing controls; this router only governs
the verdict + the human-in-the-loop approval of it.
"""
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import require_admin_jwt
from app.database import get_db

router = APIRouter(
    prefix="/admin/reassessment",
    tags=["Admin — Pool Re-assessment"],
    dependencies=[Depends(require_admin_jwt)],
)


# ── Shared admin-password verifier (same pattern as admin_financial_config) ────

def _verify_admin_password(db: Session, admin_username: str, admin_password: str) -> None:
    """Verify the supplied password against the stored admin bcrypt hash.
    Raises HTTP 401 on mismatch.  Always runs a bcrypt check (dummy hash if the
    admin row is missing) to prevent timing-based username enumeration."""
    from app.core.security import verify_admin_password
    if not verify_admin_password(db, admin_username, admin_password):
        raise HTTPException(
            status_code=401,
            detail="Admin password verification failed. The re-assessment HOLD was NOT changed.",
        )


# ── Serialization ──────────────────────────────────────────────────────────────

def _loads(s):
    """Best-effort JSON decode of a Text column; returns None on empty/garbage."""
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s   # surface the raw string rather than hide a decode problem


def _serialize(rep) -> dict:
    """Full deserialized view of one ReassessmentReport row for the dashboard."""
    failed_hard = [name for name, ok in (
        ("float",     rep.float_pass),
        ("pyramid",   rep.pyramid_pass),
        ("reconcile", rep.reconcile_pass),
    ) if not ok]
    is_active_hold = (rep.verdict == "HOLD") and (not bool(rep.approved))
    return {
        "id":                   rep.id,
        "week_id":              rep.week_id,
        "verdict":              rep.verdict,
        "is_active_hold":       is_active_hold,
        "run_at":               rep.run_at.isoformat() if rep.run_at else None,
        "gates": {
            "purity_pass":        bool(rep.purity_pass),
            "level_advance_pass": bool(rep.level_advance_pass),
            "float_pass":         bool(rep.float_pass),
            "pyramid_pass":       bool(rep.pyramid_pass),
            "reconcile_pass":     bool(rep.reconcile_pass),
        },
        "failed_hard_gates":    failed_hard,
        "financials": {
            "projected_payout_inr": rep.projected_payout_inr,
            "available_float_inr":  rep.available_float_inr,
            "net_float_inr":        rep.net_float_inr,
            "headroom_inr":         (rep.available_float_inr or 0) - (rep.projected_payout_inr or 0),
        },
        "member_pyramid":       _loads(rep.member_pyramid_json) or {},
        "winner_pyramid":       _loads(rep.winner_pyramid_json) or {},
        "audit":                _loads(rep.audit_json) or {},
        "corrected_plan":       _loads(rep.corrected_plan_json) or [],
        "approval": {
            "approved":     bool(rep.approved),
            "approved_by":  rep.approved_by,
            "approved_at":  rep.approved_at.isoformat() if rep.approved_at else None,
            "admin_note":   rep.admin_note,
        },
        "created_at":           rep.created_at.isoformat() if rep.created_at else None,
    }


# ── Request models ─────────────────────────────────────────────────────────────

class ApproveReassessmentRequest(BaseModel):
    admin_password: str  = Field(..., description="Admin password for verification")
    override:       bool = Field(
        False,
        description="False (default) = re-assess on current data; clears the hold "
                    "ONLY if the fresh verdict is PASS.  True = explicitly accept the "
                    "risk and clear the hold as-prepared (requires admin_note).",
    )
    admin_note: str | None = Field(
        None,
        description="Reviewer note.  REQUIRED when override=true (justification for "
                    "the risk-accepted override); optional otherwise.",
        max_length=2000,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET — latest report for a week
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/{week_id}")
def get_latest_reassessment(week_id: str, db: Session = Depends(get_db)):
    """Latest re-assessment report for ``week_id`` (full, deserialized).
    Returns ``{"exists": false}`` if the week has not been assessed yet — the
    panel renders an empty state rather than erroring."""
    from app.services.pool_reassessor import latest_report
    rep = latest_report(db, week_id)
    if rep is None:
        return {"exists": False, "week_id": week_id, "report": None}
    return {"exists": True, "week_id": week_id, "report": _serialize(rep)}


# ══════════════════════════════════════════════════════════════════════════════
# GET — full history for a week (audit trail; re-runs append rows)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/{week_id}/history")
def get_reassessment_history(week_id: str, db: Session = Depends(get_db)):
    """Every report row for ``week_id``, newest first — the full decision trail
    (an approval/re-assess appends rows rather than overwriting)."""
    from app.models.reassessment_report import ReassessmentReport
    rows = (
        db.query(ReassessmentReport)
        .filter(ReassessmentReport.week_id == week_id)
        .order_by(ReassessmentReport.id.desc())
        .all()
    )
    return {"week_id": week_id, "count": len(rows), "reports": [_serialize(r) for r in rows]}


# ══════════════════════════════════════════════════════════════════════════════
# POST — approve / clear a HOLD (password-gated)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{week_id}/approve")
def approve_reassessment(
    week_id: str,
    body: ApproveReassessmentRequest,
    db: Session = Depends(get_db),
    admin_username: str = Depends(require_admin_jwt),
):
    """
    Clear the active HOLD for ``week_id`` (password-gated; locked decision #1).

    See the module docstring for the two modes.  In both cases the admin password
    is verified first.  Returns the resulting (possibly new) report and whether
    the hold is now cleared.
    """
    from app.services.pool_reassessor import (
        latest_report, run_reassessment, persist_report,
    )

    # 1) authenticate the mutation
    _verify_admin_password(db, admin_username, body.admin_password)

    # 2) there must be an active hold to act on
    rep = latest_report(db, week_id)
    if rep is None:
        raise HTTPException(status_code=404, detail=f"No re-assessment report exists for week {week_id}.")
    if rep.verdict != "HOLD" or bool(rep.approved):
        # Nothing to clear — the latest verdict is already deployable.  Idempotent.
        return {
            "status":     "no_active_hold",
            "week_id":    week_id,
            "cleared":    True,
            "report":     _serialize(rep),
        }

    now = datetime.now(timezone.utc)

    # 3a) OVERRIDE — accept the risk and clear the prepared result as-is.
    if body.override:
        note = (body.admin_note or "").strip()
        if not note:
            raise HTTPException(
                status_code=422,
                detail="override=true requires a non-empty admin_note justifying the risk-accepted override.",
            )
        rep.approved    = True
        rep.approved_by = admin_username
        rep.approved_at = now
        rep.admin_note  = note
        db.commit()
        db.refresh(rep)
        return {
            "status":   "approved_override",
            "week_id":  week_id,
            "cleared":  True,
            "message":  "HOLD overridden — the prepared draw will deploy at the next "
                        "execute. Override recorded against the report for audit.",
            "report":   _serialize(rep),
        }

    # 3b) RE-ASSESS — re-run the gate on CURRENT data; the hold clears only on PASS.
    fresh = persist_report(db, run_reassessment(db, week_id))
    if body.admin_note and body.admin_note.strip():
        fresh.admin_note = body.admin_note.strip()
        fresh.approved_by = admin_username   # who requested the re-assessment
    cleared = (fresh.verdict == "PASS")
    if cleared:
        # A PASS report is inherently deployable; record who cleared it for audit.
        fresh.approved    = True
        fresh.approved_by = admin_username
        fresh.approved_at = now
    db.commit()
    db.refresh(fresh)
    return {
        "status":   "reassessed",
        "week_id":  week_id,
        "cleared":  cleared,
        "message":  ("Re-assessment PASSED on current data — the HOLD is cleared and "
                     "the draw may deploy."
                     if cleared else
                     "Re-assessment STILL HOLDS on current data — the underlying issue is "
                     "not resolved. Fix the flagged gate(s) and re-assess, or override "
                     "explicitly to accept the risk."),
        "report":   _serialize(fresh),
    }
