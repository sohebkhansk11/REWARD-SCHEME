# ── Pool geometry ─────────────────────────────────────────────────────────────
POOL_CAPACITY:   int = 12   # members per pool
WAITLIST_TRIGGER: int = 24   # spawn new pool when waitlist reaches this
NEW_POOL_INTAKE:  int = 12   # members moved from waitlist to a new pool

# ── Financial constants ────────────────────────────────────────────────────────
DEPOSIT_AMOUNT_INR:  int = 1000
PAYOUT_FEE_INR:      int = 500    # deducted from gross before payout
REFERRAL_REWARD_INR: int = 250    # REF token issued when referred user enters Active Pool
LATE_FEE_DAILY_INR:  int = 50     # accrues each day a member is Unpaid after Sunday
LATE_FEE_MAX_CAP_INR: int = 500   # maximum total late fee a member can accumulate (caps after 10 days)

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
POOL_DRAW_REGULAR  = "regular"
POOL_DRAW_TYPE_A   = "type_a"
POOL_DRAW_SDE      = "sde"
POOL_DRAW_TYPE_B   = "type_b"
# SDE Extension II  — L5 forced exit (L5 should never exist; escalation tier)
#   Upper tier: L5 ONLY    Lower tier: L1–L4 (all members below L5)
POOL_DRAW_SDE_EXT2 = "sde_ext2"
# SDE Extension III — L6 forced exit (extreme admin-override edge case only)
#   Upper tier: L6 ONLY    Lower tier: L1–L5 (all members below L6)
POOL_DRAW_SDE_EXT3 = "sde_ext3"
# Accelerated Dissolution — BOTH winners from L4+ (used when pool is >60% upper tier)
#   Both Winner 1 and Winner 2 drawn from L4/L5/L6.
#   Created simultaneously with a new relief pool from waitlist.
POOL_DRAW_ACCELERATED = "accelerated_dissolution"
# SESSION EDIT [Claude Session Jun-14 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Case C — Meta Pool cross-pool supply transfer
# POOL_DRAW_SDE_CASE_C: draw_type written to DrawHistory when the lower winner
#   was permanently transferred from a donor pool (edge_case_triggered=True).
# SDE_CASE_C_MIN_DONOR_L1L2: minimum L1/L2 a donor pool must have BEFORE donating
#   (3 = retains 2 after donating 1 — enough for future SDE lower tier if needed).
POOL_DRAW_SDE_CASE_C:     str = "sde_case_c"
SDE_CASE_C_MIN_DONOR_L1L2: int = 3
# SESSION EDIT [Claude Session Jun-14 — Soheb Khan User 2 / Sohebkhan.sk11]:
# Q4 Preventive L3 draw — both winners from L3 tier only, triggered when
# cascade_risk > CASCADE_PREVENT_L3_THRESH (2.0).  Exits 2 L3 members BEFORE
# they advance to L4 next week, reducing future SDE/cascade pressure proactively.
POOL_DRAW_SDE_PREVENTIVE_L3: str           = "sde_preventive_l3"
PREVENTIVE_L3_LEVEL:         tuple[int,int] = (3, 3)   # both winners from L3 only
CASCADE_PREVENT_L3_THRESH:   float          = 2.0      # cascade_risk threshold to trigger

# ── LPI (Level Pressure Index) thresholds ────────────────────────────────────
# LPI = (L3 + L4 + L5 + L6) ÷ Total Active Members × 100
LPI_REGULAR_MAX:  float = 14.0   # LPI < 14  → Regular Pool
LPI_TYPE_A_MIN:   float = 14.0   # LPI 14–24 → Execution Pool Type A
LPI_SDE_PROACTIVE: float = 25.0  # LPI ≥ 25  → SDE proactive (regardless of L4 count)
LPI_L3_WIN_EXCEPTION: float = 50.0  # LPI > 50 → L3 allowed to win SDE lower tier

# ── SDE Extension II tier splits ─────────────────────────────────────────────
# SDE Ext-II  triggers when any pool member reaches L5 (SDE failure / admin override)
SDE_EXT2_LEVEL_UPPER: tuple[int, int] = (5, 5)   # exactly L5 — forced exit
SDE_EXT2_LEVEL_LOWER: tuple[int, int] = (1, 4)   # L1-L4 — all below L5

