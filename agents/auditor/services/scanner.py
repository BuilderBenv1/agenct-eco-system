"""
Contract Scanner — Monitors new token deployments on Avalanche C-Chain
and gathers on-chain data for rug analysis.
"""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from shared.database import async_session
from shared.web3_client import w3
from shared.config import settings
from agents.auditor.models.db import ContractScan
from agents.auditor.config import (
    SCAN_BLOCKS_PER_POLL,
    NEW_TOKEN_MIN_LIQUIDITY_USD,
    RISK_LABELS,
)
import structlog

logger = structlog.get_logger()

# ERC-20 minimal ABI for basic checks
ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "owner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

# Known rug-pull bytecode signatures (partial matches)
RUG_BYTECODE_SIGS = [
    "a9059cbb",  # transfer (normal, but check context)
    "dd62ed3e",  # allowance
    "095ea7b3",  # approve
    "70a08231",  # balanceOf
]

# Dangerous function selectors that indicate potential rug mechanics
DANGEROUS_SELECTORS = {
    "8da5cb5b": "owner()",
    "715018a6": "renounceOwnership()",
    "f2fde38b": "transferOwnership(address)",
    "40c10f19": "mint(address,uint256)",
    "42966c68": "burn(uint256)",
    "e47d6060": "setMaxTxAmount(uint256)",
    "c0246668": "excludeFromFee(address,bool)",
    "ec28438a": "setMaxTxPercent(uint256)",
    "49bd5a5e": "uniswapV2Pair()",
    "1694505e": "setRouterAddress(address)",
    "3b124fe7": "taxFee()",
    "a457c2d7": "decreaseAllowance(address,uint256)",
    "dd467064": "lock(uint256)",
    "a69df4b5": "unlock()",
    "e4440a86": "setFeeAddress(address)",
    "8ee88c53": "setTaxFeePercent(uint256)",
    "f0f44260": "setTreasuryWallet(address)",
}


def get_contract_bytecode(address: str) -> str:
    """Fetch deployed bytecode for a contract address."""
    try:
        code = w3.eth.get_code(w3.to_checksum_address(address))
        return code.hex()
    except Exception as e:
        logger.error("bytecode_fetch_failed", address=address, error=str(e))
        return ""


def analyze_bytecode(bytecode: str) -> dict:
    """Analyze bytecode for dangerous function selectors."""
    found_dangerous = []
    for selector, name in DANGEROUS_SELECTORS.items():
        if selector in bytecode:
            found_dangerous.append(name)

    has_owner = "8da5cb5b" in bytecode
    has_mint = "40c10f19" in bytecode
    has_tax_setter = any(s in bytecode for s in ["8ee88c53", "e4440a86", "f0f44260"])
    has_max_tx = any(s in bytecode for s in ["e47d6060", "ec28438a"])
    has_blacklist = "c0246668" in bytecode

    return {
        "dangerous_functions": found_dangerous,
        "has_owner_control": has_owner,
        "has_mint": has_mint,
        "has_tax_setter": has_tax_setter,
        "has_max_tx_limit": has_max_tx,
        "has_blacklist": has_blacklist,
        "bytecode_length": len(bytecode),
    }


async def get_token_info(address: str) -> dict:
    """Fetch basic ERC-20 token info from the contract."""
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(address),
            abi=ERC20_ABI,
        )
        name = symbol = ""
        total_supply = 0
        owner = None

        try:
            name = contract.functions.name().call()
        except Exception:
            pass
        try:
            symbol = contract.functions.symbol().call()
        except Exception:
            pass
        try:
            total_supply = contract.functions.totalSupply().call()
        except Exception:
            pass
        try:
            owner = contract.functions.owner().call()
        except Exception:
            pass

        return {
            "name": name,
            "symbol": symbol,
            "total_supply": total_supply,
            "owner": owner,
        }
    except Exception as e:
        logger.error("token_info_failed", address=address, error=str(e))
        return {"name": "", "symbol": "", "total_supply": 0, "owner": None}


