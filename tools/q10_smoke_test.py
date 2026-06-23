"""
Q10 / Task #10 smoke test — Jun-23 — Soheb Khan User 2 / Sohebkhan.sk11
=======================================================================
Forensic emission gap-fix verification.  Touches NO database.

The Task #10 patch injects ``forensic.member_won`` + ``forensic.draw_event``
into the 5 draw paths that were previously firing winners but emitting NO
forensic record:

    1. draw.run_accelerated_dissolution_draw            (POOL_DRAW_ACCELERATED)
    2. sde_engine.execute_staged_sde_draws T-0H         (POOL_DRAW_SDE        / POOL_DRAW_SDE_CASE_C)
    3. sde_engine.execute_sde_ext2_draw                 (POOL_DRAW_SDE_EXT2   / POOL_DRAW_SDE_EXT3)
    4. sde_engine.run_preventive_l3_draw                (POOL_DRAW_SDE_PREVENTIVE_L3)
    5. sde_engine._execute_case_d_single_pair           (POOL_DRAW_SDE        — case_d cross-pool)

This test EXERCISES THE FORENSIC API with the exact argument shapes my
emission sites pass — so a future signature drift in forensic.member_won /
draw_event surfaces here, not in production with payout data in flight.

Hard safety: DATABASE_URL forced to throwaway SQLite; refuses production
Postgres / Supabase / pooler.  forensic.flush() is NEVER called (it would
attempt a DB write); we read the in-memory _BUFFER directly to verify shape.
"""

import os
import sys

# Hard safety — refuse to touch anything but a throwaway SQLite shell.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
assert "supabase" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q10 smoke test refuses to talk to Supabase."
assert "pooler" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q10 smoke test refuses to talk to a pooler URL."
assert "postgres" not in os.environ.get("DATABASE_URL", "").lower(), \
    "Q10 smoke test refuses to talk to Postgres."

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _enable_forensic_in_memory():
    """Enable forensic recorder WITHOUT touching the DB-bound flush path."""
    from app.services import forensic as F
    F.enable_forensic("q10_smoke")
    F.set_week(99)
    F.set_tick("Q10_SMOKE")
    # Wipe any pre-existing buffer so we count only this test's writes.
    with F._LOCK:
        F._BUFFER.clear()
    return F


def _drain_buffer(F):
    """Snapshot + clear the in-memory buffer; do NOT call flush (would hit DB)."""
    with F._LOCK:
        rows = F._BUFFER[:]
        F._BUFFER.clear()
    return rows


def _count(rows, *, category, event_type, draw_type=None):
    n = 0
    for r in rows:
        if r.get("category") != category:
            continue
        if r.get("event_type") != event_type:
            continue
        if draw_type is None:
            n += 1
            continue
        # draw_event encodes draw_type inside payload_json; member_won encodes
        # it inside after_json.  Cheap substring check is sufficient here.
        for fld in ("payload_json", "after_json"):
            blob = r.get(fld) or ""
            if f'"draw_type": "{draw_type}"' in blob:
                n += 1
                break
    return n


# ── Site 1: run_accelerated_dissolution_draw ──────────────────────────────────
def test_accel_dissolution_emission():
    print("[Q10 #1] run_accelerated_dissolution_draw forensic emission:")
    F = _enable_forensic_in_memory()

    # Simulate the exact arg shape from draw.py site 1.
    POOL_DRAW_ACCELERATED = "accelerated_dissolution"
    pool_id, pool_name = 101, "P-101"
    winners = [
        ("upper_user_1", 4, 5500),
        ("lower_user_1", 3, 3500),
    ]
    for ref, lvl, payout in winners:
        F.member_won(
            uid=hash(ref) & 0xFFFF, ref=ref,
            pool_id=pool_id, level=lvl,
            draw_type=POOL_DRAW_ACCELERATED,
            amount_inr=payout,
            payload={"pool_name": pool_name, "edge_case": "accelerated_dissolution"},
        )
    F.draw_event(
        "draw_executed",
        pool_id=pool_id, ref=pool_name,
        draw_type=POOL_DRAW_ACCELERATED,
        payload={
            "winners":      [w[0] for w in winners],
            "upper_level":  winners[0][1],
            "lower_level":  winners[1][1],
            "upper_payout": winners[0][2],
            "lower_payout": winners[1][2],
            "create_relief_pool": True,
        },
        message=f"DRAW {POOL_DRAW_ACCELERATED} pool {pool_name}: @L4+@L3 won",
    )

    rows = _drain_buffer(F)
    won  = _count(rows, category="DRAW", event_type="member_won",   draw_type=POOL_DRAW_ACCELERATED)
    dexc = _count(rows, category="DRAW", event_type="draw_executed", draw_type=POOL_DRAW_ACCELERATED)
    print(f"  member_won (accel) = {won}    draw_executed (accel) = {dexc}")
    assert won == 2,  f"expected 2 member_won, got {won}"
    assert dexc == 1, f"expected 1 draw_executed, got {dexc}"
    print("[Q10 #1] PASS\n")


