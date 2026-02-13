"""
Admin handlers — Restricted commands for bot admin.
"""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import text
from shared.database import async_session
from shared.config import settings
import structlog

logger = structlog.get_logger()

ADMIN_CHAT_IDS: set[int] = set()  # Populate from env or config


def is_admin(chat_id: int) -> bool:
    return chat_id in ADMIN_CHAT_IDS


async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show platform stats. Admin only."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Unauthorized.")
        return

    if async_session is None:
        await update.message.reply_text("Database not configured.")
        return

    async with async_session() as db:
        subs = await db.execute(text("SELECT COUNT(*) FROM subscribers"))
        signals = await db.execute(text("SELECT COUNT(*) FROM tipster_signals"))
        whale_tx = await db.execute(text("SELECT COUNT(*) FROM whale_transactions"))
        trends = await db.execute(text("SELECT COUNT(*) FROM narrative_trends WHERE is_active = true"))
        proofs = await db.execute(text("SELECT COUNT(*) FROM proof_submissions"))

    msg = f"""*Admin Stats*

Subscribers: {subs.scalar() or 0}
Tipster Signals: {signals.scalar() or 0}
Whale Transactions: {whale_tx.scalar() or 0}
Active Narratives: {trends.scalar() or 0}
Proofs Submitted: {proofs.scalar() or 0}
"""
    await update.message.reply_text(msg, parse_mode="Markdown")


async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast a message to all subscribers. Admin only."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    message = " ".join(context.args)

    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(text("SELECT chat_id FROM subscribers WHERE is_active = true"))
        chat_ids = [row[0] for row in result.fetchall()]

    from shared.telegram_bot import send_alert
    sent = 0
    for cid in chat_ids:
        try:
            await send_alert(cid, message)
            sent += 1
        except Exception:
            pass

    await update.message.reply_text(f"Broadcast sent to {sent}/{len(chat_ids)} subscribers.")
