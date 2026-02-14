"""
DCA Blockchain Service — Submits on-chain proofs via AgentProofOracle.
"""
from sqlalchemy import select, update
from shared.database import async_session
from shared.contracts import proof_oracle
from agents.dca.config import DCA_ERC8004_ID
from agents.dca.models.db import DCAReport
import structlog

logger = structlog.get_logger()


async def submit_daily_proof(report_id: int) -> str | None:
    """Submit the daily DCA report proof on-chain."""
    if async_session is None or DCA_ERC8004_ID == 0:
        return None

    async with async_session() as db:
        result = await db.execute(
            select(DCAReport).where(DCAReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if not report or report.proof_tx_hash:
            return report.proof_tx_hash if report else None

        score = max(0, int(report.pnl_pct)) if report.pnl_pct else 50
        proof_hash_bytes = bytes.fromhex(report.proof_hash[2:]) if report.proof_hash else b"\x00" * 32
        proof_uri = f"dca://report/{report.id}"

        try:
            tx_hash = proof_oracle.submit_proof(
                agent_id=DCA_ERC8004_ID,
                score=score * 100,
                score_decimals=2,
                tag1="dca",
                tag2="daily",
                proof_uri=proof_uri,
                proof_hash=proof_hash_bytes,
            )
            logger.info("dca_proof_submitted", tx_hash=tx_hash, score=score)

            await db.execute(
                update(DCAReport)
                .where(DCAReport.id == report_id)
                .values(proof_tx_hash=tx_hash, proof_uri=proof_uri)
            )
            await db.commit()
            return tx_hash
        except Exception as e:
            logger.error("dca_proof_failed", error=str(e))
            return None
