"""
DCA Executor — Executes scheduled DCA buys via Trader Joe DEX.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from shared.database import async_session
from shared.dex import swap_exact_avax_for_tokens, WAVAX, USDC
from shared.price_feed import get_price_by_symbol, get_avax_price
from shared.config import settings
from agents.dca.models.db import DCAConfig, DCAPurchase
from agents.dca.config import DEFAULT_SLIPPAGE_PCT
import structlog

logger = structlog.get_logger()

FREQUENCY_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "biweekly": timedelta(weeks=2),
    "monthly": timedelta(days=30),
}


async def execute_due_dcas():
    """Check for and execute all DCA configs that are due."""
    if async_session is None:
        return

    now = datetime.now(timezone.utc)

    async with async_session() as db:
        result = await db.execute(
            select(DCAConfig).where(
                DCAConfig.is_active == True,
                DCAConfig.next_execution_at <= now,
            )
        )
        configs = result.scalars().all()

        for config in configs:
            try:
                await _execute_single_dca(db, config, was_dip=False)
            except Exception as e:
                logger.error("dca_execution_failed", config_id=config.id, error=str(e))

        await db.commit()


async def _execute_single_dca(db, config: DCAConfig, was_dip: bool = False):
    """Execute a single DCA buy for a config."""
    amount_usd = config.amount_usd * (2.0 if was_dip else 1.0)

    # Get current AVAX price to convert USD -> AVAX
    avax_price = await get_avax_price()
    if avax_price <= 0:
        logger.warning("avax_price_unavailable", config_id=config.id)
        return

    avax_amount = amount_usd / avax_price
    avax_amount_wei = int(avax_amount * 1e18)

    # Get token price for records
    token_price = await get_price_by_symbol(config.token_symbol) or 0

    # Execute the swap
    tx_hash = None
    tokens_received = 0.0
    try:
        if settings.ORACLE_PRIVATE_KEY:
            tx_hash = swap_exact_avax_for_tokens(
                to_token=config.token_address,
                avax_amount_wei=avax_amount_wei,
                slippage_pct=DEFAULT_SLIPPAGE_PCT,
                private_key=settings.ORACLE_PRIVATE_KEY,
            )
            # Estimate tokens received
            if token_price > 0:
                tokens_received = amount_usd / token_price
        else:
            # Simulation mode — log but don't transact
            logger.info("dca_simulated", config_id=config.id, amount_usd=amount_usd)
            if token_price > 0:
                tokens_received = amount_usd / token_price
    except Exception as e:
        logger.error("dca_swap_failed", config_id=config.id, error=str(e))
        return

    # Record the purchase
    purchase = DCAPurchase(
        config_id=config.id,
        amount_usd=amount_usd,
        tokens_received=tokens_received,
        price_at_buy=token_price,
        tx_hash=tx_hash,
        was_dip_buy=was_dip,
    )
    db.add(purchase)

    # Update config tracking
    new_total_invested = (config.total_invested_usd or 0) + amount_usd
    new_total_tokens = (config.total_tokens_bought or 0) + tokens_received
    new_avg_cost = new_total_invested / new_total_tokens if new_total_tokens > 0 else 0

    next_exec = datetime.now(timezone.utc) + FREQUENCY_DELTAS.get(config.frequency, timedelta(days=1))

    await db.execute(
        update(DCAConfig)
        .where(DCAConfig.id == config.id)
        .values(
            total_invested_usd=new_total_invested,
            total_tokens_bought=new_total_tokens,
            avg_cost_basis=new_avg_cost,
            next_execution_at=next_exec,
        )
    )

    logger.info(
        "dca_executed",
        config_id=config.id,
        token=config.token_symbol,
        amount_usd=amount_usd,
        tokens_received=tokens_received,
        price=token_price,
        was_dip=was_dip,
        tx_hash=tx_hash,
    )


async def execute_manual(config_id: int) -> dict:
    """Manually trigger a DCA execution."""
    if async_session is None:
        return {"error": "no db"}

    async with async_session() as db:
        result = await db.execute(
            select(DCAConfig).where(DCAConfig.id == config_id, DCAConfig.is_active == True)
        )
        config = result.scalar_one_or_none()
        if not config:
            return {"error": "config not found or inactive"}

        await _execute_single_dca(db, config, was_dip=False)
        await db.commit()
        return {"status": "executed", "config_id": config_id}
