"""
Transaction Decoder — Decodes raw Avalanche C-Chain transactions into human-readable format.
Identifies swap, bridge, LP, stake operations from method signatures and input data.
"""
from web3 import Web3
from shared.web3_client import w3
import structlog

logger = structlog.get_logger()

# Common method signatures (first 4 bytes of keccak256)
METHOD_SIGS = {
    "0xa9059cbb": "transfer",
    "0x23b872dd": "transferFrom",
    "0x095ea7b3": "approve",
    "0x38ed1739": "swapExactTokensForTokens",
    "0x8803dbee": "swapTokensForExactTokens",
    "0x7ff36ab5": "swapExactAVAXForTokens",
    "0x18cbafe5": "swapExactTokensForAVAX",
    "0xfb3bdb41": "swapAVAXForExactTokens",
    "0xe8e33700": "addLiquidity",
    "0xf305d719": "addLiquidityAVAX",
    "0xbaa2abde": "removeLiquidity",
    "0x02751cec": "removeLiquidityAVAX",
    "0xa694fc3a": "stake",
    "0x2e1a7d4d": "withdraw",
    "0x3d18b912": "getReward",
    "0xe9fad8ee": "exit",
    "0xdb006a75": "redeem",
    "0xa0712d68": "mint",
    "0x1249c58b": "mint",
    "0xd0e30db0": "deposit",
    "0x441a3e70": "withdraw",
}

# Transaction type mapping
METHOD_TO_TYPE = {
    "transfer": "transfer",
    "transferFrom": "transfer",
    "swapExactTokensForTokens": "swap",
    "swapTokensForExactTokens": "swap",
    "swapExactAVAXForTokens": "swap",
    "swapExactTokensForAVAX": "swap",
    "swapAVAXForExactTokens": "swap",
    "addLiquidity": "lp_add",
    "addLiquidityAVAX": "lp_add",
    "removeLiquidity": "lp_remove",
    "removeLiquidityAVAX": "lp_remove",
    "stake": "stake",
    "withdraw": "unstake",
    "getReward": "unstake",
    "exit": "unstake",
    "redeem": "unstake",
    "mint": "stake",
    "deposit": "stake",
}


def decode_method(input_data: str) -> tuple[str, str]:
    """
    Decode the method name and tx type from transaction input data.
    Returns (method_name, tx_type).
    """
    if not input_data or input_data == "0x" or len(input_data) < 10:
        return "transfer", "transfer"  # plain AVAX transfer

    sig = input_data[:10].lower()
    method = METHOD_SIGS.get(sig, "unknown")
    tx_type = METHOD_TO_TYPE.get(method, "unknown")

    return method, tx_type


def get_tx_value_avax(tx: dict) -> float:
    """Get the AVAX value from a transaction in human-readable units."""
    value_wei = tx.get("value", 0)
    if isinstance(value_wei, str):
        value_wei = int(value_wei, 16) if value_wei.startswith("0x") else int(value_wei)
    return float(Web3.from_wei(value_wei, "ether"))


async def get_avax_price_usd() -> float:
    """Get current AVAX/USD price from CoinGecko."""
    import httpx
    from shared.config import settings
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.COINGECKO_API_URL}/simple/price",
                params={"ids": "avalanche-2", "vs_currencies": "usd"},
            )
            resp.raise_for_status()
            return resp.json()["avalanche-2"]["usd"]
    except Exception:
        return 0.0


def decode_transaction(tx: dict, receipt: dict | None = None) -> dict:
    """
    Decode a raw transaction into a structured format.
    """
    input_data = tx.get("input", "0x")
    method, tx_type = decode_method(input_data)
    value_avax = get_tx_value_avax(tx)

    return {
        "tx_hash": tx.get("hash", "").hex() if isinstance(tx.get("hash"), bytes) else str(tx.get("hash", "")),
        "block_number": tx.get("blockNumber"),
        "from_address": tx.get("from", ""),
        "to_address": tx.get("to", ""),
        "value_avax": value_avax,
        "decoded_method": method,
        "tx_type": tx_type,
        "gas_used": receipt.get("gasUsed", 0) if receipt else tx.get("gas", 0),
        "gas_price_gwei": float(Web3.from_wei(tx.get("gasPrice", 0), "gwei")),
        "input_data": input_data[:200] if len(input_data) > 200 else input_data,
    }
