from shared.config import settings

AGENT_NAME = "auditor"
AGENT_ERC8004_ID = 0  # Set after minting NFT
AGENT_TBA = ""

# Scanning
SCAN_POLL_INTERVAL = 60            # Check for new deployments every 60s
SCAN_BLOCKS_PER_POLL = 50
NEW_TOKEN_MIN_LIQUIDITY_USD = 100  # Minimum liquidity to bother scanning

# Risk thresholds
RISK_LABELS = {
    "safe": (0, 25),
    "caution": (26, 50),
    "danger": (51, 75),
    "rug": (76, 100),
}

# Alert on danger+ risk
ALERT_MIN_RISK = 51

# Outcome tracking
OUTCOME_CHECK_INTERVAL = 3600 * 6  # Check outcomes every 6 hours
RUG_CONFIRM_DAYS = 7               # Wait 7 days to confirm rug outcome

# Report
PROOF_SUBMIT_HOUR = 7  # UTC 7am daily
