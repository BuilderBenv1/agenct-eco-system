"""
Unified Telegram Bot — Handles commands for all three agents.
"""
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler
from shared.config import settings
from bot.handlers.start import start_handler, help_handler, register_handler, status_handler
from bot.handlers.tipster import tipster_handler
from bot.handlers.whale import whale_handler
from bot.handlers.narrative import narrative_handler
from bot.handlers.subscribe import subscribe_handler
from bot.handlers.admin import admin_stats_handler, admin_broadcast_handler
from bot.handlers.convergence import convergence_handler
import structlog

logger = structlog.get_logger()


def create_bot():
    """Create and configure the Telegram bot application."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")

    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("register", register_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("subscribe", subscribe_handler))

    # Agent commands
    app.add_handler(CommandHandler("tipster", tipster_handler))
    app.add_handler(CommandHandler("whale", whale_handler))
    app.add_handler(CommandHandler("narrative", narrative_handler))

    # Convergence
    app.add_handler(CommandHandler("convergence", convergence_handler))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin_stats_handler))
    app.add_handler(CommandHandler("broadcast", admin_broadcast_handler))

    return app


def main():
    logger.info("telegram_bot_starting")
    app = create_bot()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
