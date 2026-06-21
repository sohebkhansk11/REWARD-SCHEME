# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
pool_reassessor.py — Master Pool Re-assessment Manager
======================================================
A VIRTUAL PRE-DEPLOYMENT INTEGRITY GATE.

At T-2H, AFTER the draw result is prepared (SDE winners staged, regular draws
projectable) but BEFORE the result is deployed at T-0H, this engine:

  R1. VIRTUALLY DISSOLVES every pool (Active / Paused / orphan, any size 1..12)
      into one pool-agnostic population and segregates members level-wise.
  R2. PROJECTS the full week's winner set:
        • staged SDE winners       — read EXACTLY from SDECheckpoint (1 L4 upper
                                     + 1 L1/L2/L3 lower per sub-draw)
        • projected regular winners — for every pool that will draw at T-0H
                                     (1 high-tier + 1 low-tier, or the 2-low
                                     early-pool edge case)
  R3-R5. CROSS-VERIFIES the "purity of the draw" against five financial-grade
      checks and renders a PASS / HOLD verdict.

It writes NOTHING to the database — it is a pure analysis pass.  The caller
(draw_preparation STEP 8b) persists a ReassessmentReport row and, on HOLD,
blocks the T-0H deployment until an admin approves the proposed corrected plan
with their password.

WHY THIS EXISTS (root-cause, proven from the production CSV/forensic data):
  The SDE liability-control engine mints exactly 1 L4 winner per sub-draw
  (SDE_LEVEL_UPPER=(4,4)) and, at maturity, SDE becomes the dominant draw type
  (74% of draws in the 22-week report) because every pool that accumulates an L4
  is routed to SDE.  Result: 66% of all winners were L4 (315 of 476), the
  per-winner payout inflated from ~₹3,153 (healthy) to ₹4,703, and the report's
  L4 count (315) even EXCEEDED the theoretical ceiling its own draw-type counts
  could mint (299) — i.e. the data was internally inconsistent / non-trustable.

  This gate refuses to deploy a result until the projection is POSITIVE
  (float-solvent NOW + pyramid-sustainable FORWARD) and the level-advancement
  accumulation is resolved, exactly as required.

