"""
Grid Trading Engine — Core grid logic: place orders, check fills, execute cycles.

Grid Strategy:
  Given range $8-$11 with 10 levels (spacing = $0.30):
  - Buy levels:  $8.0, $8.3, $8.6, $8.9, $9.2  (lower half — buy AVAX with USDC)
  - Sell levels: $9.5, $9.8, $10.1, $10.4, $10.7, $11.0 (upper half — sell AVAX for USDC)
  - When price drops to buy level → buy AVAX with USDC
  - When price rises to sell level → sell AVAX for USDC
  - Each completed buy→sell = 1 cycle of profit
"""
from datetime import datetime, timezone
from sqlalchemy import select, update
from shared.database import async_session
from shared.price_feed import get_price_by_symbol
from shared.dex import (
    swap_exact_avax_for_tokens,
    swap_exact_tokens_for_avax,
    get_avax_balance,
    get_token_balance,
    get_token_decimals,
    USDC,
    WAVAX,
)
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
                    logger.warning("grid_no_price", config_id=config.id, symbol=config.token_symbol)
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
                    should_fill = False

                    if order.order_type == "buy" and current_price <= order.price:
                        should_fill = True
                        logger.info("grid_buy_triggered", config_id=config.id, level=order.level_index, price=order.price, current=current_price)

                    elif order.order_type == "sell" and current_price >= order.price:
                        should_fill = True
                        logger.info("grid_sell_triggered", config_id=config.id, level=order.level_index, price=order.price, current=current_price)

                    if should_fill:
                        tx_hash = await _execute_grid_trade(config, order, current_price)

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

                        # If sell filled, count a cycle and calculate profit
                        if order.order_type == "sell":
                            # Profit = difference between sell price and grid midpoint buy price
                            mid_price = (config.lower_price + config.upper_price) / 2
                            profit = order.amount_usd * (order.price - mid_price) / mid_price
                            await db.execute(
                                update(GridConfig)
                                .where(GridConfig.id == config.id)
                                .values(
                                    completed_cycles=GridConfig.completed_cycles + 1,
                                    total_profit_usd=GridConfig.total_profit_usd + max(profit, 0),
                                )
                            )

            except Exception as e:
                logger.error("grid_check_failed", config_id=config.id, error=str(e))

        await db.commit()


async def _execute_grid_trade(config: GridConfig, order: GridOrder, current_price: float) -> str | None:
    """Execute an on-chain swap for a grid order.

    SELL orders: Sell AVAX → USDC (swap_exact_avax_for_tokens to USDC)
    BUY orders:  Buy AVAX ← USDC (swap_exact_tokens_for_avax from USDC)
    """
    if not settings.ORACLE_PRIVATE_KEY:
        logger.warning("grid_no_private_key", order_id=order.id)
        return None

    try:
        from eth_account import Account
        wallet = Account.from_key(settings.ORACLE_PRIVATE_KEY)

        if order.order_type == "sell":
            # SELL AVAX for USDC
            # Calculate AVAX amount from USD value at current price
            avax_amount = order.amount_usd / current_price
            avax_amount_wei = int(avax_amount * 1e18)

            # Check AVAX balance
            avax_balance = get_avax_balance(wallet.address)
            # Keep 0.1 AVAX for gas
            min_gas_reserve = int(0.1 * 1e18)
            if avax_balance < avax_amount_wei + min_gas_reserve:
                logger.warning(
                    "grid_insufficient_avax",
                    order_id=order.id,
                    needed=avax_amount_wei,
                    balance=avax_balance,
                )
                return None

            tx_hash = swap_exact_avax_for_tokens(
                to_token=USDC,
                avax_amount_wei=avax_amount_wei,
                slippage_pct=DEFAULT_SLIPPAGE_PCT,
                private_key=settings.ORACLE_PRIVATE_KEY,
            )
            logger.info("grid_sell_executed", order_id=order.id, avax=avax_amount, tx=tx_hash)
            return tx_hash

        else:
            # BUY AVAX with USDC
            # USDC has 6 decimals
            usdc_decimals = 6
            usdc_amount = int(order.amount_usd * (10 ** usdc_decimals))

            # Check USDC balance
            usdc_balance = get_token_balance(USDC, wallet.address)
            if usdc_balance < usdc_amount:
                logger.warning(
                    "grid_insufficient_usdc",
                    order_id=order.id,
                    needed_usdc=usdc_amount,
                    balance_usdc=usdc_balance,
                )
                return None

            tx_hash = swap_exact_tokens_for_avax(
                from_token=USDC,
                amount_in=usdc_amount,
                slippage_pct=DEFAULT_SLIPPAGE_PCT,
                private_key=settings.ORACLE_PRIVATE_KEY,
            )
            logger.info("grid_buy_executed", order_id=order.id, usdc=order.amount_usd, tx=tx_hash)
            return tx_hash

    except Exception as e:
        logger.error("grid_trade_failed", order_id=order.id, error=str(e))
        return None
