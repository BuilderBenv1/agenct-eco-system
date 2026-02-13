"""
/whale handler — Display recent whale movements.
"""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from shared.database import async_session
from agents.whale.models.db import WhaleTransaction, WhaleWallet
import structlog

logger = structlog.get_logger()


async def whale_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent whale transactions."""
    if async_session is None:
        await update.message.reply_text("Database not configured.")
        return

    async with async_session() as db:
        result = await db.execute(
            select(WhaleTransaction)
            .order_by(WhaleTransaction.detected_at.desc())
            .limit(5)
        )
        txns = list(result.scalars().all())

    if not txns:
        await update.message.reply_text("No recent whale movements detected. Check back later!")
        return

    msg = "*Recent Whale Movements* 🐋\n\n"
    for tx in txns:
        usd = float(tx.amount_usd) if tx.amount_usd else 0
        icon = "🚨" if usd >= 1_000_000 else "🐋" if usd >= 500_000 else "📊"
        msg += f"{icon} *{tx.tx_type}* — ${usd:,.0f}\n"
        msg += f"   Token: {tx.token_symbol or 'AVAX'}\n"
        msg += f"   Method: {tx.decoded_method or 'transfer'}\n"
        msg += f"   `{tx.tx_hash[:16]}...`\n\n"

    msg += "_Use /subscribe for real-time whale alerts_"
    await update.message.reply_text(msg, parse_mode="Markdown")
