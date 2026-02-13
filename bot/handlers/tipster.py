"""
/tipster handler — Display latest signals and tipster data.
"""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from shared.database import async_session
from agents.tipster.models.db import TipsterSignal
import structlog

logger = structlog.get_logger()


async def tipster_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent high-confidence signals."""
    if async_session is None:
        await update.message.reply_text("Database not configured.")
        return

    async with async_session() as db:
        result = await db.execute(
            select(TipsterSignal)
            .where(TipsterSignal.is_valid == True, TipsterSignal.confidence >= 0.5)
            .order_by(TipsterSignal.created_at.desc())
            .limit(5)
        )
        signals = list(result.scalars().all())

    if not signals:
        await update.message.reply_text("No recent signals found. Check back later!")
        return

    msg = "*Recent Crypto Signals*\n\n"
    for s in signals:
        icon = "🟢" if s.signal_type == "BUY" else "🔴" if s.signal_type == "SELL" else "⚠️"
        msg += f"{icon} *{s.signal_type}* ${s.token_symbol or '?'} — {s.confidence:.0%}\n"
        if s.entry_price:
            msg += f"   Entry: ${float(s.entry_price):,.2f}\n"
        if s.target_prices:
            targets = ", ".join(f"${t}" for t in s.target_prices[:3])
            msg += f"   Targets: {targets}\n"
        msg += "\n"

    msg += "_Use /subscribe for real-time alerts_"
    await update.message.reply_text(msg, parse_mode="Markdown")
