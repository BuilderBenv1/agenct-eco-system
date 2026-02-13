"""
Seed RSS feed sources from examples/rss_feeds.json into the database.

Usage:
    python -m scripts.seed_rss_feeds
"""
import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from shared.database import engine

FEEDS_PATH = Path(__file__).parent.parent / "agents" / "narrative" / "examples" / "rss_feeds.json"


async def seed():
    if engine is None:
        print("ERROR: DATABASE_URL not configured.")
        return

    with open(FEEDS_PATH) as f:
        feeds = json.load(f)

    print(f"Seeding {len(feeds)} RSS feeds...")
    async with engine.begin() as conn:
        for feed in feeds:
            await conn.execute(
                text("""
                    INSERT INTO narrative_sources (source_type, name, url, category, is_active)
                    VALUES ('rss', :name, :url, :category, true)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "name": feed["name"],
                    "url": feed["url"],
                    "category": feed.get("category", "news"),
                },
            )
    print("RSS feeds seeded successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
