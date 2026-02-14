"""
Sniper Scanner — Monitors Trader Joe Factory for PairCreated events (new token launches).
"""
from shared.web3_client import w3
from shared.dex import factory_contract, get_token_balance, get_erc20_contract, WAVAX
from shared.price_feed import get_avax_price
from shared.database import async_session
from agents.sniper.models.db import SniperLaunch
from agents.sniper.config import JOE_FACTORY
import structlog

logger = structlog.get_logger()

# Track last checked block
_last_block = 0


async def scan_new_launches():
    """Scan for new PairCreated events on Trader Joe Factory."""
    global _last_block
    if async_session is None:
        return []

    try:
        current_block = w3.eth.block_number
        if _last_block == 0:
            _last_block = current_block - 100  # Start from ~100 blocks ago

        # Get PairCreated events
        event_filter = factory_contract.events.PairCreated.create_filter(
            from_block=_last_block + 1,
            to_block=current_block,
        )
        events = event_filter.get_all_entries()
        _last_block = current_block

        new_launches = []
        async with async_session() as db:
            for event in events:
                token0 = event["args"]["token0"]
                token1 = event["args"]["token1"]
                pair = event["args"]["pair"]

                # Determine which token is new (not WAVAX)
                new_token = token0 if token1.lower() == WAVAX.lower() else token1
                if new_token.lower() == WAVAX.lower():
                    continue  # Both are known tokens, skip

                # Get token info
                try:
                    token_contract = get_erc20_contract(new_token)
                    symbol = token_contract.functions.symbol().call()
                except Exception:
                    symbol = "UNKNOWN"

                # Estimate liquidity
                avax_price = await get_avax_price()
                liquidity_usd = 0
                try:
                    pair_wavax_balance = get_token_balance(WAVAX, pair)
                    liquidity_usd = (pair_wavax_balance / 1e18) * avax_price * 2  # Both sides
                except Exception:
                    pass

                # Get deployer (pair creator)
                deployer = ""
                try:
                    tx = w3.eth.get_transaction(event["transactionHash"])
                    deployer = tx["from"]
                except Exception:
                    pass

                launch = SniperLaunch(
                    token_address=new_token,
                    token_symbol=symbol,
                    pair_address=pair,
                    initial_liquidity_usd=liquidity_usd,
                    deployer_address=deployer,
                    passed_filters=False,
                )
                db.add(launch)
                new_launches.append({
                    "token_address": new_token,
                    "symbol": symbol,
                    "pair": pair,
                    "liquidity_usd": liquidity_usd,
                    "launch_id": None,  # Set after commit
                })

                logger.info(
                    "new_launch_detected",
                    token=new_token,
                    symbol=symbol,
                    pair=pair,
                    liquidity_usd=liquidity_usd,
                )

            await db.commit()

        return new_launches

    except Exception as e:
        logger.error("scan_new_launches_failed", error=str(e))
        return []
