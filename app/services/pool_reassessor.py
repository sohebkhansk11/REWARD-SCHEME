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

VERDICT (locked decision #2 — REVISED Jun-22, Soheb Khan User 2):
  HOLD if NOT (float_pass AND reconcile_pass).
  ── pyramid is now a PURE DIAGNOSTIC (de-escalated from a hard gate). ──
  The user's standing rule: "L4 ko hold nahi kar sakte — L4 ko hold karna matlab
  session draw rokna, jo system ki transparency ko users ke saamne compromise
  karti hai."  Freezing the whole weekly draw because an L4 backlog looks
  unsustainable is the WRONG remedy — it stops draws users can see, which
  destroys transparency, and it does NOT actually drain L4 (a held L4 only ever
  leaves by WINNING).  So the pyramid sustainability check NO LONGER blocks the
  draw.  It is computed with a CORRECTED forward projection (see below) and
  surfaced as a diagnostic + the L4→L12 forward-cascade trajectory, so the
  re-assessment SHOWS where the math leads if L3/L4 are never made winners — but
  the draw ALWAYS proceeds.
  purity_pass / level_advance_pass remain diagnostics as before.
  float_pass (never pay more than the float holds) and reconcile_pass (never
  deploy impossible/inconsistent data) stay HARD — they are genuine money/data
  safety, not throughput throttles, and in healthy operation they PASS.

PROJECTION CORRECTION (Jun-22):
  The old projection under-counted L4-clearing because it only credited pools that
  were ALREADY exactly 12/12 right now, treating every partial pool as if it would
  never draw.  That manufactured a phantom "L4 can never drain" backlog and tripped
  a false HOLD.  The corrected projection treats a pool as PAUSED/STUCK under EXACTLY
  ONE condition (the user's rule): paid-waitlist == 0 AND the pool can be neither a
  merge donor NOR a merge receiver.  Otherwise the pool is projected to refill (from
  the waitlist) or merge into a drawable 12/12 pool, so its L4 is projected-clearable.

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
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# WeeklyPaymentStatus needed for the corrected pause-pool projection (Jun-22): a
# partial pool counts as "will refill & draw" only while PAID waitlist supply exists.
from app.models.user import User, UserStatus, WeeklyPaymentStatus
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

# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# AUTO-DEPLOY decision weights (Task 3, Jun-21).  When the admin is unavailable at
# T-0H and the toggle is ON, auto_deploy_resolve_hold() scores every deployable
# candidate option and picks the LEAST-BAD by FUTURE-health projection.
#
#   score(opt) = (SOLVENCY_WEIGHT if solvent else 0)
#                + headroom_inr                                  # float cushion (or −shortfall)
#                − PYRAMID_PENALTY_INR × held_L4_over_band       # backlog beyond sustain band
#
# AUTODEPLOY_SOLVENCY_WEIGHT is deliberately astronomical so that ANY solvent
# option always outranks ANY insolvent one ("solvency heavily weighted so any safe
# option always wins" — locked Q2).  Among solvent options the larger float cushion
# and the smaller held-L4 overage win (favouring FUTURE projections — the user's
# explicit concern that leaving L4 undrawn damages future health).
AUTODEPLOY_SOLVENCY_WEIGHT = 10 ** 15   # ₹-equivalent; dwarfs any real headroom/penalty
AUTODEPLOY_PYRAMID_PENALTY_INR = 5_000  # per held-L4 member beyond the sustainable band

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
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Jun-22 — pyramid DE-ESCALATED to a pure diagnostic and REMOVED from the
        # hard-gate set.  A pyramid concern must NEVER drive a HOLD (= stop the
        # session draw = break user-facing transparency).  Only float-solvency and
        # reconcile — genuine money/data-safety gates — remain hard.
        """The hard gates (float/reconcile) that failed — these drive the HOLD."""
        return [
            name for name, ok in (
                ("float", self.float_pass),
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
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
#  CORRECTED L4-CLEARING PROJECTION (Jun-22) — the pause-pool rule + forward cascade
#
#  The user's diagnosis, made law: the old projection mis-counted how many flagged
#  L4 can actually drain, because it only credited pools that were ALREADY 12/12 at
#  T-2H and silently wrote off every partial pool.  In a healthy system those partial
#  pools refill from the paid waitlist (or consolidate via the donor↔receiver merger)
#  and DO draw.  Writing them off manufactured a phantom backlog → a false pyramid
#  HOLD → the session draw was frozen (transparency broken).
#
#  THE RULE (verbatim intent): "projection me pause pool ka option SIRF EK hi condition
#  me rakho — jab waitlist me member ZERO ho AND pool merge ke time na donor ban sake
#  na receiver."  Everywhere else a pool is projected as drawable.
# ─────────────────────────────────────────────────────────────────────────────

def _paid_waitlist_count(db: Session) -> int:
    """Live PAID waitlist supply — members who can refill a partial pool to 12/12."""
    return int(
        db.query(func.count(User.id)).filter(
            User.status                == UserStatus.Waitlist,
            User.weekly_payment_status == WeeklyPaymentStatus.Paid,
        ).scalar() or 0
    )


def _project_stuck_l4(db: Session) -> tuple[int, int, dict]:
    """
    Project how many flagged L4 are GENUINELY un-clearable vs how many WILL drain.

    Mechanics this honours:
      • A flagged-L4 pool is MERGE-IMMUNE (the condensation core never uses a
        contains_flagged_l4 pool as donor or receiver — waitlist.py).  So such a pool
        can become drawable in only one way: REFILL to 12/12 from the paid waitlist,
        after which its L4 clears via an SDE sub-draw.
      • Therefore a flagged-L4 pool is projected STUCK under EXACTLY the user's single
        condition: it is not already full AND the paid waitlist is empty (no refill)
        AND it cannot merge (it is flagged ⇒ cannot donate or receive).  A 12/12
        flagged pool is never stuck (it draws this cycle); a partial flagged pool is
        stuck ONLY when paid-waitlist == 0.

    Returns (projected_stuck_l4, projected_clearable_l4, breakdown).  Pure read pass.
    """
    paid_wl = _paid_waitlist_count(db)

    # Live member headcount per pool (Active only) — to know which flagged pools are
    # already full (draw now) vs partial (need refill).
    live_counts = dict(
        db.query(User.current_pool_id, func.count(User.id))
        .filter(User.status == UserStatus.Active, User.current_pool_id.isnot(None))
        .group_by(User.current_pool_id)
        .all()
    )
    # Flagged-L4 count per pool (the L4 members each flagged pool is carrying).
    flagged_per_pool = dict(
        db.query(User.current_pool_id, func.count(User.id))
        .filter(
            User.status         == UserStatus.Active,
            User.current_level  == 4,
            User.sde_required    == True,          # noqa: E712
            User.current_pool_id.isnot(None),
        )
        .group_by(User.current_pool_id)
        .all()
    )

    flagged_pool_ids = [pid for pid, n in flagged_per_pool.items() if n > 0]
    flagged_pools = (
        db.query(Pool).filter(Pool.id.in_(flagged_pool_ids)).all()
        if flagged_pool_ids else []
    )

    stuck = 0
    clearable = 0
    full_pools = partial_drawable_pools = stuck_pools = 0
    for p in flagged_pools:
        n_l4   = int(flagged_per_pool.get(p.id, 0))
        live   = int(live_counts.get(p.id, 0))
        is_full = (live >= POOL_CAPACITY)
        # The single pause condition: partial AND no waitlist refill AND can't merge.
        # A flagged pool is merge-immune ⇒ donor==receiver==False ⇒ the merge clause
        # is always True for it, so the gate collapses to (partial AND paid_wl == 0).
        will_refill_or_full = is_full or (paid_wl > 0)
        if will_refill_or_full:
            clearable += n_l4
            if is_full:
                full_pools += 1
            else:
                partial_drawable_pools += 1
        else:
            stuck += n_l4
            stuck_pools += 1

    breakdown = {
        "paid_waitlist": paid_wl,
        "flagged_pools_total": len(flagged_pools),
        "flagged_pools_full_draw_now": full_pools,
        "flagged_pools_partial_will_refill": partial_drawable_pools,
        "flagged_pools_stuck_deadend": stuck_pools,
        "projected_clearable_l4": clearable,
        "projected_stuck_l4": stuck,
        "pause_condition": "paid_waitlist==0 AND not(donor) AND not(receiver)",
    }
    return stuck, clearable, breakdown


def _project_level_cascade(stuck_high_tier: int, l3_inflow: int, *, max_level: int = 12) -> dict:
    """
    FORWARD LEVEL-CASCADE PROJECTION (virtual — diagnostic only).

    The user's rule: "uske baad projection me ye daalo — L4 agar clear nahi hua, IF
    SDE and other maturity protection hold and avoided, THEN L4→L5→L6→L7→…→L12, taaki
    projection me dikhe re-assessment ko ki calculations kahan tak le jaa sakti hain
    agar yahi par L3/L4 ko winner nahi banaya gaya toh."

    Model: the GENUINELY-stuck high-tier cohort (pools dead-ended per _project_stuck_l4)
    does not vanish if it is never made a winner.  If the SDE/maturity protection that
    HOLDS it at its level is itself avoided/exhausted, the cohort advances one rung each
    maturity cycle, while fresh L3 keep advancing into L4 behind it.  We roll that
    forward rung by rung from L4 up to L{max_level} and report the per-rung projected
    population, so the re-assessment SEES the runaway.

    IMPORTANT: the REAL engine caps at L6 (SDE Ext-II/III forced-exit valves clear L5
    and L6).  Rungs L7..L{max_level} are VIRTUAL projection levels shown ONLY to expose
    where the math runs if high-tier is never won — the engine never creates them.
    """
    max_level = max(6, int(max_level))
    rungs = list(range(4, max_level + 1))          # L4 .. L12
    ladder = {f"L{lvl}": 0 for lvl in rungs}
    if stuck_high_tier <= 0 and l3_inflow <= 0:
        return {
            "ladder": ladder, "terminal_level": "L4", "cycles_modelled": 0,
            "l3_inflow_per_cycle": int(max(0, l3_inflow)),
            "note": "No stuck high-tier and no L3 inflow — cascade is dormant.",
            "virtual_levels": [f"L{l}" for l in rungs if l > 6],
        }

    # Seed: the stuck cohort sits at L4 today.
    ladder["L4"] = int(max(0, stuck_high_tier))
    inflow = int(max(0, l3_inflow))
    cycles = len(rungs) - 1                          # L4→L5→…→L12  ⇒ (max_level-4) shifts
    terminal = 4
    for _ in range(cycles):
        # Everyone climbs one rung (top rung L{max_level} is the terminal pile-up).
        new_ladder = {f"L{lvl}": 0 for lvl in rungs}
        for lvl in rungs:
            cur = ladder[f"L{lvl}"]
            if cur <= 0:
                continue
            tgt = min(lvl + 1, max_level)
            new_ladder[f"L{tgt}"] += cur
            if tgt > terminal:
                terminal = tgt
        # Fresh L3 advance into L4 behind the climbing cohort.
        new_ladder["L4"] += inflow
        ladder = new_ladder

    return {
        "ladder": ladder,
        "terminal_level": f"L{terminal}",
        "cycles_modelled": cycles,
        "l3_inflow_per_cycle": inflow,
        "virtual_levels": [f"L{l}" for l in rungs if l > 6],
        "note": (
            f"If the {stuck_high_tier} dead-ended high-tier member(s) are never made "
            f"winners and the SDE/maturity hold is avoided, the cohort climbs "
            f"L4→…→L{max_level} over {cycles} maturity cycle(s); fresh L3 (+{inflow}/cycle) "
            f"keep feeding L4. Rungs above L6 are VIRTUAL — they show the runaway, the "
            f"engine itself force-exits at L5/L6 via SDE Ext-II/III."
        ),
    }


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

    # ── R3/R4b pyramid-sustainability (DIAGNOSTIC, Jun-22 — NO LONGER A HARD GATE) ─
    # Engine mechanics (draw.py / _advance_survivor_level): draw winners EXIT
    # (Eliminated_Won); the 10 survivors each advance +1 level — EXCEPT a flagged
    # L4 (current_level==4 AND sde_required) is HELD at L4 (Case-E true defer) and
    # L5/L6 are held.  So an L4 can only LEAVE the system by WINNING (an SDE upper
    # draw, or a regular high-tier draw).
    #
    # WHY THIS NO LONGER BLOCKS (user's standing rule): freezing the whole weekly draw
    # because the L4 backlog looks unsustainable is the WRONG remedy — it stops draws
    # users can see (breaks transparency) and does not drain L4 anyway.  So we COMPUTE
    # the sustainability picture with a CORRECTED projection and surface it as a
    # diagnostic + forward cascade; pyramid_pass NEVER drives the verdict (see hard_ok).
    #
    # flagged_l4_now is set by STEP 3 flag_l4_members earlier in this same prep
    # cycle, so at re-assessment time it is the exact flagged-L4 population.
    flagged_l4_now = int(
        db.query(func.count(User.id)).filter(
            User.status == UserStatus.Active,
            User.current_level == 4,
            User.sde_required == True,   # noqa: E712
        ).scalar() or 0
    )
    l4_now         = member_pyramid["L4"]
    l3_now         = member_pyramid["L3"]
    l4_cleared     = winner_pyramid["L4"]                 # SDE upper + regular L4 high winners THIS cycle
    # forward inflow (diagnostic): L3 survivors advancing into L4 next week
    l3_advancing   = max(0, l3_now - winner_pyramid["L3"])

    # CORRECTED PROJECTION (the pause-pool rule): a flagged-L4 pool is "stuck" ONLY
    # when it is partial AND there is no paid-waitlist refill AND it cannot merge
    # (flagged ⇒ merge-immune).  Everything else refills/merges and DOES draw.  So the
    # genuinely-unsustainable backlog is the dead-ended count, NOT (flagged − this
    # week's six).  This is what kills the phantom backlog that used to false-HOLD.
    projected_stuck_l4, projected_clearable_l4, _stuck_breakdown = _project_stuck_l4(db)
    # The realistic forward backlog = only the dead-ended members (with healthy
    # waitlist this is ~0).  Floor at 0; never below what this cycle already clears.
    l4_backlog_after = int(projected_stuck_l4)
    # Clearing power now reflects the projected drainable L4 (refill+merge aware), not
    # just the handful of pools that happened to be 12/12 at this instant.
    clear_capacity = max(l4_cleared, sde_draws, projected_clearable_l4, 1)
    # Diagnostic-only verdict (does NOT block): sustainable when nothing is dead-ended,
    # or the dead-ended backlog stays within the (now realistic) clear band.
    pyramid_pass   = (
        projected_stuck_l4 == 0
        or l4_backlog_after <= clear_capacity * PYRAMID_SUSTAIN_MULT
    )

    # FORWARD LEVEL-CASCADE (virtual, diagnostic): where the math runs if the stuck
    # high-tier are never made winners — L4→L5→…→L12 (user's explicit ask).
    level_cascade = _project_level_cascade(projected_stuck_l4, l3_advancing, max_level=12)

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

    # ── VERDICT (locked decision #2 — REVISED Jun-22) ────────────────────────
    # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    # pyramid REMOVED from the verdict — it is now a pure diagnostic and must NEVER
    # hold the draw (= stop a session = break transparency).  Only float-solvency
    # (never pay more than the float holds) and reconcile (never deploy impossible
    # data) — genuine money/data safety — can drive a HOLD.
    hard_ok = float_pass and reconcile_pass
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
        # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
        # Jun-22 — DIAGNOSTIC (severity "warning"): this NEVER holds the draw.  It
        # reports ONLY the genuinely dead-ended L4 (the corrected projected_stuck_l4 —
        # pools with no waitlist refill that also cannot merge) and the L4→L12 forward
        # cascade, so the admin SEES where the math runs if those stuck members are
        # never won — while the session draw still goes ahead.
        # how many extra SDE sub-draws would bring the dead-ended backlog within band
        target_clear = -(-l4_backlog_after // max(int(PYRAMID_SUSTAIN_MULT), 1))  # ceil
        extra_sde    = max(1, int(target_clear) - clear_capacity)
        corrected_plan.append({
            "gate": "pyramid",
            "severity": "warning",
            "finding": (
                f"{projected_stuck_l4} flagged L4 are in DEAD-ENDED pools (no paid-"
                f"waitlist refill AND cannot merge) so they cannot drain — vs "
                f"{projected_clearable_l4} that refill/merge and DO draw (clear band ≤ "
                f"{int(clear_capacity*PYRAMID_SUSTAIN_MULT)}). If never won, this cohort "
                f"cascades {level_cascade.get('ladder', {}).get('L4', 0)}→… up to "
                f"{level_cascade.get('terminal_level', 'L12')} (see forward cascade). "
                f"The draw is NOT held — this is a diagnostic only."
            ),
            "action": (
                f"Unblock the dead-end, do NOT stop the draw: inject paid-waitlist "
                f"supply (so the stuck pools refill to 12/12 and their L4 clears via "
                f"SDE), or admit more L1, or add ≈{extra_sde} SDE sub-draw(s); slowing "
                f"L3→L4 advancement also relieves the inflow feeding the cascade."
            ),
            "params": {
                "flagged_l4_now": flagged_l4_now,
                "l4_cleared": l4_cleared,
                "projected_stuck_l4": int(projected_stuck_l4),
                "projected_clearable_l4": int(projected_clearable_l4),
                "backlog_after": l4_backlog_after,
                "clear_capacity": clear_capacity,
                "extra_sde_subdraws": int(extra_sde),
                "stuck_breakdown": _stuck_breakdown,
                "forward_cascade": level_cascade,
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
            # SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
            # Jun-22 — diagnostic-only block.  l4_backlog_after now = projected_stuck_l4
            # (dead-ended only); clear_capacity is refill/merge-aware.  These keys are
            # kept stable because auto_deploy_resolve_hold reads them.
            "is_diagnostic_only": True,
            "blocks_draw": False,
            "flagged_l4_now": flagged_l4_now,
            "l4_now": l4_now, "l3_now": l3_now,
            "l4_cleared": l4_cleared, "l3_advancing": l3_advancing,
            "projected_stuck_l4": int(projected_stuck_l4),
            "projected_clearable_l4": int(projected_clearable_l4),
            "l4_backlog_after": l4_backlog_after, "clear_capacity": clear_capacity,
            "sustain_mult": PYRAMID_SUSTAIN_MULT,
            "stuck_breakdown": _stuck_breakdown,
            "forward_cascade": level_cascade,
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


# ─────────────────────────────────────────────────────────────────────────────
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# AUTO-DEPLOY (Task 3, Jun-21) — resolve a re-assessment HOLD WITHOUT a human when
# the admin is unavailable at T-0H and the master toggle is ON.
#
# The user's spec: "agar user unavailable h to best condition with projection ...
# wo choose kre — chahe pre-built draw result release krna pade (agar better h), ya
# re-assesser ka achcha option."  i.e. pick the LEAST-BAD deployable option by
# FUTURE-health projection — either release the prepared draw as-is, OR apply the
# re-assessor's pyramid-safe L4-defer first — and deploy it automatically.
#
# Two helpers:
#   defer_staged_sde_l4()   — surgically defer the newest staged L4 sub-draws so the
#                             projected payout drops below the available float.
#   auto_deploy_resolve_hold() — the decision engine (scores + applies the choice).
# ─────────────────────────────────────────────────────────────────────────────

def _autodeploy_score(*, solvent: bool, headroom_inr: int, overage: int) -> float:
    """
    Project-forward score for one deployable candidate.  Solvency DOMINATES (locked
    Q2 — "solvency heavily weighted so any safe option always wins"): a solvent
    option gets a flat astronomical base, so it always outranks any insolvent one
    regardless of headroom.  Among SOLVENT options the headroom term is intentionally
    NOT added — so freeing extra float by deferring more L4 is NEVER rewarded once
    the draw is already solvent (this honours the user's concern that leaving L4
    undrawn damages future projections: don't defer L4 you don't have to).  The held-
    L4 over-band penalty then makes the option that keeps the pyramid healthiest win.
    Among INSOLVENT options (when no safe option is reachable) the raw headroom
    (= −shortfall) ranks the least-bad, but the money-safety floor still refuses to
    auto-pay an insolvent draw.
    """
    base = float(AUTODEPLOY_SOLVENCY_WEIGHT) if solvent else float(headroom_inr)
    return base - AUTODEPLOY_PYRAMID_PENALTY_INR * float(overage)


def defer_staged_sde_l4(db: Session, week_id: str, n: int) -> dict:
    """
    Surgically DEFER the ``n`` most-recently-staged L4 SDE sub-draws for ``week_id``
    so this week's projected payout drops (float relief).  Deferred L4 members stay
    Active + flagged in their (still-locked) pool and roll to next cycle — they are
    NOT cleared this week, NOT demoted, NOT touched financially.

    SAFETY / money-conservation:
      • Defers the NEWEST staged sub-draws first (highest session, highest sub-draw)
        so the OLDEST / most-overdue L4 clearances are the ones KEPT — exactly the
        opposite of growing a stale backlog.
      • Only deletes STAGED (executed=False) checkpoints — never an executed one.
      • Leaves pool.draw_completed_this_week=True: the pool stays LOCKED for this
        cycle (the main draw will NOT regular-draw it) and post_draw_cleanup resets
        the lock so next week's preparation re-flags + re-stages the held L4.  No
        tokens, no exits, no level changes — staging never moved money in the first
        place (two-phase commit), so removing a staged checkpoint moves none either.
      • Recomputes each touched session's counters from the SURVIVING checkpoints so
        the audit trail stays internally consistent (planned == #checkpoints,
        total_payout == Σ surviving).

    Caller owns the transaction (this only flushes).  Returns
    {"deferred", "checkpoint_ids", "freed_payout_inr"}.
    """
    from app.models.sde_session import SDESession, SDECheckpoint

    if n <= 0:
        return {"deferred": 0, "checkpoint_ids": [], "freed_payout_inr": 0}

    session_ids = [
        sid for (sid,) in
        db.query(SDESession.id).filter(SDESession.week_id == week_id).all()
    ]
    if not session_ids:
        return {"deferred": 0, "checkpoint_ids": [], "freed_payout_inr": 0}

    staged = (
        db.query(SDECheckpoint)
        .join(SDESession, SDECheckpoint.session_id == SDESession.id)
        .filter(
            SDESession.week_id        == week_id,
            SDECheckpoint.executed    == False,   # noqa: E712 — staged only
            SDECheckpoint.upper_winner_level == 4,  # defer L4 upper sub-draws
        )
        .order_by(
            SDESession.session_number.desc(),
            SDECheckpoint.sub_draw_number.desc(),
        )
        .all()
    )
    to_defer = staged[: int(n)]
    if not to_defer:
        return {"deferred": 0, "checkpoint_ids": [], "freed_payout_inr": 0}

    freed = Decimal("0")
    deferred_ids: list[int] = []
    touched_sessions: set[int] = set()
    for cp in to_defer:
        freed += (cp.upper_payout_inr or Decimal("0")) + (cp.lower_payout_inr or Decimal("0"))
        deferred_ids.append(int(cp.id))
        touched_sessions.add(int(cp.session_id))
        db.delete(cp)
    db.flush()

    # Re-truth each touched session from the survivors.
    for sid in touched_sessions:
        survivors = (
            db.query(SDECheckpoint).filter(SDECheckpoint.session_id == sid).all()
        )
        sess = db.query(SDESession).filter(SDESession.id == sid).first()
        if sess is None:
            continue
        sess.l4_count_planned   = len(survivors)
        sess.l4_count_completed = min(int(sess.l4_count_completed or 0), len(survivors))
        sess.total_payout_inr   = sum(
            (c.upper_payout_inr or Decimal("0")) + (c.lower_payout_inr or Decimal("0"))
            for c in survivors
        )
    db.flush()

    _logger.warning(
        "[AUTO-DEPLOY] deferred %d staged L4 SDE sub-draw(s) for week %s "
        "(freed ₹%s; checkpoints=%s).",
        len(to_defer), week_id, int(freed), deferred_ids,
    )
    return {
        "deferred": len(to_defer),
        "checkpoint_ids": deferred_ids,
        "freed_payout_inr": int(freed),
    }


def _staged_l4_payouts_newest_first(db: Session, week_id: str) -> list[int]:
    """Per-sub-draw (upper+lower) payout of every STAGED L4 sub-draw, ordered the
    way defer_staged_sde_l4 would remove them (newest first)."""
    from app.models.sde_session import SDESession, SDECheckpoint
    rows = (
        db.query(SDECheckpoint)
        .join(SDESession, SDECheckpoint.session_id == SDESession.id)
        .filter(
            SDESession.week_id        == week_id,
            SDECheckpoint.executed    == False,   # noqa: E712
            SDECheckpoint.upper_winner_level == 4,
        )
        .order_by(
            SDESession.session_number.desc(),
            SDECheckpoint.sub_draw_number.desc(),
        )
        .all()
    )
    return [
        int((r.upper_payout_inr or 0) + (r.lower_payout_inr or 0))
        for r in rows
    ]


def auto_deploy_resolve_hold(
    db: Session,
    week_id: str,
    *,
    triggered_by: str = "auto_deploy",
) -> dict:
    """
    AUTO-DEPLOY decision engine (Task 3).  Called at T-0H when the master toggle is
    ON and an admin has NOT acted on an active re-assessment HOLD.  Picks the LEAST-
    BAD deployable option by future-health projection and, if it is SAFE, clears the
    HOLD automatically (recording approved_by=triggered_by + full rationale).

    Candidate options:
      • deploy_prepared — release the staged draw as-is.
      • defer_l4        — defer the minimum number of newest staged L4 sub-draws to
                          restore solvency (only when the HOLD is float-driven; this
                          is "the re-assessor's better option").

    MONEY-SAFETY FLOOR (overrides "always deploy"):
      • A reconcile (impossible-data) HOLD is NEVER auto-deployed — the projection is
        internally inconsistent; a human must investigate.
      • The chosen option must be SOLVENT to auto-deploy.  If even the best reachable
        option cannot cover the payout from the float, the engine REFUSES to release
        real money it does not have and keeps the HOLD for the admin.  (Among solvent
        options it always deploys the least-bad — Q2 fully honoured; it only declines
        when no safe option exists at all.)

    Returns a structured result dict (resolved / action / reason / scores / …).  Never
    raises — any internal error fails CLOSED (keeps the HOLD) so a broken engine can
    never wave money out the door.
    """
    from datetime import datetime, timezone

    out: dict = {
        "resolved": False, "action": "none", "reason": "",
        "week_id": week_id, "report_id": None,
        "deferred": 0, "scores": {}, "rationale": "",
        "triggered_by": triggered_by,
    }
    try:
        hold = get_active_hold(db, week_id)
        if hold is None:
            out.update(resolved=True, action="none", reason="no_active_hold")
            return out

        now = datetime.now(timezone.utc)

        # ── Fresh, read-only assessment of the CURRENT data ──────────────────────
        fresh = run_reassessment(db, week_id)

        # (0) Conditions already cleared since T-2H → just deploy the prepared draw.
        if fresh.verdict == "PASS":
            fresh.audit["auto_deploy"] = {
                "action": "fresh_pass", "triggered_by": triggered_by,
            }
            row = persist_report(db, fresh)
            row.approved    = True
            row.approved_by = triggered_by
            row.approved_at = now
            row.admin_note  = (
                "AUTO-DEPLOY: a fresh re-assessment of the current data PASSED all "
                "hard gates — the earlier HOLD no longer applies; the prepared draw "
                "is released automatically."
            )
            db.commit()
            db.refresh(row)
            out.update(resolved=True, action="fresh_pass",
                       reason="fresh_assessment_passed", report_id=row.id,
                       rationale=row.admin_note)
            _logger.warning("[AUTO-DEPLOY] week %s — fresh re-assessment PASSED; "
                            "released prepared draw (report #%s).", week_id, row.id)
            return out

        # (1) Impossible-data HOLD is never auto-deployable.
        if not fresh.reconcile_pass:
            out.update(resolved=False, action="escalate",
                       reason="reconcile_fail_not_auto_deployable")
            _logger.critical(
                "[AUTO-DEPLOY] week %s — reconcile gate FAILED (impossible/inconsistent "
                "data). Refusing to auto-deploy; HOLD kept for admin investigation.",
                week_id,
            )
            return out

        # ── Pull the exact gate metrics from the fresh audit ─────────────────────
        fa = fresh.audit
        P  = int(fa["float"]["projected_payout_inr"])
        F  = int(fa["float"]["available_float_inr"])
        R  = int(fa["float"]["reserve_inr"])
        FL = int(fa["pyramid"]["flagged_l4_now"])
        C  = int(fa["pyramid"]["l4_cleared"])
        S  = int(fa["pyramid"]["clear_capacity"])   # already = max(l4_cleared, sde_draws, 1)
        B0 = int(fa["pyramid"]["l4_backlog_after"])

        def _overage(backlog: int, capacity: int) -> int:
            return max(0, int(backlog) - int(capacity * PYRAMID_SUSTAIN_MULT))

        # ── Candidate A — deploy the prepared draw as-is ─────────────────────────
        prep_solvent  = bool(fresh.float_pass)
        prep_headroom = F - R - P
        prep_overage  = _overage(B0, S)
        prep_score    = _autodeploy_score(
            solvent=prep_solvent, headroom_inr=prep_headroom, overage=prep_overage,
        )

        candidates = {"deploy_prepared": {
            "score": prep_score, "solvent": prep_solvent,
            "headroom_inr": prep_headroom, "overage": prep_overage, "defer": 0,
        }}

        # ── Candidate B — defer newest L4 to restore solvency (float HOLD only) ───
        # Deferring only relieves the FLOAT gate; it WORSENS the pyramid, so we only
        # consider it when the draw is actually insolvent (a pyramid-only HOLD must
        # NOT defer — holding/deferring L4 is the very thing that hurts the future).
        if not prep_solvent:
            staged_payouts = _staged_l4_payouts_newest_first(db, week_id)
            if staged_payouts:
                freed = 0
                k = 0
                solvent_at_k = False
                for pay in staged_payouts:
                    freed += pay
                    k += 1
                    if (P - freed) + R <= F:
                        solvent_at_k = True
                        break
                # post-defer projection (analytical; the real verdict is re-checked
                # after the actual defer below)
                new_P       = P - freed
                new_C       = max(0, C - k)
                new_backlog = max(0, FL - new_C)        # k fewer cleared ⇒ +k backlog
                new_cap     = max(new_C, 1)
                defer_score = _autodeploy_score(
                    solvent=solvent_at_k,
                    headroom_inr=F - R - new_P,
                    overage=_overage(new_backlog, new_cap),
                )
                candidates["defer_l4"] = {
                    "score": defer_score, "solvent": solvent_at_k,
                    "headroom_inr": F - R - new_P,
                    "overage": _overage(new_backlog, new_cap), "defer": k,
                }

        out["scores"] = candidates

        # ── Pick the least-bad (highest score); tie ⇒ prefer deploy_prepared ─────
        best_name = max(
            candidates,
            key=lambda nm: (candidates[nm]["score"], nm == "deploy_prepared"),
        )
        best = candidates[best_name]

        # ── MONEY-SAFETY FLOOR — never auto-pay an insolvent draw ────────────────
        if not best["solvent"]:
            out.update(resolved=False, action="escalate",
                       reason="no_solvent_option_admin_required")
            _logger.critical(
                "[AUTO-DEPLOY] week %s — NO solvent deployable option (best=%s "
                "score=%.1f). Refusing to auto-release an insolvent draw; HOLD kept "
                "for admin. payout=₹%d float=₹%d.",
                week_id, best_name, best["score"], P, F,
            )
            return out

        rationale = (
            f"AUTO-DEPLOY [{triggered_by}] week {week_id}: chose '{best_name}' as the "
            f"least-bad-by-projection deployable option (admin unavailable at T-0H). "
            f"Scores: " + "; ".join(
                f"{nm}={c['score']:.0f}(solvent={c['solvent']},"
                f"headroom=₹{c['headroom_inr']},overband={c['overage']},defer={c['defer']})"
                for nm, c in candidates.items()
            ) + f". Float: payout=₹{P} float=₹{F} reserve=₹{R}. "
            f"Pyramid: flagged_L4={FL} cleared={C} backlog_after={B0}."
        )

        # ── Apply: deploy_prepared ───────────────────────────────────────────────
        if best_name == "deploy_prepared":
            hold.approved    = True
            hold.approved_by = triggered_by
            hold.approved_at = now
            hold.admin_note  = rationale
            db.commit()
            db.refresh(hold)
            out.update(resolved=True, action="deploy_prepared",
                       reason="prepared_draw_is_least_bad_and_solvent",
                       report_id=hold.id, rationale=rationale)
            _logger.warning(
                "[AUTO-DEPLOY] week %s — released PREPARED draw as least-bad solvent "
                "option (report #%s approved by %s).", week_id, hold.id, triggered_by,
            )
            return out

        # ── Apply: defer_l4 (the re-assessor's better option) ────────────────────
        k = int(best["defer"])
        defer_info = defer_staged_sde_l4(db, week_id, k)
        # Re-assess the ACTUAL post-defer state — the real verdict governs.
        fresh2 = run_reassessment(db, week_id)
        fresh2.audit["auto_deploy"] = {
            "action": "defer_l4", "triggered_by": triggered_by,
            "deferred": defer_info["deferred"],
            "freed_payout_inr": defer_info["freed_payout_inr"],
        }
        row2 = persist_report(db, fresh2)
        if fresh2.verdict == "PASS":
            row2.approved    = True
            row2.approved_by = triggered_by
            row2.approved_at = now
            row2.admin_note  = (
                rationale
                + f" Applied: deferred {defer_info['deferred']} newest L4 SDE sub-draw(s) "
                  f"(freed ₹{defer_info['freed_payout_inr']}); post-defer re-assessment "
                  f"PASSED — releasing the reduced draw."
            )
            db.commit()
            db.refresh(row2)
            out.update(resolved=True, action="defer_l4",
                       reason="deferred_l4_restored_solvency",
                       report_id=row2.id, deferred=defer_info["deferred"],
                       rationale=row2.admin_note)
            _logger.warning(
                "[AUTO-DEPLOY] week %s — deferred %d L4 SDE sub-draw(s); post-defer "
                "re-assessment PASSED (report #%s approved by %s).",
                week_id, defer_info["deferred"], row2.id, triggered_by,
            )
            return out

        # Projection disagreed with reality — fail CLOSED.  The defer already reduced
        # the payout (conservative), but we do NOT auto-approve a still-HOLD result.
        db.commit()  # persist fresh2 as an (unapproved) HOLD for the audit trail
        db.refresh(row2)
        out.update(resolved=False, action="defer_l4_still_hold",
                   reason="post_defer_still_hold_admin_required",
                   report_id=row2.id, deferred=defer_info["deferred"])
        _logger.critical(
            "[AUTO-DEPLOY] week %s — deferred %d L4 but post-defer re-assessment STILL "
            "HOLDS (report #%s). Defer stands (payout reduced); HOLD kept for admin.",
            week_id, defer_info["deferred"], row2.id,
        )
        return out

    except Exception as exc:
        # Fail CLOSED — never let an engine error clear a HOLD.
        try:
            db.rollback()
        except Exception:
            pass
        _logger.critical(
            "[AUTO-DEPLOY] week %s — engine error; failing CLOSED (HOLD kept): %s",
            week_id, exc, exc_info=True,
        )
        out.update(resolved=False, action="error", reason=f"engine_error: {exc}")
        return out
