"""
Whale Monitor — Polls Avalanche C-Chain for new transactions from tracked whale wallets.
Uses the Snowtrace/RPC endpoint to fetch recent transactions.
"""
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.web3_client import w3
from agents.whale.models.db import WhaleWallet, WhaleTransaction
from agents.whale.services.decoder import decode_transaction, get_avax_price_usd
from agents.whale.config import MIN_VALUE_USD, MAX_BLOCKS_PER_POLL
import structlog

logger = structlog.get_logger()

_last_block: int | None = None


async def _get_start_block() -> int:
    global _last_block
    if _last_block is not None:
        return _last_block
    current = w3.eth.block_number
    _last_block = max(current - 50, 0)
    return _last_block


async def get_active_wallets(db: AsyncSession) -> list[WhaleWallet]:
    result = await db.execute(
        select(WhaleWallet).where(WhaleWallet.is_active == True)
    )
    return list(result.scalars().all())


async def check_wallet_transactions(
    db: AsyncSession,
    wallet: WhaleWallet,
    from_block: int,
    to_block: int,
    avax_price: float,
) -> list[WhaleTransaction]:
    """Check for new transactions from a specific whale wallet."""
    new_txns = []
    address = wallet.address.lower()

    for block_num in range(from_block, to_block + 1):
        try:
            block = w3.eth.get_block(block_num, full_transactions=True)
        except Exception as e:
            logger.debug("block_fetch_failed", block=block_num, error=str(e))
            continue

        for tx in block.transactions:
            tx_from = (tx.get("from") or "").lower()
            tx_to = (tx.get("to") or "").lower()

            if tx_from != address and tx_to != address:
                continue

            tx_hash_hex = tx["hash"].hex() if isinstance(tx["hash"], bytes) else str(tx["hash"])

            # Check if already tracked
            existing = await db.execute(
                select(WhaleTransaction).where(WhaleTransaction.tx_hash == tx_hash_hex)
            )
            if existing.scalar_one_or_none():
                continue

            # Decode transaction
            decoded = decode_transaction(tx)
            value_usd = decoded["value_avax"] * avax_price

            if value_usd < MIN_VALUE_USD and decoded["tx_type"] == "transfer":
                continue  # Skip low-value plain transfers

            whale_tx = WhaleTransaction(
                wallet_id=wallet.id,
                tx_hash=tx_hash_hex,
                block_number=block_num,
                chain="avalanche",
                tx_type=decoded["tx_type"],
                from_address=decoded["from_address"],
                to_address=decoded["to_address"],
                token_symbol="AVAX" if decoded["value_avax"] > 0 else None,
                amount=decoded["value_avax"],
                amount_usd=value_usd,
                gas_used=decoded["gas_used"],
                gas_price_gwei=decoded["gas_price_gwei"],
                decoded_method=decoded["decoded_method"],
                raw_input=decoded["input_data"],
                detected_at=datetime.now(timezone.utc),
            )
            db.add(whale_tx)
            new_txns.append(whale_tx)

    if new_txns:
        await db.execute(
            update(WhaleWallet)
            .where(WhaleWallet.id == wallet.id)
            .values(total_tx_tracked=WhaleWallet.total_tx_tracked + len(new_txns))
        )

    return new_txns


async def poll_whale_transactions() -> list[WhaleTransaction]:
    """Poll all tracked wallets for new transactions."""
    global _last_block

    if async_session is None:
        logger.error("database_not_configured")
        return []

    try:
        current_block = w3.eth.block_number
    except Exception as e:
        logger.error("rpc_failed", error=str(e))
        return []

    from_block = await _get_start_block()
    to_block = min(from_block + MAX_BLOCKS_PER_POLL, current_block)

    if from_block >= to_block:
        return []

    avax_price = await get_avax_price_usd()
    if avax_price == 0:
        logger.warning("avax_price_unavailable")
        return []

    all_new = []
    async with async_session() as db:
        wallets = await get_active_wallets(db)
        if not wallets:
            _last_block = to_block + 1
            return []

        for wallet in wallets:
            new_txns = await check_wallet_transactions(db, wallet, from_block, to_block, avax_price)
            all_new.extend(new_txns)

        if all_new:
            await db.commit()

    _last_block = to_block + 1
    if all_new:
        logger.info("whale_txns_found", count=len(all_new), blocks=f"{from_block}-{to_block}")
    return all_new
