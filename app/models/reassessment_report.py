# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
ReassessmentReport — Master Pool Re-assessment Manager audit trail
==================================================================
One row per re-assessment run (normally one per draw week, but re-runs after a
corrected-plan approval append new rows so the full decision history is kept).

The re-assessor is a VIRTUAL PRE-DEPLOYMENT INTEGRITY GATE.  At T-2H, AFTER the
draw result is prepared (SDE winners staged, regular draws projectable) but
BEFORE the result is deployed at T-0H, it virtually dissolves every pool
(Active / Paused / orphan — any size), segregates members level-wise, projects
the full week's winner set, and cross-verifies the "purity of the draw" against
five financial-grade checks:

  1. purity_pass        — winner level-mix is balanced vs the member pyramid
                          (catches the 66%-L4 over-representation)
  2. level_advance_pass — the L4 backlog is not growing unsustainably
                          (the user's "level-advancement issue")
  3. float_pass         — projected payout ≤ available float (solvent NOW)
  4. pyramid_pass       — forward projection stays sustainable (solvent FUTURE)
  5. reconcile_pass     — per-type draw counts and per-level winner counts are
                          internally consistent (catches the "non-trustable
                          data" the report exhibited: 315 L4 > 299 theoretical)

VERDICT (locked decision #2 — positive future projection = BOTH float-solvent
AND pyramid-sustainable):

    HOLD  if NOT (float_pass AND pyramid_pass AND reconcile_pass)
    PASS  otherwise   (purity / level_advance failures are surfaced as
                       diagnostics and drive the proposed corrected plan, but
                       only escalate to HOLD when they co-occur with a money
                       signal, so a normal mature week is never frozen).

On HOLD the real result is NOT deployed at T-0H until an admin reviews the
proposed corrected_plan_json and approves it with their password (locked
decision #1 — hold + propose corrected plan for password-approval).

This table is created by Base.metadata.create_all() on deploy (it is a NEW
table, so create_all picks it up without a column migration).
"""
import enum

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class ReassessmentVerdict(str, enum.Enum):
    PASS = "PASS"   # all hard gates satisfied — result may deploy
    HOLD = "HOLD"   # one or more hard gates failed — deployment blocked pending approval


class ReassessmentReport(Base):
    __tablename__ = "reassessment_reports"

    id      = Column(Integer, primary_key=True, index=True)

    # ISO week key of the draw cycle being assessed.  NOT unique — re-runs after
    # an approval append additional rows for a full audit trail.
    week_id = Column(String(10), nullable=False, index=True)

    run_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # PASS / HOLD (stored as the string value of ReassessmentVerdict).
    verdict = Column(String(8), nullable=False)

    # ── The five gate checks (True = passed) ─────────────────────────────────
    purity_pass        = Column(Boolean, default=True, server_default="true", nullable=False)
    level_advance_pass = Column(Boolean, default=True, server_default="true", nullable=False)
    float_pass         = Column(Boolean, default=True, server_default="true", nullable=False)
    pyramid_pass       = Column(Boolean, default=True, server_default="true", nullable=False)
    reconcile_pass     = Column(Boolean, default=True, server_default="true", nullable=False)

    # ── Financial snapshot (whole rupees; matches the rest of the engine) ────
    projected_payout_inr = Column(Integer, default=0, server_default="0", nullable=False)
    available_float_inr  = Column(Integer, default=0, server_default="0", nullable=False)
    net_float_inr        = Column(Integer, default=0, server_default="0", nullable=False)

    # ── Distributions + full audit (JSON-encoded strings) ────────────────────
    # member_pyramid_json: {"L1":n,...,"L6":n} live Active members by level
    # winner_pyramid_json: {"L1":n,...,"L6":n} projected winners by level
    # audit_json:          full structured audit — every metric, band, and reason
    # corrected_plan_json: the money-safe corrected plan proposed on HOLD (or null)
    member_pyramid_json = Column(Text, nullable=True)
    winner_pyramid_json = Column(Text, nullable=True)
    audit_json          = Column(Text, nullable=True)
    corrected_plan_json = Column(Text, nullable=True)

    # ── Human-in-loop approval (password-gated; locked decision #1) ──────────
    approved    = Column(Boolean, default=False, server_default="false", nullable=False)
    approved_by = Column(String(64), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    admin_note  = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
