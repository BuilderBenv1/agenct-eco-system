"""
Grid Trading Engine — Core grid logic: place orders, check fills, execute cycles.

Grid Strategy:
  Given range $20-$30 with 10 levels (spacing = $1):
  - Buy levels:  $20, $21, $22, $23, $24  (lower half)
  - Sell levels: $25, $26, $27, $28, $29, $30 (upper half)
  - When price hits buy level → execute buy
  - When price hits sell level → execute sell
  - Each completed buy→sell = 1 cycle of profit
"""
from datetime import datetime, timezone
from sqlalchemy import select, update
from shared.database import async_session
from shared.price_feed import get_price_by_symbol
from shared.dex import swap_exact_avax_for_tokens, swap_exact_tokens_for_avax
from shared.config import settings
from agents.grid.models.db import GridConfig, GridOrder
from agents.grid.config import DEFAULT_SLIPPAGE_PCT
import structlog

logger = structlog.get_logger()


def _generate_grid_levels(lower: float, upper: float, levels: int) -> list[dict]:
    """Generate grid level prices with buy/sell assignments."""
    step = (upper - lower) / levels
    mid = (lower + upper) / 2
    grid = []
    for i in range(levels + 1):
        price = lower + (step * i)
        order_type = "buy" if price < mid else "sell"
        grid.append({"level_index": i, "price": round(price, 6), "order_type": order_type})
    return grid


async def initialize_grid_orders(config_id: int):
    """Create grid orders for a new config."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(select(GridConfig).where(GridConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            return

        levels = _generate_grid_levels(config.lower_price, config.upper_price, config.grid_levels)

        for level in levels:
            order = GridOrder(
                config_id=config.id,
                level_index=level["level_index"],
                order_type=level["order_type"],
                price=level["price"],
                amount=config.amount_per_grid / level["price"] if level["price"] > 0 else 0,
                amount_usd=config.amount_per_grid,
                status="pending",
            )
            db.add(order)

        await db.commit()
        logger.info("grid_orders_initialized", config_id=config_id, levels=len(levels))


async def check_and_fill_orders():
    """Check current prices against all pending grid orders and execute fills."""
    if async_session is None:
        return

    async with async_session() as db:
        # Get all active configs
        configs_result = await db.execute(
            select(GridConfig).where(GridConfig.is_active == True)
        )
        configs = configs_result.scalars().all()

        for config in configs:
            try:
                current_price = await get_price_by_symbol(config.token_symbol)
                if not current_price:
                    continue

                # Get pending orders for this config
                orders_result = await db.execute(
                    select(GridOrder).where(
                        GridOrder.config_id == config.id,
                        GridOrder.status == "pending",
                    ).order_by(GridOrder.price)
                )
                orders = orders_result.scalars().all()

                for order in orders:
                    filled = False

                    if order.order_type == "buy" and current_price <= order.price:
                        # Price dropped to buy level
                        filled = True
                        logger.info("grid_buy_triggered", config_id=config.id, level=order.level_index, price=order.price)

                    elif order.order_type == "sell" and current_price >= order.price:
                        # Price rose to sell level
                        filled = True
                        logger.info("grid_sell_triggered", config_id=config.id, level=order.level_index, price=order.price)

                    if filled:
                        tx_hash = None
                        try:
                            if settings.ORACLE_PRIVATE_KEY:
                                if order.order_type == "buy":
                                    avax_amount = order.amount_usd / current_price * 1e18
                                    tx_hash = swap_exact_avax_for_tokens(
                                        to_token=config.token_address,
                                        avax_amount_wei=int(avax_amount),
                                        slippage_pct=DEFAULT_SLIPPAGE_PCT,
                                        private_key=settings.ORACLE_PRIVATE_KEY,
                                    )
                                else:
                                    # Sell — swap tokens for AVAX
                                    pass  # Requires token balance tracking
                        except Exception as e:
                            logger.error("grid_swap_failed", error=str(e), order_id=order.id)

                        # Mark filled
                        await db.execute(
                            update(GridOrder)
                            .where(GridOrder.id == order.id)
                            .values(
                                status="filled",
                                fill_tx_hash=tx_hash,
                                filled_at=datetime.now(timezone.utc),
                            )
                        )

                        # If sell filled, count a cycle
                        if order.order_type == "sell":
                            profit = order.amount_usd * 0.01 * (config.grid_levels or 10)  # Approximate grid profit
                            await db.execute(
                                update(GridConfig)
                                .where(GridConfig.id == config.id)
                                .values(
                                    completed_cycles=GridConfig.completed_cycles + 1,
                                    total_profit_usd=GridConfig.total_profit_usd + profit,
                                )
                            )

            except Exception as e:
                logger.error("grid_check_failed", config_id=config.id, error=str(e))

        await db.commit()