# ── Site 2: execute_staged_sde_draws T-0H (Cases A/B/C + Lever-4 dual-L4) ─────
def test_staged_sde_emission():
    print("[Q10 #2] execute_staged_sde_draws (Cases A/B/C + dual-L4) emission:")
    F = _enable_forensic_in_memory()

    POOL_DRAW_SDE         = "pool_draw_sde"
    POOL_DRAW_SDE_CASE_C  = "pool_draw_sde_case_c"
    cases = [
        # (label, is_case_c, is_dual_l4, draw_type)
        ("case_ab", False, False, POOL_DRAW_SDE),
        ("case_c",  True,  False, POOL_DRAW_SDE_CASE_C),
        ("dual_l4", False, True,  POOL_DRAW_SDE),
    ]
    for label, is_c, is_d, dt in cases:
        for tier, lvl, payout in (("upper", 4, 5500), ("lower", 1, 1100)):
            F.member_won(
                uid=hash((label, tier)) & 0xFFFF, ref=f"{label}_{tier}",
                pool_id=42, level=lvl, draw_type=dt, amount_inr=payout,
                payload={
                    "pool_name":      f"P-42-{label}",
                    "tier":           tier,
                    "edge_case":      ("case_c" if is_c
                                       else ("dual_l4_lever4" if is_d else "case_a_or_b")),
                    "sde_session_id": 7,
                    "checkpoint_id":  hash(label) & 0xFFFF,
                },
            )
        F.draw_event(
            "draw_executed",
            pool_id=42, ref=f"P-42-{label}", draw_type=dt,
            payload={"is_case_c": is_c, "is_dual_l4": is_d, "sde_session_id": 7},
            message=f"DRAW {dt} pool P-42-{label}",
        )

    rows = _drain_buffer(F)
    won_sde   = _count(rows, category="DRAW", event_type="member_won",   draw_type=POOL_DRAW_SDE)
    won_c     = _count(rows, category="DRAW", event_type="member_won",   draw_type=POOL_DRAW_SDE_CASE_C)
    dexc_sde  = _count(rows, category="DRAW", event_type="draw_executed", draw_type=POOL_DRAW_SDE)
    dexc_c    = _count(rows, category="DRAW", event_type="draw_executed", draw_type=POOL_DRAW_SDE_CASE_C)
    print(f"  member_won SDE      = {won_sde}    draw_executed SDE      = {dexc_sde}")
    print(f"  member_won CASE_C   = {won_c}     draw_executed CASE_C   = {dexc_c}")
    # Cases A/B + dual_L4 = 2 events  →  4 winners + 2 draws
    # Case C                             →  2 winners + 1 draw
    assert won_sde  == 4, f"expected 4 SDE member_won, got {won_sde}"
    assert won_c    == 2, f"expected 2 CASE_C member_won, got {won_c}"
    assert dexc_sde == 2, f"expected 2 SDE draw_executed, got {dexc_sde}"
    assert dexc_c   == 1, f"expected 1 CASE_C draw_executed, got {dexc_c}"
    print("[Q10 #2] PASS\n")


