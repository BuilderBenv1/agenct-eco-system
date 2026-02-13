"""
Clawntenna handler for Narrative agent — processes encrypted queries about market narratives.

Query examples:
  "What narratives are trending right now?"
  "Sentiment on AVAX ecosystem?"
  "What's emerging this week?"
  "Is AI agents narrative still growing?"
"""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from shared.clawntenna import ClawntennMessage
from shared.lightning import get_lightning
from agents.narrative.models.db import NarrativeTrend, NarrativeSentiment, NarrativeSource
from agents.narrative.config import AGENT_NAME
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def handle_narrative_query(msg: ClawntennMessage) -> str | None:
    """Handle an incoming Clawntenna query for the Narrative agent."""
    query = msg.text.strip().lower()

    lightning.emit_action("clawntenna_query", {"query": query, "sender": msg.sender})

    try:
        if "trending" in query or "top" in query or "hot" in query:
            result = await _get_trending_narratives()
        elif "emerging" in query or "new" in query:
            result = await _get_emerging_narratives()
        elif "sentiment" in query:
            result = await _get_market_sentiment(query)
        elif "fading" in query or "dying" in query:
            result = await _get_fading_narratives()
        else:
            result = await _get_trending_narratives()

        lightning.log_success("clawntenna_query", output=result)
        return json.dumps(result, default=str)

    except Exception as e:
        lightning.log_failure(
            task="clawntenna_query",
            error=str(e),
            context={"query": query, "sender": msg.sender},
        )
        return json.dumps({"error": "Query processing failed", "agent": "narrative"})


async def _get_trending_narratives() -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    async with async_session() as db:
        result = await db.execute(
            select(NarrativeTrend)
            .where(NarrativeTrend.is_active == True)
            .order_by(NarrativeTrend.strength.desc())
            .limit(8)
        )
        trends = list(result.scalars().all())

        return {
            "agent": "narrative",
            "query_type": "trending",
            "count": len(trends),
            "trending": [
                {
                    "name": t.narrative_name,
                    "category": t.narrative_category,
                    "strength": t.strength,
                    "momentum": t.momentum,
                    "tokens": t.related_tokens or [],
                    "mentions": t.mention_count,
                }
                for t in trends
            ],
            "sources_monitored": await _count_sources(),
            "verified_by": "AgentProof",
        }


async def _get_emerging_narratives() -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    async with async_session() as db:
        result = await db.execute(
            select(NarrativeTrend)
            .where(
                NarrativeTrend.is_active == True,
                NarrativeTrend.momentum.in_(["emerging", "growing"]),
            )
            .order_by(NarrativeTrend.strength.desc())
            .limit(5)
        )
        trends = list(result.scalars().all())

        return {
            "agent": "narrative",
            "query_type": "emerging",
            "count": len(trends),
            "emerging": [
                {
                    "name": t.narrative_name,
                    "category": t.narrative_category,
                    "strength": t.strength,
                    "momentum": t.momentum,
                    "tokens": t.related_tokens or [],
                    "first_detected": t.first_detected.isoformat() if t.first_detected else None,
                }
                for t in trends
            ],
            "verified_by": "AgentProof",
        }


async def _get_fading_narratives() -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    async with async_session() as db:
        result = await db.execute(
            select(NarrativeTrend)
            .where(
                NarrativeTrend.is_active == True,
                NarrativeTrend.momentum == "fading",
            )
            .order_by(NarrativeTrend.strength.asc())
            .limit(5)
        )
        trends = list(result.scalars().all())

        return {
            "agent": "narrative",
            "query_type": "fading",
            "count": len(trends),
            "fading": [
                {
                    "name": t.narrative_name,
                    "strength": t.strength,
                    "tokens": t.related_tokens or [],
                }
                for t in trends
            ],
            "verified_by": "AgentProof",
        }


async def _get_market_sentiment(query: str) -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    async with async_session() as db:
        result = await db.execute(
            select(NarrativeSentiment)
            .where(NarrativeSentiment.analyzed_at >= day_ago)
        )
        sentiments = list(result.scalars().all())

        if not sentiments:
            return {"agent": "narrative", "query_type": "sentiment", "message": "No recent data"}

        avg_score = sum(s.sentiment_score or 0 for s in sentiments) / len(sentiments)

        # Token-specific if mentioned
        token_scores: dict[str, list] = {}
        for s in sentiments:
            for tok in (s.tokens_mentioned or []):
                token_scores.setdefault(tok, []).append(s.sentiment_score or 0)

        token_sentiment = {
            tok: sum(scores) / len(scores)
            for tok, scores in token_scores.items()
        }

        # Sort by mention count
        top_tokens = sorted(token_sentiment.items(), key=lambda x: len(token_scores[x[0]]), reverse=True)[:10]

        label = _score_to_label(avg_score)

        return {
            "agent": "narrative",
            "query_type": "sentiment",
            "period": "24h",
            "overall_sentiment": label,
            "overall_score": round(avg_score, 3),
            "items_analyzed": len(sentiments),
            "token_sentiment": {tok: round(score, 3) for tok, score in top_tokens},
            "verified_by": "AgentProof",
        }


def _score_to_label(score: float) -> str:
    if score > 0.6: return "very_bullish"
    if score > 0.2: return "bullish"
    if score > -0.2: return "neutral"
    if score > -0.6: return "bearish"
    return "very_bearish"


async def _count_sources() -> int:
    if async_session is None:
        return 0
    async with async_session() as db:
        result = await db.execute(
            select(func.count()).select_from(NarrativeSource).where(NarrativeSource.is_active == True)
        )
        return result.scalar() or 0
