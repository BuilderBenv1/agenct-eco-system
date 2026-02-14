from shared.config import settings

AGENT_NAME = "sos"
SOS_ERC8004_ID = 0
SOS_TBA = ""

# Monitoring intervals
CRASH_CHECK_INTERVAL = 60          # Check for crashes every 60 seconds
PROTOCOL_CHECK_INTERVAL = 120     # Check protocol TVL every 2 minutes
HEALTH_CHECK_INTERVAL = 120       # Check lending health factors every 2 minutes
PROOF_SUBMIT_HOUR = 8

# Defaults
DEFAULT_CRASH_THRESHOLD_PCT = 15.0       # 15% drop in 1 hour
DEFAULT_PROTOCOL_TVL_THRESHOLD_PCT = 50  # 50% TVL drop = potential hack
DEFAULT_HEALTH_FACTOR_THRESHOLD = 1.05
DEFAULT_EXIT_TOKEN = "USDC"
DEFAULT_SLIPPAGE_PCT = 2.0  # Higher slippage for emergency exits

SUBSCRIPTION_PLAN_ID = 0
