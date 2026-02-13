from shared.config import settings

AGENT_NAME = "yield_oracle"
AGENT_ERC8004_ID = 0  # Set after minting NFT
AGENT_TBA = ""

# Scraping intervals
YIELD_SCRAPE_INTERVAL = 900         # Scrape yields every 15 min
PORTFOLIO_REBALANCE_INTERVAL = 3600 * 6  # Rebalance every 6 hours

# Protocols to monitor on Avalanche
PROTOCOLS = {
    "benqi": {
        "name": "Benqi",
        "type": "lending",
        "comptroller": "0x486Af39519B4Dc9a7fCcd318217352830E8AD9b4",
    },
    "aave_v3": {
        "name": "Aave V3",
        "type": "lending",
        "pool": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
    },
    "trader_joe": {
        "name": "Trader Joe",
        "type": "dex",
        "router": "0x60aE616a2155Ee3d9A68541Ba4544862310933d4",
        "factory": "0x9Ad6C38BE94206cA50bb0d90783181834C915697",
    },
    "yield_yak": {
        "name": "Yield Yak",
        "type": "autocompounder",
        "api_url": "https://staging-api.yieldyak.com/apys",
    },
    "pangolin": {
        "name": "Pangolin",
        "type": "dex",
        "router": "0xE54Ca86531e17Ef3616d22Ca28b0D458b6C89106",
        "factory": "0xefa94DE7a4656D787667C749f7E1223D71E9FD88",
    },
}

# Risk scoring
RISK_WEIGHTS = {
    "protocol_risk": 0.25,    # How safe is the protocol?
    "impermanent_loss": 0.20, # IL risk for LP positions
    "smart_contract": 0.20,   # Audit status, age, TVL
    "liquidity_depth": 0.15,  # Can you exit without slippage?
    "complexity": 0.10,       # Number of smart contract interactions
    "volatility": 0.10,      # Underlying asset volatility
}

# Portfolio models
PORTFOLIO_MODELS = {
    "conservative": {"max_risk": 30, "min_tvl_usd": 10_000_000},
    "balanced": {"max_risk": 60, "min_tvl_usd": 1_000_000},
    "aggressive": {"max_risk": 90, "min_tvl_usd": 100_000},
}

# Proof
PROOF_SUBMIT_HOUR = 9  # UTC 9am daily

# Known stablecoins (lower risk)
STABLECOINS = {"USDC", "USDT", "DAI", "USDC.e", "USDT.e", "DAI.e", "FRAX", "MIM"}
