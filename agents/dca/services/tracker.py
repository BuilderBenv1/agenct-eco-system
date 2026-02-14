"""
DCA Tracker — Track P&L, avg cost basis, and generate reports.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from shared.price_feed import get_price_by_symbol
from agents.dca.models.db import DCAConfig, DCAPurchase, DCAReport
import structlog

logger = structlog.get_logger()


async def get_dca_stats() -> dict:
    """Get aggregated DCA stats."""
    if async_session is None:
        return {}

    async with async_session() as db:
        total = await db.execute(select(func.count()).select_from(DCAConfig))
        active = await db.execute(
            select(func.count()).select_from(DCAConfig).where(DCAConfig.is_active == True)
        )
        total_invested = await db.execute(
            select(func.coalesce(func.sum(DCAConfig.total_invested_usd), 0))
        )
        total_purchases = await db.execute(select(func.count()).select_from(DCAPurchase))
        dip_buys = await db.execute(
            select(func.count()).select_from(DCAPurchase).where(DCAPurchase.was_dip_buy == True)
        )

        return {
            "total_configs": total.scalar() or 0,
            "active_configs": active.scalar() or 0,
            "total_invested_usd": float(total_invested.scalar() or 0),
            "total_purchases": total_purchases.scalar() or 0,
            "dip_buys": dip_buys.scalar() or 0,
        }


async def generate_daily_report() -> dict | None:
    """Generate daily DCA performance report."""
    if async_session is None:
        return None

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    async with async_session() as db:
        # Active configs
        configs_result = await db.execute(
            select(DCAConfig).where(DCAConfig.is_active == True)
        )
        configs = configs_result.scalars().all()

        # Purchases today
        purchases_result = await db.execute(
            select(func.count()).select_from(DCAPurchase)
            .where(DCAPurchase.executed_at >= day_ago)
        )
        purchases_today = purchases_result.scalar() or 0

        dip_buys_result = await db.execute(
            select(func.count()).select_from(DCAPurchase)
            .where(DCAPurchase.executed_at >= day_ago, DCAPurchase.was_dip_buy == True)
        )
        dip_buys_today = dip_buys_result.scalar() or 0

        # Calculate total P&L across configs
        total_invested = sum(c.total_invested_usd or 0 for c in configs)
        total_current_value = 0
        for config in configs:
            price = await get_price_by_symbol(config.token_symbol)
            if price and config.total_tokens_bought:
                total_current_value += price * config.total_tokens_bought

        pnl_pct = ((total_current_value - total_invested) / total_invested * 100) if total_invested > 0 else 0

        import hashlib
        proof_data = f"dca-daily-{now.date()}-invested:{total_invested:.2f}-value:{total_current_value:.2f}-pnl:{pnl_pct:.2f}"
        proof_hash = "0x" + hashlib.sha256(proof_data.encode()).hexdigest()

        report = DCAReport(
            report_type="daily",
            period_start=day_ago,
            period_end=now,
            total_configs=len(configs),
            total_invested=total_invested,
            current_value=total_current_value,
            pnl_pct=pnl_pct,
            purchases_made=purchases_today,
            dip_buys_made=dip_buys_today,
            report_text=f"DCA Daily: {len(configs)} configs, ${total_invested:.0f} invested, "
                        f"${total_current_value:.0f} value, {pnl_pct:.1f}% P&L, "
                        f"{purchases_today} buys ({dip_buys_today} dip buys)",
            proof_hash=proof_hash,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        logger.info("dca_daily_report", report_id=report.id, pnl_pct=pnl_pct)
        return {"report_id": report.id, "score": max(0, int(pnl_pct))}
