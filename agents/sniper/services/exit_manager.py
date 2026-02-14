"""
Sniper Exit Manager — Manages take-profit and stop-loss exits for open sniper trades.
"""
from datetime import datetime, timezone
from sqlalchemy import select, update
from shared.database import async_session
from shared.price_feed import get_price_by_address
from shared.dex import swap_exact_tokens_for_avax, get_token_balance
from shared.config import settings
from agents.sniper.models.db import SniperTrade, SniperConfig
import structlog

logger = structlog.get_logger()


async def check_exits():
    """Check all open trades for take-profit or stop-loss conditions."""
    if async_session is None:
        return

    async with async_session() as db:
        trades_result = await db.execute(
            select(SniperTrade).where(SniperTrade.status == "open")
        )
        trades = trades_result.scalars().all()

        for trade in trades:
            try:
                current_price = await get_price_by_address(trade.token_address)
                if not current_price or not trade.buy_price or trade.buy_price == 0:
                    continue

                pnl_pct = ((current_price - trade.buy_price) / trade.buy_price) * 100

                # Get config for TP/SL settings
                config_result = await db.execute(
                    select(SniperConfig).where(SniperConfig.id == trade.config_id)
                )
                config = config_result.scalar_one_or_none()
                if not config:
                    continue

                should_sell = False
                exit_reason = ""

                # Take profit: current price >= buy * multiplier
                tp_price = trade.buy_price * (config.take_profit_multiplier or 2.0)
                if current_price >= tp_price:
                    should_sell = True
                    exit_reason = "take_profit"

                # Stop loss: price dropped > stop_loss_pct
                if pnl_pct <= -(config.stop_loss_pct or 50):
                    should_sell = True
                    exit_reason = "stop_loss"

                if should_sell:
                    tx_hash = None
                    sell_amount_usd = 0

                    try:
                        if settings.ORACLE_PRIVATE_KEY:
                            from eth_account import Account
                            account = Account.from_key(settings.ORACLE_PRIVATE_KEY)
                            balance = get_token_balance(trade.token_address, account.address)
                            if balance > 0:
                                tx_hash = swap_exact_tokens_for_avax(
                                    from_token=trade.token_address,
                                    amount_in=balance,
                                    slippage_pct=3.0,
                                    private_key=settings.ORACLE_PRIVATE_KEY,
                                )
                                from shared.dex import get_token_decimals
                                decimals = get_token_decimals(trade.token_address)
                                sell_amount_usd = (balance / (10 ** decimals)) * current_price
                    except Exception as e:
                        logger.error("sniper_exit_swap_failed", trade_id=trade.id, error=str(e))

                    pnl_usd = (sell_amount_usd or 0) - (trade.buy_amount_usd or 0)
                    status = "closed" if exit_reason == "take_profit" else "stopped_out"

                    await db.execute(
                        update(SniperTrade)
                        .where(SniperTrade.id == trade.id)
                        .values(
                            sell_price=current_price,
                            sell_amount_usd=sell_amount_usd,
                            sell_tx_hash=tx_hash,
                            sold_at=datetime.now(timezone.utc),
                            pnl_usd=pnl_usd,
                            pnl_pct=pnl_pct,
                            status=status,
                        )
                    )

                    # Update config stats
                    if pnl_usd > 0:
                        await db.execute(
                            update(SniperConfig)
                            .where(SniperConfig.id == config.id)
                            .values(
                                profitable_trades=SniperConfig.profitable_trades + 1,
                                total_pnl_usd=SniperConfig.total_pnl_usd + pnl_usd,
                            )
                        )
                    else:
                        await db.execute(
                            update(SniperConfig)
                            .where(SniperConfig.id == config.id)
                            .values(total_pnl_usd=SniperConfig.total_pnl_usd + pnl_usd)
                        )

                    logger.info(
                        "sniper_exit",
                        trade_id=trade.id,
                        token=trade.token_symbol,
                        reason=exit_reason,
                        pnl_pct=pnl_pct,
                        pnl_usd=pnl_usd,
                    )

            except Exception as e:
                logger.error("sniper_exit_check_failed", trade_id=trade.id, error=str(e))

        await db.commit()
