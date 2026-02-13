"""
Trend Detector — Aggregates sentiment data to identify narrative trends.
Uses Claude to synthesize patterns across multiple sources.
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.claude_client import ask_claude_json
from agents.narrative.models.db import NarrativeSentiment, NarrativeTrend
from agents.narrative.config import TREND_MIN_MENTIONS
import structlog

logger = structlog.get_logger()

PROMPT_PATH = Path(__file__).parent.parent / "templates" / "narrative_prompt.txt"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    return _system_prompt


async def detect_trends():
    """Run trend detection on recent sentiment data."""
    if async_session is None:
        return

    async with async_session() as db:
        # Get recent sentiments (last 24h)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await db.execute(
            select(NarrativeSentiment)
            .where(NarrativeSentiment.analyzed_at >= cutoff)
            .order_by(NarrativeSentiment.analyzed_at.desc())
            .limit(100)
        )
        sentiments = list(result.scalars().all())

        if len(sentiments) < TREND_MIN_MENTIONS:
            logger.debug("not_enough_data_for_trends", count=len(sentiments))
            return

        # Prepare data for Claude
        sentiment_data = [
            {
                "sentiment": s.overall_sentiment,
                "score": s.sentiment_score,
                "tokens": s.tokens_mentioned,
                "topics": s.topics,
                "claims": s.key_claims,
            }
            for s in sentiments
        ]

        # Get existing active trends for context
        existing_q = await db.execute(
            select(NarrativeTrend).where(NarrativeTrend.is_active == True)
        )
        existing_trends = [
            {"name": t.narrative_name, "category": t.narrative_category, "strength": t.strength, "momentum": t.momentum}
            for t in existing_q.scalars().all()
        ]

        try:
            result_data = ask_claude_json(
                system_prompt=_get_system_prompt(),
                user_message=json.dumps({
                    "recent_sentiments": sentiment_data,
                    "existing_trends": existing_trends,
                }, default=str),
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("trend_detection_failed", error=str(e))
            return

        narratives = result_data.get("narratives", [])
        now = datetime.now(timezone.utc)

        # Mark all existing trends as potentially fading
        await db.execute(
            update(NarrativeTrend)
            .where(NarrativeTrend.is_active == True)
            .values(momentum="fading")
        )

        for n in narratives:
            name = n.get("name", "")
            if not name:
                continue

            # Check if trend already exists
            existing = await db.execute(
                select(NarrativeTrend).where(NarrativeTrend.narrative_name == name)
            )
            trend = existing.scalar_one_or_none()

            if trend:
                trend.strength = n.get("strength", trend.strength)
                trend.momentum = n.get("momentum", "growing")
                trend.last_seen = now
                trend.mention_count = trend.mention_count + 1
                trend.related_tokens = n.get("related_tokens", trend.related_tokens)
                trend.is_active = True
                trend.description = n.get("description", trend.description)
            else:
                trend = NarrativeTrend(
                    narrative_name=name,
                    narrative_category=n.get("category"),
                    description=n.get("description"),
                    strength=n.get("strength", 0.5),
                    momentum=n.get("momentum", "emerging"),
                    first_detected=now,
                    last_seen=now,
                    mention_count=1,
                    related_tokens=n.get("related_tokens", []),
                    is_active=True,
                )
                db.add(trend)

        await db.commit()
        logger.info("trends_updated", detected=len(narratives))
