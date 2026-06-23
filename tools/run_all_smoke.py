"""
Unified smoke-suite runner — Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11
=========================================================================
ONE launch gate for the four W22-W27-collapse fixes.  Touches NO database.

Runs, in order:
    Q1  L5/L6 pure-protection invariant      (commit 8694892)
    Q2  steady BALANCED posture invariant    (commit ea6510c)
    Q3  steady spawn-reserve + waitlist surface (commit 4f45fe7)
    Q10 draw-level forensic emission gap-fix (commit 2239724)

Each sub-test enforces its own SQLite-only DATABASE_URL guard (refuses
Supabase / pooler / postgres), so this aggregator can never touch production
even if invoked with a stray env var.

Exit code 0 == all green == the four fixes are intact and the system is
clear of the feast-or-famine / L5-leak regime.  Non-zero == a regression
re-opened one of the fixes; DO NOT launch.

Usage:
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 DATABASE_URL=sqlite:///:memory: \
        python tools/run_all_smoke.py
"""

import importlib
import os
import sys
import traceback

# Hard safety — refuse to talk to anything but a throwaway SQLite shell.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
for _banned in ("supabase", "pooler", "postgres"):
    assert _banned not in os.environ.get("DATABASE_URL", "").lower(), \
        f"run_all_smoke refuses to talk to a '{_banned}' URL."

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# (module_name, [callable test names in run order])
_SUITES = [
    ("tools.q1_smoke_test", [
        "test_l4_is_always_held",
        "test_l1_l3_advance_normally",
        "test_legacy_l5_l6_never_climb",
        "test_hard_upper_bound_invariant",
    ]),
    ("tools.q2_smoke_test", [
        "test_posture_is_always_balanced_fifo",
        "test_steady_constants_exact",
        "test_determinism",
    ]),
    ("tools.q3_smoke_test", [
        "test_compute_dynamic_reserve_is_steady",
        "test_waitlist_module_imports_cleanly",
        "test_converge_signature_unchanged",
    ]),
    ("tools.q10_smoke_test", [
        "test_modules_import_after_edits",
        "test_accel_dissolution_emission",
        "test_staged_sde_emission",
        "test_ext2_emission",
        "test_preventive_l3_emission",
        "test_case_d_cross_pool_emission",
    ]),
]


def main() -> int:
    print("#" * 70)
    print("# REWARD-SCHEME LAUNCH GATE — Q1+Q2+Q3+Q10 composite smoke suite")
    print("#" * 70)
    passed = 0
    failed = 0
    failures: list[str] = []

    for mod_name, test_names in _SUITES:
        label = mod_name.split(".")[-1].replace("_smoke_test", "").upper()
        print(f"\n{'=' * 70}\n>>> SUITE {label}  ({mod_name})\n{'=' * 70}")
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:
            failed += len(test_names)
            failures.append(f"{mod_name}: IMPORT FAILED — {exc}")
            traceback.print_exc()
            continue

        for tname in test_names:
            fn = getattr(mod, tname, None)
            if fn is None:
                failed += 1
                failures.append(f"{mod_name}.{tname}: MISSING")
                print(f"  [MISSING] {tname}")
                continue
            try:
                fn()
                passed += 1
            except Exception as exc:
                failed += 1
                failures.append(f"{mod_name}.{tname}: {exc}")
                print(f"  [FAIL] {tname} — {exc}")
                traceback.print_exc()

    print("\n" + "#" * 70)
    print(f"# RESULT: {passed} passed, {failed} failed")
    if failed:
        print("# LAUNCH GATE: RED — DO NOT LAUNCH")
        for f in failures:
            print(f"#   ✗ {f}")
        print("#" * 70)
        return 1
    print("# LAUNCH GATE: GREEN — all four fixes intact "
          "(no feast-or-famine, no L5/L6 leak, forensic visible)")
    print("#" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
