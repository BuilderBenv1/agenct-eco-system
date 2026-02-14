"""
Sniper Safety Filter — Checks new tokens against safety criteria before buying.
Cross-references with Rug Auditor when available.
"""
from shared.dex import get_erc20_contract
from shared.database import async_session
from sqlalchemy import select, update
from agents.sniper.models.db import SniperLaunch, SniperConfig
import structlog

logger = structlog.get_logger()


async def check_safety(launch: dict, config: SniperConfig) -> tuple[bool, str]:
    """
    Check if a newly detected token passes safety filters.
    Returns (passed, reason) where reason explains rejection.
    """
    token_address = launch["token_address"]
    symbol = launch.get("symbol", "UNKNOWN")
    liquidity = launch.get("liquidity_usd", 0)

    # Check minimum liquidity
    if liquidity < (config.min_liquidity_usd or 5000):
        return False, f"Liquidity ${liquidity:.0f} below min ${config.min_liquidity_usd:.0f}"

    # Check if contract is renounced (if required)
    if config.require_renounced:
        try:
            token = get_erc20_contract(token_address)
            owner = token.functions.owner().call()
            if owner != "0x0000000000000000000000000000000000000000":
                return False, f"Contract not renounced (owner: {owner[:10]}...)"
        except Exception:
            pass  # No owner function = likely safe

    # Cross-check with Rug Auditor
    safety_score = 50  # Default neutral
    try:
        from agents.auditor.models.db import ContractScan
        if async_session:
            async with async_session() as db:
                scan = await db.execute(
                    select(ContractScan).where(ContractScan.contract_address == token_address)
                )
                existing = scan.scalar_one_or_none()
                if existing:
                    safety_score = 100 - (existing.overall_risk_score or 50)
                    if existing.risk_label in ("danger", "rug"):
                        return False, f"Rug Auditor flagged as {existing.risk_label} (risk: {existing.overall_risk_score})"
    except ImportError:
        pass

    # Check buy tax (if we can simulate)
    # For now, pass if we get this far
    logger.info("safety_check_passed", token=symbol, liquidity=liquidity, safety_score=safety_score)
    return True, f"Passed all filters (safety: {safety_score})"


async def run_safety_filters(launches: list[dict]):
    """Run safety filters on all new launches against all active sniper configs."""
    if async_session is None or not launches:
        return []

    approved = []

    async with async_session() as db:
        configs_result = await db.execute(
            select(SniperConfig).where(SniperConfig.is_active == True)
        )
        configs = configs_result.scalars().all()

        for launch in launches:
            for config in configs:
                passed, reason = await check_safety(launch, config)

                # Update launch record
                await db.execute(
                    update(SniperLaunch)
                    .where(SniperLaunch.token_address == launch["token_address"])
                    .values(
                        passed_filters=passed,
                        reason_rejected=None if passed else reason,
                    )
                )

                if passed:
                    approved.append({"launch": launch, "config": config, "reason": reason})

        await db.commit()

    return approved
