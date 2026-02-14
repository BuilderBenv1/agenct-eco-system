"""
SOS Executor — Emergency exit logic. Sells tokens to stable on crash detection.
"""
from datetime import datetime, timezone
from sqlalchemy import update
from shared.dex import (
    swap_exact_tokens_for_avax, swap_exact_tokens, swap_exact_avax_for_tokens,
    USDC, WAVAX, get_token_balance, get_avax_balance, get_token_decimals,
)
from shared.price_feed import get_price_by_symbol
from shared.config import settings
from agents.sos.models.db import SOSConfig, SOSEvent
from agents.sos.config import DEFAULT_SLIPPAGE_PCT
import structlog

logger = structlog.get_logger()


async def execute_emergency_exit(
    db, config: SOSConfig, token_symbol: str, token_address: str,
    trigger_type: str, trigger_details: dict,
) -> dict | None:
    """Execute an emergency exit — sell token to USDC."""
    tx_hashes = []
    value_saved = 0.0

    try:
        # Get current price to estimate value
        price = await get_price_by_symbol(token_symbol)

        if settings.ORACLE_PRIVATE_KEY and token_address:
            from eth_account import Account
            account = Account.from_key(settings.ORACLE_PRIVATE_KEY)

            is_avax = token_address.lower() == WAVAX.lower()

            if is_avax:
                # Native AVAX — use get_avax_balance, not ERC20 balance
                balance_wei = get_avax_balance(account.address)
                # Keep 0.2 AVAX for gas
                gas_reserve = int(0.2 * 1e18)
                sellable = balance_wei - gas_reserve

                if sellable > 0 and price:
                    value_saved = (sellable / 1e18) * price
                    try:
                        tx_hash = swap_exact_avax_for_tokens(
                            to_token=USDC,
                            avax_amount_wei=sellable,
                            slippage_pct=DEFAULT_SLIPPAGE_PCT,
                            private_key=settings.ORACLE_PRIVATE_KEY,
                        )
                        tx_hashes.append(tx_hash)
                        logger.info("sos_exit_avax_executed", value_usd=value_saved, tx=tx_hash)
                    except Exception as e:
                        logger.error("sos_avax_swap_failed", error=str(e))
            else:
                # ERC20 token
                balance = get_token_balance(token_address, account.address)

                if balance > 0 and price:
                    decimals = get_token_decimals(token_address)
                    token_amount = balance / (10 ** decimals)
                    value_saved = token_amount * price

                    try:
                        tx_hash = swap_exact_tokens(
                            from_token=token_address,
                            to_token=USDC,
                            amount_in=balance,
                            slippage_pct=DEFAULT_SLIPPAGE_PCT,
                            private_key=settings.ORACLE_PRIVATE_KEY,
                        )
                        tx_hashes.append(tx_hash)
                        logger.info("sos_exit_executed", token=token_symbol, value_usd=value_saved, tx=tx_hash)
                    except Exception as e:
                        logger.error("sos_swap_failed", token=token_symbol, error=str(e))
        else:
            # Simulation mode
            logger.info("sos_exit_simulated", token=token_symbol, trigger=trigger_type)
            value_saved = 100.0  # Placeholder

    except Exception as e:
        logger.error("sos_executor_error", error=str(e))

    # Record event
    event = SOSEvent(
        config_id=config.id,
        trigger_type=trigger_type,
        trigger_details=trigger_details,
        tokens_exited=[{"symbol": token_symbol, "address": token_address}],
        total_value_saved_usd=value_saved,
        exit_tx_hashes=tx_hashes,
    )
    db.add(event)

    # Update config
    await db.execute(
        update(SOSConfig)
        .where(SOSConfig.id == config.id)
        .values(
            triggers_fired=SOSConfig.triggers_fired + 1,
            total_value_saved_usd=SOSConfig.total_value_saved_usd + value_saved,
        )
    )

    return {"value_saved": value_saved, "tx_hashes": tx_hashes, "trigger": trigger_type}
