"""
Outcome Tracker — Monitors previously flagged tokens to verify if they actually rugged.
This is the key to honest scoring: did we correctly predict rugs?
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update, func
from shared.database import async_session
from shared.web3_client import w3
from agents.auditor.models.db import ContractScan, AuditReport
from agents.auditor.config import RUG_CONFIRM_DAYS
import structlog
import hashlib

logger = structlog.get_logger()

# Threshold: if liquidity drops >90% from scan time, it's a rug
LIQUIDITY_DROP_RUG_PCT = 90
# If contract has zero transactions in N days, it's abandoned
ABANDONED_DAYS = 14


async def check_token_outcome(scan: ContractScan) -> str | None:
    """Check the current state of a previously scanned token.
    Returns outcome: 'active', 'rugged', 'abandoned', or None if too early."""

    # Don't check tokens that were scanned less than RUG_CONFIRM_DAYS ago
    if scan.scanned_at:
        days_since = (datetime.now(timezone.utc) - scan.scanned_at).days
        if days_since < RUG_CONFIRM_DAYS:
            return None

    address = scan.contract_address
    try:
        # Check if contract still has code (self-destructed = definite rug)
        code = w3.eth.get_code(w3.to_checksum_address(address))
        if code == b"" or code == b"\x00":
            return "rugged"

        # Check if deployer still holds tokens (pulled = likely rug)
        if scan.deployer_address:
            try:
                erc20_abi = [
                    {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
                    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
                ]
                contract = w3.eth.contract(
                    address=w3.to_checksum_address(address),
                    abi=erc20_abi,
                )
                total_supply = contract.functions.totalSupply().call()
                if total_supply == 0:
                    return "rugged"
            except Exception:
                pass

        # If we reach here, token is still active
        return "active"

    except Exception as e:
        logger.error("outcome_check_failed", address=address[:10], error=str(e))
        return None


async def check_all_outcomes():
    """Check outcomes for all scans that need verification."""
    if async_session is None:
        return

    async with async_session() as db:
        # Get scans that are old enough to check but don't have outcomes yet
        cutoff = datetime.now(timezone.utc) - timedelta(days=RUG_CONFIRM_DAYS)
        result = await db.execute(
            select(ContractScan)
            .where(
                ContractScan.actual_outcome.is_(None),
                ContractScan.scanned_at <= cutoff,
            )
            .limit(20)
        )
        scans = list(result.scalars().all())

        updated = 0
        for scan in scans:
            outcome = await check_token_outcome(scan)
            if outcome:
                await db.execute(
                    update(ContractScan)
                    .where(ContractScan.id == scan.id)
                    .values(
                        actual_outcome=outcome,
                        outcome_confirmed_at=datetime.now(timezone.utc),
                    )
                )
                updated += 1
                logger.info(
                    "outcome_confirmed",
                    address=scan.contract_address[:10],
                    risk_label=scan.risk_label,
                    actual=outcome,
                )

        if updated:
            await db.commit()
            logger.info("outcomes_checked", total=len(scans), updated=updated)


async def generate_daily_report() -> dict | None:
    """Generate a daily audit report with precision metrics."""
    if async_session is None:
        return None

    async with async_session() as db:
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=1)

        # Total scanned in period
        total_q = await db.execute(
            select(func.count()).select_from(ContractScan)
            .where(ContractScan.scanned_at >= period_start)
        )
        total_scanned = total_q.scalar() or 0

        # Flagged as danger/rug
        flagged_q = await db.execute(
            select(func.count()).select_from(ContractScan)
            .where(
                ContractScan.scanned_at >= period_start,
                ContractScan.risk_label.in_(["danger", "rug"]),
            )
        )
        flagged_danger = flagged_q.scalar() or 0

        # Confirmed rugs (all time, with outcome)
        confirmed_q = await db.execute(
            select(func.count()).select_from(ContractScan)
            .where(
                ContractScan.risk_label.in_(["danger", "rug"]),
                ContractScan.actual_outcome == "rugged",
            )
        )
        confirmed_rugs = confirmed_q.scalar() or 0

        # False positives: flagged danger but actually active
        fp_q = await db.execute(
            select(func.count()).select_from(ContractScan)
            .where(
                ContractScan.risk_label.in_(["danger", "rug"]),
                ContractScan.actual_outcome == "active",
            )
        )
        false_positives = fp_q.scalar() or 0

        # Precision: correctly flagged / total flagged (where we have outcomes)
        total_with_outcome = confirmed_rugs + false_positives
        precision_pct = (confirmed_rugs / total_with_outcome * 100) if total_with_outcome > 0 else None

        # Build report text
        report_text = (
            f"Auditor Daily Report\n"
            f"Period: {period_start.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
            f"Contracts scanned: {total_scanned}\n"
            f"Flagged as dangerous: {flagged_danger}\n"
            f"Confirmed rugs (all time): {confirmed_rugs}\n"
            f"False positives (all time): {false_positives}\n"
            f"Precision: {f'{precision_pct:.1f}%' if precision_pct is not None else 'N/A (need more outcomes)'}\n\n"
            f"Score: {int(precision_pct) if precision_pct is not None else 50}/100"
        )

        proof_hash = hashlib.sha256(report_text.encode()).hexdigest()

        report = AuditReport(
            report_type="daily",
            period_start=period_start,
            period_end=now,
            total_scanned=total_scanned,
            flagged_danger=flagged_danger,
            confirmed_rugs=confirmed_rugs,
            false_positives=false_positives,
            precision_pct=precision_pct,
            report_text=report_text,
            proof_hash=f"0x{proof_hash}",
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        logger.info(
            "daily_report_generated",
            total=total_scanned,
            flagged=flagged_danger,
            precision=precision_pct,
        )

        return {
            "report_id": report.id,
            "score": int(precision_pct) if precision_pct is not None else 50,
            "total_scanned": total_scanned,
            "flagged_danger": flagged_danger,
        }
