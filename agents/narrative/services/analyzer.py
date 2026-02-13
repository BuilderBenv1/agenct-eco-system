"""
Sentiment Analyzer — Uses Claude to analyze sentiment of fetched content items.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.claude_client import ask_claude_json
from shared.lightning import get_lightning
from agents.narrative.models.db import NarrativeItem, NarrativeSentiment
from agents.narrative.config import AGENT_NAME
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)

PROMPT_PATH = Path(__file__).parent.parent / "templates" / "sentiment_prompt.txt"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    return _system_prompt


async def analyze_item(db: AsyncSession, item: NarrativeItem) -> NarrativeSentiment | None:
    """Analyze sentiment of a single content item."""
    content = item.title or ""
    if item.content:
        content += "\n\n" + item.content

    if len(content.strip()) < 30:
        return None

    lightning.emit_action("analyze_sentiment", {"item_id": item.id, "title": (item.title or "")[:100]})

    try:
        result = ask_claude_json(
            system_prompt=_get_system_prompt(),
            user_message=content[:4000],
            max_tokens=512,
        )
    except Exception as e:
        logger.error("sentiment_analysis_failed", error=str(e), item_id=item.id)
        lightning.log_failure(task="analyze_sentiment", error=str(e), context={"item_id": item.id})
        return None

    sentiment = NarrativeSentiment(
        item_id=item.id,
        overall_sentiment=result.get("overall_sentiment", "neutral"),
        sentiment_score=result.get("sentiment_score", 0.0),
        tokens_mentioned=result.get("tokens_mentioned", []),
        topics=result.get("topics", []),
        key_claims=result.get("key_claims", []),
        claude_reasoning=result.get("reasoning", ""),
        analyzed_at=datetime.now(timezone.utc),
    )
    db.add(sentiment)
    lightning.log_success("analyze_sentiment", output={"sentiment": sentiment.overall_sentiment, "score": sentiment.sentiment_score})

    logger.debug(
        "sentiment_analyzed",
        item_id=item.id,
        sentiment=sentiment.overall_sentiment,
        score=sentiment.sentiment_score,
    )
    return sentiment


async def analyze_pending_items():
    """Analyze all items that don't have sentiment yet."""
    if async_session is None:
        return

    async with async_session() as db:
        # Find items without sentiment analysis
        analyzed_ids = select(NarrativeSentiment.item_id)
        result = await db.execute(
            select(NarrativeItem)
            .where(NarrativeItem.id.notin_(analyzed_ids))
            .order_by(NarrativeItem.fetched_at.desc())
            .limit(30)
        )
        items = list(result.scalars().all())

        analyzed = 0
        for item in items:
            s = await analyze_item(db, item)
            if s:
                analyzed += 1

        if analyzed:
            await db.commit()
            logger.info("batch_sentiment_analysis_complete", analyzed=analyzed, total=len(items))
