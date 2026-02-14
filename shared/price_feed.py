"""
Shared price feed — CoinGecko + on-chain fallback.

Caches prices for 60 seconds. Used by DCA, Grid, SOS, and Sniper bots.
"""
import time
import httpx
from shared.config import settings
import structlog

logger = structlog.get_logger()

# CoinGecko IDs for common Avalanche tokens
TOKEN_COINGECKO_IDS = {
    "AVAX": "avalanche-2",
    "WAVAX": "wrapped-avax",
    "JOE": "joe",
    "GMX": "gmx",
    "USDC": "usd-coin",
    "USDT": "tether",
    "USDC.e": "usd-coin",
    "USDT.e": "tether",
    "BTC.b": "bitcoin",
    "WETH.e": "ethereum",
    "WBTC.e": "wrapped-bitcoin",
    "sAVAX": "benqi-liquid-staked-avax",
    "QI": "benqi",
    "PNG": "pangolin",
}

# Token address -> CoinGecko ID
TOKEN_ADDRESS_IDS = {
    "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7": "wrapped-avax",       # WAVAX
    "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E": "usd-coin",           # USDC
    "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7": "tether",              # USDT
    "0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB": "ethereum",            # WETH.e
    "0x152b9d0FdC40C096DE345fFCc9B86F0d5a9F8731": "bitcoin",             # BTC.b
    "0x6e84a6216eA6dACC71eE8E6b0a5B7322EEbC0fDd": "joe",                # JOE
    "0x62edc0692BD897D2295872a9FFCac5425011c661": "gmx",                 # GMX
    "0x2b2C81e08f1Af8835a78Bb2A90AE924ACE0eA4bE": "benqi-liquid-staked-avax",  # sAVAX
}

# Price cache: {coingecko_id: (price_usd, timestamp)}
_price_cache: dict[str, tuple[float, float]] = {}
CACHE_TTL = 60  # seconds


async def get_price_by_symbol(symbol: str) -> float | None:
    """Get USD price by token symbol."""
    cg_id = TOKEN_COINGECKO_IDS.get(symbol.upper())
    if not cg_id:
        return None
    return await _fetch_price(cg_id)


async def get_price_by_address(token_address: str) -> float | None:
    """Get USD price by token contract address."""
    cg_id = TOKEN_ADDRESS_IDS.get(token_address)
    if not cg_id:
        # Try CoinGecko platform lookup
        return await _fetch_price_by_contract(token_address)
    return await _fetch_price(cg_id)


async def get_avax_price() -> float:
    """Get AVAX price in USD."""
    price = await _fetch_price("avalanche-2")
    return price or 0.0


async def get_prices_batch(symbols: list[str]) -> dict[str, float]:
    """Get prices for multiple symbols at once."""
    ids = []
    symbol_to_id = {}
    for s in symbols:
        cg_id = TOKEN_COINGECKO_IDS.get(s.upper())
        if cg_id:
            ids.append(cg_id)
            symbol_to_id[s.upper()] = cg_id

    if not ids:
        return {}

    # Check cache first
    now = time.time()
    result = {}
    missing_ids = []
    for sym, cg_id in symbol_to_id.items():
        if cg_id in _price_cache and (now - _price_cache[cg_id][1]) < CACHE_TTL:
            result[sym] = _price_cache[cg_id][0]
        else:
            missing_ids.append(cg_id)

    # Fetch missing
    if missing_ids:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{settings.COINGECKO_API_URL}/simple/price",
                    params={"ids": ",".join(set(missing_ids)), "vs_currencies": "usd"},
                )
                data = resp.json()
                for sym, cg_id in symbol_to_id.items():
                    if cg_id in data and "usd" in data[cg_id]:
                        price = data[cg_id]["usd"]
                        _price_cache[cg_id] = (price, now)
                        result[sym] = price
        except Exception as e:
            logger.error("batch_price_fetch_failed", error=str(e))

    return result


async def _fetch_price(coingecko_id: str) -> float | None:
    """Fetch a single token price from CoinGecko with caching."""
    now = time.time()
    if coingecko_id in _price_cache:
        cached_price, cached_at = _price_cache[coingecko_id]
        if (now - cached_at) < CACHE_TTL:
            return cached_price

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.COINGECKO_API_URL}/simple/price",
                params={"ids": coingecko_id, "vs_currencies": "usd"},
            )
            data = resp.json()
            if coingecko_id in data and "usd" in data[coingecko_id]:
                price = data[coingecko_id]["usd"]
                _price_cache[coingecko_id] = (price, now)
                return price
    except Exception as e:
        logger.error("price_fetch_failed", coingecko_id=coingecko_id, error=str(e))

    # Return stale cache if available
    if coingecko_id in _price_cache:
        return _price_cache[coingecko_id][0]
    return None


async def _fetch_price_by_contract(token_address: str) -> float | None:
    """Fetch price by contract address from CoinGecko."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.COINGECKO_API_URL}/simple/token_price/avalanche",
                params={"contract_addresses": token_address.lower(), "vs_currencies": "usd"},
            )
            data = resp.json()
            addr_lower = token_address.lower()
            if addr_lower in data and "usd" in data[addr_lower]:
                return data[addr_lower]["usd"]
    except Exception as e:
        logger.error("contract_price_fetch_failed", address=token_address, error=str(e))
    return None


async def get_price_change_pct(symbol: str, hours: int = 1) -> float | None:
    """Get price change percentage over the last N hours. Uses 24h data from CoinGecko."""
    cg_id = TOKEN_COINGECKO_IDS.get(symbol.upper())
    if not cg_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.COINGECKO_API_URL}/coins/{cg_id}",
                params={"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"},
            )
            data = resp.json()
            if hours <= 1:
                return data.get("market_data", {}).get("price_change_percentage_1h_in_currency", {}).get("usd")
            elif hours <= 24:
                return data.get("market_data", {}).get("price_change_percentage_24h")
            else:
                return data.get("market_data", {}).get("price_change_percentage_7d")
    except Exception as e:
        logger.error("price_change_fetch_failed", symbol=symbol, error=str(e))
    return None
