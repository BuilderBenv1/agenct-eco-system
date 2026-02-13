"""
Blockchain Service — Submits on-chain proofs for the Tipster agent via AgentProofOracle.
"""
import hashlib
from sqlalchemy import select, update
from shared.database import async_session
from shared.contracts import proof_oracle
from shared.convergence import get_convergence_boost
from agents.tipster.config import AGENT_ERC8004_ID, AGENT_NAME
from agents.tipster.models.db import TipsterReport
import structlog

logger = structlog.get_logger()


async def submit_weekly_proof(report_id: int) -> str | None:
    """
    Submit the weekly report proof on-chain.
    Returns the transaction hash or None on failure.
    """
    if async_session is None:
        logger.error("database_not_configured")
        return None

    async with async_session() as db:
        result = await db.execute(
            select(TipsterReport).where(TipsterReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if not report:
            logger.error("report_not_found", report_id=report_id)
            return None

        if report.proof_tx_hash:
            logger.warning("proof_already_submitted", report_id=report_id)
            return report.proof_tx_hash

        # Parse score from report text
        score = _extract_score_from_report(report)
        proof_hash_bytes = bytes.fromhex(report.proof_hash[2:]) if report.proof_hash else b"\x00" * 32

        # Construct proof URI (could be IPFS in production)
        proof_uri = f"tipster://report/{report.id}"

        # Check for convergence boost on top token
        top_token = _extract_top_token(report)
        boost = await get_convergence_boost("tipster", top_token) if top_token else 1.0
        adjusted_score = int(score * boost)
        tag2 = "weekly" if boost == 1.0 else f"weekly-conv-{boost:.1f}x"

        try:
            tx_hash = proof_oracle.submit_proof(
                agent_id=AGENT_ERC8004_ID,
                score=adjusted_score,
                score_decimals=2,
                tag1="tipster",
                tag2=tag2,
                proof_uri=proof_uri,
                proof_hash=proof_hash_bytes,
            )
            logger.info("proof_submitted", tx_hash=tx_hash, score=adjusted_score, boost=boost, report_id=report_id)

            # Update report with tx hash
            await db.execute(
                update(TipsterReport)
                .where(TipsterReport.id == report_id)
                .values(proof_tx_hash=tx_hash, proof_uri=proof_uri)
            )
            await db.commit()

            return tx_hash
        except Exception as e:
            logger.error("proof_submission_failed", error=str(e), report_id=report_id)
            return None


def _extract_score_from_report(report: TipsterReport) -> int:
    """Extract score from report text. Score is 0-10000 (with 2 decimals on-chain)."""
    if not report.report_text:
        return 5000  # default 50.00

    for line in reversed(report.report_text.split("\n")):
        line = line.strip()
        if line.lower().startswith("score:"):
            parts = line.split(":")[-1].strip().split("/")
            try:
                raw = int(parts[0].strip())
                return raw * 100  # 75/100 -> 7500 (= 75.00 with 2 decimals)
            except (ValueError, IndexError):
                pass
    return 5000


def _extract_top_token(report: TipsterReport) -> str | None:
    """Extract the most profitable token from the report for convergence lookup."""
    if not report.report_text:
        return None
    import re
    for line in report.report_text.split("\n"):
        if "best" in line.lower() or "top" in line.lower():
            tokens = re.findall(r'\b([A-Z]{2,6})\b', line)
            for t in tokens:
                if t not in ("BUY", "SELL", "HOLD", "THE", "AND", "FOR", "TOP", "BEST"):
                    return t
    return None
