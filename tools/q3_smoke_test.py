"""
Q3 smoke test — Jun-23 — Soheb Khan User 2 / Sohebkhan.sk11
============================================================
Pure-function verification of the Q3 fixes.  Touches NO database.

  1. compute_dynamic_reserve — must return the lean (pools × 4) floor for
     EVERY scenario / multiplier combination (Q3 steady rule).
  2. waitlist module must import cleanly and expose:
        _rehome_orphans_once, run_merger_refill_converge,
        run_pool_merger_engine, _condense_pools_once
     so the converge driver and the new orphan core are wired up.
  3. run_merger_refill_converge signature must still accept (db, user_prefix,
     max_rounds) — no breaking changes for existing callers.
"""

import os
import sys
import math

# Hard safety — refuse to talk to anything but a throwaway SQLite shell.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
assert "supabase" not in os.environ.get("DATABASE_URL", "").lower()
assert "pooler"   not in os.environ.get("DATABASE_URL", "").lower()
assert "postgres" not in os.environ.get("DATABASE_URL", "").lower()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_compute_dynamic_reserve_is_steady() -> None:
    """For ALL scenario/multiplier inputs, reserve = pools × 4 (Q3 steady rule)."""
    from app.services.ai_quant_engine import compute_dynamic_reserve, HEALTHY_RESERVE_PER_POOL

    # Q3 steady floor: 4/pool, NEVER 12 × multiplier.
    cases = [
        # (pools, multiplier, scenario)
        (10,  0.50, "SUSTAINABLE_WAVE"),
        (10,  0.75, "BOOM_GOLDEN_CROSS"),
        (10,  1.00, "NEUTRAL"),
        (10,  1.00, "VELOCITY_CLIFF"),
        (10,  1.50, "FLASH_FLOOD"),
        (10,  2.00, "DRY_PHASE"),
        (10,  2.00, "REFERRAL_LIFELINE"),
        # Edge cases the brain can produce:
        (0,   2.00, "DRY_PHASE"),         # zero pools → zero reserve
        (74,  2.00, "DRY_PHASE"),         # production state (W22-W27)
        (100, 0.50, "SUSTAINABLE_WAVE"),
        (1,   3.00, "REFERRAL_LIFELINE"), # extreme multiplier ignored
    ]
    print("[Q3 #1] compute_dynamic_reserve — steady-rule smoke:")
    ok = True
    for pools, mult, scen in cases:
        got      = compute_dynamic_reserve(pools, mult, scen)
        expected = pools * HEALTHY_RESERVE_PER_POOL
        flag     = "PASS" if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"  [{flag}] pools={pools:>3}  mult={mult:.2f}  scenario={scen:<20s}  "
              f"reserve={got:>4}  expected={expected}")

    # Sanity: the old (broken) formula would have produced pools × 12 × mult for
    # non-healthy scenarios — confirm we are NOT returning that anymore for the
    # W22-W27 production case (74 pools × 12 × 2.0 = 1776 → would have frozen
    # the waitlist forever).
    broken_old = 74 * 12 * 2.0
    new_steady = compute_dynamic_reserve(74, 2.0, "DRY_PHASE")
    print(f"\n  Production W22-W27 case (74 pools × 12 × 2.0):")
    print(f"    old broken reserve = {broken_old:.0f}  (waitlist could NEVER breach)")
    print(f"    Q3  steady reserve = {new_steady:.0f}  (waitlist breaches at ~{new_steady + 12} paid)")
    assert new_steady < broken_old / 5, "Q3 must produce a dramatically smaller reserve than the old formula"

    if not ok:
        raise AssertionError("compute_dynamic_reserve did not return the steady-rule floor")
    print("[Q3 #1] ALL PASS\n")


def test_waitlist_module_imports_cleanly() -> None:
    """Q3 must not have broken the waitlist module surface."""
    print("[Q3 #2] waitlist module surface check:")
    from app.services import waitlist as W
    required = [
        "_rehome_orphans_once",        # NEW in Q3
        "run_merger_refill_converge",  # converge driver — now calls rehome
        "run_pool_merger_engine",      # back-compat entry
        "_condense_pools_once",        # merger core
        "assign_waitlist_to_pools",    # master refill engine
        "dissolve_pool_manually",      # admin manual donor↔receiver
        "manual_create_pool",          # admin force-spawn
    ]
    for name in required:
        present = hasattr(W, name)
        flag = "PASS" if present else "FAIL"
        print(f"  [{flag}] {name}")
        if not present:
            raise AssertionError(f"waitlist.{name} is missing")
    print("[Q3 #2] ALL PASS\n")


def test_converge_signature_unchanged() -> None:
    """Existing callers (draw.py, draw_preparation.py) must still work."""
    import inspect
    from app.services.waitlist import run_merger_refill_converge

    sig = inspect.signature(run_merger_refill_converge)
    params = list(sig.parameters.keys())
    print("[Q3 #3] run_merger_refill_converge signature:")
    print(f"  params = {params}")
    expected = ["db", "user_prefix", "max_rounds"]
    if params != expected:
        raise AssertionError(
            f"signature changed — callers will break.  expected={expected}  got={params}"
        )
    print("[Q3 #3] ALL PASS\n")


if __name__ == "__main__":
    test_compute_dynamic_reserve_is_steady()
    test_waitlist_module_imports_cleanly()
    test_converge_signature_unchanged()
    print("=" * 60)
    print("Q3 SMOKE TEST — ALL PASS")
    print("=" * 60)
