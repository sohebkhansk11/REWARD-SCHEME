"""
Stress Simulator  — app/services/stress_simulator.py
======================================================
Specification-named entry point for the Heavy Engine Stress Test Simulator.

All implementation lives in real_simulation.py.  This module re-exports the
public API under the canonical spec names and adds the public run_cycles()
interface described in the PHASE 2 requirements.

Public API
----------
  ChronosEngine          — Time-travel: mocks datetime.now() globally
  MassLoadInjector       — Dummy traffic: users + DEP tokens + auto_pay_installments
  StressSimulator        — run_cycles(weeks=X) entry point (spec-required name)
  run_stress_test(...)   — convenience function for one-shot runs

Architecture
------------
The simulator acts ONLY as:
  1. A Load Injector (MassLoadInjector)
  2. A Time-Travel controller (ChronosEngine)

It drives the REAL production services in strict chronological order:

  [Monday]
    a. inject_week()               — X new users → DEP tokens burned → Waitlist/Paid
    b. auto_pay_installments()     — all Active members → Paid

  [Applied before T-2H]
    c. apply_abc_model()           — A/B/C late-fee + elimination

  [Saturday 22:00 — T-2H]
    d. start_draw_preparation()    ← REAL production service
       Internally runs:
         - flag_l4_members()
         - redistribute_multi_l4_pools()
         - run_sde_meta_pool()
         - acquires draw_engine system lock
         - writes WeeklyDrawState (LPI snapshot, SDE sessions, admin override flag)

  [Sunday 00:00 — T-0H]
    e. execute_weekly_draw()       ← REAL production service
       Internally runs:
         - check_and_run_sde_extensions() (Ext-II/III pre-pass)
         - SafeStop check (pools < 12 members paused)
         - draw loop (SDE-processed pools skipped via draw_completed_this_week)
         - assign_waitlist_to_pools() (Phase 1/2/3 refill)

  [Sunday 00:05 — T+5m]
    f. post_draw_cleanup()         ← REAL production service
       - Resets draw_completed_this_week on all pools
       - Clears stale L4/SDE flags
       - Releases draw_engine system lock

DRY GUARANTEE: no business logic is duplicated here.  Every formula, constant,
and algorithm lives exclusively in the production service modules.  Any change
to the production system is automatically reflected in the simulation.
"""

# Re-export the core classes under their canonical spec names
from app.services.real_simulation import (
    ChronosEngine as ChronosEngine,
    MassLoadInjector as MassLoadInjector,
    RealSimEngine,
    _create_sim_db,
    _snapshot,
)


# ── Public spec-named aliases ─────────────────────────────────────────────────

class StressSimulator(RealSimEngine):
    """
    Specification-named wrapper around RealSimEngine.

    Usage:
        sim = StressSimulator(
            weeks=52,
            users_per_week=24,
            initial_users=48,
            organic_ratio=0.7,
            late_ratio=0.03,
            elim_pct_a=80.0,
            grace_pct_c=15.0,
        )
        result = sim.run_cycles()
    """

    def run_cycles(self, weeks: int | None = None) -> dict:
        """
        Run the stress test for `weeks` weekly draw cycles.

        If `weeks` is not provided, uses the value set at construction.
        Returns a dict with `simulation_summary`, `weekly_detail`, `cycle_logs`.

        This method is a dumb loop that calls real production services in
        exact chronological order — no core logic lives here.
        """
        if weeks is not None:
            self.weeks = max(1, min(weeks, 200))
        return self.run()


def run_stress_test(
    weeks:           int   = 52,
    users_per_week:  int   = 24,
    initial_users:   int   = 24,
    organic_ratio:   float = 0.6,
    late_ratio:      float = 0.02,
    elim_pct_a:      float = 80.0,
    grace_pct_c:     float = 15.0,
    volatility_mode: bool  = False,
    volatility_max:  int   = 100,
    start_year:      int   = 2024,
    start_week:      int   = 1,
) -> dict:
    """
    Convenience function: create a StressSimulator and run it immediately.

    Example:
        from app.services.stress_simulator import run_stress_test
        result = run_stress_test(weeks=52, users_per_week=30)
        print(result["simulation_summary"]["total_winners_drawn"])
    """
    sim = StressSimulator(
        weeks           = weeks,
        users_per_week  = users_per_week,
        initial_users   = initial_users,
        organic_ratio   = organic_ratio,
        late_ratio      = late_ratio,
        elim_pct_a      = elim_pct_a,
        grace_pct_c     = grace_pct_c,
        volatility_mode = volatility_mode,
        volatility_max  = volatility_max,
        start_year      = start_year,
        start_week      = start_week,
    )
    return sim.run_cycles()


# ── Module-level constants exposed for external callers ───────────────────────

CHRONOLOGICAL_ORDER = [
    "a. inject_week()               [Monday]          — users + DEP tokens → Waitlist",
    "b. auto_pay_installments()     [Monday]          — Active members → Paid",
    "c. apply_abc_model()           [Wednesday-Thu]   — A/B/C late-fee + elimination",
    "d. start_draw_preparation()    [Saturday 22:00]  — lock + L4 flag + SDE meta-pool",
    "e. execute_weekly_draw()       [Sunday 00:00]    — Ext-II/III + all pool draws",
    "f. post_draw_cleanup()         [Sunday 00:05]    — reset flags + release lock",
]
