"""
Clawntenna handler for Whale agent — processes encrypted queries about whale movements.

Query examples:
  "Has 0x1234... been active today?"
  "Largest whale transactions in the last 24h"
  "Alert me when whales buy AVAX"
  "Top whale wallets by volume"
"""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from shared.clawntenna import ClawntennMessage
from shared.lightning import get_lightning
from agents.whale.models.db import WhaleTransaction, WhaleWallet, WhaleAnalysis
from agents.whale.config import AGENT_NAME
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def handle_whale_query(msg: ClawntennMessage) -> str | None:
    """Handle an incoming Clawntenna query for the Whale agent."""
    query = msg.text.strip().lower()

    lightning.emit_action("clawntenna_query", {"query": query, "sender": msg.sender})

    try:
        if "0x" in query:
            # Wallet-specific query
            address = _extract_address(msg.text)
            if address:
                result = await _get_wallet_activity(address)
            else:
                result = {"error": "Invalid wallet address"}
        elif "largest" in query or "top" in query or "biggest" in query:
            result = await _get_largest_transactions()
        elif "volume" in query or "summary" in query:
            result = await _get_daily_summary()
        else:
            result = await _get_latest_whale_moves()

        lightning.log_success("clawntenna_query", output=result)
        return json.dumps(result, default=str)

    except Exception as e:
        lightning.log_failure(
            task="clawntenna_query",
            error=str(e),
            context={"query": query, "sender": msg.sender},
        )
        return json.dumps({"error": "Query processing failed", "agent": "whale"})


def _extract_address(text: str) -> str | None:
    """Extract an Ethereum address from query text."""
    import re
    match = re.search(r"0x[a-fA-F0-9]{40}", text)
    return match.group(0) if match else None


async def _get_wallet_activity(address: str) -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    async with async_session() as db:
        wallet_q = await db.execute(
            select(WhaleWallet).where(WhaleWallet.address == address)
        )
        wallet = wallet_q.scalar_one_or_none()

        if not wallet:
            return {
                "agent": "whale",
                "query_type": "wallet",
                "address": address,
                "tracked": False,
                "message": "This wallet is not in our tracking list.",
            }

        day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        txns_q = await db.execute(
            select(WhaleTransaction)
            .where(WhaleTransaction.wallet_id == wallet.id, WhaleTransaction.detected_at >= day_ago)
            .order_by(WhaleTransaction.detected_at.desc())
            .limit(10)
        )
        txns = list(txns_q.scalars().all())

        return {
            "agent": "whale",
            "query_type": "wallet_activity",
            "address": address,
            "label": wallet.label,
            "category": wallet.category,
            "transactions_24h": len(txns),
            "recent": [
                {
                    "type": t.tx_type,
                    "token": t.token_symbol or "AVAX",
                    "amount_usd": float(t.amount_usd) if t.amount_usd else 0,
                    "method": t.decoded_method,
                    "time": t.detected_at.isoformat() if t.detected_at else None,
                }
                for t in txns[:5]
            ],
            "verified_by": "AgentProof",
        }


async def _get_largest_transactions() -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    async with async_session() as db:
        result = await db.execute(
            select(WhaleTransaction)
            .where(WhaleTransaction.detected_at >= day_ago)
            .order_by(WhaleTransaction.amount_usd.desc())
            .limit(10)
        )
        txns = list(result.scalars().all())

        return {
            "agent": "whale",
            "query_type": "largest_transactions",
            "period": "24h",
            "count": len(txns),
            "transactions": [
                {
                    "tx_hash": t.tx_hash[:16] + "...",
                    "type": t.tx_type,
                    "amount_usd": float(t.amount_usd) if t.amount_usd else 0,
                    "token": t.token_symbol or "AVAX",
                }
                for t in txns
            ],
            "verified_by": "AgentProof",
        }


async def _get_latest_whale_moves() -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    async with async_session() as db:
        result = await db.execute(
            select(WhaleTransaction)
            .order_by(WhaleTransaction.detected_at.desc())
            .limit(5)
        )
        txns = list(result.scalars().all())

        return {
            "agent": "whale",
            "query_type": "latest",
            "count": len(txns),
            "transactions": [
                {
                    "type": t.tx_type,
                    "token": t.token_symbol or "AVAX",
                    "amount_usd": float(t.amount_usd) if t.amount_usd else 0,
                    "method": t.decoded_method,
                }
                for t in txns
            ],
            "verified_by": "AgentProof",
        }


async def _get_daily_summary() -> dict:
    if async_session is None:
        return {"error": "Database not configured"}

    day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    async with async_session() as db:
        count = await db.execute(
            select(func.count()).select_from(WhaleTransaction)
            .where(WhaleTransaction.detected_at >= day_ago)
        )
        volume = await db.execute(
            select(func.sum(WhaleTransaction.amount_usd))
            .where(WhaleTransaction.detected_at >= day_ago)
        )

        return {
            "agent": "whale",
            "query_type": "daily_summary",
            "transactions_24h": count.scalar() or 0,
            "total_volume_usd": float(volume.scalar() or 0),
            "verified_by": "AgentProof",
        }