async def get_deployer_info(address: str) -> dict:
    """Find the deployer of a contract by checking creation tx."""
    try:
        # Check first few transactions to the contract
        code = w3.eth.get_code(w3.to_checksum_address(address))
        if code == b"" or code == b"\x00":
            return {"deployer": None, "deployment_block": None, "deployment_tx": None}

        # We can't easily get deployer from RPC alone without trace calls.
        # In production, use Snowtrace API or similar.
        return {
            "deployer": None,
            "deployment_block": None,
            "deployment_tx": None,
        }
    except Exception as e:
        logger.error("deployer_info_failed", address=address, error=str(e))
        return {"deployer": None, "deployment_block": None, "deployment_tx": None}


async def get_holder_concentration(address: str, token_info: dict) -> dict:
    """Estimate holder concentration. In production, use Snowtrace/Covalent API."""
    total_supply = token_info.get("total_supply", 0)
    owner = token_info.get("owner")
    owner_balance = 0

    if owner and total_supply > 0:
        try:
            contract = w3.eth.contract(
                address=w3.to_checksum_address(address),
                abi=ERC20_ABI,
            )
            owner_balance = contract.functions.balanceOf(
                w3.to_checksum_address(owner)
            ).call()
        except Exception:
            pass

    owner_pct = (owner_balance / total_supply * 100) if total_supply > 0 else 0.0

    return {
        "owner_balance": owner_balance,
        "owner_pct": owner_pct,
        "total_supply": total_supply,
    }


def compute_risk_scores(bytecode_analysis: dict, holder_data: dict) -> dict:
    """Compute preliminary risk scores from on-chain data.
    These are initial scores that get refined by Claude analysis."""

    # Honeypot score
    honeypot = 0
    if bytecode_analysis.get("has_blacklist"):
        honeypot += 30
    if bytecode_analysis.get("has_max_tx_limit"):
        honeypot += 20
    if bytecode_analysis.get("bytecode_length", 0) < 500:
        honeypot += 15  # Suspiciously small contract

    # Ownership concentration
    ownership = 0
    owner_pct = holder_data.get("owner_pct", 0)
    if owner_pct > 80:
        ownership = 90
    elif owner_pct > 50:
        ownership = 70
    elif owner_pct > 30:
        ownership = 50
    elif owner_pct > 10:
        ownership = 25

    # Liquidity lock (start high, reduce with evidence of lock)
    liquidity = 70  # Default: assume no lock until proven otherwise

    # Code similarity to rug patterns
    code_similarity = 0
    dangerous_count = len(bytecode_analysis.get("dangerous_functions", []))
    if dangerous_count >= 8:
        code_similarity = 80
    elif dangerous_count >= 5:
        code_similarity = 60
    elif dangerous_count >= 3:
        code_similarity = 40
    elif dangerous_count >= 1:
        code_similarity = 20

    # Tax manipulation
    tax = 0
    if bytecode_analysis.get("has_tax_setter"):
        tax += 50
    if bytecode_analysis.get("has_owner_control") and bytecode_analysis.get("has_tax_setter"):
        tax += 20  # Owner can change taxes = very dangerous

    # Overall risk = weighted average
    overall = int(
        honeypot * 0.25 +
        ownership * 0.25 +
        liquidity * 0.20 +
        code_similarity * 0.15 +
        tax * 0.15
    )

    return {
        "honeypot_score": min(honeypot, 100),
        "ownership_concentration_score": min(ownership, 100),
        "liquidity_lock_score": min(liquidity, 100),
        "code_similarity_rug_score": min(code_similarity, 100),
        "tax_manipulation_score": min(tax, 100),
        "overall_risk_score": min(overall, 100),
    }


def get_risk_label(score: int) -> str:
    """Convert numeric risk score to label."""
    for label, (low, high) in RISK_LABELS.items():
        if low <= score <= high:
            return label
    return "rug" if score > 75 else "safe"


