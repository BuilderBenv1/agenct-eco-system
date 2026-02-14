from shared.config import settings

AGENT_NAME = "sniper"
SNIPER_ERC8004_ID = 0
SNIPER_TBA = ""

# Scanning
SCAN_INTERVAL = 15               # Scan for new pairs every 15 seconds
EXIT_CHECK_INTERVAL = 30         # Check TP/SL every 30 seconds
PROOF_SUBMIT_HOUR = 8

# Defaults
DEFAULT_MAX_BUY_AMOUNT_USD = 50.0
DEFAULT_MIN_LIQUIDITY_USD = 5000.0
DEFAULT_MAX_BUY_TAX_PCT = 10.0
DEFAULT_TAKE_PROFIT_MULTIPLIER = 2.0  # Sell at 2x
DEFAULT_STOP_LOSS_PCT = 50.0          # Sell if down 50%
DEFAULT_SLIPPAGE_PCT = 3.0            # Higher for new tokens

# Trader Joe Factory for PairCreated events
JOE_FACTORY = "0x9Ad6C38BE94206cA50bb0d90783181834C78e05e"

SUBSCRIPTION_PLAN_ID = 0
