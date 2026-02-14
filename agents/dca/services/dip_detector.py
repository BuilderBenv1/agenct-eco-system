"""
DCA Dip Detector — Detects price dips for 2x buy mode.
"""
from sqlalchemy import select
from shared.database import async_session
from shared.price_feed import get_price_change_pct
from agents.dca.models.db import DCAConfig
from agents.dca.services.executor import _execute_single_dca
import structlog

logger = structlog.get_logger()


async def check_dip_buys():
    """Check if any DCA configs with buy_dips enabled should trigger a dip buy."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(DCAConfig).where(
                DCAConfig.is_active == True,
                DCAConfig.buy_dips == True,
            )
        )
        configs = result.scalars().all()

        for config in configs:
            try:
                pct_change = await get_price_change_pct(config.token_symbol, hours=1)
                if pct_change is None:
                    continue

                # Negative change = price drop
                if pct_change <= -(config.dip_threshold_pct or 10):
                    logger.info(
                        "dip_detected",
                        token=config.token_symbol,
                        change_pct=pct_change,
                        threshold=config.dip_threshold_pct,
                        config_id=config.id,
                    )
                    await _execute_single_dca(db, config, was_dip=True)
            except Exception as e:
                logger.error("dip_check_failed", config_id=config.id, error=str(e))

        await db.commit()
