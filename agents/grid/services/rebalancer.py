"""
Grid Rebalancer — Adjusts grid when price exits the range.
"""
from sqlalchemy import select, update
from shared.database import async_session
from shared.price_feed import get_price_by_symbol
from agents.grid.models.db import GridConfig, GridOrder
from agents.grid.services.engine import initialize_grid_orders
import structlog

logger = structlog.get_logger()


async def rebalance_grids():
    """Check if price has exited any grid's range and offer rebalancing."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(GridConfig).where(GridConfig.is_active == True)
        )
        configs = result.scalars().all()

        for config in configs:
            try:
                price = await get_price_by_symbol(config.token_symbol)
                if not price:
                    continue

                # Check if price is outside grid range
                if price < config.lower_price * 0.95 or price > config.upper_price * 1.05:
                    logger.warning(
                        "grid_out_of_range",
                        config_id=config.id,
                        token=config.token_symbol,
                        price=price,
                        range=f"${config.lower_price}-${config.upper_price}",
                    )
                    # Cancel all pending orders
                    await db.execute(
                        update(GridOrder)
                        .where(GridOrder.config_id == config.id, GridOrder.status == "pending")
                        .values(status="cancelled")
                    )

                    # Rebalance: shift grid to center on current price
                    grid_width = config.upper_price - config.lower_price
                    new_lower = price - (grid_width / 2)
                    new_upper = price + (grid_width / 2)

                    await db.execute(
                        update(GridConfig)
                        .where(GridConfig.id == config.id)
                        .values(lower_price=new_lower, upper_price=new_upper)
                    )
                    await db.commit()

                    # Re-create orders
                    await initialize_grid_orders(config.id)
                    logger.info("grid_rebalanced", config_id=config.id, new_range=f"${new_lower:.2f}-${new_upper:.2f}")

            except Exception as e:
                logger.error("rebalance_failed", config_id=config.id, error=str(e))

        await db.commit()
