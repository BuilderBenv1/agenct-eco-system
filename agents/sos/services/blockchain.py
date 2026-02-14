"""
SOS Blockchain Service — Submits on-chain proofs via AgentProofOracle.
"""
from sqlalchemy import select, update
from shared.database import async_session
from shared.contracts import proof_oracle
from agents.sos.config import SOS_ERC8004_ID
from agents.sos.models.db import SOSReport
import structlog

logger = structlog.get_logger()


async def submit_daily_proof(report_id: int) -> str | None:
    if async_session is None or SOS_ERC8004_ID == 0:
        return None

    async with async_session() as db:
        result = await db.execute(select(SOSReport).where(SOSReport.id == report_id))
        report = result.scalar_one_or_none()
        if not report or report.proof_tx_hash:
            return report.proof_tx_hash if report else None

        score = max(0, min(100, int(report.total_value_saved / max(report.active_configs, 1))))
        proof_hash_bytes = bytes.fromhex(report.proof_hash[2:]) if report.proof_hash else b"\x00" * 32

        try:
            tx_hash = proof_oracle.submit_proof(
                agent_id=SOS_ERC8004_ID,
                score=score * 100,
                score_decimals=2,
                tag1="sos",
                tag2="daily",
                proof_uri=f"sos://report/{report.id}",
                proof_hash=proof_hash_bytes,
            )
            await db.execute(
                update(SOSReport).where(SOSReport.id == report_id)
                .values(proof_tx_hash=tx_hash, proof_uri=f"sos://report/{report.id}")
            )
            await db.commit()
            return tx_hash
        except Exception as e:
            logger.error("sos_proof_failed", error=str(e))
            return None
