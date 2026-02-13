"""
Blockchain Service — Submits on-chain proofs for the Auditor agent via AgentProofOracle.
"""
from sqlalchemy import select, update
from shared.database import async_session
from shared.contracts import proof_oracle
from shared.convergence import get_convergence_boost
from agents.auditor.config import AGENT_ERC8004_ID
from agents.auditor.models.db import AuditReport
import structlog

logger = structlog.get_logger()


async def submit_daily_proof(report_id: int) -> str | None:
    """Submit the daily audit report proof on-chain."""
    if async_session is None:
        return None

    async with async_session() as db:
        result = await db.execute(
            select(AuditReport).where(AuditReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if not report:
            logger.error("report_not_found", report_id=report_id)
            return None

        if report.proof_tx_hash:
            logger.warning("proof_already_submitted", report_id=report_id)
            return report.proof_tx_hash

        score = _extract_score(report)
        proof_hash_bytes = bytes.fromhex(report.proof_hash[2:]) if report.proof_hash else b"\x00" * 32
        proof_uri = f"auditor://report/{report.id}"

        # Check for convergence boost
        # The auditor's "top token" is the most-flagged token
        top_token = _extract_top_flagged_token()
        boost = await get_convergence_boost("auditor", top_token) if top_token else 1.0
        adjusted_score = int(score * boost)
        tag2 = "daily" if boost == 1.0 else f"daily-conv-{boost:.1f}x"

        try:
            tx_hash = proof_oracle.submit_proof(
                agent_id=AGENT_ERC8004_ID,
                score=adjusted_score * 100,
                score_decimals=2,
                tag1="audit",
                tag2=tag2,
                proof_uri=proof_uri,
                proof_hash=proof_hash_bytes,
            )
            logger.info("audit_proof_submitted", tx_hash=tx_hash, score=adjusted_score, boost=boost, report_id=report_id)

            await db.execute(
                update(AuditReport)
                .where(AuditReport.id == report_id)
                .values(proof_tx_hash=tx_hash, proof_uri=proof_uri)
            )
            await db.commit()
            return tx_hash
        except Exception as e:
            logger.error("proof_submission_failed", error=str(e), report_id=report_id)
            return None


def _extract_score(report: AuditReport) -> int:
    """Extract the score from the report. Score = precision percentage."""
    if report.precision_pct is not None:
        return int(report.precision_pct)
    # Default: 50 when we don't have enough outcome data yet
    return 50


def _extract_top_flagged_token() -> str | None:
    """Get the most recently flagged dangerous token for convergence lookup.
    This is a sync helper that queries the last flagged scan."""
    # We use a blocking approach here since this is called during proof submission
    # In production, cache the last flagged token
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't await in sync context, return None
            return None
    except RuntimeError:
        return None
    return None