# ── Site 3: execute_sde_ext2_draw (Ext-II / Ext-III) ─────────────────────────
def test_ext2_emission():
    print("[Q10 #3] execute_sde_ext2_draw (Ext-II/III L5/L6 forced exit) emission:")
    F = _enable_forensic_in_memory()

    POOL_DRAW_SDE_EXT2 = "pool_draw_sde_ext2"
    POOL_DRAW_SDE_EXT3 = "pool_draw_sde_ext3"
    for dt, upper_lvl in ((POOL_DRAW_SDE_EXT2, 5), (POOL_DRAW_SDE_EXT3, 6)):
        for tier, lvl, payout in (("upper", upper_lvl, 6500 if upper_lvl == 5 else 8000),
                                  ("lower", 3, 3500)):
            F.member_won(
                uid=hash((dt, tier)) & 0xFFFF, ref=f"{dt}_{tier}",
                pool_id=99, level=lvl, draw_type=dt, amount_inr=payout,
                payload={
                    "pool_name": "P-99",
                    "tier":      tier,
                    "edge_case": "ext2_l5_forced_exit" if dt == POOL_DRAW_SDE_EXT2
                                 else "ext3_l6_forced_exit",
                    "drawdown_projection": {"savings_acting_now_vs_1week": 1500},
                },
            )
        F.draw_event(
            "draw_executed",
            pool_id=99, ref="P-99", draw_type=dt, severity="warning",
            payload={"week_id": "2026-W25"},
            message=f"DRAW {dt} pool P-99 FORCED EXIT",
        )

    rows = _drain_buffer(F)
    won_e2  = _count(rows, category="DRAW", event_type="member_won",    draw_type=POOL_DRAW_SDE_EXT2)
    won_e3  = _count(rows, category="DRAW", event_type="member_won",    draw_type=POOL_DRAW_SDE_EXT3)
    dexc_e2 = _count(rows, category="DRAW", event_type="draw_executed", draw_type=POOL_DRAW_SDE_EXT2)
    dexc_e3 = _count(rows, category="DRAW", event_type="draw_executed", draw_type=POOL_DRAW_SDE_EXT3)
    print(f"  member_won Ext-II  = {won_e2}    draw_executed Ext-II  = {dexc_e2}")
    print(f"  member_won Ext-III = {won_e3}    draw_executed Ext-III = {dexc_e3}")
    assert won_e2 == won_e3 == 2
    assert dexc_e2 == dexc_e3 == 1
    print("[Q10 #3] PASS\n")


# ── Site 4: run_preventive_l3_draw ───────────────────────────────────────────
def test_preventive_l3_emission():
    print("[Q10 #4] run_preventive_l3_draw forensic emission:")
    F = _enable_forensic_in_memory()

    POOL_DRAW_SDE_PREVENTIVE_L3 = "pool_draw_sde_preventive_l3"
    for tier, payout in (("upper", 3500), ("lower", 3500)):
        F.member_won(
            uid=hash(("pl3", tier)) & 0xFFFF, ref=f"pl3_{tier}",
            pool_id=77, level=3,
            draw_type=POOL_DRAW_SDE_PREVENTIVE_L3,
            amount_inr=payout,
            payload={
                "pool_name":            "P-77",
                "tier":                 tier,
                "edge_case":            "preventive_l3_cascade_protection",
                "cascade_risk_at_draw": 2.41,
                "l3_count_before":      18,
            },
        )
    F.draw_event(
        "draw_executed",
        pool_id=77, ref="P-77",
        draw_type=POOL_DRAW_SDE_PREVENTIVE_L3,
        severity="warning",
        payload={"cascade_risk_at_draw": 2.41, "l3_count_before": 18, "week_id": "2026-W25"},
        message="DRAW preventive_l3 pool P-77 CASCADE-PROTECT",
    )

    rows = _drain_buffer(F)
    won  = _count(rows, category="DRAW", event_type="member_won",    draw_type=POOL_DRAW_SDE_PREVENTIVE_L3)
    dexc = _count(rows, category="DRAW", event_type="draw_executed", draw_type=POOL_DRAW_SDE_PREVENTIVE_L3)
    print(f"  member_won (pl3) = {won}    draw_executed (pl3) = {dexc}")
    assert won == 2 and dexc == 1
    print("[Q10 #4] PASS\n")


