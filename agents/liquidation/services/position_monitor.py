"""
Position Monitor — Reads lending positions from Benqi and Aave v3 on Avalanche
to detect positions approaching liquidation.
"""
import json
from datetime import datetime, timezone
from sqlalchemy import select, update
from shared.database import async_session
from shared.web3_client import w3
from agents.liquidation.models.db import LiquidationPosition
from agents.liquidation.config import (
    BENQI_COMPTROLLER, BENQI_QIAVAX, BENQI_QIUSDC, BENQI_QIETH, BENQI_QIBTC,
    AAVE_POOL, AAVE_POOL_DATA_PROVIDER,
    HEALTH_FACTOR_DANGER, RISK_LEVELS,
)
import structlog

logger = structlog.get_logger()

# Benqi Comptroller ABI (minimal for position queries)
COMPTROLLER_ABI = [
    {"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "getAccountLiquidity", "outputs": [{"name": "", "type": "uint256"}, {"name": "", "type": "uint256"}, {"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "getAllMarkets", "outputs": [{"name": "", "type": "address[]"}], "type": "function"},
]

# QiToken ABI (minimal)
QITOKEN_ABI = [
    {"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "getAccountSnapshot", "outputs": [{"name": "", "type": "uint256"}, {"name": "", "type": "uint256"}, {"name": "", "type": "uint256"}, {"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "borrowRatePerTimestamp", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "supplyRatePerTimestamp", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalBorrows", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "underlying", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "exchangeRateStored", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

# Aave v3 Pool ABI (minimal)
AAVE_POOL_ABI = [
    {"inputs": [{"name": "user", "type": "address"}], "name": "getUserAccountData", "outputs": [{"name": "totalCollateralBase", "type": "uint256"}, {"name": "totalDebtBase", "type": "uint256"}, {"name": "availableBorrowsBase", "type": "uint256"}, {"name": "currentLiquidationThreshold", "type": "uint256"}, {"name": "ltv", "type": "uint256"}, {"name": "healthFactor", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getReservesList", "outputs": [{"name": "", "type": "address[]"}], "stateMutability": "view", "type": "function"},
]


def get_risk_level(health_factor: float) -> str:
    """Map health factor to risk level."""
    for level, (low, high) in RISK_LEVELS.items():
        if low <= health_factor < high:
            return level
    if health_factor < 1.0:
        return "critical"
    return "low"


async def check_benqi_position(wallet_address: str) -> dict | None:
    """Check a wallet's Benqi lending position."""
    try:
        comptroller = w3.eth.contract(
            address=w3.to_checksum_address(BENQI_COMPTROLLER),
            abi=COMPTROLLER_ABI,
        )

        # getAccountLiquidity returns (error, liquidity, shortfall)
        error, liquidity, shortfall = comptroller.functions.getAccountLiquidity(
            w3.to_checksum_address(wallet_address)
        ).call()

        if error != 0:
            return None

        # liquidity in USD (18 decimals), shortfall means underwater
        liquidity_usd = liquidity / 1e18
        shortfall_usd = shortfall / 1e18

        if liquidity_usd == 0 and shortfall_usd == 0:
            return None  # No position

        # Estimate health factor from liquidity/shortfall
        # HF > 1 means healthy, HF < 1 means liquidatable
        if shortfall_usd > 0:
            health_factor = 0.5  # Underwater
        elif liquidity_usd > 0:
            # We need total borrow to compute real HF
            # Approximate: HF = 1 + (excess_liquidity / assumed_borrow)
            # For now, if there's excess liquidity, position is healthy
            health_factor = 2.0  # Healthy estimate
        else:
            health_factor = 1.0

        return {
            "protocol": "benqi",
            "wallet_address": wallet_address,
            "health_factor": health_factor,
            "collateral_amount_usd": liquidity_usd + shortfall_usd,
            "debt_amount_usd": shortfall_usd if shortfall_usd > 0 else 0,
            "risk_level": get_risk_level(health_factor),
        }

    except Exception as e:
        logger.error("benqi_check_failed", wallet=wallet_address[:10], error=str(e))
        return None


async def check_aave_position(wallet_address: str) -> dict | None:
    """Check a wallet's Aave v3 lending position."""
    try:
        pool = w3.eth.contract(
            address=w3.to_checksum_address(AAVE_POOL),
            abi=AAVE_POOL_ABI,
        )

        result = pool.functions.getUserAccountData(
            w3.to_checksum_address(wallet_address)
        ).call()

        total_collateral = result[0] / 1e8   # Aave uses 8 decimals for USD
        total_debt = result[1] / 1e8
        available_borrows = result[2] / 1e8
        liq_threshold = result[3] / 1e4      # Basis points
        ltv = result[4] / 1e4
        health_factor = result[5] / 1e18

        if total_collateral == 0 and total_debt == 0:
            return None  # No position

        # Distance to liquidation: how much collateral can drop before HF = 1
        distance_pct = ((health_factor - 1.0) / health_factor * 100) if health_factor > 0 else 0

        return {
            "protocol": "aave_v3",
            "wallet_address": wallet_address,
            "health_factor": health_factor,
            "collateral_amount_usd": total_collateral,
            "debt_amount_usd": total_debt,
            "ltv": ltv,
            "liquidation_threshold": liq_threshold,
            "distance_to_liquidation_pct": max(0, distance_pct),
            "risk_level": get_risk_level(health_factor),
        }

    except Exception as e:
        logger.error("aave_check_failed", wallet=wallet_address[:10], error=str(e))
        return None


async def get_whale_wallets() -> list[str]:
    """Get wallet addresses from whale_wallets table to cross-check lending positions."""
    if async_session is None:
        return []

    try:
        async with async_session() as db:
            from sqlalchemy import text
            result = await db.execute(
                text("SELECT address FROM whale_wallets WHERE is_active = true LIMIT 50")
            )
            return [row[0] for row in result.fetchall()]
    except Exception:
        return []


async def save_position(position_data: dict) -> LiquidationPosition | None:
    """Save or update a lending position."""
    if async_session is None:
        return None

    async with async_session() as db:
        # Check for existing position for this wallet+protocol
        existing = await db.execute(
            select(LiquidationPosition).where(
                LiquidationPosition.wallet_address == position_data["wallet_address"],
                LiquidationPosition.protocol == position_data["protocol"],
                LiquidationPosition.is_active == True,
            )
        )
        pos = existing.scalar_one_or_none()

        if pos:
            # Update existing position
            await db.execute(
                update(LiquidationPosition)
                .where(LiquidationPosition.id == pos.id)
                .values(
                    health_factor=position_data["health_factor"],
                    risk_level=position_data["risk_level"],
                    collateral_amount_usd=position_data.get("collateral_amount_usd"),
                    debt_amount_usd=position_data.get("debt_amount_usd"),
                    ltv=position_data.get("ltv"),
                    liquidation_threshold=position_data.get("liquidation_threshold"),
                    distance_to_liquidation_pct=position_data.get("distance_to_liquidation_pct"),
                )
            )
            await db.commit()
            return pos
        else:
            # Create new position
            pos = LiquidationPosition(
                protocol=position_data["protocol"],
                wallet_address=position_data["wallet_address"],
                health_factor=position_data["health_factor"],
                risk_level=position_data["risk_level"],
                collateral_amount_usd=position_data.get("collateral_amount_usd"),
                collateral_token=position_data.get("collateral_token"),
                debt_amount_usd=position_data.get("debt_amount_usd"),
                debt_token=position_data.get("debt_token"),
                ltv=position_data.get("ltv"),
                liquidation_threshold=position_data.get("liquidation_threshold"),
                distance_to_liquidation_pct=position_data.get("distance_to_liquidation_pct"),
            )
            db.add(pos)
            await db.commit()
            await db.refresh(pos)
            return pos


async def scan_all_positions():
    """Scan all tracked whale wallets for lending positions on Benqi and Aave."""
    wallets = await get_whale_wallets()
    if not wallets:
        logger.debug("no_wallets_to_scan")
        return

    found = 0
    at_risk = 0

    for wallet in wallets:
        # Check both protocols
        for check_fn in [check_benqi_position, check_aave_position]:
            position_data = await check_fn(wallet)
            if position_data:
                pos = await save_position(position_data)
                if pos:
                    found += 1
                    if position_data["risk_level"] in ("high", "critical"):
                        at_risk += 1

    if found:
        logger.info("positions_scanned", wallets=len(wallets), found=found, at_risk=at_risk)
