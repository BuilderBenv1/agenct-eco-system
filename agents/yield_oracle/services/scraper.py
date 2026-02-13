"""
Yield Scraper — Fetches yield data from DeFi protocols on Avalanche.
Reads on-chain rates from Benqi/Aave and uses APIs for DEX/vault yields.
"""
import httpx
from datetime import datetime, timezone
from sqlalchemy import select, update
from shared.database import async_session
from shared.web3_client import w3
from agents.yield_oracle.models.db import YieldOpportunity
from agents.yield_oracle.config import PROTOCOLS, STABLECOINS
import structlog

logger = structlog.get_logger()

# Benqi QiToken ABI for supply/borrow rates
QITOKEN_ABI = [
    {"constant": True, "inputs": [], "name": "supplyRatePerTimestamp", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "borrowRatePerTimestamp", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "exchangeRateStored", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "getCash", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

# Aave v3 Pool ABI
AAVE_POOL_ABI = [
    {"inputs": [], "name": "getReservesList", "outputs": [{"name": "", "type": "address[]"}], "stateMutability": "view", "type": "function"},
]

AAVE_DATA_PROVIDER_ABI = [
    {"inputs": [{"name": "asset", "type": "address"}], "name": "getReserveData", "outputs": [
        {"name": "unbacked", "type": "uint256"},
        {"name": "accruedToTreasuryScaled", "type": "uint256"},
        {"name": "totalAToken", "type": "uint256"},
        {"name": "totalStableDebt", "type": "uint256"},
        {"name": "totalVariableDebt", "type": "uint256"},
        {"name": "liquidityRate", "type": "uint256"},
        {"name": "variableBorrowRate", "type": "uint256"},
        {"name": "stableBorrowRate", "type": "uint256"},
        {"name": "averageStableBorrowRate", "type": "uint256"},
        {"name": "liquidityIndex", "type": "uint256"},
        {"name": "variableBorrowIndex", "type": "uint256"},
        {"name": "lastUpdateTimestamp", "type": "uint40"},
    ], "stateMutability": "view", "type": "function"},
]

# Known Benqi markets
BENQI_MARKETS = {
    "0x5C0401e81Bc07Ca70fAD469b451682c0d747Ef1c": {"symbol": "qiAVAX", "underlying": "AVAX", "decimals": 18},
    "0xBEb5d47A3f720Ec0a390d04b4d41ED7d9688bC7F": {"symbol": "qiUSDC", "underlying": "USDC", "decimals": 6},
    "0x334AD834Cd4481BB02d09615E7c11a00579A7909": {"symbol": "qiETH", "underlying": "ETH", "decimals": 18},
    "0xe194c4c5aC32a3C9ffDb358d9Bfd523a0B6d1568": {"symbol": "qiBTC", "underlying": "BTC", "decimals": 8},
    "0x835866d37AFB8CB8F8334dCCdaf66cf01832Ff5D": {"symbol": "qiDAI", "underlying": "DAI", "decimals": 18},
}

# Seconds per year for APY calculation
SECONDS_PER_YEAR = 365.25 * 24 * 3600


async def scrape_benqi_yields() -> list[dict]:
    """Fetch supply APYs from Benqi lending markets."""
    opportunities = []

    for market_address, info in BENQI_MARKETS.items():
        try:
            contract = w3.eth.contract(
                address=w3.to_checksum_address(market_address),
                abi=QITOKEN_ABI,
            )

            supply_rate = contract.functions.supplyRatePerTimestamp().call()
            # APY = (1 + rate_per_second) ^ seconds_per_year - 1
            supply_apy = ((1 + supply_rate / 1e18) ** SECONDS_PER_YEAR - 1) * 100

            # Estimate TVL from getCash
            try:
                cash = contract.functions.getCash().call()
                decimals = info["decimals"]
                tvl_tokens = cash / (10 ** decimals)
                # Rough USD estimate (would use price feed in production)
                tvl_usd = tvl_tokens * _get_rough_price(info["underlying"])
            except Exception:
                tvl_usd = 0

            opportunities.append({
                "protocol": "benqi",
                "pool_name": f"Benqi {info['underlying']} Supply",
                "pool_address": market_address,
                "pool_type": "lending",
                "token_a": info["underlying"],
                "token_a_address": market_address,
                "apy": round(supply_apy, 2),
                "base_apy": round(supply_apy, 2),
                "reward_apy": 0.0,  # QI rewards would need separate query
                "tvl_usd": tvl_usd,
            })

            logger.debug("benqi_yield_fetched", market=info["symbol"], apy=f"{supply_apy:.2f}%")

        except Exception as e:
            logger.error("benqi_scrape_failed", market=info["symbol"], error=str(e))

    return opportunities


async def scrape_aave_yields() -> list[dict]:
    """Fetch supply APYs from Aave v3 on Avalanche."""
    opportunities = []
    aave_pool = PROTOCOLS["aave_v3"]["pool"]
    data_provider = "0x69FA688f1Dc47d4B5d8029D5a35FB7a548310654"

    try:
        pool = w3.eth.contract(
            address=w3.to_checksum_address(aave_pool),
            abi=AAVE_POOL_ABI,
        )
        reserves = pool.functions.getReservesList().call()

        provider = w3.eth.contract(
            address=w3.to_checksum_address(data_provider),
            abi=AAVE_DATA_PROVIDER_ABI,
        )

        for reserve_address in reserves[:10]:  # Limit to top 10
            try:
                data = provider.functions.getReserveData(reserve_address).call()
                liquidity_rate = data[5]  # liquidityRate in ray (27 decimals)
                supply_apy = (liquidity_rate / 1e27) * 100  # Convert ray to percentage

                # Try to get token symbol
                token_symbol = _address_to_symbol(reserve_address)

                total_supply_scaled = data[2]
                tvl_usd = (total_supply_scaled / 1e18) * _get_rough_price(token_symbol)

                opportunities.append({
                    "protocol": "aave_v3",
                    "pool_name": f"Aave V3 {token_symbol} Supply",
                    "pool_address": reserve_address,
                    "pool_type": "lending",
                    "token_a": token_symbol,
                    "token_a_address": reserve_address,
                    "apy": round(supply_apy, 2),
                    "base_apy": round(supply_apy, 2),
                    "reward_apy": 0.0,
                    "tvl_usd": tvl_usd,
                })

            except Exception as e:
                logger.debug("aave_reserve_failed", reserve=reserve_address[:10], error=str(e))

    except Exception as e:
        logger.error("aave_scrape_failed", error=str(e))

    return opportunities


async def scrape_yield_yak() -> list[dict]:
    """Fetch yield data from Yield Yak auto-compounder API."""
    opportunities = []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(PROTOCOLS["yield_yak"]["api_url"])
            if resp.status_code != 200:
                logger.warning("yield_yak_api_failed", status=resp.status_code)
                return []

            data = resp.json()

            # Yield Yak returns APYs keyed by farm address
            for farm_address, farm_data in list(data.items())[:20]:
                if not isinstance(farm_data, dict):
                    continue

                apy = farm_data.get("apy", 0)
                if not isinstance(apy, (int, float)) or apy <= 0:
                    continue

                opportunities.append({
                    "protocol": "yield_yak",
                    "pool_name": f"Yield Yak {farm_data.get('name', farm_address[:10])}",
                    "pool_address": farm_address,
                    "pool_type": "vault",
                    "token_a": farm_data.get("symbol", ""),
                    "apy": round(float(apy), 2),
                    "base_apy": round(float(apy), 2),
                    "reward_apy": 0.0,
                    "tvl_usd": float(farm_data.get("tvl", 0)) if farm_data.get("tvl") else 0,
                })

    except Exception as e:
        logger.error("yield_yak_scrape_failed", error=str(e))

    return opportunities


def _get_rough_price(symbol: str) -> float:
    """Rough USD price estimates. In production, use price feeds."""
    prices = {
        "AVAX": 35.0, "ETH": 3500.0, "BTC": 95000.0,
        "USDC": 1.0, "USDT": 1.0, "DAI": 1.0,
        "USDC.e": 1.0, "USDT.e": 1.0, "DAI.e": 1.0,
        "LINK": 25.0, "WETH.e": 3500.0, "WBTC.e": 95000.0,
    }
    return prices.get(symbol, 1.0)


def _address_to_symbol(address: str) -> str:
    """Try to map an address to a token symbol."""
    known = {
        "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7": "WAVAX",
        "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e": "USDC",
        "0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7": "USDT",
        "0x49d5c2bdffac6ce2bfdb6fd9b6002f85860dacdb": "WETH.e",
        "0x50b7545627a5162f82a992c33b87adc75187b218": "WBTC.e",
        "0xd586e7f844cea2f87f50152665bcbc2c279d8d70": "DAI.e",
        "0x5947bb275c521040051d82396192181b413227a3": "LINK.e",
        "0xa7d7079b0fead91f3e65f86e8915cb59c1a4c664": "USDC.e",
    }
    return known.get(address.lower(), address[:8])


async def scrape_all_yields() -> list[dict]:
    """Scrape yields from all configured protocols."""
    all_opportunities = []

    benqi = await scrape_benqi_yields()
    all_opportunities.extend(benqi)
    logger.info("benqi_yields_scraped", count=len(benqi))

    aave = await scrape_aave_yields()
    all_opportunities.extend(aave)
    logger.info("aave_yields_scraped", count=len(aave))

    yak = await scrape_yield_yak()
    all_opportunities.extend(yak)
    logger.info("yield_yak_scraped", count=len(yak))

    logger.info("total_yields_scraped", count=len(all_opportunities))
    return all_opportunities


async def save_opportunities(opportunities: list[dict]):
    """Save or update yield opportunities in the database."""
    if async_session is None or not opportunities:
        return

    async with async_session() as db:
        for opp in opportunities:
            # Check for existing
            existing = await db.execute(
                select(YieldOpportunity).where(
                    YieldOpportunity.protocol == opp["protocol"],
                    YieldOpportunity.pool_address == opp.get("pool_address"),
                    YieldOpportunity.is_active == True,
                )
            )
            record = existing.scalar_one_or_none()

            if record:
                await db.execute(
                    update(YieldOpportunity)
                    .where(YieldOpportunity.id == record.id)
                    .values(
                        apy=opp["apy"],
                        base_apy=opp.get("base_apy", opp["apy"]),
                        reward_apy=opp.get("reward_apy", 0),
                        tvl_usd=opp.get("tvl_usd", 0),
                        last_updated=datetime.now(timezone.utc),
                    )
                )
            else:
                record = YieldOpportunity(
                    protocol=opp["protocol"],
                    pool_name=opp["pool_name"],
                    pool_address=opp.get("pool_address"),
                    pool_type=opp.get("pool_type"),
                    token_a=opp.get("token_a"),
                    token_b=opp.get("token_b"),
                    token_a_address=opp.get("token_a_address"),
                    token_b_address=opp.get("token_b_address"),
                    apy=opp["apy"],
                    base_apy=opp.get("base_apy", opp["apy"]),
                    reward_apy=opp.get("reward_apy", 0),
                    tvl_usd=opp.get("tvl_usd", 0),
                )
                db.add(record)

        await db.commit()
        logger.info("opportunities_saved", count=len(opportunities))


async def scrape_and_save():
    """Full scraping pipeline."""
    opportunities = await scrape_all_yields()
    await save_opportunities(opportunities)
    return len(opportunities)
