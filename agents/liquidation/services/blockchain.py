"""
Blockchain Service — Submits on-chain proofs for the Liquidation Sentinel via AgentProofOracle.
"""
from sqlalchemy import select, update
from shared.database import async_session
from shared.contracts import proof_oracle
from shared.convergence import get_convergence_boost
from agents.liquidation.config import AGENT_ERC8004_ID
from agents.liquidation.models.db import LiquidationReport
import structlog

logger = structlog.get_logger()


async def submit_daily_proof(report_id: int) -> str | None:
    """Submit the daily liquidation report proof on-chain."""
    if async_session is None:
        return None

    async with async_session() as db:
        result = await db.execute(
            select(LiquidationReport).where(LiquidationReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if not report:
            logger.error("report_not_found", report_id=report_id)
            return None

        if report.proof_tx_hash:
            logger.warning("proof_already_submitted", report_id=report_id)
            return report.proof_tx_hash

        score = int(report.prediction_accuracy_pct) if report.prediction_accuracy_pct is not None else 50
        proof_hash_bytes = bytes.fromhex(report.proof_hash[2:]) if report.proof_hash else b"\x00" * 32
        proof_uri = f"liquidation://report/{report.id}"

        # Convergence boost
        boost = await get_convergence_boost("liquidation", None)
        adjusted_score = int(score * boost) if boost > 1.0 else score
        tag2 = "daily" if boost == 1.0 else f"daily-conv-{boost:.1f}x"

        try:
            tx_hash = proof_oracle.submit_proof(
                agent_id=AGENT_ERC8004_ID,
                score=adjusted_score * 100,
                score_decimals=2,
                tag1="liquidation",
                tag2=tag2,
                proof_uri=proof_uri,
                proof_hash=proof_hash_bytes,
            )
            logger.info("liquidation_proof_submitted", tx_hash=tx_hash, score=adjusted_score, report_id=report_id)

            await db.execute(
                update(LiquidationReport)
                .where(LiquidationReport.id == report_id)
                .values(proof_tx_hash=tx_hash, proof_uri=proof_uri)
            )
            await db.commit()
            return tx_hash
        except Exception as e:
            logger.error("proof_submission_failed", error=str(e), report_id=report_id)
            return None
