"""
Sniper Executor — Fast buy execution for approved token launches.
"""
from sqlalchemy import update
from shared.database import async_session
from shared.dex import swap_exact_avax_for_tokens
from shared.price_feed import get_avax_price
from shared.config import settings
from agents.sniper.models.db import SniperTrade, SniperConfig
from agents.sniper.config import DEFAULT_SLIPPAGE_PCT
import structlog

logger = structlog.get_logger()


async def execute_snipe(config: SniperConfig, launch: dict) -> dict | None:
    """Execute a snipe buy for an approved launch."""
    if async_session is None:
        return None

    token_address = launch["token_address"]
    symbol = launch.get("symbol", "UNKNOWN")
    buy_amount_usd = config.max_buy_amount_usd or 50.0

    # Convert USD to AVAX
    avax_price = await get_avax_price()
    if avax_price <= 0:
        return None

    avax_amount_wei = int((buy_amount_usd / avax_price) * 1e18)

    tx_hash = None
    buy_price = 0

    try:
        if settings.ORACLE_PRIVATE_KEY:
            tx_hash = swap_exact_avax_for_tokens(
                to_token=token_address,
                avax_amount_wei=avax_amount_wei,
                slippage_pct=DEFAULT_SLIPPAGE_PCT,
                private_key=settings.ORACLE_PRIVATE_KEY,
            )
            # Estimate buy price from liquidity
            liquidity = launch.get("liquidity_usd", 0)
            if liquidity > 0:
                buy_price = buy_amount_usd / (liquidity / 2)  # Rough estimate
        else:
            logger.info("snipe_simulated", token=symbol, amount_usd=buy_amount_usd)
    except Exception as e:
        logger.error("snipe_buy_failed", token=symbol, error=str(e))
        return None

    # Record trade
    async with async_session() as db:
        trade = SniperTrade(
            config_id=config.id,
            token_address=token_address,
            token_symbol=symbol,
            buy_price=buy_price,
            buy_amount_usd=buy_amount_usd,
            buy_tx_hash=tx_hash,
            status="open",
        )
        db.add(trade)

        # Update config stats
        await db.execute(
            update(SniperConfig)
            .where(SniperConfig.id == config.id)
            .values(total_trades=SniperConfig.total_trades + 1)
        )
        await db.commit()

    logger.info("snipe_executed", token=symbol, amount_usd=buy_amount_usd, tx=tx_hash)
    return {"token": symbol, "amount_usd": buy_amount_usd, "tx_hash": tx_hash}
