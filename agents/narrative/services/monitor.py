"""
RSS/News Monitor — Fetches content from RSS feeds and CoinGecko trending data.
"""
import hashlib
from datetime import datetime, timezone
from xml.etree import ElementTree
import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.config import settings
from shared.database import async_session
from agents.narrative.models.db import NarrativeSource, NarrativeItem
from agents.narrative.config import MAX_ITEMS_PER_SOURCE, MAX_CONTENT_LENGTH
import structlog

logger = structlog.get_logger()


async def _fetch_rss(url: str) -> list[dict]:
    """Fetch and parse an RSS feed, returning list of items."""
    items = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.text)

            # Handle both RSS 2.0 and Atom feeds
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # RSS 2.0
            for item in root.findall(".//item")[:MAX_ITEMS_PER_SOURCE]:
                title = item.findtext("title", "")
                desc = item.findtext("description", "")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")
                guid = item.findtext("guid", link or title)
                items.append({
                    "title": title,
                    "content": desc[:MAX_CONTENT_LENGTH],
                    "url": link,
                    "external_id": hashlib.md5(guid.encode()).hexdigest(),
                    "published_at": pub_date,
                })

            # Atom
            if not items:
                for entry in root.findall("atom:entry", ns)[:MAX_ITEMS_PER_SOURCE]:
                    title = entry.findtext("atom:title", "", ns)
                    content = entry.findtext("atom:content", "", ns) or entry.findtext("atom:summary", "", ns)
                    link_el = entry.find("atom:link", ns)
                    link = link_el.get("href", "") if link_el is not None else ""
                    entry_id = entry.findtext("atom:id", link or title, ns)
                    items.append({
                        "title": title,
                        "content": content[:MAX_CONTENT_LENGTH],
                        "url": link,
                        "external_id": hashlib.md5(entry_id.encode()).hexdigest(),
                        "published_at": entry.findtext("atom:updated", "", ns),
                    })
    except Exception as e:
        logger.error("rss_fetch_failed", url=url, error=str(e))

    return items


async def _fetch_coingecko_trending() -> list[dict]:
    """Fetch CoinGecko trending coins and convert to content items."""
    items = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{settings.COINGECKO_API_URL}/search/trending")
            resp.raise_for_status()
            data = resp.json()

            coins = data.get("coins", [])
            if coins:
                trending_text = "CoinGecko Trending Coins: " + ", ".join(
                    f"{c['item']['symbol']} ({c['item']['name']})" for c in coins[:10]
                )
                items.append({
                    "title": "CoinGecko Trending",
                    "content": trending_text,
                    "url": "https://www.coingecko.com/trending",
                    "external_id": f"cg_trending_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                })

            # Also get trending categories
            nfts = data.get("nfts", [])
            categories = data.get("categories", [])
            if categories:
                cat_text = "Trending Categories: " + ", ".join(
                    c.get("name", "") for c in categories[:5]
                )
                items.append({
                    "title": "CoinGecko Trending Categories",
                    "content": cat_text,
                    "url": "https://www.coingecko.com",
                    "external_id": f"cg_categories_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                })
    except Exception as e:
        logger.error("coingecko_trending_failed", error=str(e))

    return items


async def poll_rss_sources():
    """Poll all active RSS sources for new content."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(NarrativeSource).where(
                NarrativeSource.is_active == True,
                NarrativeSource.source_type == "rss",
            )
        )
        sources = list(result.scalars().all())

        for source in sources:
            if not source.url:
                continue
            items = await _fetch_rss(source.url)
            new_count = 0

            for item_data in items:
                # Check for duplicate
                existing = await db.execute(
                    select(NarrativeItem).where(
                        NarrativeItem.source_id == source.id,
                        NarrativeItem.external_id == item_data["external_id"],
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                ni = NarrativeItem(
                    source_id=source.id,
                    external_id=item_data["external_id"],
                    title=item_data["title"],
                    content=item_data["content"],
                    url=item_data["url"],
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
                logger.info("rss_items_fetched", source=source.name, new=new_count)

        await db.commit()


async def poll_coingecko_trending():
    """Fetch CoinGecko trending data and store as narrative items."""
    if async_session is None:
        return

    async with async_session() as db:
        # Find or create CoinGecko source
        result = await db.execute(
            select(NarrativeSource).where(
                NarrativeSource.source_type == "coingecko",
                NarrativeSource.name == "CoinGecko Trending",
            )
        )
        source = result.scalar_one_or_none()
        if not source:
            source = NarrativeSource(
                source_type="coingecko",
                name="CoinGecko Trending",
                url="https://api.coingecko.com/api/v3/search/trending",
                category="news",
            )
            db.add(source)
            await db.commit()
            await db.refresh(source)

        items = await _fetch_coingecko_trending()
        for item_data in items:
            existing = await db.execute(
                select(NarrativeItem).where(
                    NarrativeItem.source_id == source.id,
                    NarrativeItem.external_id == item_data["external_id"],
                )
            )
            if existing.scalar_one_or_none():
                continue

            ni = NarrativeItem(
                source_id=source.id,
                external_id=item_data["external_id"],
                title=item_data["title"],
                content=item_data["content"],
                url=item_data["url"],
                fetched_at=datetime.now(timezone.utc),
            )
            db.add(ni)

        await db.execute(
            update(NarrativeSource)
            .where(NarrativeSource.id == source.id)
            .values(last_fetched=datetime.now(timezone.utc))
        )
        await db.commit()
