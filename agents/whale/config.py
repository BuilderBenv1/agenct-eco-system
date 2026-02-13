from shared.config import settings

AGENT_NAME = "whale"
AGENT_ERC8004_ID = settings.WHALE_ERC8004_ID
AGENT_TBA = settings.WHALE_TBA

# Monitoring
TX_POLL_INTERVAL = 30              # Check for new txns every 30s
ANALYSIS_BATCH_SIZE = 10           # Max txns to analyze per cycle
MIN_VALUE_USD = 10_000             # Minimum USD value to track

# Significance thresholds (USD)
SIGNIFICANCE_THRESHOLDS = {
    "critical": 1_000_000,
    "high": 500_000,
    "medium": 100_000,
    "low": 10_000,
}

# Alert thresholds — only alert on high+ significance
ALERT_MIN_SIGNIFICANCE = "high"

# Report
REPORT_INTERVAL_HOURS = 24         # Daily report
PROOF_SUBMIT_HOUR = 6              # UTC 6am daily

# Snowtrace/RPC
MAX_BLOCKS_PER_POLL = 100
