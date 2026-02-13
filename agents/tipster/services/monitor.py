"""
Channel Monitor — Uses Telethon to read messages from tracked Telegram channels,
then passes them to the parser for signal extraction.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.tl.types import Channel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.config import settings
from shared.database import async_session
from shared.telegram_bot import send_alert
from agents.tipster.models.db import TipsterChannel, TipsterSignal
from agents.tipster.services.parser import parse_signal
from agents.tipster.config import HIGH_CONFIDENCE
import structlog

logger = structlog.get_logger()

_client: TelegramClient | None = None


async def get_telethon_client() -> TelegramClient:
    """Get or create the Telethon user client for reading channels."""
    global _client
    if _client is None or not _client.is_connected():
        _client = TelegramClient(
            "tipster_session",
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )
        await _client.start()
        logger.info("telethon_client_started")
    return _client


async def get_active_channels(db: AsyncSession) -> list[TipsterChannel]:
    result = await db.execute(
        select(TipsterChannel).where(TipsterChannel.is_active == True)
    )
    return list(result.scalars().all())


async def _check_rug_risk(db: AsyncSession, token_address: str | None, token_symbol: str | None) -> dict | None:
    """Cross-validate with Rug Detector. Returns scan data if flagged dangerous."""
    if not token_address and not token_symbol:
        return None
    try:
        from agents.auditor.models.db import ContractScan
        q = select(ContractScan).where(
            ContractScan.risk_label.in_(["danger", "rug"])
        )
        if token_address:
            q = q.where(ContractScan.contract_address == token_address)
        elif token_symbol:
            q = q.where(ContractScan.token_symbol == token_symbol.upper())
        result = await db.execute(q.limit(1))
        scan = result.scalar_one_or_none()
        if scan:
            return {
                "risk_label": scan.risk_label,
                "overall_risk_score": scan.overall_risk_score,
                "red_flags": scan.red_flags or [],
            }
    except Exception as e:
        logger.debug("rug_check_failed", error=str(e))
    return None


async def process_message(
    db: AsyncSession,
    channel: TipsterChannel,
    message_id: int,
    text: str,
    subscribers: list[int],
):
    """Parse a single message and store if it's a valid signal."""
    parsed = parse_signal(text)
    if parsed is None:
        return

    # Cross-validate BUY signals with Rug Detector
    rug_warning = None
    if parsed.signal_type == "BUY":
        rug_data = await _check_rug_risk(db, parsed.token_address, parsed.token_symbol)
        if rug_data:
            # Reduce confidence for dangerous tokens
            original_confidence = parsed.confidence
            parsed.confidence = max(0.1, parsed.confidence * 0.3)
            rug_warning = (
                f"RUG ALERT: {parsed.token_symbol} flagged as {rug_data['risk_label'].upper()} "
                f"(score {rug_data['overall_risk_score']}/100). "
                f"Confidence reduced from {original_confidence:.0%} to {parsed.confidence:.0%}."
            )
            if rug_data["red_flags"]:
                rug_warning += f" Flags: {', '.join(rug_data['red_flags'][:3])}"
            logger.warning(
                "rug_cross_validation",
                token=parsed.token_symbol,
                risk=rug_data["risk_label"],
                original_conf=original_confidence,
                new_conf=parsed.confidence,
            )

    signal = TipsterSignal(
        channel_id=channel.channel_id,
        message_id=message_id,
        raw_text=text,
        token_symbol=parsed.token_symbol,
        token_name=parsed.token_name,
        token_address=parsed.token_address,
        chain=parsed.chain,
        signal_type=parsed.signal_type,
        confidence=parsed.confidence,
        entry_price=parsed.entry_price,
        target_prices=parsed.target_prices,
        stop_loss=parsed.stop_loss,
        timeframe=parsed.timeframe,
        parsed_at=datetime.now(timezone.utc),
        claude_analysis=(parsed.reasoning or "") + (f"\n\n⚠️ {rug_warning}" if rug_warning else ""),
    )
    db.add(signal)

    # Update channel stats
    await db.execute(
        update(TipsterChannel)
        .where(TipsterChannel.channel_id == channel.channel_id)
        .values(total_signals=TipsterChannel.total_signals + 1)
    )
    await db.commit()

    logger.info(
        "signal_stored",
        signal_id=signal.id,
        token=parsed.token_symbol,
        type=parsed.signal_type,
        confidence=parsed.confidence,
        channel=channel.channel_name,
    )

    # Send alert for high-confidence signals
    if parsed.confidence >= HIGH_CONFIDENCE and subscribers:
        alert = _format_alert(parsed, channel.channel_name)
        if rug_warning:
            alert += f"\n\n🚨 {rug_warning}"
        for chat_id in subscribers:
            try:
                await send_alert(chat_id, alert)
            except Exception as e:
                logger.error("alert_send_failed", chat_id=chat_id, error=str(e))


def _format_alert(parsed, channel_name: str) -> str:
    direction = "🟢" if parsed.signal_type == "BUY" else "🔴" if parsed.signal_type == "SELL" else "⚠️"
    msg = f"{direction} *{parsed.signal_type} Signal — ${parsed.token_symbol}*\n"
    msg += f"Confidence: {parsed.confidence:.0%}\n"
    if parsed.entry_price:
        msg += f"Entry: ${parsed.entry_price}\n"
    if parsed.target_prices:
        targets = ", ".join(f"${t}" for t in parsed.target_prices)
        msg += f"Targets: {targets}\n"
    if parsed.stop_loss:
        msg += f"Stop-loss: ${parsed.stop_loss}\n"
    if parsed.timeframe:
        msg += f"Timeframe: {parsed.timeframe}\n"
    msg += f"\nSource: {channel_name}"
    if parsed.reasoning:
        msg += f"\n_{parsed.reasoning}_"
    return msg


async def poll_channels(subscriber_chat_ids: list[int] | None = None):
    """Poll all active channels for new messages (last 60 seconds)."""
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        logger.warning("telegram_api_not_configured")
        return

    client = await get_telethon_client()
    if async_session is None:
        logger.error("database_not_configured")
        return

    async with async_session() as db:
        channels = await get_active_channels(db)
        if not channels:
            logger.debug("no_active_channels")
            return

        since = datetime.now(timezone.utc) - timedelta(seconds=90)
        subs = subscriber_chat_ids or []

        for ch in channels:
            try:
                entity = await client.get_entity(ch.channel_id)
                async for msg in client.iter_messages(entity, offset_date=since, reverse=True):
                    if msg.text:
                        await process_message(db, ch, msg.id, msg.text, subs)
            except Exception as e:
                logger.error("channel_poll_failed", channel=ch.channel_name, error=str(e))