# SDE Extension III triggers when any pool member reaches L6 (extreme edge case)
SDE_EXT3_LEVEL_UPPER: tuple[int, int] = (6, 6)   # exactly L6 — forced exit
SDE_EXT3_LEVEL_LOWER: tuple[int, int] = (1, 5)   # L1-L5 — all below L6

# Accelerated Dissolution tier split — BOTH winners from upper tier
ACCEL_DISS_LEVEL_LOWER: tuple[int, int] = (4, 6)  # L4-L6 (lower = minimum L4)
ACCEL_DISS_LEVEL_UPPER: tuple[int, int] = (4, 6)  # L4-L6 (upper = any L4+)
# Trigger: this fraction of pool members must be L4+ to auto-activate
ACCEL_DISS_TRIGGER_RATIO: float = 0.60   # 60% of pool is L4+ → accelerated draws
# After accelerated draws, dissolve pool if active member count drops below this
ACCEL_DISS_DISSOLVE_BELOW: int  = 8

# ── L5/L6 Payout Drawdown Protection ──────────────────────────────────────────
# If any member reaches L5, dual-L5 draw is ALWAYS cheaper than waiting.
# Math:  dual-L5 = ₹6,500 × 2 = ₹13,000 payout
#        L5+L6   = ₹6,500 + ₹8,000 = ₹14,500 (₹1,500 more per week of delay)
#        L6+L6   = ₹8,000 × 2 = ₹16,000 (₹3,000 more per 2-week delay)
# System always chooses lowest-drawdown option: eliminate L5 NOW via SDE Ext-II.
L5_DRAWDOWN_ENABLED: bool = True   # compute and log projection before Ext-II draw

# ── SDE operational constraints ───────────────────────────────────────────────
SDE_MAX_POOLS_PER_SESSION:  int = 6   # sub-draws per SDE session (6 shared seeds)
SDE_L1L2_THRESHOLD_PER_L4:  int = 2   # minimum L1/L2 candidates needed per L4 member
# Emergency WL promotion: when L1/L2 < 1 for lower tier, pull this many WL members
SDE_WL_EMERGENCY_PROMOTE:   int = 2   # max WL members to pull per emergency draw

# ── LEVER 5 — Meta-Pool Receiver (surplus-L4 drain venue) ─────────────────────
# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
# When a saturated pool has shed its 2 oldest flagged L4 (Lever 4) and is LOCKED,
# any 3rd+ flagged L4 has NO unlocked draw venue this week; left alone it survives
# its locked pool's staged draw and advances L4->L5 at T-0H (the unbounded leak).
# Lever 5 spawns a TEMPORARY meta pool from the Paid waitlist to give each such
# surplus L4 an UNLOCKED venue so it EXITS this week (Discussion.md Q3 / Question B;
# design: a meta pool needs only L4>=1 plus a small lower tier).
#   META_POOL_LOWER_MIN_NORMAL — lower-tier size pulled from WL in normal conditions.
#   META_POOL_LOWER_MIN_WORST  — absolute floor (worst case: WL has only 2 Paid left).
#   META_POOL_MAX_PER_WEEK     — cap on temporary pools spawned per draw cycle.
META_POOL_LOWER_MIN_NORMAL: int = 6   # 1 L4 + 6 lower = healthy meta pool (Q3 ~8)
META_POOL_LOWER_MIN_WORST:  int = 2   # 1 L4 + 2 lower = worst-case minimum pool
META_POOL_MAX_PER_WEEK:     int = 6   # bound spawned meta pools (== max pools/session)

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

# ── Adaptive Pool Creation Threshold ──────────────────────────────────────────
# Default threshold: 24 paid waitlist members triggers a new pool of 12.
# When growth rate ≤ pool consumption rate (active_pools × 2/week), the WL never
# accumulates enough to hit 24 → system freezes in single-pool equilibrium.
# Fix: reduce threshold when pressure rises or growth is insufficient.
#
# Formula:
#   effective_threshold = max(POOL_CAPACITY, WAITLIST_TRIGGER × (1 - pressure_factor))
#   pressure_factor     = min(0.5, LPI / 100)
#   Emergency override: if growth ≤ consumption AND LPI > 10% → threshold = POOL_CAPACITY
ADAPTIVE_THRESHOLD_ENABLED: bool  = True    # auto-reduce threshold under pressure
ADAPTIVE_THRESHOLD_MIN:     int   = 12      # hard floor = pool capacity
ADAPTIVE_THRESHOLD_LPI_FULL: float = 50.0  # LPI at which threshold = POOL_CAPACITY
