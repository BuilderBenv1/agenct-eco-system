"""
Blockchain Service — Submits on-chain proofs for the Yield Oracle via AgentProofOracle.
"""
from sqlalchemy import select, update
from shared.database import async_session
from shared.contracts import proof_oracle
from shared.convergence import get_convergence_boost
from agents.yield_oracle.config import AGENT_ERC8004_ID
from agents.yield_oracle.models.db import YieldReport
import structlog

logger = structlog.get_logger()


async def submit_daily_proof(report_id: int) -> str | None:
    """Submit the daily yield report proof on-chain."""
    if async_session is None:
        return None

    async with async_session() as db:
        result = await db.execute(
            select(YieldReport).where(YieldReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if not report:
            logger.error("report_not_found", report_id=report_id)
            return None

        if report.proof_tx_hash:
            logger.warning("proof_already_submitted", report_id=report_id)
            return report.proof_tx_hash

        # Score = alpha over benchmark + 50 baseline
        score = max(0, min(100, int(report.alpha_vs_avax + 50)))
        proof_hash_bytes = bytes.fromhex(report.proof_hash[2:]) if report.proof_hash else b"\x00" * 32
        proof_uri = f"yield://report/{report.id}"

        # Convergence boost
        boost = await get_convergence_boost("yield_oracle", None)
        adjusted_score = int(score * boost) if boost > 1.0 else score
        tag2 = "daily" if boost == 1.0 else f"daily-conv-{boost:.1f}x"

        try:
            tx_hash = proof_oracle.submit_proof(
                agent_id=AGENT_ERC8004_ID,
                score=adjusted_score * 100,
                score_decimals=2,
                tag1="yield",
                tag2=tag2,
                proof_uri=proof_uri,
                proof_hash=proof_hash_bytes,
            )
            logger.info("yield_proof_submitted", tx_hash=tx_hash, score=adjusted_score, report_id=report_id)

            await db.execute(
                update(YieldReport)
                .where(YieldReport.id == report_id)
                .values(proof_tx_hash=tx_hash, proof_uri=proof_uri)
            )
            await db.commit()
            return tx_hash
        except Exception as e:
            logger.error("proof_submission_failed", error=str(e), report_id=report_id)
            return None
