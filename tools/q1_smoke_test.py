"""
Q1 smoke test — Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11
============================================================
Keystone regression gate for the L5/L6 PURE-PROTECTION fix (commit 8694892).
Touches NO database.

WHY THIS IS THE MOST IMPORTANT TEST IN THE SUITE
-------------------------------------------------
The W22-W27 production autopsy showed members leaking L4 -> L5 -> L6 unbounded.
EVERY level change a draw survivor can experience funnels through ONE pure
function: ``sde_engine._advance_survivor_level(current_level, sde_required)``.
It is called by:
    • draw.run_dual_draw                 (regular weekly survivors)
    • draw.run_accelerated_dissolution_draw (accel survivors)
    • sde_engine.execute_staged_sde_draws   (staged T-0H survivors)
    • sde_engine.execute_sde_ext2_draw       (Ext-II/III survivors)
    • sde_engine._execute_case_d_single_pair (Case-D cross-pool survivors)

If this function can EVER return new_level >= 5 for a member entering at L4,
the leak is open.  Q1 made the rule: L4 is HELD (never climbs), legacy L5/L6
are HELD (never climb), only L1-L3 advance +1.  This test proves that rule
exhaustively and asserts the hard upper-bound invariant the docstring claims.

A green run here is the launch-gate guarantee that NO member can climb into
the L5/L6 payout band via the survivor-advance path.
"""

import os
import sys

# Hard safety — refuse to talk to anything but a throwaway SQLite shell.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
assert "supabase" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q1 smoke test refuses to talk to Supabase."
assert "pooler" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q1 smoke test refuses to talk to a pooler URL."
assert "postgres" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q1 smoke test refuses to talk to Postgres."

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_l4_is_always_held() -> None:
    """A member entering a survivor advance at L4 MUST be held at L4 — both
    sde_required states — never advanced to L5.  This is the exact leak the
    W22-W27 autopsy traced."""
    from app.services.sde_engine import _advance_survivor_level
    print("[Q1 #1] L4 HOLD (no L4->L5 leak):")
    ok = True
    for sde_required in (True, False):
        new_level, held = _advance_survivor_level(4, sde_required)
        flag = "PASS" if (new_level == 4 and held is True) else "FAIL"
        if not (new_level == 4 and held is True):
            ok = False
        print(f"  [{flag}] L4 sde_required={sde_required!s:<5} -> "
              f"(new_level={new_level}, held={held})  expected=(4, True)")
    if not ok:
        raise AssertionError("L4 survivor was NOT held at L4 — the L5 leak is OPEN")
    print("[Q1 #1] ALL PASS\n")


def test_l1_l3_advance_normally() -> None:
    """L1/L2/L3 survivors advance exactly +1 and are NOT flagged held."""
    from app.services.sde_engine import _advance_survivor_level
    print("[Q1 #2] L1-L3 normal +1 advancement:")
    ok = True
    expected = {1: 2, 2: 3, 3: 4}
    for lvl in (1, 2, 3):
        for sde_required in (True, False):
            new_level, held = _advance_survivor_level(lvl, sde_required)
            want_level = expected[lvl]
            # Reaching L4 (the lvl==3 case) returns held=False from THIS function;
            # the caller atomically sets sde_required=True on the same DB write.
            good = (new_level == want_level and held is False)
            flag = "PASS" if good else "FAIL"
            if not good:
                ok = False
            print(f"  [{flag}] L{lvl} sde_required={sde_required!s:<5} -> "
                  f"(new_level={new_level}, held={held})  expected=({want_level}, False)")
    if not ok:
        raise AssertionError("L1-L3 advancement is wrong")
    print("[Q1 #2] ALL PASS\n")


def test_legacy_l5_l6_never_climb() -> None:
    """Legacy L5/L6 members (pre-Q1 data only) are HELD at their level — they
    MUST exit via the Ext-II/III legacy cleaner, never climb further."""
    from app.services.sde_engine import _advance_survivor_level
    print("[Q1 #3] legacy L5/L6 defensive HOLD (no further climb):")
    ok = True
    for lvl in (5, 6):
        for sde_required in (True, False):
            new_level, held = _advance_survivor_level(lvl, sde_required)
            good = (new_level == lvl and held is True)
            flag = "PASS" if good else "FAIL"
            if not good:
                ok = False
            print(f"  [{flag}] L{lvl} sde_required={sde_required!s:<5} -> "
                  f"(new_level={new_level}, held={held})  expected=({lvl}, True)")
    if not ok:
        raise AssertionError("Legacy L5/L6 member CLIMBED — defensive hold broken")
    print("[Q1 #3] ALL PASS\n")


def test_hard_upper_bound_invariant() -> None:
    """THE launch-gate invariant: for EVERY member entering at L1-L4 (the only
    levels a real, non-legacy member can be in), the survivor-advance path can
    NEVER produce a level >= 5.  No member can be pushed into the L5/L6 payout
    band by surviving a draw."""
    from app.services.sde_engine import _advance_survivor_level
    print("[Q1 #4] HARD UPPER-BOUND INVARIANT (real members L1-L4 never reach L5):")
    violations = []
    for lvl in (1, 2, 3, 4):
        for sde_required in (True, False):
            new_level, _held = _advance_survivor_level(lvl, sde_required)
            if new_level >= 5:
                violations.append((lvl, sde_required, new_level))
    if violations:
        for lvl, sde, nl in violations:
            print(f"  [FAIL] L{lvl} sde_required={sde} -> L{nl}  (BREACHED L5 BAND)")
        raise AssertionError(
            f"{len(violations)} input(s) pushed a real member into the L5/L6 band — "
            f"the leak is OPEN"
        )
    print("  [PASS] all L1-L4 x {{True,False}} inputs -> new_level <= 4")
    print("[Q1 #4] ALL PASS\n")


if __name__ == "__main__":
    print("=" * 64)
    print("Q1 SMOKE TEST — L5/L6 pure-protection invariant")
    print("=" * 64)
    test_l4_is_always_held()
    test_l1_l3_advance_normally()
    test_legacy_l5_l6_never_climb()
    test_hard_upper_bound_invariant()
    print("=" * 64)
    print("Q1 SMOKE TEST — ALL PASS")
    print("=" * 64)
