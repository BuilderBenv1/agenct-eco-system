from shared.config import settings

AGENT_NAME = "dca"
DCA_ERC8004_ID = 0  # Set after minting NFT
DCA_TBA = ""

# Scheduling
DCA_CHECK_INTERVAL = 60           # Check for due executions every 60 seconds
DIP_CHECK_INTERVAL = 300          # Check for dip-buy conditions every 5 minutes
PROOF_SUBMIT_HOUR = 8             # UTC 08:00

# Defaults
DEFAULT_SLIPPAGE_PCT = 1.0        # 1% slippage tolerance
DEFAULT_DIP_THRESHOLD_PCT = 10.0  # 10% drop = dip buy (2x)
DEFAULT_TAKE_PROFIT_PCT = 100.0   # Sell 25% at 2x
DEFAULT_TAKE_PROFIT_SELL_PCT = 25.0

# Subscription plan ID for DCA bot (on-chain)
SUBSCRIPTION_PLAN_ID = 0  # Set after creating plan on SubscriptionManager