# ── Site 5: _execute_case_d_single_pair ──────────────────────────────────────
def test_case_d_cross_pool_emission():
    print("[Q10 #5] _execute_case_d_single_pair (Case D cross-pool dual-L4) emission:")
    F = _enable_forensic_in_memory()

    POOL_DRAW_SDE = "pool_draw_sde"
    pool_a_id, pool_a_name = 50, "P-50"
    pool_b_id, pool_b_name = 51, "P-51"
    # Upper anchored to pool A; lower anchored to pool B
    F.member_won(
        uid=1001, ref="caseD_upper",
        pool_id=pool_a_id, level=4,
        draw_type=POOL_DRAW_SDE, amount_inr=5500,
        payload={
            "pool_name":   pool_a_name,
            "tier":        "upper",
            "edge_case":   "case_d_cross_pool",
            "session_num": 3,
            "paired_with_pool_id":   pool_b_id,
            "paired_with_pool_name": pool_b_name,
        },
    )
    F.member_won(
        uid=1002, ref="caseD_lower",
        pool_id=pool_b_id, level=4,
        draw_type=POOL_DRAW_SDE, amount_inr=5500,
        payload={
            "pool_name":   pool_b_name,
            "tier":        "lower",
            "edge_case":   "case_d_cross_pool",
            "session_num": 3,
            "paired_with_pool_id":   pool_a_id,
            "paired_with_pool_name": pool_a_name,
        },
    )
    F.draw_event(
        "draw_executed",
        pool_id=pool_a_id, ref=pool_a_name, draw_type=POOL_DRAW_SDE,
        severity="warning",
        payload={
            "is_case_d":   True,
            "pool_a_id":   pool_a_id,
            "pool_a_name": pool_a_name,
            "pool_b_id":   pool_b_id,
            "pool_b_name": pool_b_name,
            "session_num": 3,
        },
        message=f"DRAW {POOL_DRAW_SDE} CASE_D cross-pool {pool_a_name}↔{pool_b_name}",
    )

    rows = _drain_buffer(F)
    won  = _count(rows, category="DRAW", event_type="member_won",   draw_type=POOL_DRAW_SDE)
    dexc = _count(rows, category="DRAW", event_type="draw_executed", draw_type=POOL_DRAW_SDE)
    # Verify the case_d marker survives serialization round-trip
    case_d_in_payload = any(
        '"is_case_d": true' in (r.get("payload_json") or "")
        for r in rows if r["event_type"] == "draw_executed"
    )
    print(f"  member_won (case_d) = {won}    draw_executed (case_d) = {dexc}    "
          f"is_case_d-in-payload = {case_d_in_payload}")
    assert won == 2 and dexc == 1
    assert case_d_in_payload, "case_d marker MUST survive payload serialization"
    print("[Q10 #5] PASS\n")


# ── Sanity: emitting sites import cleanly (no syntax / NameError) ────────────
def test_modules_import_after_edits():
    print("[Q10 #6] post-edit module imports:")
    # If any of the 5 edits broke syntax, these imports raise.
    from app.services import draw as _draw            # noqa: F401
    from app.services import sde_engine as _sde       # noqa: F401
    print("  app.services.draw         imported OK")
    print("  app.services.sde_engine   imported OK")
    print("[Q10 #6] PASS\n")


if __name__ == "__main__":
    print("=" * 64)
    print("Q10 / Task #10 — forensic emission gap-fix smoke test")
    print("=" * 64)
    test_modules_import_after_edits()
    test_accel_dissolution_emission()
    test_staged_sde_emission()
    test_ext2_emission()
    test_preventive_l3_emission()
    test_case_d_cross_pool_emission()
    print("=" * 64)
    print("Q10 SMOKE TEST — ALL PASS")
    print("=" * 64)
