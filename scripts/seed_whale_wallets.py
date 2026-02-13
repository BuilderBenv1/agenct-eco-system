"""
Seed whale wallets from examples/whale_wallets.json into the database.

Usage:
    python -m scripts.seed_whale_wallets
"""
import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from shared.database import engine

WALLETS_PATH = Path(__file__).parent.parent / "agents" / "whale" / "examples" / "whale_wallets.json"


async def seed():
    if engine is None:
        print("ERROR: DATABASE_URL not configured.")
        return

    with open(WALLETS_PATH) as f:
        wallets = json.load(f)

    print(f"Seeding {len(wallets)} whale wallets...")
    async with engine.begin() as conn:
        for w in wallets:
            await conn.execute(
                text("""
                    INSERT INTO whale_wallets (address, label, category, chain, is_active)
                    VALUES (:address, :label, :category, 'avalanche', true)
                    ON CONFLICT (address) DO NOTHING
                """),
                {
                    "address": w["address"],
                    "label": w.get("label"),
                    "category": w.get("category"),
                },
            )
    print("Whale wallets seeded successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
