"""
Grid Tracker — Track grid P&L per cycle and generate reports.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from agents.grid.models.db import GridConfig, GridOrder, GridReport
import hashlib
import structlog

logger = structlog.get_logger()


async def generate_daily_report() -> dict | None:
    """Generate daily grid trading report."""
    if async_session is None:
        return None

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    async with async_session() as db:
        active = await db.execute(
            select(func.count()).select_from(GridConfig).where(GridConfig.is_active == True)
        )
        active_count = active.scalar() or 0

        total_cycles = await db.execute(
            select(func.coalesce(func.sum(GridConfig.completed_cycles), 0))
        )
        cycles = total_cycles.scalar() or 0

        total_profit = await db.execute(
            select(func.coalesce(func.sum(GridConfig.total_profit_usd), 0))
        )
        profit = float(total_profit.scalar() or 0)

        fills_today = await db.execute(
            select(func.count()).select_from(GridOrder)
            .where(GridOrder.status == "filled", GridOrder.filled_at >= day_ago)
        )
        fills = fills_today.scalar() or 0

        profit_per_cycle = profit / cycles if cycles > 0 else 0

        proof_data = f"grid-daily-{now.date()}-grids:{active_count}-cycles:{cycles}-profit:{profit:.2f}"
        proof_hash = "0x" + hashlib.sha256(proof_data.encode()).hexdigest()

        report = GridReport(
            report_type="daily",
            period_start=day_ago,
            period_end=now,
            active_grids=active_count,
            cycles_completed=cycles,
            profit_per_cycle=profit_per_cycle,
            total_profit=profit,
            orders_filled=fills,
            report_text=f"Grid Daily: {active_count} grids, {cycles} cycles, "
                        f"${profit:.2f} total profit, {fills} fills today",
            proof_hash=proof_hash,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        total_capital = active_count * 100  # Rough estimate
        score = int(profit / total_capital * 100) if total_capital > 0 else 50
        return {"report_id": report.id, "score": max(0, score)}
