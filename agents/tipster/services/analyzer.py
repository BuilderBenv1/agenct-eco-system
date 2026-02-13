"""
Signal Analyzer — Aggregates signal performance data for reporting.
Calculates win rates, returns, and channel reliability scores.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, update, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from agents.tipster.models.db import (
    TipsterSignal, TipsterPriceCheck, TipsterChannel
)
import structlog

logger = structlog.get_logger()


async def get_signal_performance(db: AsyncSession, signal_id: int) -> dict | None:
    """Get the latest price performance for a specific signal."""
    result = await db.execute(
        select(TipsterPriceCheck)
        .where(TipsterPriceCheck.signal_id == signal_id)
        .order_by(TipsterPriceCheck.checked_at.desc())
        .limit(1)
    )
    check = result.scalar_one_or_none()
    if not check:
        return None
    return {
        "signal_id": signal_id,
        "current_price": float(check.current_price) if check.current_price else None,
        "price_at_signal": float(check.price_at_signal) if check.price_at_signal else None,
        "change_pct": check.price_change_pct,
        "last_checked": check.checked_at.isoformat(),
    }


async def get_weekly_stats(
    db: AsyncSession,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> dict:
    """Calculate weekly aggregated statistics for reporting."""
    if period_end is None:
        period_end = datetime.now(timezone.utc)
    if period_start is None:
        period_start = period_end - timedelta(days=7)

    # Get all signals in period
    signals_q = await db.execute(
        select(TipsterSignal)
        .where(
            TipsterSignal.created_at >= period_start,
            TipsterSignal.created_at <= period_end,
            TipsterSignal.is_valid == True,
        )
        .order_by(TipsterSignal.created_at)
    )
    signals = list(signals_q.scalars().all())

    performances = []
    best = {"signal_id": None, "change_pct": float("-inf")}
    worst = {"signal_id": None, "change_pct": float("inf")}

    for sig in signals:
        perf = await get_signal_performance(db, sig.id)
        if perf and perf["change_pct"] is not None:
            performances.append(perf)
            if perf["change_pct"] > best["change_pct"]:
                best = perf
            if perf["change_pct"] < worst["change_pct"]:
                worst = perf

    profitable = [p for p in performances if p["change_pct"] and p["change_pct"] > 0]
    avg_return = (
        sum(p["change_pct"] for p in performances) / len(performances)
        if performances else 0.0
    )

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_signals": len(signals),
        "tracked_signals": len(performances),
        "profitable_signals": len(profitable),
        "win_rate": len(profitable) / len(performances) if performances else 0.0,
        "avg_return_pct": avg_return,
        "best_signal": best if best["signal_id"] else None,
        "worst_signal": worst if worst["signal_id"] else None,
        "signals": [
            {
                "id": s.id,
                "token": s.token_symbol,
                "type": s.signal_type,
                "confidence": s.confidence,
                "entry_price": float(s.entry_price) if s.entry_price else None,
                "channel_id": s.channel_id,
            }
            for s in signals
        ],
    }


async def update_channel_reliability():
    """Recalculate reliability scores for all channels based on signal outcomes."""
    if async_session is None:
        return

    async with async_session() as db:
        channels_q = await db.execute(select(TipsterChannel).where(TipsterChannel.is_active == True))
        channels = list(channels_q.scalars().all())

        for ch in channels:
            # Count profitable signals (latest price check > entry price for BUY)
            signals_q = await db.execute(
                select(TipsterSignal)
                .where(TipsterSignal.channel_id == ch.channel_id, TipsterSignal.is_valid == True)
            )
            signals = list(signals_q.scalars().all())
            total = len(signals)
            profitable = 0

            for sig in signals:
                perf = await get_signal_performance(db, sig.id)
                if perf and perf["change_pct"] is not None:
                    is_profitable = (
                        (sig.signal_type == "BUY" and perf["change_pct"] > 0) or
                        (sig.signal_type == "SELL" and perf["change_pct"] < 0) or
                        (sig.signal_type == "AVOID")
                    )
                    if is_profitable:
                        profitable += 1

            reliability = profitable / total if total > 0 else 0.5
            await db.execute(
                update(TipsterChannel)
                .where(TipsterChannel.channel_id == ch.channel_id)
                .values(
                    total_signals=total,
                    profitable_signals=profitable,
                    reliability_score=reliability,
                )
            )
        await db.commit()
        logger.info("channel_reliability_updated", channels=len(channels))
