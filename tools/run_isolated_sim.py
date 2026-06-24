"""
SQLite-isolated multi-week sim validation — Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11
=======================================================================================
END-TO-END launch gate.  Runs the REAL production engine (RealSimEngine — the
same draw / SDE / compliance / pool-formation / waitlist services that run live)
for a multi-week horizon against a THROWAWAY local SQLite database, then asserts
the composite Q1-Q4 invariants over every weekly snapshot.

WHY THIS EXISTS
---------------
The Q1/Q2/Q3 unit smoke tests (tools/run_all_smoke.py) prove each fix in
isolation as a pure function.  They do NOT prove the fixes *compose* once the
real services run them together, week after week, under member inflow, pool
churn, SDE pressure and compliance elimination.  The W22-W27 production
collapse was an emergent, multi-week interaction — exactly the class of failure
a pure-function test cannot see.  This driver reproduces that horizon on real
code and asserts the system never re-enters the collapse regime:

    INV-1  Q1  zero L5/L6 in EVERY week (the keystone money-safety invariant)
    INV-2  Q2  no multi-week draw FREEZE (no long zero-draw streak)
    INV-3  Q2  no draw BLOWOUT (winners in a week never exceed the live member base)
    INV-4  Q3  waitlist DRAINS — members are absorbed into pools, not piled up
    INV-5  Q3  pool counts stay BOUNDED and sane; orphan (Paused) pools resolve
    INV-6  ——  the engine completed every week (no mid-run abort)

SAFETY (NON-NEGOTIABLE)
-----------------------
This script MUST NEVER touch the shared Supabase production database.  It sets
DATABASE_URL to a throwaway local SQLite FILE *before* importing anything that
reads it, and then triple-checks the resolved URL is sqlite and contains none of
{supabase, pooler, postgres}.  If any guard trips, it aborts before a single
table is created.  The file-backed SQLite engine uses NullPool (see
app/database.py) so the forensic recorder's flush session is fully isolated from
the simulation's transaction — exactly like production PostgreSQL.

Usage:
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python tools/run_isolated_sim.py
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python tools/run_isolated_sim.py --weeks 40

Exit code 0 == GREEN == the real engine held every invariant across the horizon.
Non-zero == a real-code regression re-opened the collapse regime; DO NOT launch.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
import uuid

# ══════════════════════════════════════════════════════════════════════════════
# 0. HARD SAFETY GATE — set a throwaway SQLite URL *before* any app import
# ══════════════════════════════════════════════════════════════════════════════
# A unique temp file per run avoids any chance of colliding with a previous run's
# leftover DB.  We keep the path so we can delete it in the finally block.
_TMP_DIR   = tempfile.gettempdir()
_DB_FILE   = os.path.join(_TMP_DIR, f"reward_isolated_sim_{uuid.uuid4().hex[:12]}.db")
# SQLAlchemy SQLite URL wants forward slashes even on Windows.
_SQLITE_URL = "sqlite:///" + _DB_FILE.replace("\\", "/")

# Force-override ANY inherited DATABASE_URL (e.g. a real Supabase URL in .env or
# the shell).  We do NOT use setdefault here — this is the one script that must
# guarantee the value, not merely provide a fallback.
os.environ["DATABASE_URL"] = _SQLITE_URL

# Belt-and-suspenders: refuse to proceed if the URL is anything but throwaway sqlite.
_url_lc = os.environ["DATABASE_URL"].lower()
assert _url_lc.startswith("sqlite:"), \
    f"ISOLATED SIM refuses to run on a non-sqlite URL: {os.environ['DATABASE_URL']!r}"
for _banned in ("supabase", "pooler", "postgres"):
    assert _banned not in _url_lc, \
        f"ISOLATED SIM refuses to talk to a '{_banned}' URL."

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ══════════════════════════════════════════════════════════════════════════════
# 1. INVARIANT THRESHOLDS  (named so the launch gate is auditable at a glance)
# ══════════════════════════════════════════════════════════════════════════════
MAX_ZERO_DRAW_STREAK = 3   # >3 consecutive zero-draw weeks (post warm-up) == FREEZE
# A blowout is structurally impossible to miss: more winners than living members.
# winners_this_week must never exceed the members alive that week
# (active at draw time == current active + those who exited as winners this week).


def _banner(text: str) -> None:
    print("\n" + "=" * 74)
    print(text)
    print("=" * 74)


# ══════════════════════════════════════════════════════════════════════════════
# 2. INVARIANT ASSERTIONS over the weekly snapshot stream
# ══════════════════════════════════════════════════════════════════════════════
def _check_invariants(result: dict, weeks_requested: int) -> list[str]:
    """
    Return a list of human-readable FAILURE strings.  Empty list == all green.
    Every check prints a PASS/FAIL line so the run is self-documenting.
    """
    failures: list[str] = []
    wd: list[dict] = result.get("weekly_detail", []) or []
    summary = result.get("simulation_summary", {}) or {}
    health  = summary.get("system_health", {}) or {}

    # ── INV-6: completeness — the engine ran every requested week ──────────────
    _banner("INV-6  COMPLETENESS — engine completed every week")
    if len(wd) != weeks_requested:
        msg = f"engine produced {len(wd)} weekly rows, expected {weeks_requested} (mid-run abort?)"
        print(f"  [FAIL] {msg}")
        failures.append(f"INV-6: {msg}")
    else:
        print(f"  [PASS] {len(wd)} / {weeks_requested} weekly snapshots produced")
    if not wd:
        # Nothing else can be checked without snapshots.
        failures.append("INV-6: no weekly_detail rows — cannot validate any invariant")
        return failures

    # ── INV-1: Q1 keystone — ZERO L5/L6 in every single week ───────────────────
    _banner("INV-1  Q1 KEYSTONE — zero L5/L6 in EVERY week (no payout-band leak)")
    l5l6_breaches = []
    for w in wd:
        ld = w.get("level_distribution", {}) or {}
        l5 = max(int(w.get("l5_count", 0) or 0), int(ld.get("L5", 0) or 0))
        l6 = max(int(w.get("l6_count", 0) or 0), int(ld.get("L6", 0) or 0))
        if l5 or l6:
            l5l6_breaches.append((w.get("week"), l5, l6))
    max_l5_sum = int(health.get("max_l5_count", 0) or 0)
    max_l6_sum = int(health.get("max_l6_count", 0) or 0)
    if l5l6_breaches:
        for wk, l5, l6 in l5l6_breaches[:10]:
            print(f"  [FAIL] week {wk}: L5={l5} L6={l6}  (member leaked into payout band)")
        failures.append(
            f"INV-1: {len(l5l6_breaches)} week(s) had L5/L6 members — the L5/L6 leak is OPEN"
        )
    elif max_l5_sum or max_l6_sum:
        msg = f"summary reports max_l5={max_l5_sum} max_l6={max_l6_sum} despite clean weekly rows"
        print(f"  [FAIL] {msg}")
        failures.append(f"INV-1: {msg}")
    else:
        print(f"  [PASS] all {len(wd)} weeks: L5=0 L6=0 (summary max_l5={max_l5_sum}, max_l6={max_l6_sum})")

    # ── INV-2: Q2 — no multi-week draw FREEZE ──────────────────────────────────
    _banner("INV-2  Q2 — no multi-week draw FREEZE (no long zero-draw streak)")
    draws = [int(w.get("draws_this_week", 0) or 0) for w in wd]
    total_draws = sum(draws)
    if total_draws == 0:
        print(f"  [FAIL] TOTAL FREEZE — 0 draws across all {len(wd)} weeks")
        failures.append("INV-2: total freeze — the engine never drew once")
    else:
        # Warm-up = everything up to and including the first week that drew.
        first_draw_idx = next(i for i, d in enumerate(draws) if d > 0)
        post = draws[first_draw_idx + 1:]
        longest_zero = cur = 0
        for d in post:
            cur = cur + 1 if d == 0 else 0
            longest_zero = max(longest_zero, cur)
        print(f"  first draw in week {wd[first_draw_idx].get('week')} "
              f"(warm-up = {first_draw_idx + 1} week(s)); total draws = {total_draws}")
        if longest_zero > MAX_ZERO_DRAW_STREAK:
            msg = (f"longest post-warm-up zero-draw streak = {longest_zero} weeks "
                   f"(> {MAX_ZERO_DRAW_STREAK}) — feast-or-famine FREEZE regime")
            print(f"  [FAIL] {msg}")
            failures.append(f"INV-2: {msg}")
        else:
            print(f"  [PASS] longest post-warm-up zero-draw streak = {longest_zero} "
                  f"(<= {MAX_ZERO_DRAW_STREAK})")

    # ── INV-3: Q2 — no draw BLOWOUT (winners never exceed living members) ───────
    _banner("INV-3  Q2 — no BLOWOUT (winners in a week never exceed the live member base)")
    blowouts = []
    for w in wd:
        winners = int(w.get("winners_this_week", 0) or 0)
        # Members alive at draw time = those still active + those who exited AS
        # winners during this week's draws.  Winners cannot exceed that.
        alive_at_draw = int(w.get("active_users", 0) or 0) + int(w.get("members_exited_this_week", 0) or 0)
        if winners > alive_at_draw:
            blowouts.append((w.get("week"), winners, alive_at_draw))
    if blowouts:
        for wk, win, alive in blowouts[:10]:
            print(f"  [FAIL] week {wk}: {win} winners > {alive} living members (impossible blowout)")
        failures.append(f"INV-3: {len(blowouts)} week(s) drew more winners than living members")
    else:
        peak = max((int(w.get("winners_this_week", 0) or 0) for w in wd), default=0)
        print(f"  [PASS] no week's winner count exceeded its living member base (peak winners/wk = {peak})")

    # ── INV-4: Q3 — waitlist DRAINS (members get absorbed, not piled up) ────────
    _banner("INV-4  Q3 — waitlist DRAINS (absorbed into pools, never monotonically piling up)")
    wl = [int(w.get("waitlist_count", 0) or 0) for w in wd]
    active_final = int(wd[-1].get("active_users", 0) or 0)
    wl_final = wl[-1]
    # A healthy system shows at least one DRAIN event (a week where the waitlist
    # falls or hits zero).  A waitlist that strictly rises every single week means
    # members are never absorbed — the Q3 pathology.
    drained_at_some_point = any(wl[i] < wl[i - 1] or wl[i] == 0 for i in range(1, len(wl))) or (len(wl) == 1 and wl[0] == 0)
    if not drained_at_some_point and len(wl) > 1:
        msg = (f"waitlist strictly non-draining across all {len(wl)} weeks "
               f"(trajectory tail: {wl[-6:]}) — members never absorbed")
        print(f"  [FAIL] {msg}")
        failures.append(f"INV-4: {msg}")
    else:
        print(f"  [PASS] waitlist drained at least once (tail: {wl[-6:]})")
    # And the final backlog must not dwarf the active base (bounded absorption lag).
    if wl_final > max(active_final, 1) and active_final > 0:
        msg = f"final waitlist {wl_final} exceeds final active membership {active_final} (absorption stalled)"
        print(f"  [FAIL] {msg}")
        failures.append(f"INV-4: {msg}")
    else:
        print(f"  [PASS] final waitlist {wl_final} <= final active {active_final} (backlog bounded)")

    # ── INV-5: Q3 — pool counts bounded & sane; orphan (Paused) pools resolve ───
    _banner("INV-5  Q3 — pool counts bounded & sane; orphan (Paused) pools resolve")
    pa = [int(w.get("pools_active", 0) or 0) for w in wd]
    pp = [int(w.get("pools_paused", 0) or 0) for w in wd]
    au = [int(w.get("active_users", 0) or 0) for w in wd]
    # A pool needs at least one member, so active pools cannot exceed active members.
    pool_overflows = [(wd[i].get("week"), pa[i], au[i]) for i in range(len(wd)) if pa[i] > max(au[i], 0)]
    if pool_overflows:
        for wk, p, u in pool_overflows[:10]:
            print(f"  [FAIL] week {wk}: {p} active pools > {u} active members (phantom pools)")
        failures.append(f"INV-5: {len(pool_overflows)} week(s) had more active pools than members")
    else:
        print(f"  [PASS] active pools never exceeded active members (peak active pools = {max(pa, default=0)})")
    # After warm-up there must be at least one active pool (the system is alive).
    if pa and max(pa) == 0:
        print(f"  [FAIL] no active pool ever formed across {len(pa)} weeks")
        failures.append("INV-5: no active pool ever formed")
    else:
        print(f"  [PASS] at least one active pool formed (max active pools = {max(pa, default=0)})")
    # Orphan (Paused_Awaiting_Members) pools must not grow without bound — the
    # final paused count must not exceed the active pool count (orphans resolve).
    pp_final, pa_final = (pp[-1], pa[-1])
    if pp_final > max(pa_final, 1):
        msg = f"final paused/orphan pools {pp_final} exceed active pools {pa_final} (orphans accumulating)"
        print(f"  [FAIL] {msg}  (paused tail: {pp[-6:]})")
        failures.append(f"INV-5: {msg}")
    else:
        print(f"  [PASS] orphan pools bounded — final paused {pp_final} <= active {pa_final} (paused tail: {pp[-6:]})")

    return failures


# ══════════════════════════════════════════════════════════════════════════════
# 3. FORENSIC visibility report (best-effort — NOT a hard gate)
# ══════════════════════════════════════════════════════════════════════════════
def _report_forensic(run_id: str) -> None:
    """Read the persisted ForensicEvent table to confirm draw-level forensic
    events actually landed end-to-end (closes the Q10 loop on real code).  Pure
    reporting — never affects the exit verdict."""
    _banner("FORENSIC VISIBILITY (Q10) — events persisted this run (informational)")
    try:
        from app.database import SessionLocal
        from app.models.forensic_event import ForensicEvent
        from sqlalchemy import func
        db = SessionLocal()
        try:
            total = db.query(func.count(ForensicEvent.id)).filter(ForensicEvent.run_id == run_id).scalar() or 0
            by_type = (
                db.query(ForensicEvent.event_type, func.count(ForensicEvent.id))
                .filter(ForensicEvent.run_id == run_id)
                .group_by(ForensicEvent.event_type)
                .all()
            )
        finally:
            db.close()
        print(f"  total forensic events persisted: {total}")
        for etype, cnt in sorted(by_type, key=lambda r: -r[1])[:15]:
            print(f"    {etype:<28} {cnt}")
        if total == 0:
            print("  (note) no events persisted — forensic flush may have no-op'd; "
                  "this does NOT affect the invariant verdict.")
    except Exception as exc:
        print(f"  (forensic report skipped — {exc})")


# ══════════════════════════════════════════════════════════════════════════════
# 4. MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite-isolated multi-week sim validation")
    parser.add_argument("--weeks", type=int, default=30,
                        help="number of weeks to simulate (default 30; covers the W22-W27 danger zone)")
    parser.add_argument("--users-per-week", type=int, default=30,
                        help="member inflow per week (default 30)")
    args = parser.parse_args()

    print("#" * 74)
    print("# REWARD-SCHEME ISOLATED MULTI-WEEK SIM — real engine on throwaway SQLite")
    print("#" * 74)
    print(f"# DB file : {_DB_FILE}")
    print(f"# DB URL  : {os.environ['DATABASE_URL']}")
    print(f"# weeks   : {args.weeks}   users/week: {args.users_per_week}")
    print("#" * 74)

    # ── Import the app stack now that DATABASE_URL is locked to throwaway sqlite ──
    import app.database as _db_mod
    # Final defensive assertion on the RESOLVED url the engine will actually use.
    assert str(_db_mod.engine.url).lower().startswith("sqlite"), \
        f"resolved engine is not sqlite: {_db_mod.engine.url!r}"
    assert _db_mod.DATABASE_URL == _SQLITE_URL, \
        f"app.database resolved a different URL than we set: {_db_mod.DATABASE_URL!r}"

    # Register every ORM table on Base.metadata, then create the schema.
    import app.models  # noqa: F401  (side-effect: imports all model modules)
    from app.database import Base, engine
    Base.metadata.create_all(bind=engine)
    print(f"\n[schema] created {len(Base.metadata.tables)} tables on isolated SQLite")

    # ── Turn forensic ON so draw-level events are emitted + persisted ──────────
    # NOTE: RealSimEngine truncates its run_id to 8 chars (real_simulation.py:1628
    # — ``self._run_id = (run_id or uuid.hex)[:8]``) and tags every forensic event
    # with that truncated id via set_run().  We therefore use an exactly-8-char id
    # so enable_forensic(), the engine's tag, and our read-back query all agree;
    # a longer id would be silently truncated by the engine and our forensic
    # visibility query would find nothing.
    from app.services import forensic as _forensic
    run_id = uuid.uuid4().hex[:8]
    _forensic.enable_forensic(run_id)
    print(f"[forensic] ENABLED  run_id={run_id}")

    # ── Run the REAL engine ────────────────────────────────────────────────────
    from app.services.real_simulation import RealSimEngine

    def _progress(week_num: int, total_weeks: int, metrics: dict) -> None:
        print(f"  [W{week_num:>3}/{total_weeks}] "
              f"active={metrics.get('active_users', 0):>4} "
              f"wait={metrics.get('waitlist_count', 0):>4} "
              f"poolsA={metrics.get('pools_active', 0):>3} "
              f"poolsP={metrics.get('pools_paused', 0):>3} "
              f"draws={metrics.get('draws_this_week', 0):>3} "
              f"L5={metrics.get('l5_count', 0)} L6={metrics.get('l6_count', 0)}")

    _banner(f"RUNNING REAL ENGINE — {args.weeks} weeks")
    engine_obj = RealSimEngine(
        weeks=args.weeks,
        users_per_week=args.users_per_week,
        initial_users=args.users_per_week,
        simulation_label="isolated_launch_gate",
        run_id=run_id,
    )
    result = engine_obj.run(progress_callback=_progress)

    # ── Validate ───────────────────────────────────────────────────────────────
    failures = _check_invariants(result, args.weeks)
    _report_forensic(run_id)

    # ── Verdict ────────────────────────────────────────────────────────────────
    print("\n" + "#" * 74)
    if failures:
        print(f"# RESULT: {len(failures)} INVARIANT FAILURE(S) — LAUNCH GATE: RED — DO NOT LAUNCH")
        for f in failures:
            print(f"#   ✗ {f}")
        print("#" * 74)
        return 1
    print("# RESULT: ALL INVARIANTS HELD — LAUNCH GATE: GREEN")
    print("# Real engine ran the full horizon with zero L5/L6 leak, no draw freeze,")
    print("# no blowout, a draining waitlist, and bounded/sane pool counts.")
    print("#" * 74)
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except Exception:
        print("\n[ISOLATED SIM] UNHANDLED EXCEPTION — treating as RED:")
        traceback.print_exc()
        rc = 2
    finally:
        # Best-effort cleanup of the throwaway DB file (dispose engine first so
        # NullPool releases the file handle on Windows).
        try:
            import app.database as _db_mod  # may not be imported if we failed very early
            _db_mod.engine.dispose()
        except Exception:
            pass
        try:
            if os.path.exists(_DB_FILE):
                os.remove(_DB_FILE)
                print(f"[cleanup] removed throwaway DB {_DB_FILE}")
        except Exception as _exc:
            print(f"[cleanup] could not remove {_DB_FILE}: {_exc}")
    sys.exit(rc)
