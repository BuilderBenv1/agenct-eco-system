"""
Whale Reporter — Generates daily whale movement reports and sends alerts.
"""
import json
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.claude_client import ask_claude
from shared.telegram_bot import send_alert
from agents.whale.models.db import WhaleReport, WhaleAnalysis
from agents.whale.services.analyzer import get_daily_stats
from agents.whale.config import ALERT_MIN_SIGNIFICANCE
import structlog

logger = structlog.get_logger()

SIGNIFICANCE_ORDER = ["low", "medium", "high", "critical"]


def _significance_gte(a: str, b: str) -> bool:
    return SIGNIFICANCE_ORDER.index(a) >= SIGNIFICANCE_ORDER.index(b)


async def send_whale_alert(
    analysis: WhaleAnalysis,
    subscriber_chat_ids: list[int],
):
    """Send a real-time alert for significant whale movements."""
    if not _significance_gte(analysis.significance, ALERT_MIN_SIGNIFICANCE):
        return
    if not subscriber_chat_ids:
        return

    icon = {"critical": "🚨", "high": "🐋", "medium": "📊", "low": "📝"}.get(analysis.significance, "📊")
    msg = f"{icon} *Whale Alert — {analysis.significance.upper()}*\n\n"
    if analysis.analysis_text:
        msg += f"{analysis.analysis_text}\n"
    if analysis.market_impact:
        msg += f"\n_Impact: {analysis.market_impact}_"

    for chat_id in subscriber_chat_ids:
        try:
            await send_alert(chat_id, msg)
        except Exception as e:
            logger.error("whale_alert_failed", chat_id=chat_id, error=str(e))


async def generate_daily_report(
    subscriber_chat_ids: list[int] | None = None,
) -> dict | None:
    """Generate daily whale activity report."""
    if async_session is None:
        return None

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=1)

    async with async_session() as db:
        stats = await get_daily_stats(db, period_start, now)

        if stats["total_transactions"] == 0:
            logger.info("no_whale_activity_for_report")
            return None

        # Generate report with Claude
        report_prompt = (
            "You are a whale movement analyst. Generate a concise daily report for Avalanche C-Chain whale activity.\n"
            "Include: total transactions, volume, top movers, notable patterns.\n"
            "Format for Telegram using *bold* (not **bold**). Max 400 words.\n"
            "End with: Score: X/100 (based on how significant the day's whale activity was)"
        )
        try:
            report_text = ask_claude(
                system_prompt=report_prompt,
                user_message=f"Daily whale data:\n{json.dumps(stats, indent=2, default=str)}",
                max_tokens=1536,
            )
        except Exception as e:
            logger.error("report_generation_failed", error=str(e))
            return None

        score = _extract_score(report_text)
        proof_hash = "0x" + hashlib.sha256(report_text.encode()).hexdigest()

        report = WhaleReport(
            report_type="daily",
            period_start=period_start,
            period_end=now,
            total_transactions=stats["total_transactions"],
            total_volume_usd=stats["total_volume_usd"],
            top_movers=stats["top_movers"],
            notable_patterns=[],
            report_text=report_text,
            proof_hash=proof_hash,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        logger.info("daily_whale_report_generated", report_id=report.id, score=score)

        if subscriber_chat_ids:
            summary = f"🐋 *Daily Whale Report*\n\n{report_text[:3000]}"
            for chat_id in subscriber_chat_ids:
                try:
                    await send_alert(chat_id, summary)
                except Exception as e:
                    logger.error("report_alert_failed", chat_id=chat_id, error=str(e))

        return {
            "report_id": report.id,
            "score": score,
            "proof_hash": proof_hash,
            "total_transactions": stats["total_transactions"],
            "total_volume_usd": stats["total_volume_usd"],
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
