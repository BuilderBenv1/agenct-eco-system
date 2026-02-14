"""
Shared DEX integration — Trader Joe V2 on Avalanche.

Provides price queries, swap execution, and pair lookups used by
the DCA, Grid, SOS, and Sniper bots.
"""
import json
import time
from pathlib import Path
from web3 import Web3
from eth_account import Account
from shared.web3_client import w3
from shared.config import settings
import structlog

logger = structlog.get_logger()

ABI_DIR = Path(__file__).parent / "abis"

# Trader Joe V2 addresses on Avalanche C-Chain
JOE_ROUTER = "0x60aE616a2155Ee3d9A68541Ba4544862310933d4"
JOE_FACTORY = "0x9Ad6C38BE94206cA50bb0d90783181834C78e05e"
WAVAX = "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7"

# Common Avalanche tokens
USDC = "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E"
USDT = "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7"
WETH_E = "0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB"
BTC_B = "0x152b9d0FdC40C096DE345fFCc9B86F0d5a9F8731"
JOE = "0x6e84a6216eA6dACC71eE8E6b0a5B7322EEbC0fDd"
GMX = "0x62edc0692BD897D2295872a9FFCac5425011c661"


def _load_abi(name: str) -> list:
    with open(ABI_DIR / f"{name}.json") as f:
        return json.load(f)


# Contract instances
router_contract = w3.eth.contract(
    address=Web3.to_checksum_address(JOE_ROUTER),
    abi=_load_abi("JoeRouter"),
)

factory_contract = w3.eth.contract(
    address=Web3.to_checksum_address(JOE_FACTORY),
    abi=_load_abi("JoeFactory"),
)


def get_erc20_contract(token_address: str):
    return w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=_load_abi("ERC20"),
    )


def get_token_decimals(token_address: str) -> int:
    try:
        return get_erc20_contract(token_address).functions.decimals().call()
    except Exception:
        return 18


def estimate_output(from_token: str, to_token: str, amount_in: int) -> int:
    """Estimate output amount for a swap via WAVAX if needed."""
    from_addr = Web3.to_checksum_address(from_token)
    to_addr = Web3.to_checksum_address(to_token)
    wavax = Web3.to_checksum_address(WAVAX)

    if from_addr == wavax or to_addr == wavax:
        path = [from_addr, to_addr]
    else:
        path = [from_addr, wavax, to_addr]

    try:
        amounts = router_contract.functions.getAmountsOut(amount_in, path).call()
        return amounts[-1]
    except Exception as e:
        logger.error("estimate_output_failed", error=str(e))
        return 0


def get_pair_address(token_a: str, token_b: str) -> str | None:
    """Get the pair address for two tokens."""
    try:
        pair = factory_contract.functions.getPair(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
        ).call()
        return pair if pair != "0x0000000000000000000000000000000000000000" else None
    except Exception:
        return None


def approve_token(token_address: str, spender: str, amount: int, private_key: str) -> str:
    """Approve a token for spending by the router."""
    token = get_erc20_contract(token_address)
    account = Account.from_key(private_key)

    tx = token.functions.approve(
        Web3.to_checksum_address(spender), amount
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": settings.CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def swap_exact_avax_for_tokens(
    to_token: str,
    avax_amount_wei: int,
    slippage_pct: float,
    private_key: str,
) -> str:
    """Swap AVAX for tokens."""
    account = Account.from_key(private_key)
    wavax = Web3.to_checksum_address(WAVAX)
    to_addr = Web3.to_checksum_address(to_token)
    path = [wavax, to_addr]

    amounts_out = router_contract.functions.getAmountsOut(avax_amount_wei, path).call()
    min_out = int(amounts_out[-1] * (1 - slippage_pct / 100))
    deadline = int(time.time()) + 300

    tx = router_contract.functions.swapExactAVAXForTokens(
        min_out, path, account.address, deadline
    ).build_transaction({
        "from": account.address,
        "value": avax_amount_wei,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 300_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": settings.CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    logger.info("swap_avax_for_tokens", to=to_token, amount_wei=avax_amount_wei, tx=tx_hash.hex())
    return tx_hash.hex()


def swap_exact_tokens_for_avax(
    from_token: str,
    amount_in: int,
    slippage_pct: float,
    private_key: str,
) -> str:
    """Swap tokens for AVAX."""
    account = Account.from_key(private_key)
    from_addr = Web3.to_checksum_address(from_token)
    wavax = Web3.to_checksum_address(WAVAX)
    path = [from_addr, wavax]

    # Ensure approval
    token = get_erc20_contract(from_token)
    allowance = token.functions.allowance(account.address, Web3.to_checksum_address(JOE_ROUTER)).call()
    if allowance < amount_in:
        approve_tx = approve_token(from_token, JOE_ROUTER, 2**256 - 1, private_key)
        w3.eth.wait_for_transaction_receipt(bytes.fromhex(approve_tx), timeout=60)

    amounts_out = router_contract.functions.getAmountsOut(amount_in, path).call()
    min_out = int(amounts_out[-1] * (1 - slippage_pct / 100))
    deadline = int(time.time()) + 300

    tx = router_contract.functions.swapExactTokensForAVAX(
        amount_in, min_out, path, account.address, deadline
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 300_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": settings.CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    logger.info("swap_tokens_for_avax", from_token=from_token, amount=amount_in, tx=tx_hash.hex())
    return tx_hash.hex()


def swap_exact_tokens(
    from_token: str,
    to_token: str,
    amount_in: int,
    slippage_pct: float,
    private_key: str,
) -> str:
    """Swap tokens for tokens via WAVAX."""
    account = Account.from_key(private_key)
    from_addr = Web3.to_checksum_address(from_token)
    to_addr = Web3.to_checksum_address(to_token)
    wavax = Web3.to_checksum_address(WAVAX)

    # Route through WAVAX
    if from_addr == wavax:
        path = [wavax, to_addr]
    elif to_addr == wavax:
        path = [from_addr, wavax]
    else:
        path = [from_addr, wavax, to_addr]

    # Ensure approval
    token = get_erc20_contract(from_token)
    allowance = token.functions.allowance(account.address, Web3.to_checksum_address(JOE_ROUTER)).call()
    if allowance < amount_in:
        approve_tx = approve_token(from_token, JOE_ROUTER, 2**256 - 1, private_key)
        w3.eth.wait_for_transaction_receipt(bytes.fromhex(approve_tx), timeout=60)

    amounts_out = router_contract.functions.getAmountsOut(amount_in, path).call()
    min_out = int(amounts_out[-1] * (1 - slippage_pct / 100))
    deadline = int(time.time()) + 300

    tx = router_contract.functions.swapExactTokensForTokens(
        amount_in, min_out, path, account.address, deadline
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 350_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": settings.CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    logger.info("swap_tokens", from_token=from_token, to_token=to_token, amount=amount_in, tx=tx_hash.hex())
    return tx_hash.hex()


def get_token_balance(token_address: str, wallet_address: str) -> int:
    """Get token balance for a wallet."""
    token = get_erc20_contract(token_address)
    return token.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()


def get_avax_balance(wallet_address: str) -> int:
    """Get AVAX balance for a wallet."""
    return w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