async def scan_contract(contract_address: str) -> dict | None:
    """Full scan pipeline for a single contract address.
    Returns scan result dict or None on failure."""
    address = contract_address.strip()
    if not w3.is_address(address):
        logger.error("invalid_address", address=address)
        return None

    address = w3.to_checksum_address(address)

    # Check if already scanned
    if async_session is None:
        return None

    async with async_session() as db:
        existing = await db.execute(
            select(ContractScan).where(ContractScan.contract_address == address)
        )
        if existing.scalar_one_or_none():
            logger.info("already_scanned", address=address)
            return None

    # Gather data
    bytecode = get_contract_bytecode(address)
    if not bytecode or bytecode == "0x":
        logger.warning("no_bytecode", address=address)
        return None

    bytecode_analysis = analyze_bytecode(bytecode)
    token_info = await get_token_info(address)
    deployer_info = await get_deployer_info(address)
    holder_data = await get_holder_concentration(address, token_info)

    # Compute initial risk scores
    scores = compute_risk_scores(bytecode_analysis, holder_data)
    risk_label = get_risk_label(scores["overall_risk_score"])

    # Build red flags list
    red_flags = []
    if bytecode_analysis.get("has_mint"):
        red_flags.append("Mint function accessible")
    if bytecode_analysis.get("has_blacklist"):
        red_flags.append("Blacklist/whitelist mechanism")
    if bytecode_analysis.get("has_tax_setter"):
        red_flags.append("Adjustable tax fees")
    if bytecode_analysis.get("has_max_tx_limit"):
        red_flags.append("Max transaction limit (potential sell trap)")
    if holder_data.get("owner_pct", 0) > 50:
        red_flags.append(f"Owner holds {holder_data['owner_pct']:.1f}% of supply")
    if holder_data.get("owner_pct", 0) > 80:
        red_flags.append("Extreme ownership concentration (>80%)")

    scan_data = {
        "contract_address": address,
        "token_symbol": token_info.get("symbol") or None,
        "token_name": token_info.get("name") or None,
        "deployer_address": deployer_info.get("deployer") or token_info.get("owner"),
        "deployment_tx": deployer_info.get("deployment_tx"),
        "deployment_block": deployer_info.get("deployment_block"),
        "honeypot_score": scores["honeypot_score"],
        "ownership_concentration_score": scores["ownership_concentration_score"],
        "liquidity_lock_score": scores["liquidity_lock_score"],
        "code_similarity_rug_score": scores["code_similarity_rug_score"],
        "tax_manipulation_score": scores["tax_manipulation_score"],
        "overall_risk_score": scores["overall_risk_score"],
        "risk_label": risk_label,
        "red_flags": red_flags,
        "top_holder_pct": holder_data.get("owner_pct"),
        "holder_count": None,  # Requires indexer API
        "bytecode_analysis": bytecode_analysis,
        "token_info": token_info,
    }

    logger.info(
        "contract_scanned",
        address=address[:10],
        risk_label=risk_label,
        score=scores["overall_risk_score"],
        flags=len(red_flags),
    )

    return scan_data


async def save_scan(scan_data: dict) -> ContractScan | None:
    """Persist a scan result to the database."""
    if async_session is None:
        return None

    async with async_session() as db:
        scan = ContractScan(
            contract_address=scan_data["contract_address"],
            token_symbol=scan_data.get("token_symbol"),
            token_name=scan_data.get("token_name"),
            deployer_address=scan_data.get("deployer_address"),
            deployment_tx=scan_data.get("deployment_tx"),
            deployment_block=scan_data.get("deployment_block"),
            honeypot_score=scan_data["honeypot_score"],
            ownership_concentration_score=scan_data["ownership_concentration_score"],
            liquidity_lock_score=scan_data["liquidity_lock_score"],
            code_similarity_rug_score=scan_data["code_similarity_rug_score"],
            tax_manipulation_score=scan_data["tax_manipulation_score"],
            overall_risk_score=scan_data["overall_risk_score"],
            risk_label=scan_data["risk_label"],
            red_flags=scan_data["red_flags"],
            top_holder_pct=scan_data.get("top_holder_pct"),
            holder_count=scan_data.get("holder_count"),
        )
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        return scan


async def scan_and_save(contract_address: str) -> ContractScan | None:
    """Scan a contract and save results. Full pipeline entry point."""
    scan_data = await scan_contract(contract_address)
    if not scan_data:
        return None
    return await save_scan(scan_data)
