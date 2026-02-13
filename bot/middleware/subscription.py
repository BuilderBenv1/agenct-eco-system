"""
Subscription middleware — checks on-chain subscription before allowing premium commands.
"""
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from shared.auth import check_subscription
from sqlalchemy import select
from shared.database import async_session
import structlog

logger = structlog.get_logger()

# Plan IDs for each agent (set after subscription plans are created)
PLAN_IDS = {
    "tipster": 1,
    "whale": 2,
    "narrative": 3,
}


async def _get_wallet_for_chat(chat_id: int) -> str | None:
    """Look up the registered wallet address for a chat ID."""
    if async_session is None:
        return None
    async with async_session() as db:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT wallet_address FROM subscribers WHERE chat_id = :cid"),
            {"cid": chat_id},
        )
        row = result.first()
        return row[0] if row else None


def require_subscription(agent_name: str):
    """Decorator for handlers requiring an active on-chain subscription."""
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            chat_id = update.effective_chat.id
            wallet = await _get_wallet_for_chat(chat_id)

            if not wallet:
                await update.message.reply_text(
                    "You need to register your wallet first.\n"
                    "Use /register <wallet_address> to link your wallet."
                )
                return

            plan_id = PLAN_IDS.get(agent_name, 1)
            if not check_subscription(wallet, plan_id):
                await update.message.reply_text(
                    f"You need an active subscription to the *{agent_name}* agent.\n"
                    f"Subscribe on-chain at our dApp to access premium features.",
                    parse_mode="Markdown",
                )
                return

            return await func(update, context)
        return wrapper
    return decorator
