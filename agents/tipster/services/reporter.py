"""
Reporter — Generates weekly performance reports using Claude,
stores them, and sends summaries to subscribers.
"""
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.claude_client import ask_claude
from shared.telegram_bot import send_alert
from agents.tipster.models.db import TipsterReport
from agents.tipster.services.analyzer import get_weekly_stats, update_channel_reliability
import structlog

logger = structlog.get_logger()

REPORT_PROMPT_PATH = Path(__file__).parent.parent / "templates" / "weekly_report.md"
_report_prompt: str | None = None


def _get_report_prompt() -> str:
    global _report_prompt
    if _report_prompt is None:
        _report_prompt = REPORT_PROMPT_PATH.read_text(encoding="utf-8")
    return _report_prompt


def _compute_proof_hash(report_text: str) -> str:
    """SHA-256 hash of the report text for on-chain proof."""
    return "0x" + hashlib.sha256(report_text.encode()).hexdigest()


def _extract_score(report_text: str) -> int:
    """Extract the 0-100 score from the report text."""
    for line in reversed(report_text.split("\n")):
        line = line.strip()
        if line.lower().startswith("score:"):
            parts = line.split(":")[-1].strip().split("/")
            try:
                return int(parts[0].strip())
            except (ValueError, IndexError):
                pass
    return 50  # default


async def generate_weekly_report(
    subscriber_chat_ids: list[int] | None = None,
) -> dict | None:
    """
    Generate the weekly performance report.
    Returns report metadata dict or None on failure.
    """
    if async_session is None:
        logger.error("database_not_configured")
        return None

    # Update channel reliability first
    await update_channel_reliability()

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=7)

    async with async_session() as db:
        stats = await get_weekly_stats(db, period_start, now)

        if stats["total_signals"] == 0:
            logger.info("no_signals_for_report")
            return None

        # Generate report with Claude
        data_str = json.dumps(stats, indent=2, default=str)
        try:
            report_text = ask_claude(
                system_prompt=_get_report_prompt(),
                user_message=f"Weekly signal data:\n{data_str}",
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("report_generation_failed", error=str(e))
            return None

        score = _extract_score(report_text)
        proof_hash = _compute_proof_hash(report_text)

        # Store report
        report = TipsterReport(
            report_type="weekly",
            period_start=period_start,
            period_end=now,
            total_signals=stats["total_signals"],
            profitable_signals=stats["profitable_signals"],
            avg_return_pct=stats["avg_return_pct"],
            best_signal_id=stats["best_signal"]["signal_id"] if stats["best_signal"] else None,
            worst_signal_id=stats["worst_signal"]["signal_id"] if stats["worst_signal"] else None,
            report_text=report_text,
            proof_hash=proof_hash,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        logger.info("weekly_report_generated", report_id=report.id, score=score)

        # Send to subscribers
        if subscriber_chat_ids:
            summary = f"📊 *Weekly Tipster Report*\n\n{report_text[:3000]}"
            for chat_id in subscriber_chat_ids:
                try:
                    await send_alert(chat_id, summary)
                except Exception as e:
                    logger.error("report_alert_failed", chat_id=chat_id, error=str(e))

        return {
            "report_id": report.id,
            "score": score,
            "proof_hash": proof_hash,
            "total_signals": stats["total_signals"],
            "profitable_signals": stats["profitable_signals"],
            "avg_return_pct": stats["avg_return_pct"],
        }
