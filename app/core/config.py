# ── Pool geometry ─────────────────────────────────────────────────────────────
POOL_CAPACITY:   int = 12   # members per pool
WAITLIST_TRIGGER: int = 24   # spawn new pool when waitlist reaches this
NEW_POOL_INTAKE:  int = 12   # members moved from waitlist to a new pool

# ── Financial constants ────────────────────────────────────────────────────────
DEPOSIT_AMOUNT_INR:  int = 1000
PAYOUT_FEE_INR:      int = 500    # deducted from gross before payout
REFERRAL_REWARD_INR: int = 250    # REF token issued when referred user enters Active Pool
LATE_FEE_DAILY_INR:  int = 50     # accrues each day a member is Unpaid after Sunday

# Per-level payouts: level → (gross_inr, net_inr after ₹500 fee)
# L5 / L6 are edge-case only (admin override / extreme scenarios).
# Normal operation cap: L4 upper (₹5,500 net) + L2 lower (₹3,000 net) = ₹8,500 max.
LEVEL_PAYOUTS: dict[int, tuple[int, int]] = {
    1: (2500, 2000),
    2: (3500, 3000),
    3: (4500, 4000),
    4: (6000, 5500),
    5: (7000, 6500),
    6: (8500, 8000),
}

# ── Tier split constants ───────────────────────────────────────────────────────
# REGULAR pool tier split (legacy / low-LPI pools)
#   Lower tier: L1–L3   Upper tier: L4–L6
LEVEL_LOW:  tuple[int, int] = (1, 3)
LEVEL_HIGH: tuple[int, int] = (4, 6)

# EXECUTION pool tier split (Type A and SDE pools — new architecture)
#   Lower tier: L1–L2   Upper tier: L3–L4
EXEC_LEVEL_LOW:  tuple[int, int] = (1, 2)
EXEC_LEVEL_HIGH: tuple[int, int] = (3, 4)

# SDE pool tier split (SDE sub-draws)
#   Lower tier: L1–L2 (L3 allowed only under LPI > 50% exception)
#   Upper tier: L4 ONLY (hardcoded single candidate — guaranteed exit)
SDE_LEVEL_LOWER_NORMAL:    tuple[int, int] = (1, 2)   # normal operation
SDE_LEVEL_LOWER_EXCEPTION: tuple[int, int] = (1, 3)   # LPI > 50% exception
SDE_LEVEL_UPPER:           tuple[int, int] = (4, 4)   # always exactly L4

# TYPE B pool tier split (fallback when L1/L2 exhausted)
#   Lower tier: L3 only   Upper tier: L4 only
TYPE_B_LEVEL_LOW:  tuple[int, int] = (3, 3)
TYPE_B_LEVEL_HIGH: tuple[int, int] = (4, 4)

# ── Draw type string constants (stored in pool.pool_draw_type) ────────────────
POOL_DRAW_REGULAR = "regular"
POOL_DRAW_TYPE_A  = "type_a"
POOL_DRAW_SDE     = "sde"
POOL_DRAW_TYPE_B  = "type_b"

# ── LPI (Level Pressure Index) thresholds ────────────────────────────────────
# LPI = (L3 + L4 + L5 + L6) ÷ Total Active Members × 100
LPI_REGULAR_MAX:  float = 14.0   # LPI < 14  → Regular Pool
LPI_TYPE_A_MIN:   float = 14.0   # LPI 14–24 → Execution Pool Type A
LPI_SDE_PROACTIVE: float = 25.0  # LPI ≥ 25  → SDE proactive (regardless of L4 count)
LPI_L3_WIN_EXCEPTION: float = 50.0  # LPI > 50 → L3 allowed to win SDE lower tier

# ── SDE operational constraints ───────────────────────────────────────────────
SDE_MAX_POOLS_PER_SESSION:  int = 6   # sub-draws per SDE session (6 shared seeds)
SDE_L1L2_THRESHOLD_PER_L4:  int = 2   # minimum L1/L2 candidates needed per L4 member

# ── Condensation / draw window ────────────────────────────────────────────────
# System pauses only when confirmed new member inflow drops below this threshold.
SYSTEM_PAUSE_INFLOW_THRESHOLD:    int = 2    # confirmed DEP token burns per week
# Draw preparation window (hours before draw time)
DRAW_PREPARATION_HOURS_BEFORE:    int = 2
# Post-draw cleanup window (minutes after draw — lock held until cleanup completes)
DRAW_LOCK_TOTAL_MINUTES:          int = 130  # 2h prep + 0h draw + 10m cleanup

# ── Admin override: auto-select timeout ───────────────────────────────────────
ADMIN_OVERRIDE_TIMEOUT_HOURS: int = 2   # auto-select after this if admin is silent

# ── Brain 2 velocity windows ──────────────────────────────────────────────────
BRAIN2_SLOW_VELOCITY_DAYS: int = 14     # SMA window (was 21 — reduced for responsiveness)
BRAIN2_FAST_VELOCITY_HOURS: int = 48    # EMA lookback
# Tri-velocity blend weights (must sum to 1.0)
BRAIN2_WEIGHT_SLOW:    float = 0.50
BRAIN2_WEIGHT_FAST:    float = 0.30
BRAIN2_WEIGHT_FORWARD: float = 0.20
# Cliff detection: if today_rate < N days ago rate × this factor → cliff
BRAIN2_CLIFF_REFERENCE_DAYS: int = 3
BRAIN2_CLIFF_FACTOR:        float = 0.5

# ── SDE AI weight formula coefficients ────────────────────────────────────────
# Weight = (weeks_in_pool × W_TIME) + (deposits_k × W_DEPOSIT)
#        + (pauses × W_PAUSE) + (organic_score × W_ORGANIC)
#        + (random_noise × W_NOISE)
SDE_WEIGHT_TIME:    float = 0.30
SDE_WEIGHT_DEPOSIT: float = 0.25
SDE_WEIGHT_PAUSE:   float = 0.20
SDE_WEIGHT_ORGANIC: float = 0.15   # 1.0 if organic join, 0.3 if referred
SDE_WEIGHT_NOISE:   float = 0.10
SDE_WEIGHT_MIN_FLOOR: float = 0.05  # minimum probability floor for any eligible candidate
