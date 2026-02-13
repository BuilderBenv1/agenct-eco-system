"""
Narrative Reporter — Generates daily narrative intelligence reports.
"""
import json
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.claude_client import ask_claude
from shared.telegram_bot import send_alert
from agents.narrative.models.db import (
    NarrativeTrend, NarrativeSentiment, NarrativeReport
)
import structlog

logger = structlog.get_logger()


async def get_daily_narrative_stats(
    db: AsyncSession,
    period_start: datetime,
    period_end: datetime,
) -> dict:
    """Aggregate narrative data for the reporting period."""
    # Active trends
    trends_q = await db.execute(
        select(NarrativeTrend)
        .where(NarrativeTrend.is_active == True)
        .order_by(NarrativeTrend.strength.desc())
    )
    trends = list(trends_q.scalars().all())

    # Recent sentiments
    sentiments_q = await db.execute(
        select(NarrativeSentiment)
        .where(NarrativeSentiment.analyzed_at >= period_start)
    )
    sentiments = list(sentiments_q.scalars().all())

    avg_sentiment = (
        sum(s.sentiment_score or 0 for s in sentiments) / len(sentiments)
        if sentiments else 0.0
    )

    # Categorize trends
    emerging = [t for t in trends if t.momentum == "emerging"]
    growing = [t for t in trends if t.momentum == "growing"]
    peaking = [t for t in trends if t.momentum == "peaking"]
    fading = [t for t in trends if t.momentum == "fading"]

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_items_analyzed": len(sentiments),
        "avg_sentiment_score": avg_sentiment,
        "top_narratives": [
            {
                "name": t.narrative_name,
                "category": t.narrative_category,
                "strength": t.strength,
                "momentum": t.momentum,
                "tokens": t.related_tokens,
            }
            for t in trends[:10]
        ],
        "emerging": [{"name": t.narrative_name, "strength": t.strength} for t in emerging],
        "fading": [{"name": t.narrative_name, "strength": t.strength} for t in fading],
        "sentiment_distribution": _sentiment_distribution(sentiments),
    }


def _sentiment_distribution(sentiments: list) -> dict:
    dist = {"very_bullish": 0, "bullish": 0, "neutral": 0, "bearish": 0, "very_bearish": 0}
    for s in sentiments:
        cat = s.overall_sentiment or "neutral"
        if cat in dist:
            dist[cat] += 1
    return dist


def _score_to_sentiment(score: float) -> str:
    if score > 0.6:
        return "very_bullish"
    if score > 0.2:
        return "bullish"
    if score > -0.2:
        return "neutral"
    if score > -0.6:
        return "bearish"
    return "very_bearish"


async def generate_daily_report(
    subscriber_chat_ids: list[int] | None = None,
) -> dict | None:
    """Generate daily narrative intelligence report."""
    if async_session is None:
        return None

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=1)

    async with async_session() as db:
        stats = await get_daily_narrative_stats(db, period_start, now)

        if stats["total_items_analyzed"] == 0:
            logger.info("no_narrative_data_for_report")
            return None

        report_prompt = (
            "You are a crypto narrative intelligence analyst. Generate a concise daily report.\n"
            "Include: market sentiment overview, top narratives with momentum, emerging/fading trends.\n"
            "Format for Telegram using *bold* (not **bold**). Max 500 words.\n"
            "End with: Score: X/100 (based on how eventful the narrative landscape was)"
        )

        try:
            report_text = ask_claude(
                system_prompt=report_prompt,
                user_message=f"Daily narrative data:\n{json.dumps(stats, indent=2, default=str)}",
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("report_generation_failed", error=str(e))
            return None

        score = _extract_score(report_text)
        proof_hash = "0x" + hashlib.sha256(report_text.encode()).hexdigest()
        market_sentiment = _score_to_sentiment(stats["avg_sentiment_score"])

        report = NarrativeReport(
            report_type="daily",
            period_start=period_start,
            period_end=now,
            top_narratives=stats["top_narratives"],
            market_sentiment=market_sentiment,
            sentiment_score=stats["avg_sentiment_score"],
            emerging_trends=stats["emerging"],
            fading_trends=stats["fading"],
            report_text=report_text,
            proof_hash=proof_hash,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        logger.info("narrative_report_generated", report_id=report.id, score=score)

        if subscriber_chat_ids:
            summary = f"📰 *Daily Narrative Intelligence*\n\n{report_text[:3000]}"
            for chat_id in subscriber_chat_ids:
                try:
                    await send_alert(chat_id, summary)
                except Exception as e:
                    logger.error("report_alert_failed", chat_id=chat_id, error=str(e))

        return {
            "report_id": report.id,
            "score": score,
            "proof_hash": proof_hash,
            "items_analyzed": stats["total_items_analyzed"],
            "avg_sentiment": stats["avg_sentiment_score"],
            "market_sentiment": market_sentiment,
        }


def _extract_score(text: str) -> int:
    for line in reversed(text.split("\n")):
        line = line.strip()
        if line.lower().startswith("score:"):
            parts = line.split(":")[-1].strip().split("/")
            try:
                return int(parts[0].strip())
            except (ValueError, IndexError):
                pass
    return 50
