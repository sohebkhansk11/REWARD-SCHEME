"""
Draw Priority — Steady-Rule Deterministic Lean  (Q2 rewrite, Jun-23)
====================================================================
A PURE module (no DB reads, no DB writes, no side effects).  It returns a
single, deterministic ``DrawPriorityPlan`` that the rest of the draw pipeline
consumes read-only — one steady rule, every week, regardless of regime.

Q2 — Posture-switching removed (Jun-23 user directive — verbatim:
    "Nahi — posture switching hatao, ek hi steady rule har week chalegi")

The previous design switched between THROUGHPUT / BALANCED / LIABILITY_CONTROL
based on the quant brain's reserve multiplier.  Forensic run a4243fd2 proved
that switching caused feast-or-famine:

  • W1–W4   BALANCED/VELOCITY_CLIFF        → 4–5 draws/week
  • W5–W8   LIABILITY_CONTROL/DRY_PHASE    → freeze + 16/17 draw blowouts
  • W9–W19  LIABILITY_CONTROL/DRY_PHASE    → 11 consecutive zero-draw freezes
  • W20–W21 LIABILITY_CONTROL/DRY_PHASE    → 60-draw + 80-winner blowout
  • W22+    LIABILITY_CONTROL/DRY_PHASE    → 12-week collapse + L5 leak begins

The blowout was driven by ``l4_density_desc`` pool ordering (defensive
LIABILITY_CONTROL preset) draining the densest L4 pools all at once, then
having no waitlist to refill, then having no draws for weeks until inventory
quietly rebuilt — repeat.

Q2 fix: ``compute_draw_priority()`` now ignores the multiplier entirely and
always returns the BALANCED preset (today's production-static config).  The
multiplier is still computed by the quant brain because reserve-pool calcs
elsewhere depend on it, but it no longer steers draw posture.

Design constraints (financial-grade — INVIOLABLE)
-------------------------------------------------
1. **No DB mutation.**  This module only returns a frozen dataclass.
2. **Hard-safety ordering is untouched.**  Ext-II/III L5/L6 clearance still
   runs first; SDE staging→execution order is fixed; only-12/12 eligibility
   is fixed.  This plan now only fixes valve *intensity* + per-pool routing
   cutoffs + pool ordering to ONE deterministic value.
3. **Every number is clamped to a safe band.**  The clamps below are now
   redundant (constants live well inside) but are kept as belt-and-suspenders
   against accidental future edits.
4. **Steady rule == today's production-static BALANCED preset EXACTLY.**
   regular<14, type_a 14–24, sde≥25, cascade 2.0, accel 0.60, pool_order=fifo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # annotation-only import — no runtime cost / cycle
    from app.services.engine_snapshot import SystemSnapshot

_logger = logging.getLogger(__name__)


# ── Safe clamp bands (financial-grade — NO posture may breach these) ──────────
# These are the absolute outer limits.  The per-posture presets below all sit
# inside these bands; the clamp is belt-and-suspenders so that even if a preset
# is mis-edited in future it can never escape the safe envelope.
_REGULAR_MAX_BAND: tuple[float, float] = (8.0, 20.0)   # LPI cutoff: regular → type_a
_SDE_MIN_BAND:     tuple[float, float] = (16.0, 32.0)  # LPI cutoff: type_a → sde
_CASCADE_BAND:     tuple[float, float] = (1.5, 2.5)    # Preventive-L3 trigger
_ACCEL_BAND:       tuple[float, float] = (0.50, 0.70)  # Accel-Dissolution trigger


class DrawPosture(Enum):
    """The three situational leans.  String values flow into telemetry/CSV."""
    THROUGHPUT        = "THROUGHPUT"          # growth — keep regular draws flowing
    BALANCED          = "BALANCED"            # neutral — today's static config
    LIABILITY_CONTROL = "LIABILITY_CONTROL"   # defensive — shed L4+ liability hard


@dataclass(frozen=True)
class DrawPriorityPlan:
    """
    Immutable, read-only situational draw lean for ONE weekly cycle.

    Consumed by:
      • engine_snapshot.decide_pool_draw_type(lpi, plan) — per-pool routing
      • draw.execute_weekly_draw Preventive-L3 pre-pass  — cascade_threshold
      • draw.execute_weekly_draw Accel-Dissolution pre-pass — accel_ratio
      • draw.execute_weekly_draw eligible-pool ordering  — pool_order_key
    """
    posture:           DrawPosture
    regular_max:       float   # LPI <  regular_max          → 'regular'
    type_a_min:        float   # regular_max ≤ LPI < sde_min → 'type_a'  (== regular_max)
    sde_min:           float   # LPI ≥  sde_min              → 'sde'
    cascade_threshold: float   # cascade_risk above this → Preventive-L3 fires
    accel_ratio:       float   # pool L4+ fraction ≥ this → Accelerated Dissolution fires
    pool_order_key:    str     # 'fifo' | 'l4_density_desc'


def _clamp(value: float, lo: float, hi: float) -> float:
    """Hard-clamp a value into [lo, hi].  The financial-grade safety net."""
    return max(lo, min(hi, value))


# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Q2 STEADY-RULE (Jun-23): the constants below are the one-and-only draw lean
# the engine will ever use.  They reproduce the production-static BALANCED
# preset that pre-dated the posture-switching experiment.  Any future tuning
# must be a one-time edit here, NOT a runtime-conditional switch on a
# multiplier / scenario / brain output — that path is what caused W18-W19
# freeze + W20-W21 blowout + W22+ collapse.
_STEADY_REGULAR_MAX:       float = 14.0
_STEADY_SDE_MIN:           float = 25.0
_STEADY_CASCADE_THRESHOLD: float = 2.0
_STEADY_ACCEL_RATIO:       float = 0.60
_STEADY_POOL_ORDER_KEY:    str   = "fifo"


def compute_draw_priority(snap: "SystemSnapshot") -> DrawPriorityPlan:
    """
    Q2 STEADY-RULE: return the one deterministic draw lean for every week.

    PURE: ignores ``snap`` entirely.  The argument is retained for signature
    stability (the single caller in draw.py:766 still passes a snapshot, and
    we don't want to ripple a signature change through unrelated tests).
    Every returned number is still passed through the safe-band clamp — those
    clamps are now belt-and-suspenders against accidental future re-tuning.

    Posture is always ``BALANCED``.  Pool order is always ``fifo``.
    No multiplier-driven switching, no scenario-driven switching.
    """
    # The clamps are no-ops at today's constants but kept as a safety net
    # against accidental constant re-edits that could escape the safe envelope.
    regular_max       = _clamp(_STEADY_REGULAR_MAX,       *_REGULAR_MAX_BAND)
    sde_min           = _clamp(_STEADY_SDE_MIN,           *_SDE_MIN_BAND)
    cascade_threshold = _clamp(_STEADY_CASCADE_THRESHOLD, *_CASCADE_BAND)
    accel_ratio       = _clamp(_STEADY_ACCEL_RATIO,       *_ACCEL_BAND)

    plan = DrawPriorityPlan(
        posture           = DrawPosture.BALANCED,
        regular_max       = regular_max,
        type_a_min        = regular_max,    # type_a band opens exactly where regular closes
        sde_min           = sde_min,
        cascade_threshold = cascade_threshold,
        accel_ratio       = accel_ratio,
        pool_order_key    = _STEADY_POOL_ORDER_KEY,
    )
    _logger.debug(
        "compute_draw_priority: STEADY rule (Q2) → "
        "regular<%.0f type_a<%.0f sde≥%.0f cascade>%.2f accel≥%.2f order=%s",
        regular_max, sde_min, sde_min,
        cascade_threshold, accel_ratio, _STEADY_POOL_ORDER_KEY,
    )
    return plan