VERDICT (locked decision #2):
  HOLD if NOT (float_pass AND pyramid_pass AND reconcile_pass).
  purity_pass / level_advance_pass are surfaced as diagnostics and drive the
  proposed corrected plan; they do not, on their own, freeze a normal mature
  week (which would halt the whole scheme) — they escalate to HOLD only when a
  hard money/data gate also fails.

All thresholds are module constants (safe, conservative defaults) so they can be
promoted to admin-configurable settings later without touching the logic.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import (
    LEVEL_LOW, LEVEL_HIGH, POOL_CAPACITY,
)
from app.models.user import User, UserStatus
from app.models.pool import Pool, PoolStatus
from app.models.token import Token, TokenType, TokenStatus

_logger = logging.getLogger("reassessor")


class ReassessmentHoldError(RuntimeError):
    """
    Raised at T-0H by execute_weekly_draw when the latest re-assessment for the
    week is an UNAPPROVED HOLD.  Deployment is blocked — NO winners are committed,
    NO tokens issued, NO staged SDE executed — until an admin reviews the proposed
    corrected plan and approves it with their password (locked decision #1).

    The staged result (SDECheckpoint rows, executed=False) is untouched and simply
    waits; on approval the draw can be re-triggered and will deploy.
    """

    def __init__(self, week_id: str, report_id: int, failed_gates: list[str]):
        self.week_id = week_id
        self.report_id = report_id
        self.failed_gates = failed_gates
        super().__init__(
            f"Re-assessment HOLD for week {week_id} (report #{report_id}); "
            f"failed hard gate(s): {', '.join(failed_gates) or 'unknown'}. "
            f"Deployment blocked pending admin approval of the corrected plan."
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Tunable bands (conservative defaults).  A normal mature week must PASS; only a
#  genuinely dangerous week (insolvent / runaway L4 / impossible data) must HOLD.
# ─────────────────────────────────────────────────────────────────────────────

# Float-solvency reserve: payout must leave at least this fraction of available
# float untouched.  0.0 = bare solvency (payout ≤ float).
FLOAT_RESERVE_FRACTION   = 0.0

# Purity — winner high-tier (L4+) share may be at most this multiple of the
# member high-tier share (the 66%-vs-19% case → 3.5×, which exceeds 2.5 → fail).
PURITY_OVERREP_BAND      = 2.5
# Purity — at least this fraction of winners must be low-tier (L1-L3).
PURITY_LOW_FLOOR         = 0.20

# Level-advancement — member population L4+ share above this ceiling means
# advancement is outpacing exit (diagnostic, drives corrected plan).
LEVEL_ADVANCE_MEMBER_CEIL = 0.45

# Pyramid sustainability (HARD gate) — next-week projected L4 backlog must be
# either non-growing OR within this multiple of the weekly L4-clear capacity.
PYRAMID_SUSTAIN_MULT     = 2.0

_EPS = 1e-9


@dataclass
class ReassessResult:
    """Structured outcome of one re-assessment pass (persisted by the caller)."""
    week_id: str
    verdict: str                       # "PASS" | "HOLD"

    purity_pass: bool
    level_advance_pass: bool
    float_pass: bool
    pyramid_pass: bool
    reconcile_pass: bool

    projected_payout_inr: int
    available_float_inr: int
    net_float_inr: int

    member_pyramid: dict               # {"L1":n,...,"L6":n}
    winner_pyramid: dict               # projected winners by level
    audit: dict                        # full structured metrics + reasons
    corrected_plan: list = field(default_factory=list)  # remediation actions on HOLD

    @property
    def is_hold(self) -> bool:
        return self.verdict == "HOLD"

    @property
    def failed_hard_gates(self) -> list[str]:
        """The hard gates (float/pyramid/reconcile) that failed — these drive the HOLD."""
        return [
            name for name, ok in (
                ("float", self.float_pass),
                ("pyramid", self.pyramid_pass),
                ("reconcile", self.reconcile_pass),
            ) if not ok
        ]


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_pyramid() -> dict:
    return {f"L{i}": 0 for i in range(1, 7)}


def _high_share(pyr: dict) -> tuple[int, int, float]:
    """Return (high_count L4-L6, total, high_share)."""
    total = sum(pyr.values())
    high  = pyr["L4"] + pyr["L5"] + pyr["L6"]
    return high, total, (high / total if total else 0.0)


def _low_count(pyr: dict) -> int:
    return pyr["L1"] + pyr["L2"] + pyr["L3"]


def _payout_net(db: Session, level: int) -> int:
    """Net payout (whole rupees) at a level, via the DB-backed dynamic getter."""
    from app.services.global_config import get_level_payout
    lvl = max(1, min(int(level or 1), 6))
    return int(get_level_payout(db, lvl)[1])


# ─────────────────────────────────────────────────────────────────────────────
#  R1 — virtual dissolve + level segregation (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def _virtual_dissolve(db: Session) -> tuple[dict, list[dict]]:
    """
    Treat ALL live Active members as one pool-agnostic population segregated by
    level (the "virtual dissolve"), and inventory every live pool regardless of
    size (Active / Paused / orphan 1..12).  No DB writes.

    Returns (member_pyramid, pool_inventory).
    """
    pyramid = _empty_pyramid()
    rows = (
        db.query(User.current_level, func.count(User.id))
        .filter(User.status == UserStatus.Active)
        .group_by(User.current_level)
        .all()
    )
    for level, cnt in rows:
        lvl = max(1, min(int(level or 1), 6))
        pyramid[f"L{lvl}"] += int(cnt)

    live_pools = (
        db.query(Pool)
        .filter(Pool.status.in_([PoolStatus.Active, PoolStatus.Paused_Awaiting_Members]))
        .all()
    )
    live_counts = dict(
        db.query(User.current_pool_id, func.count(User.id))
        .filter(User.status == UserStatus.Active, User.current_pool_id.isnot(None))
        .group_by(User.current_pool_id)
        .all()
    )
    inventory = [
        {
            "pool_id": p.id,
            "name": p.name,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "members": int(live_counts.get(p.id, 0)),
            "flagged_l4": bool(p.contains_flagged_l4),
        }
        for p in live_pools
    ]
    return pyramid, inventory


# ─────────────────────────────────────────────────────────────────────────────
#  R2 — project the full week's winner set (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def _project_staged_sde(db: Session, week_id: str) -> tuple[dict, int, int, int]:
    """
    Read the EXACT staged SDE winners for this week from SDECheckpoint.
    Returns (winner_pyramid_contribution, sde_draws, sde_winners, sde_payout_inr).
    """
    from app.models.sde_session import SDESession, SDECheckpoint

    pyr = _empty_pyramid()
    session_ids = [
        sid for (sid,) in
        db.query(SDESession.id).filter(SDESession.week_id == week_id).all()
    ]
    if not session_ids:
        return pyr, 0, 0, 0

    checkpoints = (
        db.query(SDECheckpoint)
        .filter(
            SDECheckpoint.session_id.in_(session_ids),
            SDECheckpoint.executed == False,   # noqa: E712  — staged, not yet deployed
        )
        .all()
    )
    payout = Decimal("0")
    for cp in checkpoints:
        up = max(1, min(int(cp.upper_winner_level or 4), 6))
        lo = max(1, min(int(cp.lower_winner_level or 1), 6))
        pyr[f"L{up}"] += 1
        pyr[f"L{lo}"] += 1
        payout += (cp.upper_payout_inr or Decimal("0")) + (cp.lower_payout_inr or Decimal("0"))

    sde_draws   = len(checkpoints)
    sde_winners = sde_draws * 2
    return pyr, sde_draws, sde_winners, int(payout)


def _project_regular_draws(db: Session) -> tuple[dict, int, int, int]:
    """
    Project the winners of the REGULAR draws that will run at T-0H — every pool
    that is Active, NOT SDE-locked (draw_completed_this_week == False), NOT
    flagged, and holds exactly POOL_CAPACITY members.

    Winner-level projection is deterministic and uses the MODAL level present in
    each tier (the most representative outcome of secrets.choice over that tier),
    which is what the purity check needs.  Payout uses that same modal level.

    Returns (winner_pyramid_contribution, reg_draws, reg_winners, reg_payout_inr).
    """
    pyr = _empty_pyramid()
    candidate_pools = (
        db.query(Pool)
        .filter(
            Pool.status == PoolStatus.Active,
            Pool.draw_completed_this_week == False,   # noqa: E712 — not SDE-locked at T-2H
            Pool.contains_flagged_l4 == False,        # noqa: E712 — flagged pools route to SDE
        )
        .all()
    )

    reg_draws = 0
    payout = 0
    for pool in candidate_pools:
        levels = [
            int(l or 1) for (l,) in
            db.query(User.current_level)
            .filter(User.current_pool_id == pool.id, User.status == UserStatus.Active)
            .all()
        ]
        if len(levels) != POOL_CAPACITY:
            continue   # only 12/12 pools draw — mirrors execute_weekly_draw eligibility

        low  = sorted(l for l in levels if LEVEL_LOW[0]  <= l <= LEVEL_LOW[1])
        high = sorted(l for l in levels if LEVEL_HIGH[0] <= l <= LEVEL_HIGH[1])

        def _modal(seq: list[int]) -> int:
            return Counter(seq).most_common(1)[0][0]

        if high:
            # normal draw: 1 low winner + 1 high winner
            if not low:
                # no low tier — under current code this pool RAISES at T-0H and is
                # skipped; do not project a phantom winner for it.
                continue
            w_low  = _modal(low)
            w_high = _modal(high)
            pyr[f"L{w_low}"]  += 1
            pyr[f"L{w_high}"] += 1
            payout += _payout_net(db, w_low) + _payout_net(db, w_high)
            reg_draws += 1
        else:
            # early-pool edge case: 2 low winners
            if len(low) < 2:
                continue
            w1 = _modal(low)
            # second winner = next modal (or same level if only one level present)
            rest = low.copy()
            rest.remove(w1)
            w2 = _modal(rest) if rest else w1
            pyr[f"L{w1}"] += 1
            pyr[f"L{w2}"] += 1
            payout += _payout_net(db, w1) + _payout_net(db, w2)
            reg_draws += 1

    reg_winners = reg_draws * 2
    return pyr, reg_draws, reg_winners, payout


# ─────────────────────────────────────────────────────────────────────────────
#  Available float (canonical ledger identity — matches dev.py SSOT)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_float(db: Session) -> tuple[int, int, dict]:
    """
    available_float = Σ Deposit(Burned)
                      − Σ Withdraw(Burned)        (already paid out)
                      − Σ Withdraw(Active)        (outstanding committed liability)
                      − Σ Referral_Withdraw(Burned)

    net_float (the dashboard SSOT, dev.py:1175) excludes the outstanding-liability
    term.  We report both; the gate uses the conservative available_float.

    Returns (available_float_inr, net_float_inr, breakdown).
    """
    def _sum(ttype, tstatus) -> Decimal:
        return db.query(func.coalesce(func.sum(Token.value_inr), 0)).filter(
            Token.type == ttype, Token.status == tstatus,
        ).scalar() or Decimal("0")

    dep        = _sum(TokenType.Deposit, TokenStatus.Burned)
    wit_burned = _sum(TokenType.Withdraw, TokenStatus.Burned)
    wit_active = _sum(TokenType.Withdraw, TokenStatus.Active)

    # Referral_Withdraw may not exist as an enum value on older deployments —
    # guard so the gate never crashes on a missing token type.
    try:
        ref_paid = _sum(TokenType.Referral_Withdraw, TokenStatus.Burned)
    except Exception:
        ref_paid = Decimal("0")

    net_float       = int(dep - wit_burned - ref_paid)
    available_float = int(dep - wit_burned - wit_active - ref_paid)
    breakdown = {
        "deposits_collected_inr":     int(dep),
        "withdrawals_paid_inr":       int(wit_burned),
        "withdrawals_outstanding_inr": int(wit_active),
        "referral_paid_inr":          int(ref_paid),
    }
    return available_float, net_float, breakdown


# ─────────────────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_reassessment(db: Session, week_id: str) -> ReassessResult:
    """
    Run the full virtual integrity gate for ``week_id``.  Pure read pass — no
    DB writes.  Returns a ReassessResult the caller persists as a
    ReassessmentReport.
    """
    # ── R1: virtual dissolve + level segregation ─────────────────────────────
    member_pyramid, pool_inventory = _virtual_dissolve(db)
    member_total = sum(member_pyramid.values())

    # ── R2: project the full week's winners ──────────────────────────────────
    sde_pyr,  sde_draws,  sde_winners,  sde_payout  = _project_staged_sde(db, week_id)
    reg_pyr,  reg_draws,  reg_winners,  reg_payout  = _project_regular_draws(db)

    winner_pyramid = {k: sde_pyr[k] + reg_pyr[k] for k in sde_pyr}
    projected_draws   = sde_draws + reg_draws
    projected_winners = sum(winner_pyramid.values())

    # Projected payout for the FLOAT gate: take the conservative MAX of the
    # composition-consistent projection and the canonical worst-case ceiling
    # already computed at STEP 6 (state.float_projection_inr), so the gate never
    # under-estimates the outflow.
    composition_payout = sde_payout + reg_payout
    try:
        from app.services.draw_preparation import _calculate_projected_payout
        worstcase_payout = int(_calculate_projected_payout(db))
    except Exception:
        worstcase_payout = composition_payout
    projected_payout = max(composition_payout, worstcase_payout)

    # ── Available float ──────────────────────────────────────────────────────
    available_float, net_float, float_breakdown = _compute_float(db)

    # ── R2 purity: winner mix vs member mix ──────────────────────────────────
    w_high, w_tot, w_high_share = _high_share(winner_pyramid)
    m_high, m_tot, m_high_share = _high_share(member_pyramid)
    w_low_share  = (_low_count(winner_pyramid) / w_tot) if w_tot else 1.0
    over_rep     = (w_high_share / max(m_high_share, _EPS)) if w_tot else 0.0
    purity_pass  = (w_tot == 0) or (over_rep <= PURITY_OVERREP_BAND and w_low_share >= PURITY_LOW_FLOOR)

    # ── Level-advancement: member population L4+ share (diagnostic) ──────────
    level_advance_pass = (m_high_share <= LEVEL_ADVANCE_MEMBER_CEIL) or (m_tot == 0)

    # ── R4 float-solvency (HARD): payout ≤ available float (minus reserve) ───
    reserve = int(available_float * FLOAT_RESERVE_FRACTION)
    float_pass = (available_float - reserve - projected_payout) >= 0

    # ── R3/R4b pyramid-sustainability (HARD): flagged-L4 backlog vs clear rate ─
    # Engine mechanics (draw.py / _advance_survivor_level): draw winners EXIT
    # (Eliminated_Won); the 10 survivors each advance +1 level — EXCEPT a flagged
    # L4 (current_level==4 AND sde_required) is HELD at L4 (Case-E true defer) and
    # L5/L6 are held.  So an L4 can only LEAVE the system by WINNING (an SDE upper
    # draw, or a regular high-tier draw).  The sustainability risk is therefore a
    # growing HELD-L4 backlog: if flagged L4 accumulate faster than the draw clears
    # them, future weeks inherit an ever-larger liability the SDE valve can never
    # catch up to (and the held band edges toward an L5/L6 leak).
    #
    # flagged_l4_now is set by STEP 3 flag_l4_members earlier in this same prep
    # cycle, so at re-assessment time it is the exact backlog this week must clear.
    flagged_l4_now = int(
        db.query(func.count(User.id)).filter(
            User.status == UserStatus.Active,
            User.current_level == 4,
            User.sde_required == True,   # noqa: E712
        ).scalar() or 0
    )
    l4_now         = member_pyramid["L4"]
    l3_now         = member_pyramid["L3"]
    l4_cleared     = winner_pyramid["L4"]                 # SDE upper + regular L4 high winners
    l4_backlog_after = max(0, flagged_l4_now - l4_cleared)
    # forward inflow (diagnostic): L3 survivors advancing into L4 next week
    l3_advancing   = max(0, l3_now - winner_pyramid["L3"])
    clear_capacity = max(l4_cleared, sde_draws, 1)        # this week's L4-clearing power
    pyramid_pass   = (
        flagged_l4_now == 0                                            # nothing to clear, OR
        or l4_backlog_after <= clear_capacity * PYRAMID_SUSTAIN_MULT   # catchable in ≤ MULT weeks
    )

    # ── R5 reconciliation (HARD): internal consistency + impossible-data guard ─
    # (a) winner totals reconcile with draw counts
    count_ok = (projected_winners == projected_draws * 2)
    # (b) cannot project more winners at a level than members exist at that level
    #     (this is exactly the "315 L4 > members" impossible-data signature)
    impossible_levels = [
        k for k in winner_pyramid
        if winner_pyramid[k] > member_pyramid[k]
    ]
    reconcile_pass = count_ok and not impossible_levels

    # ── VERDICT (locked decision #2) ─────────────────────────────────────────
    hard_ok = float_pass and pyramid_pass and reconcile_pass
    verdict = "PASS" if hard_ok else "HOLD"

    # ── Corrected plan (locked decision #1) — proposed on HOLD ───────────────
    corrected_plan: list[dict] = []
    if not float_pass:
        shortfall = projected_payout - (available_float - reserve)
        avg_high  = _payout_net(db, 4)
        defer_n   = max(1, -(-shortfall // max(avg_high, 1)))  # ceil division to cover shortfall

        # ── SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # CONFLICT-AWARE REMEDIATION (Jun-21).  The re-assessor is NOT a naive draw-cost
        # minimiser: deferring L4 draws frees float THIS week but GROWS the held-L4
        # backlog, which damages FUTURE projections (the user's explicit concern: "if
        # you leave L4 undrawn it will damage future projections") and can itself breach
        # the pyramid-sustainability band.  So the float remediation and the pyramid
        # remediation point in OPPOSITE directions — defer-L4 (float) vs add-L4-subdraws
        # (pyramid).  We resolve the conflict in favour of FUTURE health: only propose
        # the L4 defer when it provably stays inside the pyramid band; otherwise protect
        # every due L4 clearance and propose a float TOP-UP for the exact shortfall.
        backlog_if_deferred   = l4_backlog_after + defer_n
        capacity_if_deferred  = max(0, clear_capacity - defer_n)
        defer_is_pyramid_safe = (
            flagged_l4_now == 0
            or backlog_if_deferred <= capacity_if_deferred * PYRAMID_SUSTAIN_MULT
        )
        if defer_is_pyramid_safe:
            float_action = (
                f"Throttle this week's high-tier payouts: defer {defer_n} SDE L4 "
                f"draw(s) to next week so projected payout ≤ available float. Pyramid "
                f"stays within band (held-L4 would be {backlog_if_deferred} ≤ "
                f"{int(capacity_if_deferred * PYRAMID_SUSTAIN_MULT)}), so deferring does "
                f"not endanger future projections."
            )
            float_params = {
                "remediation":       "defer_l4_pyramid_safe",
                "defer_sde_draws":   int(defer_n),
                "shortfall_inr":     int(shortfall),
                "backlog_if_deferred": int(backlog_if_deferred),
            }
        else:
            float_action = (
                f"DO NOT defer L4 to save float — it would grow the held-L4 backlog to "
                f"{backlog_if_deferred} (sustainable band ≤ "
                f"{int(capacity_if_deferred * PYRAMID_SUSTAIN_MULT)}) and damage future "
                f"projections. Instead TOP UP the float by ≈₹{shortfall:,} (inject "
                f"deposits / defer non-L4 withdrawals) so EVERY due L4 still clears this "
                f"week and the backlog does not compound."
            )
            float_params = {
                "remediation":                "topup_float_protect_l4",
                "topup_float_inr":            int(shortfall),
                "shortfall_inr":              int(shortfall),
                "would_be_backlog_if_deferred": int(backlog_if_deferred),
            }
        corrected_plan.append({
            "gate": "float",
            "severity": "critical",
            "finding": (
                f"Projected payout ₹{projected_payout:,} exceeds available float "
                f"₹{available_float:,} by ₹{shortfall:,}."
            ),
            "action": float_action,
            "params": float_params,
        })
    if not pyramid_pass:
        # how many extra SDE sub-draws would bring the backlog within capacity
        target_clear = -(-l4_backlog_after // max(int(PYRAMID_SUSTAIN_MULT), 1))  # ceil
        extra_sde    = max(1, int(target_clear) - clear_capacity)
        corrected_plan.append({
            "gate": "pyramid",
            "severity": "critical",
            "finding": (
                f"Flagged-L4 backlog {flagged_l4_now} vs this week's clear capacity "
                f"{clear_capacity}: {l4_backlog_after} flagged L4 would remain HELD "
                f"after the draw (sustainable band ≤ {int(clear_capacity*PYRAMID_SUSTAIN_MULT)}). "
                f"L4 is accumulating faster than the SDE valve can shed it."
            ),
            "action": (
                f"Add ≈{extra_sde} SDE sub-draw(s) this week to clear the held-L4 "
                f"backlog before it climbs toward the L5/L6 leak band; if supply is "
                f"exhausted, slow L3→L4 advancement (defer maturing pools)."
            ),
            "params": {
                "flagged_l4_now": flagged_l4_now,
                "l4_cleared": l4_cleared,
                "backlog_after": l4_backlog_after,
                "clear_capacity": clear_capacity,
                "extra_sde_subdraws": int(extra_sde),
            },
        })
    if not reconcile_pass:
        corrected_plan.append({
            "gate": "reconcile",
            "severity": "critical",
            "finding": (
                f"Projected winners do not reconcile with draw counts "
                f"(winners={projected_winners}, expected={projected_draws*2}) "
                + (f"or exceed available members at level(s) {impossible_levels}."
                   if impossible_levels else ".")
            ),
            "action": "Data inconsistency — re-run preparation; DO NOT deploy this result.",
            "params": {"impossible_levels": impossible_levels},
        })
    # purity / level-advance are diagnostics — appended even when verdict is PASS
    # so the admin always sees the rebalance recommendation.
    if not purity_pass:
        rebalance = max(0, int(w_high - (m_high_share * PURITY_OVERREP_BAND) * max(w_tot, 1)))
        corrected_plan.append({
            "gate": "purity",
            "severity": "warning",
            "finding": (
                f"Winner high-tier share {w_high_share*100:.0f}% vs member "
                f"{m_high_share*100:.0f}% (over-representation {over_rep:.1f}×, "
                f"band {PURITY_OVERREP_BAND}×)."
            ),
            "action": (
                f"Rebalance ≈{rebalance} high-tier winner slot(s) toward low-tier "
                f"draws so the winner pyramid tracks the member pyramid."
            ),
            "params": {"over_representation": round(over_rep, 2), "rebalance_slots": rebalance},
        })
    if not level_advance_pass:
        corrected_plan.append({
            "gate": "level_advance",
            "severity": "warning",
            "finding": (
                f"Member L4+ share {m_high_share*100:.0f}% exceeds ceiling "
                f"{LEVEL_ADVANCE_MEMBER_CEIL*100:.0f}% — advancement outpacing exit."
            ),
            "action": "Increase shed rate or admit more L1 members to rebalance the pyramid.",
            "params": {"member_high_share": round(m_high_share, 3)},
        })

    audit = {
        "draws": {
            "sde": sde_draws, "regular": reg_draws, "total": projected_draws,
            "projected_winners": projected_winners,
        },
        "purity": {
            "winner_high_share": round(w_high_share, 3),
            "member_high_share": round(m_high_share, 3),
            "over_representation": round(over_rep, 2),
            "winner_low_share": round(w_low_share, 3),
            "band": PURITY_OVERREP_BAND, "low_floor": PURITY_LOW_FLOOR,
        },
        "level_advance": {
            "member_high_share": round(m_high_share, 3),
            "ceiling": LEVEL_ADVANCE_MEMBER_CEIL,
        },
        "float": {
            "projected_payout_inr": projected_payout,
            "composition_payout_inr": composition_payout,
            "worstcase_payout_inr": worstcase_payout,
            "available_float_inr": available_float,
            "net_float_inr": net_float,
            "reserve_inr": reserve,
            "breakdown": float_breakdown,
        },
        "pyramid": {
            "flagged_l4_now": flagged_l4_now,
            "l4_now": l4_now, "l3_now": l3_now,
            "l4_cleared": l4_cleared, "l3_advancing": l3_advancing,
            "l4_backlog_after": l4_backlog_after, "clear_capacity": clear_capacity,
            "sustain_mult": PYRAMID_SUSTAIN_MULT,
        },
        "reconcile": {
            "count_ok": count_ok, "impossible_levels": impossible_levels,
        },
        "pool_inventory": pool_inventory,
        "member_total": member_total,
    }

    result = ReassessResult(
        week_id=week_id,
        verdict=verdict,
        purity_pass=purity_pass,
        level_advance_pass=level_advance_pass,
        float_pass=float_pass,
        pyramid_pass=pyramid_pass,
        reconcile_pass=reconcile_pass,
        projected_payout_inr=projected_payout,
        available_float_inr=available_float,
        net_float_inr=net_float,
        member_pyramid=member_pyramid,
        winner_pyramid=winner_pyramid,
        audit=audit,
        corrected_plan=corrected_plan,
    )

    _logger.info(
        "Re-assessment %s: verdict=%s  [purity=%s level_adv=%s float=%s pyramid=%s reconcile=%s]  "
        "payout=₹%d float=₹%d  winners L4=%d/%d (%.0f%%)",
        week_id, verdict, purity_pass, level_advance_pass, float_pass, pyramid_pass,
        reconcile_pass, projected_payout, available_float,
        winner_pyramid["L4"], projected_winners,
        (winner_pyramid["L4"] / projected_winners * 100) if projected_winners else 0.0,
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Persistence + hold-state helpers (used by the T-2H wiring and T-0H gate)
# ─────────────────────────────────────────────────────────────────────────────

def persist_report(db: Session, result: "ReassessResult"):
    """
    Build and ADD a ReassessmentReport row from a ReassessResult.  The caller is
    responsible for committing (in _run_preparation this happens at STEP 9).  The
    row is flushed so its id is available immediately.  Returns the ORM row.
    """
    import json
    from app.models.reassessment_report import ReassessmentReport

    row = ReassessmentReport(
        week_id=result.week_id,
        verdict=result.verdict,
        purity_pass=result.purity_pass,
        level_advance_pass=result.level_advance_pass,
        float_pass=result.float_pass,
        pyramid_pass=result.pyramid_pass,
        reconcile_pass=result.reconcile_pass,
        projected_payout_inr=int(result.projected_payout_inr),
        available_float_inr=int(result.available_float_inr),
        net_float_inr=int(result.net_float_inr),
        member_pyramid_json=json.dumps(result.member_pyramid),
        winner_pyramid_json=json.dumps(result.winner_pyramid),
        audit_json=json.dumps(result.audit, default=str),
        corrected_plan_json=json.dumps(result.corrected_plan, default=str),
        approved=False,
    )
    db.add(row)
    db.flush()
    return row


def latest_report(db: Session, week_id: str):
    """Return the most recent ReassessmentReport for week_id (or None)."""
    from app.models.reassessment_report import ReassessmentReport
    return (
        db.query(ReassessmentReport)
        .filter(ReassessmentReport.week_id == week_id)
        .order_by(ReassessmentReport.id.desc())
        .first()
    )


def get_active_hold(db: Session, week_id: str):
    """
    Return the latest ReassessmentReport for ``week_id`` IF it is an unapproved
    HOLD (i.e. deployment must be blocked), else None.

    Failure-isolated by the caller: a lookup error (e.g. table missing on a stale
    deploy) must NOT block the draw — STEP 8b is the authoritative gate that writes
    the verdict; this is only a read of that verdict at T-0H.
    """
    rep = latest_report(db, week_id)
    if rep is not None and rep.verdict == "HOLD" and not bool(rep.approved):
        return rep
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# ROUTE-VIA-REASSESSMENT (Jun-21, Task 2) — every donor↔receiver MERGE / DISSOLVE
# is routed through the virtual integrity gate so a structurally-changed pool layout
# is always re-verified and recorded BEFORE the system trusts it.  Locked decision
# #3: VALIDATE + REPORT, never roll back the structural change.
# ─────────────────────────────────────────────────────────────────────────────

def route_pool_change_via_reassessment(
    db: Session,
    week_id: str,
    *,
    trigger: str,
    commit: bool = True,
):
    """
    Re-run the virtual integrity gate on the NEWLY merged/dissolved pool layout and
    PERSIST a tagged ReassessmentReport (locked decision #3 — "validate + report,
    not rollback").

    The user's rule: "dissolver+merger jab bhi run ho to wo route via re-assessment
    ho, taki proper pool ban ske."  After any structural change — a manual dissolve,
    the post-draw merger convergence, or (implicitly) the T-2H merge that STEP 8b
    already re-assesses — the resulting layout is verified and recorded so:
      • the decision trail shows WHICH structural event produced the assessment
        (audit.routed_trigger), and
      • on HOLD the existing T-0H gate (get_active_hold / ReassessmentHoldError)
        blocks deployment until an admin clears it.

    MONEY-SAFETY (decision #3):
      • This NEVER rolls back the merge/dissolve.  Those operations are already
        correct, level-preserving moves (ONLY current_pool_id changes); undoing them
        would itself be the unsafe act.  We validate the *outcome* and report it.
      • Failure-isolated + FAIL-CLOSED: if the engine errors, we write a HOLD report
        carrying the error (never a silent PASS), so a broken gate can't wave a bad
        structure through.  The structural change itself stays intact.

    ``commit`` — True (default): commit the report immediately (manual dissolve /
    post-draw, which run outside the preparation transaction).  False: only flush
    (caller owns the surrounding transaction, e.g. inside draw preparation).

    Returns the persisted ReassessmentReport row, or None if even the fail-closed
    write was impossible.
    """
    import json
    from app.models.reassessment_report import ReassessmentReport

    try:
        result = run_reassessment(db, week_id)
        # Tag the audit with the structural trigger that produced this assessment so
        # the decision trail is self-explaining (no new column — migration-safe).
        try:
            result.audit["routed_trigger"] = trigger
        except Exception:
            pass
        row = persist_report(db, result)
        if commit:
            db.commit()
            db.refresh(row)
        _logger.info(
            "[ROUTE-REASSESS] trigger=%s week=%s → report #%s verdict=%s "
            "(failed hard gate(s): %s) payout=₹%d float=₹%d",
            trigger, week_id, row.id, result.verdict,
            ", ".join(result.failed_hard_gates) or "none",
            result.projected_payout_inr, result.available_float_inr,
        )
        return row
    except Exception as exc:
        # FAIL CLOSED — never let a gate error silently approve a changed layout.
        _logger.critical(
            "[ROUTE-REASSESS] trigger=%s week=%s — engine error, failing CLOSED "
            "(writing HOLD report; structural change stays intact): %s",
            trigger, week_id, exc, exc_info=True,
        )
        try:
            # Discard ONLY the failed re-assessment's pending writes.  The merge/
            # dissolve was already committed by its own caller, so this rollback
            # cannot undo the structural change.
            db.rollback()
        except Exception:
            pass
        try:
            row = ReassessmentReport(
                week_id=week_id, verdict="HOLD",
                purity_pass=True, level_advance_pass=True,
                float_pass=False, pyramid_pass=False, reconcile_pass=False,
                projected_payout_inr=0, available_float_inr=0, net_float_inr=0,
                audit_json=json.dumps({"engine_error": str(exc), "routed_trigger": trigger}),
                corrected_plan_json=json.dumps([{
                    "gate": "engine", "severity": "critical",
                    "finding": f"Post-{trigger} re-assessment engine raised: {exc}",
                    "action": ("Investigate the gate error. The structural change itself "
                               "is intact and level-preserving; re-run preparation or "
                               "approve explicitly to override the fail-closed hold."),
                    "params": {},
                }]),
                approved=False,
            )
            db.add(row)
            if commit:
                db.commit()
                db.refresh(row)
            else:
                db.flush()
            return row
        except Exception:
            _logger.critical(
                "[ROUTE-REASSESS] could not persist the fail-closed HOLD report.",
                exc_info=True,
            )
            return None
