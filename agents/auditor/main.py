"""
Rug Detector Agent — FastAPI application (port 8004)

Scans new token deployments on Avalanche C-Chain for rug pull indicators,
tracks outcomes for verifiable scoring, and submits on-chain proofs.

Interfaces: HTTP API + Clawntenna encrypted messaging + Agent Lightning RL
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
from shared.config import settings
from agents.auditor.routes.api import router
from agents.auditor.services.analyzer import analyze_pending_scans
from agents.auditor.services.tracker import check_all_outcomes, generate_daily_report
from agents.auditor.services.blockchain import submit_daily_proof
from agents.auditor.config import (
    AGENT_NAME,
    SCAN_POLL_INTERVAL,
    OUTCOME_CHECK_INTERVAL,
    PROOF_SUBMIT_HOUR,
)
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def _analyze_job():
    """Run pending Claude analyses on recently scanned contracts."""
    try:
        await analyze_pending_scans()
    except Exception as e:
        logger.error("analyze_job_failed", error=str(e))
        lightning.log_failure(task="analyze_scans", error=str(e))


async def _outcome_job():
    """Check outcomes of previously flagged tokens."""
    try:
        await check_all_outcomes()
    except Exception as e:
        logger.error("outcome_job_failed", error=str(e))


async def _daily_report_job():
    """Generate daily report and submit proof."""
    try:
        result = await generate_daily_report()
        if result:
            tx = await submit_daily_proof(result["report_id"])
            if tx:
                logger.info("daily_proof_submitted", tx_hash=tx)
                lightning.log_success("daily_proof", output={"tx": tx, "score": result["score"]})
    except Exception as e:
        logger.error("daily_report_job_failed", error=str(e))
        lightning.log_failure(task="daily_report", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("auditor_agent_starting", interfaces=["api", "lightning"])
    start_scheduler()

    # Analyze pending scans every 2 minutes
    scheduler.add_job(
        _analyze_job, "interval", seconds=SCAN_POLL_INTERVAL * 2, id="auditor_analyze"
    )

    # Check outcomes every 6 hours
    scheduler.add_job(
        _outcome_job, "interval", seconds=OUTCOME_CHECK_INTERVAL, id="auditor_outcomes"
    )

    # Daily report at configured hour
    scheduler.add_job(
        _daily_report_job,
        "cron",
        hour=PROOF_SUBMIT_HOUR,
        id="auditor_daily_report",
    )

    yield

    stop_scheduler()
    logger.info("auditor_agent_stopped")


app = FastAPI(
    title="Rug Detector Agent",
    description="AI agent that scans Avalanche token contracts for rug pull indicators, "
                "tracks outcomes, and submits verifiable proofs on-chain.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.auditor.main:app", host="0.0.0.0", port=8004, reload=True)
