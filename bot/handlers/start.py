"""
/start and /help handlers — Welcome message, registration, and help.
"""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import text
from shared.database import async_session
import structlog

logger = structlog.get_logger()

WELCOME_MSG = """
*Welcome to AgentProof Intelligence* 🤖

Three AI agents, verified on-chain via the Avalanche blockchain.

*Available Agents:*
📊 *Tipster Verifier* — Parses & verifies crypto signals
🐋 *Whale Tracker* — Monitors large wallet movements
📰 *Narrative Scanner* — Detects market trends & sentiment

*Commands:*
/register <wallet> — Link your wallet
/tipster — Latest trading signals
/whale — Recent whale movements
/narrative — Active market narratives
/subscribe — Subscription info
/status — Your account status
/help — This message

_Powered by AgentProof on Avalanche_
"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MSG, parse_mode="Markdown")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MSG, parse_mode="Markdown")


async def register_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register or update wallet address."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /register <wallet_address>\nExample: /register 0x1234...abcd")
        return

    wallet = context.args[0].strip()
    if not wallet.startswith("0x") or len(wallet) != 42:
        await update.message.reply_text("Invalid wallet address. Must be a 42-character hex address starting with 0x.")
        return

    chat_id = update.effective_chat.id
    username = update.effective_user.username or ""

    if async_session is None:
        await update.message.reply_text("Database not configured. Contact admin.")
        return

    async with async_session() as db:
        await db.execute(
            text("""
                INSERT INTO subscribers (chat_id, username, wallet_address, subscribed_agents, is_active)
                VALUES (:cid, :username, :wallet, '[]', true)
                ON CONFLICT (chat_id) DO UPDATE SET wallet_address = :wallet, username = :username
            """),
            {"cid": chat_id, "username": username, "wallet": wallet},
        )
        await db.commit()

    logger.info("wallet_registered", chat_id=chat_id, wallet=wallet)
    await update.message.reply_text(
        f"Wallet registered: `{wallet}`\n\n"
        "You can now access agent data if you have active subscriptions.",
        parse_mode="Markdown",
    )


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's subscription status."""
    chat_id = update.effective_chat.id

    if async_session is None:
        await update.message.reply_text("Database not configured.")
        return

    async with async_session() as db:
        result = await db.execute(
            text("SELECT wallet_address, subscribed_agents FROM subscribers WHERE chat_id = :cid"),
            {"cid": chat_id},
        )
        row = result.first()

    if not row:
        await update.message.reply_text("Not registered yet. Use /register <wallet> first.")
        return

    wallet = row[0]
    agents = row[1] or []

    msg = f"*Your Status*\n\nWallet: `{wallet}`\nAgents: {', '.join(agents) if agents else 'None'}\n"

    # Check on-chain subscriptions
    from shared.auth import check_subscription
    from bot.middleware.subscription import PLAN_IDS

    for agent_name, plan_id in PLAN_IDS.items():
        active = check_subscription(wallet, plan_id) if wallet else False
        status = "Active" if active else "Inactive"
        msg += f"\n{agent_name}: {status}"

    await update.message.reply_text(msg, parse_mode="Markdown")
