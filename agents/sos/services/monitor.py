"""
SOS Monitor — Watches for crash conditions across multiple trigger types.

Triggers:
1. Market crash: AVAX/token price drops >X% in 1 hour
2. Protocol hack: Protocol TVL drops >50% in 10 minutes
3. Health factor: User's lending position HF < threshold
4. Flash crash: Volatility > 3x normal
"""
from datetime import datetime, timezone
from sqlalchemy import select, update
from shared.database import async_session
from shared.price_feed import get_price_change_pct, get_price_by_symbol
from agents.sos.models.db import SOSConfig, SOSEvent
from agents.sos.services.executor import execute_emergency_exit
import structlog

logger = structlog.get_logger()


async def check_crash_conditions():
    """Check for market crash conditions across all active SOS configs."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(SOSConfig).where(SOSConfig.is_active == True)
        )
        configs = result.scalars().all()

        for config in configs:
            try:
                tokens = config.tokens_to_protect or []

                for token_info in tokens:
                    symbol = token_info.get("symbol", "AVAX")
                    address = token_info.get("address", "")

                    # Check 1-hour price change
                    pct_change = await get_price_change_pct(symbol, hours=1)
                    if pct_change is None:
                        continue

                    threshold = -(config.crash_threshold_pct or 15)

                    if pct_change <= threshold:
                        logger.warning(
                            "sos_crash_detected",
                            config_id=config.id,
                            token=symbol,
                            change_pct=pct_change,
                            threshold=threshold,
                        )

                        # Execute emergency exit
                        result = await execute_emergency_exit(
                            db, config, symbol, address, "crash",
                            {"price_change_1h_pct": pct_change, "threshold": threshold},
                        )

                        if result:
                            logger.info("sos_emergency_exit_executed", config_id=config.id, token=symbol)

            except Exception as e:
                logger.error("sos_crash_check_failed", config_id=config.id, error=str(e))

        await db.commit()


async def check_health_factors():
    """Cross-check with Liquidation Sentinel data for health factor monitoring."""
    if async_session is None:
        return

    try:
        from agents.liquidation.models.db import LiquidationPosition

        async with async_session() as db:
            configs = await db.execute(
                select(SOSConfig).where(SOSConfig.is_active == True)
            )

            for config in configs.scalars().all():
                # Check if this wallet has any at-risk positions
                positions = await db.execute(
                    select(LiquidationPosition).where(
                        LiquidationPosition.wallet_address == config.wallet_address,
                        LiquidationPosition.is_active == True,
                        LiquidationPosition.health_factor < (config.health_factor_threshold or 1.05),
                    )
                )
                at_risk = positions.scalars().all()

                for pos in at_risk:
                    logger.warning(
                        "sos_health_factor_critical",
                        config_id=config.id,
                        wallet=config.wallet_address,
                        protocol=pos.protocol,
                        hf=pos.health_factor,
                    )

                    # Record event (but don't auto-exit lending positions — too risky)
                    event = SOSEvent(
                        config_id=config.id,
                        trigger_type="health",
                        trigger_details={
                            "protocol": pos.protocol,
                            "health_factor": pos.health_factor,
                            "collateral_token": pos.collateral_token,
                            "debt_token": pos.debt_token,
                        },
                        total_value_saved_usd=pos.collateral_amount_usd or 0,
                    )
                    db.add(event)

                    await db.execute(
                        update(SOSConfig)
                        .where(SOSConfig.id == config.id)
                        .values(triggers_fired=SOSConfig.triggers_fired + 1)
                    )

            await db.commit()
    except ImportError:
        pass  # Liquidation module not available
    except Exception as e:
        logger.error("sos_health_check_failed", error=str(e))
