"""
/narrative handler — Display active market narratives and trends.
"""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from shared.database import async_session
from agents.narrative.models.db import NarrativeTrend
import structlog

logger = structlog.get_logger()


async def narrative_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show active narrative trends."""
    if async_session is None:
        await update.message.reply_text("Database not configured.")
        return

    async with async_session() as db:
        result = await db.execute(
            select(NarrativeTrend)
            .where(NarrativeTrend.is_active == True)
            .order_by(NarrativeTrend.strength.desc())
            .limit(8)
        )
        trends = list(result.scalars().all())

    if not trends:
        await update.message.reply_text("No active narratives detected yet. Check back later!")
        return

    momentum_icons = {
        "emerging": "🌱",
        "growing": "📈",
        "peaking": "🔥",
        "fading": "📉",
    }

    msg = "*Active Market Narratives* 📰\n\n"
    for t in trends:
        icon = momentum_icons.get(t.momentum, "📊")
        msg += f"{icon} *{t.narrative_name}* ({t.momentum})\n"
        msg += f"   Strength: {t.strength:.0%}\n"
        if t.related_tokens:
            tokens = ", ".join(f"${tok}" for tok in t.related_tokens[:4])
            msg += f"   Tokens: {tokens}\n"
        msg += "\n"

    msg += "_Use /subscribe for daily narrative reports_"
    await update.message.reply_text(msg, parse_mode="Markdown")
