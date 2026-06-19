"""
Draw Priority — Quant-Adaptive Situational Lean  (Phase B)
==========================================================
A PURE module (no DB reads, no DB writes, no side effects).  It derives a
``DrawPriorityPlan`` from the atomic ``SystemSnapshot`` the engine already
reads once per cycle, and the rest of the draw pipeline consumes that plan
read-only.

Why this exists
---------------
The user's stress tests showed the engine running a single static draw lean in
every market regime.  The request: make draw-type intensity *situational* —
defensive scenarios should shed L4+ liability harder and route to SDE sooner;
growth scenarios should keep regular throughput high — WITHOUT touching the
hard money-safety ordering.

Design constraints (financial-grade — INVIOLABLE)
-------------------------------------------------
1. **No DB mutation.**  This module only reads scalar fields off the snapshot
   and returns a frozen dataclass.  It can never corrupt pool/payout state.
2. **Hard-safety ordering is untouched.**  Ext-II/III L5/L6 clearance always
   runs first; SDE staging→execution order is fixed; only-12/12 eligibility is
   fixed.  This plan changes only valve *intensity* (cascade / accel triggers),
   per-pool *routing* cutoffs, and eligible-pool *draw order* — never WHICH
   safety draw runs or in what order the safety phases execute.
3. **Every number is clamped to a safe band.**  No posture — however extreme
   the quant multiplier — can push a trigger outside the bands below.  This is
   the guarantee that a misread scenario can never break payout math or starve
   a safety draw.
4. **BALANCED == today's static config EXACTLY.**  In the neutral regime
   (multiplier == 1.00) the returned plan reproduces the current production
   constants (regular<14, type_a 14–24, sde≥25, cascade 2.0, accel 0.60, FIFO).
   So this whole module is a *no-op* unless the quant brain leaves NEUTRAL.

Posture derivation
------------------
Posture comes from the quant reserve multiplier, which the quant brain already
computes by blending velocity / burn-rate / RDR / cascade-risk.  Reusing it
means the draw lean tracks the SAME scenario the reserve logic reacts to (one
brain, one signal — no second, divergent classifier to keep in sync):

    multiplier <= 0.75  → THROUGHPUT          (SUSTAINABLE_WAVE / BOOM_GOLDEN_CROSS)
    multiplier == 1.00  → BALANCED            (NEUTRAL / VELOCITY_CLIFF)
    multiplier >= 1.50  → LIABILITY_CONTROL   (FLASH_FLOOD / DRY_PHASE / REFERRAL_LIFELINE)
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


def compute_draw_priority(snap: "SystemSnapshot") -> DrawPriorityPlan:
    """
    Derive the situational draw lean from the atomic snapshot's quant multiplier.

    PURE: reads only ``snap.multiplier`` (with a safe 1.0 fallback) and returns a
    frozen plan.  Never raises on a missing/odd multiplier — defaults to BALANCED.
    Every returned number is clamped into its safe band before being handed back.
    """
    mult = getattr(snap, "multiplier", 1.0)
    try:
        mult = float(mult)
    except (TypeError, ValueError):
        mult = 1.0

    if mult <= 0.75:
        # Growth regime — keep regular throughput high, relax the shed valves.
        posture                       = DrawPosture.THROUGHPUT
        regular_max, sde_min          = 18.0, 30.0
        cascade_threshold, accel_ratio = 2.5, 0.70
        pool_order_key                = "fifo"
    elif mult >= 1.50:
        # Defensive regime — route to SDE sooner, fire the shed valves earlier,
        # and draw the highest-liability (most L4-dense) pools FIRST.
        posture                       = DrawPosture.LIABILITY_CONTROL
        regular_max, sde_min          = 10.0, 18.0
        cascade_threshold, accel_ratio = 1.5, 0.50
        pool_order_key                = "l4_density_desc"
    else:
        # Neutral regime — EXACT reproduction of today's static production config.
        posture                       = DrawPosture.BALANCED
        regular_max, sde_min          = 14.0, 25.0
        cascade_threshold, accel_ratio = 2.0, 0.60
        pool_order_key                = "fifo"

    # Belt-and-suspenders clamp — no posture can ever escape the safe envelope.
    regular_max       = _clamp(regular_max,       *_REGULAR_MAX_BAND)
    sde_min           = _clamp(sde_min,           *_SDE_MIN_BAND)
    cascade_threshold = _clamp(cascade_threshold, *_CASCADE_BAND)
    accel_ratio       = _clamp(accel_ratio,       *_ACCEL_BAND)

    plan = DrawPriorityPlan(
        posture           = posture,
        regular_max       = regular_max,
        type_a_min        = regular_max,    # type_a band opens exactly where regular closes
        sde_min           = sde_min,
        cascade_threshold = cascade_threshold,
        accel_ratio       = accel_ratio,
        pool_order_key    = pool_order_key,
    )
    _logger.debug(
        "compute_draw_priority: multiplier=%.2f → posture=%s "
        "(regular<%.0f type_a<%.0f sde≥%.0f cascade>%.2f accel≥%.2f order=%s)",
        mult, posture.value, regular_max, sde_min, sde_min,
        cascade_threshold, accel_ratio, pool_order_key,
    )
    return plan
