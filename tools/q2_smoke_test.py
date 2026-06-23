"""
Q2 smoke test — Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11
============================================================
Regression gate for the POSTURE-SWITCHING REMOVAL fix (commit ea6510c).
Touches NO database.

WHY
----
Forensic run a4243fd2 proved that switching the draw lean between
THROUGHPUT / BALANCED / LIABILITY_CONTROL based on the quant brain's reserve
multiplier caused the feast-or-famine pattern (freeze weeks -> blowout weeks
-> L5 leak).  Q2's rule: ``compute_draw_priority()`` IGNORES the multiplier
entirely and ALWAYS returns the production-static BALANCED preset with fifo
pool ordering.

This test proves the function is now invariant: no snapshot input — across the
full multiplier band, NaN, None, garbage — can move the posture off BALANCED
or the pool order off fifo, and the four routing/trigger constants are exactly
the production-static values (regular<14, sde>=25, cascade 2.0, accel 0.60).

A green run guarantees the draw pipeline cannot re-enter the posture-switching
regime that drove the W18-W27 collapse.
"""

import os
import sys
import math

# Hard safety — refuse to talk to anything but a throwaway SQLite shell.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
assert "supabase" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q2 smoke test refuses to talk to Supabase."
assert "pooler" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q2 smoke test refuses to talk to a pooler URL."
assert "postgres" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q2 smoke test refuses to talk to Postgres."

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _StubSnap:
    """Minimal stand-in for SystemSnapshot.  compute_draw_priority is PURE and
    never reads the snapshot, but we feed it a wide variety of multiplier-like
    states anyway to prove the output truly does not depend on the input."""
    def __init__(self, multiplier, scenario="STUB"):
        self.reserve_multiplier = multiplier
        self.multiplier         = multiplier
        self.scenario           = scenario


def test_posture_is_always_balanced_fifo() -> None:
    """Across the full input space the plan is ALWAYS BALANCED + fifo."""
    from app.services.draw_priority import compute_draw_priority, DrawPosture
    print("[Q2 #1] posture/order invariance across the multiplier band:")

    inputs = [
        _StubSnap(0.10, "SUSTAINABLE_WAVE"),
        _StubSnap(0.50, "SUSTAINABLE_WAVE"),
        _StubSnap(0.75, "BOOM_GOLDEN_CROSS"),
        _StubSnap(1.00, "NEUTRAL"),
        _StubSnap(1.00, "VELOCITY_CLIFF"),
        _StubSnap(1.50, "FLASH_FLOOD"),
        _StubSnap(2.00, "DRY_PHASE"),
        _StubSnap(2.00, "REFERRAL_LIFELINE"),
        _StubSnap(3.00, "REFERRAL_LIFELINE"),
        _StubSnap(float("nan"), "GARBAGE"),
        _StubSnap(None, "NONE"),
        _StubSnap("garbage", "GARBAGE_STR"),
        None,   # the function ignores snap entirely — even None must be safe
    ]
    ok = True
    for snap in inputs:
        plan = compute_draw_priority(snap)
        good = (plan.posture is DrawPosture.BALANCED and plan.pool_order_key == "fifo")
        flag = "PASS" if good else "FAIL"
        if not good:
            ok = False
        mult = getattr(snap, "multiplier", "—")
        if isinstance(mult, float) and math.isnan(mult):
            mult = "NaN"
        print(f"  [{flag}] mult={mult!s:<8} -> posture={plan.posture.value:<10} "
              f"order={plan.pool_order_key}")
    if not ok:
        raise AssertionError("posture or pool order drifted off BALANCED/fifo")
    print("[Q2 #1] ALL PASS\n")


def test_steady_constants_exact() -> None:
    """The four routing/trigger constants must match the production-static
    BALANCED preset EXACTLY (the values that pre-dated the posture experiment)."""
    from app.services.draw_priority import compute_draw_priority
    print("[Q2 #2] steady routing/trigger constants are exact:")
    plan = compute_draw_priority(_StubSnap(1.00, "NEUTRAL"))
    checks = [
        ("regular_max",       plan.regular_max,       14.0),
        ("type_a_min",        plan.type_a_min,        14.0),   # opens where regular closes
        ("sde_min",           plan.sde_min,           25.0),
        ("cascade_threshold", plan.cascade_threshold, 2.0),
        ("accel_ratio",       plan.accel_ratio,       0.60),
        ("pool_order_key",    plan.pool_order_key,    "fifo"),
    ]
    ok = True
    for name, got, want in checks:
        good = (got == want)
        flag = "PASS" if good else "FAIL"
        if not good:
            ok = False
        print(f"  [{flag}] {name:<18} = {got!r:<8} expected {want!r}")
    if not ok:
        raise AssertionError("steady constants drifted from the production-static preset")
    print("[Q2 #2] ALL PASS\n")


def test_determinism() -> None:
    """Two calls with wildly different inputs return identical plans — the
    plan is a function of NOTHING but the steady constants."""
    from app.services.draw_priority import compute_draw_priority
    print("[Q2 #3] determinism — identical plan regardless of input:")
    a = compute_draw_priority(_StubSnap(0.10, "SUSTAINABLE_WAVE"))
    b = compute_draw_priority(_StubSnap(2.00, "DRY_PHASE"))
    fields = ("posture", "regular_max", "type_a_min", "sde_min",
              "cascade_threshold", "accel_ratio", "pool_order_key")
    ok = True
    for f in fields:
        good = (getattr(a, f) == getattr(b, f))
        flag = "PASS" if good else "FAIL"
        if not good:
            ok = False
        print(f"  [{flag}] {f:<18} low-mult={getattr(a, f)!r}  high-mult={getattr(b, f)!r}")
    if not ok:
        raise AssertionError("plan depends on the multiplier — posture switching is BACK")
    print("[Q2 #3] ALL PASS\n")


if __name__ == "__main__":
    print("=" * 64)
    print("Q2 SMOKE TEST — steady BALANCED posture invariant")
    print("=" * 64)
    test_posture_is_always_balanced_fifo()
    test_steady_constants_exact()
    test_determinism()
    print("=" * 64)
    print("Q2 SMOKE TEST — ALL PASS")
    print("=" * 64)
