from shared.config import settings

AGENT_NAME = "narrative"
AGENT_ERC8004_ID = settings.NARRATIVE_ERC8004_ID
AGENT_TBA = settings.NARRATIVE_TBA

# Monitoring intervals
RSS_POLL_INTERVAL = 600            # Check RSS every 10 min
TELEGRAM_POLL_INTERVAL = 120       # Check Telegram channels every 2 min
COINGECKO_TRENDING_INTERVAL = 900  # Check CoinGecko trending every 15 min
TREND_ANALYSIS_INTERVAL = 3600     # Run trend detection every hour

# Sentiment thresholds
STRONG_SENTIMENT_THRESHOLD = 0.6   # |score| > 0.6 is strong sentiment
TREND_MIN_MENTIONS = 3             # Minimum mentions to form a trend

# Report
REPORT_INTERVAL_HOURS = 24
PROOF_SUBMIT_HOUR = 8              # UTC 8am daily

# Content limits
MAX_CONTENT_LENGTH = 5000          # Truncate long articles for Claude
MAX_ITEMS_PER_SOURCE = 20          # Max items to fetch per source per poll
