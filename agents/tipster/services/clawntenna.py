"""
Clawntenna handler for Tipster agent — processes encrypted queries and returns verified signal data.

Query examples:
  "What's the accuracy of @CryptoKing last 30 days?"
  "Latest BUY signals with >70% confidence"
  "Show me AVAX signals this week"
"""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from shared.clawntenna import ClawntennMessage
from shared.lightning import get_lightning
from agents.tipster.models.db import TipsterSignal, TipsterChannel
from agents.tipster.services.analyzer import get_signal_performance
from agents.tipster.config import AGENT_NAME
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def handle_tipster_query(msg: ClawntennMessage) -> str | None:
    """
    Handle an incoming Clawntenna query for the Tipster agent.
    Returns formatted JSON response string.
    """
    query = msg.text.strip().lower()

    lightning.emit_action("clawntenna_query", {"query": query, "sender": msg.sender})

    try:
        if "latest" in query or "signal" in query or "recent" in query:
            result = await _get_latest_signals(query)
        elif "accuracy" in query or "performance" in query or "verify" in query:
            result = await _get_performance_data(query)
        elif "channel" in query or "source" in query:
            result = await _get_channel_stats()
        else:
            result = await _get_latest_signals(query)

        lightning.log_success("clawntenna_query", output=result)
        return json.dumps(result, default=str)

    except Exception as e:
        lightning.log_failure(
            task="clawntenna_query",
            error=str(e),
            context={"query": query, "sender": msg.sender},
        )
        return json.dumps({"error": "Query processing failed", "agent": "tipster"})


async def _get_latest_signals(query: str) -> dict:
    """Get latest signals, optionally filtered by token or type."""
    if async_session is None:
        return {"error": "Database not configured"}

    async with async_session() as db:
        q = select(TipsterSignal).where(TipsterSignal.is_valid == True)

        # Parse filters from query
        if "buy" in query:
            q = q.where(TipsterSignal.signal_type == "BUY")
        elif "sell" in query:
            q = q.where(TipsterSignal.signal_type == "SELL")

        # Token filter
        for token in ["avax", "joe", "gmx", "link", "btc", "eth"]:
            if token in query:
                q = q.where(TipsterSignal.token_symbol == token.upper())
                break

        q = q.order_by(TipsterSignal.created_at.desc()).limit(5)
        result = await db.execute(q)
        signals = list(result.scalars().all())

        return {
            "agent": "tipster",
            "query_type": "latest_signals",
            "count": len(signals),
            "signals": [
                {
                    "token": s.token_symbol,
                    "type": s.signal_type,
                    "confidence": s.confidence,
                    "entry_price": float(s.entry_price) if s.entry_price else None,
                    "targets": s.target_prices or [],
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in signals
            ],
            "verified_by": "AgentProof",
        }


async def _get_performance_data(query: str) -> dict:
    """Get aggregate performance metrics."""
    if async_session is None:
        return {"error": "Database not configured"}

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    async with async_session() as db:
        total = await db.execute(
            select(func.count()).select_from(TipsterSignal)
            .where(TipsterSignal.created_at >= week_ago, TipsterSignal.is_valid == True)
        )
        total_count = total.scalar() or 0

        signals = await db.execute(
            select(TipsterSignal)
            .where(TipsterSignal.created_at >= week_ago, TipsterSignal.is_valid == True)
        )
        all_signals = list(signals.scalars().all())

        profitable = 0
        for s in all_signals:
            perf = await get_signal_performance(db, s.id)
            if perf and perf["change_pct"] and perf["change_pct"] > 0:
                profitable += 1

        return {
            "agent": "tipster",
            "query_type": "performance",
            "period": "7d",
            "total_signals": total_count,
            "profitable_signals": profitable,
            "accuracy": f"{(profitable / total_count * 100):.1f}%" if total_count > 0 else "N/A",
            "verified_by": "AgentProof",
            "reputation_score": f"ERC-8004 #{1633}",
        }


async def _get_channel_stats() -> dict:
    """Get channel reliability stats."""
    if async_session is None:
        return {"error": "Database not configured"}

    async with async_session() as db:
        result = await db.execute(
            select(TipsterChannel)
            .where(TipsterChannel.is_active == True)
            .order_by(TipsterChannel.reliability_score.desc())
        )
        channels = list(result.scalars().all())

        return {
            "agent": "tipster",
            "query_type": "channels",
            "count": len(channels),
            "channels": [
                {
                    "name": c.channel_name,
                    "reliability": f"{c.reliability_score:.0%}",
                    "total_signals": c.total_signals,
                    "profitable": c.profitable_signals,
                }
                for c in channels[:10]
            ],
            "verified_by": "AgentProof",
        }
