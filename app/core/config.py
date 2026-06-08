POOL_CAPACITY: int = 12
WAITLIST_TRIGGER: int = 24
NEW_POOL_INTAKE: int = 12

DEPOSIT_AMOUNT_INR: int = 1000
PAYOUT_FEE_INR: int = 500
REFERRAL_REWARD_INR: int = 250   # REF token issued when referred user enters Active Pool
LATE_FEE_DAILY_INR: int = 50     # accrues each day a member is Unpaid after Sunday

# Per-level payouts: level → (gross_inr, net_inr after ₹500 fee)
LEVEL_PAYOUTS: dict[int, tuple[int, int]] = {
    1: (2500, 2000),
    2: (3500, 3000),
    3: (4500, 4000),
    4: (6000, 5500),
    5: (7000, 6500),
    6: (8500, 8000),
}

LEVEL_LOW: tuple[int, int] = (1, 3)
LEVEL_HIGH: tuple[int, int] = (4, 6)
