"""
Sniper Tracker — Track P&L and win rate, generate reports.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from agents.sniper.models.db import SniperConfig, SniperTrade, SniperLaunch, SniperReport
import hashlib
import structlog

logger = structlog.get_logger()


async def generate_daily_report() -> dict | None:
    if async_session is None:
        return None

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    async with async_session() as db:
        launches = await db.execute(
            select(func.count()).select_from(SniperLaunch)
            .where(SniperLaunch.detected_at >= day_ago)
        )
        launches_today = launches.scalar() or 0

        trades = await db.execute(
            select(func.count()).select_from(SniperTrade)
            .where(SniperTrade.bought_at >= day_ago)
        )
        trades_today = trades.scalar() or 0

        profitable = await db.execute(
            select(func.count()).select_from(SniperTrade)
            .where(SniperTrade.pnl_usd > 0, SniperTrade.status != "open")
        )
        total_closed = await db.execute(
            select(func.count()).select_from(SniperTrade)
            .where(SniperTrade.status != "open")
        )
        prof = profitable.scalar() or 0
        closed = total_closed.scalar() or 0
        win_rate = (prof / closed * 100) if closed > 0 else 0

        total_pnl = await db.execute(
            select(func.coalesce(func.sum(SniperTrade.pnl_usd), 0))
            .where(SniperTrade.status != "open")
        )
        pnl = float(total_pnl.scalar() or 0)

        proof_data = f"sniper-daily-{now.date()}-launches:{launches_today}-trades:{trades_today}-winrate:{win_rate:.1f}"
        proof_hash = "0x" + hashlib.sha256(proof_data.encode()).hexdigest()

        report = SniperReport(
            report_type="daily",
            period_start=day_ago,
            period_end=now,
            launches_detected=launches_today,
            trades_executed=trades_today,
            profitable_trades=prof,
            win_rate=win_rate,
            total_pnl_usd=pnl,
            report_text=f"Sniper Daily: {launches_today} launches, {trades_today} trades, "
                        f"{win_rate:.1f}% win rate, ${pnl:.2f} P&L",
            proof_hash=proof_hash,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        return {"report_id": report.id, "score": max(0, int(win_rate))}
