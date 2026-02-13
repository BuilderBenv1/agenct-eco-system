"""
Telegram Scraper — Uses Telethon to read messages from crypto Telegram channels
for narrative/sentiment analysis (separate from tipster signal parsing).
"""
import hashlib
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.config import settings
from shared.database import async_session
from agents.narrative.models.db import NarrativeSource, NarrativeItem
from agents.narrative.config import MAX_ITEMS_PER_SOURCE, MAX_CONTENT_LENGTH
import structlog

logger = structlog.get_logger()

_client: TelegramClient | None = None


async def get_telethon_client() -> TelegramClient:
    global _client
    if _client is None or not _client.is_connected():
        _client = TelegramClient(
            "narrative_session",
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )
        await _client.start()
        logger.info("narrative_telethon_started")
    return _client


async def poll_telegram_channels():
    """Poll all active Telegram sources for new messages."""
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        logger.warning("telegram_api_not_configured")
        return

    if async_session is None:
        return

    client = await get_telethon_client()

    async with async_session() as db:
        result = await db.execute(
            select(NarrativeSource).where(
                NarrativeSource.is_active == True,
                NarrativeSource.source_type == "telegram",
            )
        )
        sources = list(result.scalars().all())
        since = datetime.now(timezone.utc) - timedelta(minutes=5)

        for source in sources:
            if not source.channel_id:
                continue

            try:
                entity = await client.get_entity(source.channel_id)
                new_count = 0

                async for msg in client.iter_messages(entity, offset_date=since, reverse=True, limit=MAX_ITEMS_PER_SOURCE):
                    if not msg.text or len(msg.text.strip()) < 20:
                        continue

                    ext_id = hashlib.md5(f"{source.channel_id}_{msg.id}".encode()).hexdigest()

                    existing = await db.execute(
                        select(NarrativeItem).where(
                            NarrativeItem.source_id == source.id,
                            NarrativeItem.external_id == ext_id,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    ni = NarrativeItem(
                        source_id=source.id,
                        external_id=ext_id,
                        title=f"Telegram: {source.name}",
                        content=msg.text[:MAX_CONTENT_LENGTH],
                        published_at=msg.date,
                        fetched_at=datetime.now(timezone.utc),
                    )
                    db.add(ni)
                    new_count += 1

                await db.execute(
                    update(NarrativeSource)
                    .where(NarrativeSource.id == source.id)
                    .values(last_fetched=datetime.now(timezone.utc))
                )

                if new_count:
                    logger.info("telegram_items_fetched", source=source.name, new=new_count)

            except Exception as e:
                logger.error("telegram_poll_failed", source=source.name, error=str(e))

        await db.commit()
