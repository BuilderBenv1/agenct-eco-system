"""
Blockchain Service — Submits on-chain proofs for the Whale agent via AgentProofOracle.
"""
from sqlalchemy import select, update
from shared.database import async_session
from shared.contracts import proof_oracle
from shared.convergence import get_convergence_boost
from agents.whale.config import AGENT_ERC8004_ID
from agents.whale.models.db import WhaleReport
import structlog

logger = structlog.get_logger()


async def submit_daily_proof(report_id: int) -> str | None:
    """Submit the daily whale report proof on-chain."""
    if async_session is None:
        return None

    async with async_session() as db:
        result = await db.execute(
            select(WhaleReport).where(WhaleReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if not report:
            logger.error("report_not_found", report_id=report_id)
            return None

        if report.proof_tx_hash:
            logger.warning("proof_already_submitted", report_id=report_id)
            return report.proof_tx_hash

        score = _extract_score(report.report_text or "")
        proof_hash_bytes = bytes.fromhex(report.proof_hash[2:]) if report.proof_hash else b"\x00" * 32
        proof_uri = f"whale://report/{report.id}"

        # Check for convergence boost on top tokens
        top_token = _extract_top_token(report)
        boost = await get_convergence_boost("whale", top_token) if top_token else 1.0
        adjusted_score = int(score * boost)
        tag2 = "daily" if boost == 1.0 else f"daily-conv-{boost:.1f}x"

        try:
            tx_hash = proof_oracle.submit_proof(
                agent_id=AGENT_ERC8004_ID,
                score=adjusted_score * 100,
                score_decimals=2,
                tag1="whale",
                tag2=tag2,
                proof_uri=proof_uri,
                proof_hash=proof_hash_bytes,
            )
            logger.info("whale_proof_submitted", tx_hash=tx_hash, score=adjusted_score, boost=boost, report_id=report_id)

            await db.execute(
                update(WhaleReport)
                .where(WhaleReport.id == report_id)
                .values(proof_tx_hash=tx_hash, proof_uri=proof_uri)
            )
            await db.commit()
            return tx_hash
        except Exception as e:
            logger.error("proof_submission_failed", error=str(e), report_id=report_id)
            return None


def _extract_score(text: str) -> int:
    for line in reversed(text.split("\n")):
        line = line.strip()
        if line.lower().startswith("score:"):
            parts = line.split(":")[-1].strip().split("/")
            try:
                return int(parts[0].strip())
            except (ValueError, IndexError):
                pass
    return 50


def _extract_top_token(report: WhaleReport) -> str | None:
    """Extract the most-mentioned token from the report for convergence lookup."""
    if not report.top_movers:
        return None
    movers = report.top_movers if isinstance(report.top_movers, list) else []
    if movers and isinstance(movers[0], dict):
        return movers[0].get("label", "").upper() or None
    return None
