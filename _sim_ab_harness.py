"""
TEMP A/B harness (not committed) — confirms the draw-stall deadlock fix.
Runs RealSimEngine on isolated in-memory SQLite (no production DB touched).
Seeds `random` for a reproducible structural comparison pre-fix vs post-fix.
"""
import random, json, sys

SEED   = 4242
PARAMS = dict(
    weeks=20,
    users_per_week=24,
    initial_users=24,
    organic_ratio=0.6,
    late_ratio=0.08,        # elevated to induce under-capacity → the deadlock path
    elim_pct_a=80.0,
    grace_pct_c=15.0,
    start_year=2024,
    start_week=1,
    inflow_pattern="linear",
    run_id="abtest00",
)

def main():
    random.seed(SEED)
    from app.services.real_simulation import RealSimEngine
    engine = RealSimEngine(**PARAMS)
    result = engine.run()
    wd = result.get("weekly_detail", [])
    print("wk | draws win | gDrawn | poolsAct poolsPaused | waitlist | scenario")
    zero_streak = 0
    max_streak  = 0
    for w in wd:
        d = w.get("draws_this_week", 0)
        if d == 0:
            zero_streak += 1
            max_streak = max(max_streak, zero_streak)
        else:
            zero_streak = 0
        print(f"{str(w.get('week')).rjust(2)} | "
              f"{str(d).rjust(3)} {str(w.get('winners_this_week',0)).rjust(3)} | "
              f"{str(w.get('gate_pools_drawn',0)).rjust(4)} | "
              f"{str(w.get('pools_active',0)).rjust(7)} {str(w.get('pools_paused',0)).rjust(11)} | "
              f"{str(w.get('waitlist_count',0)).rjust(4)} | {w.get('scenario','')[:20]}")
    total_draws = sum(w.get("draws_this_week", 0) for w in wd)
    zero_weeks  = sum(1 for w in wd if w.get("draws_this_week", 0) == 0)
    print(f"\nSUMMARY: total_draws={total_draws}  zero_draw_weeks={zero_weeks}/{len(wd)}  "
          f"max_consecutive_zero_streak={max_streak}")

if __name__ == "__main__":
    main()
