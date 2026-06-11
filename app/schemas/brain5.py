"""
Brain 5 data-transfer objects
==============================
All dataclasses here are pure Python — no SQLAlchemy, no Pydantic.
They carry computed Brain 5 state between service layers without
touching the DB session.
"""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LevelDistribution:
    """Snapshot of active member counts per level at a given instant."""
    l1: int = 0
    l2: int = 0
    l3: int = 0
    l4: int = 0
    l5: int = 0
    l6: int = 0

    @property
    def total(self) -> int:
        return self.l1 + self.l2 + self.l3 + self.l4 + self.l5 + self.l6

    @property
    def pressure_count(self) -> int:
        """Numerator of LPI: members at L3 and above."""
        return self.l3 + self.l4 + self.l5 + self.l6

    @property
    def l1l2_count(self) -> int:
        return self.l1 + self.l2

    def as_dict(self) -> dict:
        return {1: self.l1, 2: self.l2, 3: self.l3, 4: self.l4, 5: self.l5, 6: self.l6}


@dataclass
class PoolTypeDecision:
    """
    Brain 5 pool-type routing decision for the current draw cycle.

    Priority hierarchy:
      P1 = SDE         — triggered by ANY L4 existence (hard override) OR LPI ≥ 25
      P2 = TYPE_A      — LPI 14-24% AND L3 members present
      P3 = REGULAR     — LPI < 14%
      P4 = TYPE_B      — fallback when L1/L2 pool is exhausted

    Multiple priorities can be active simultaneously (e.g. some pools get SDE,
    others get TYPE_A, remainder get REGULAR).
    """
    lpi: float
    dist: LevelDistribution

    # Routing decisions
    p1_sde_active:   bool = False
    p1_sde_reason:   str  = ""    # "hard_override_l4" | "proactive_lpi" | ""
    p2_type_a_active: bool = False
    p3_regular_active: bool = False
    p4_type_b_active:  bool = False

    # SDE-specific
    l4_flagged_count:     int  = 0
    sde_threshold_met:    bool = False   # l1l2_available >= l4_count × 2

    # Type B
    l1l2_exhausted:       bool = False

    def summary(self) -> str:
        parts = []
        if self.p1_sde_active:
            parts.append(f"P1=SDE[{self.p1_sde_reason}]")
        if self.p2_type_a_active:
            parts.append("P2=TYPE_A")
        if self.p3_regular_active:
            parts.append("P3=REGULAR")
        if self.p4_type_b_active:
            parts.append("P4=TYPE_B")
        return " | ".join(parts) if parts else "NO_DRAW"


@dataclass
class SDEDemand:
    """
    Quantified SDE resource requirement for the current draw cycle.

    l4_members: User ORM objects — DO NOT serialize these to JSON directly.
    """
    l4_count:          int
    sessions_needed:   int        # ceil(l4_count / 6)
    l1l2_threshold:    int        # l4_count × 2 — minimum L1/L2 candidates needed
    l4_members:        list       # list[User] — ordered by join_date ASC (FIFO)
    l1l2_available:    int        # actual L1/L2 active members in the system
    clearable_count:   int        # min(l4_count, l1l2_available // 2)
    overflow_count:    int        # l4_count - clearable_count
    overflow_requires_admin: bool # True when overflow_count > 0


@dataclass
class PoolRedistribution:
    """Record of one inter-pool L4 member move during multi-L4 redistribution."""
    user_id:     int
    username:    str
    old_pool_id: int
    old_pool_name: str
    new_pool_id:   int
    new_pool_name: str
    reason:        str   # e.g. "multi_l4_in_pool" — second L4 in same pool moved
