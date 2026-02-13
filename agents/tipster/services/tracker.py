"""
Price Tracker — Polls CoinGecko for prices of tokens mentioned in signals,
records price changes over time for performance verification.
"""
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared.config import settings
from shared.database import async_session
from agents.tipster.models.db import TipsterSignal, TipsterPriceCheck
from agents.tipster.config import PRICE_TRACK_DURATION_HOURS, COINGECKO_BATCH_SIZE
import structlog

logger = structlog.get_logger()

# Common Avalanche token symbol -> CoinGecko ID mapping
SYMBOL_TO_COINGECKO = {
    "AVAX": "avalanche-2",
    "JOE": "joe",
    "GMX": "gmx",
    "AAVE": "aave",
    "LINK": "chainlink",
    "BTC": "bitcoin",
    "WBTC": "wrapped-bitcoin",
    "ETH": "ethereum",
    "WETH": "weth",
    "USDC": "usd-coin",
    "USDT": "tether",
    "DAI": "dai",
    "PNG": "pangolin",
    "QI": "benqi",
    "XAVA": "avalaunch",
    "PTP": "platypus-finance",
    "STG": "stargate-finance",
    "SUSHI": "sushi",
    "CRV": "curve-dao-token",
    "YAK": "yield-yak",
    "BSGG": "betswirl",
    "COQ": "coq-inu",
    "KIMBO": "kimbo",
}


async def _fetch_prices(coingecko_ids: list[str]) -> dict[str, float]:
    """Fetch current USD prices from CoinGecko for a batch of token IDs."""
    if not coingecko_ids:
        return {}
    ids_str = ",".join(coingecko_ids)
    url = f"{settings.COINGECKO_API_URL}/simple/price"
    params = {"ids": ids_str, "vs_currencies": "usd"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return {cid: data[cid]["usd"] for cid in data if "usd" in data[cid]}
    except Exception as e:
        logger.error("coingecko_fetch_failed", error=str(e))
        return {}


def _resolve_coingecko_id(symbol: str) -> str | None:
    """Map token symbol to CoinGecko ID."""
    return SYMBOL_TO_COINGECKO.get(symbol.upper())


async def check_signal_prices():
    """
    Check prices for all active signals (created within PRICE_TRACK_DURATION_HOURS).
    Records a new price check entry for each.
    """
    if async_session is None:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=PRICE_TRACK_DURATION_HOURS)

    async with async_session() as db:
        result = await db.execute(
            select(TipsterSignal)
            .where(
                TipsterSignal.is_valid == True,
                TipsterSignal.created_at >= cutoff,
                TipsterSignal.token_symbol.isnot(None),
            )
        )
        signals = list(result.scalars().all())
        if not signals:
            return

        # Collect unique symbols and their CoinGecko IDs
        symbol_map: dict[str, str] = {}
        for sig in signals:
            sym = sig.token_symbol.upper()
            if sym not in symbol_map:
                cg_id = _resolve_coingecko_id(sym)
                if cg_id:
                    symbol_map[sym] = cg_id

        if not symbol_map:
            logger.debug("no_resolvable_tokens")
            return

        # Batch fetch prices
        cg_ids = list(symbol_map.values())
        batches = [cg_ids[i:i + COINGECKO_BATCH_SIZE] for i in range(0, len(cg_ids), COINGECKO_BATCH_SIZE)]
        all_prices: dict[str, float] = {}
        for batch in batches:
            prices = await _fetch_prices(batch)
            all_prices.update(prices)

        # Reverse map: CoinGecko ID -> price
        id_to_price = all_prices

        # Create price checks
        now = datetime.now(timezone.utc)
        for sig in signals:
            sym = sig.token_symbol.upper()
            cg_id = symbol_map.get(sym)
            if not cg_id or cg_id not in id_to_price:
                continue

            current_price = id_to_price[cg_id]
            price_at_signal = float(sig.entry_price) if sig.entry_price else None
            change_pct = None
            if price_at_signal and price_at_signal > 0:
                change_pct = ((current_price - price_at_signal) / price_at_signal) * 100

            check = TipsterPriceCheck(
                signal_id=sig.id,
                token_symbol=sym,
                coingecko_id=cg_id,
                price_at_signal=price_at_signal,
                current_price=current_price,
                price_change_pct=change_pct,
                checked_at=now,
            )
            db.add(check)

        await db.commit()
        logger.info("price_checks_completed", signals_checked=len(signals))
