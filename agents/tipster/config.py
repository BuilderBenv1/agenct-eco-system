from shared.config import settings

# Tipster-specific constants
AGENT_NAME = "tipster"
AGENT_ERC8004_ID = settings.TIPSTER_ERC8004_ID
AGENT_TBA = settings.TIPSTER_TBA

# Monitoring intervals (seconds)
SIGNAL_POLL_INTERVAL = 60          # Check Telegram channels every 60s
PRICE_CHECK_INTERVAL = 900         # Check prices every 15 min
REPORT_INTERVAL_HOURS = 168        # Weekly report (7 days)

# Signal parsing thresholds
MIN_CONFIDENCE = 0.3               # Minimum confidence to store signal
HIGH_CONFIDENCE = 0.7              # Threshold for high-confidence alerts

# Price tracking
PRICE_TRACK_DURATION_HOURS = 168   # Track price for 7 days after signal
MAX_TARGETS = 5                    # Max target prices per signal

# CoinGecko batch size (free tier)
COINGECKO_BATCH_SIZE = 50

# Proof submission
PROOF_SUBMIT_DAY = 0               # Monday (0=Mon, 6=Sun)
PROOF_SUBMIT_HOUR = 12             # UTC noon
