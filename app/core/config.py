POOL_CAPACITY: int = 12          # members per active pool
WAITLIST_TRIGGER: int = 24       # paid waitlist count that fires auto-scale
NEW_POOL_INTAKE: int = 12        # members moved from waitlist into the new pool

DEPOSIT_AMOUNT_INR: int = 1000   # required face-value of a redeemable Deposit token
BASE_PAYOUT_INR: int = 5000      # gross payout per winner before fee
PAYOUT_FEE_INR: int = 500        # platform fee deducted from gross payout
NET_PAYOUT_INR: int = BASE_PAYOUT_INR - PAYOUT_FEE_INR  # 4 500

LEVEL_LOW: tuple[int, int] = (1, 3)   # level range for the first draw winner
LEVEL_HIGH: tuple[int, int] = (4, 6)  # level range for the second draw winner
