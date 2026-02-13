"""
Liquidation Sentinel Agent — FastAPI application (port 8005)

Monitors Benqi and Aave v3 lending positions on Avalanche for approaching
liquidations, predicts outcomes, and submits verifiable proofs on-chain.

Interfaces: HTTP API + Agent Lightning RL
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
from agents.liquidation.routes.api import router
from agents.liquidation.services.position_monitor import scan_all_positions
from agents.liquidation.services.predictor import predict_at_risk_positions
from agents.liquidation.services.tracker import check_prediction_outcomes, generate_daily_report
from agents.liquidation.services.blockchain import submit_daily_proof
from agents.liquidation.config import (
    AGENT_NAME,
    POSITION_POLL_INTERVAL,
    OUTCOME_CHECK_INTERVAL,
    PROOF_SUBMIT_HOUR,
)
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def _scan_job():
    try:
        await scan_all_positions()
    except Exception as e:
        logger.error("scan_job_failed", error=str(e))
        lightning.log_failure(task="scan_positions", error=str(e))


async def _predict_job():
    try:
        await predict_at_risk_positions()
    except Exception as e:
        logger.error("predict_job_failed", error=str(e))


async def _outcome_job():
    try:
        await check_prediction_outcomes()
    except Exception as e:
        logger.error("outcome_job_failed", error=str(e))


async def _daily_report_job():
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
    logger.info("liquidation_sentinel_starting", interfaces=["api", "lightning"])
    start_scheduler()

    # Scan positions every 2 minutes
    scheduler.add_job(
        _scan_job, "interval", seconds=POSITION_POLL_INTERVAL, id="liq_scan"
    )

    # Predict liquidations every 5 minutes
    scheduler.add_job(
        _predict_job, "interval", seconds=300, id="liq_predict"
    )

    # Check outcomes every hour
    scheduler.add_job(
        _outcome_job, "interval", seconds=OUTCOME_CHECK_INTERVAL, id="liq_outcomes"
    )

    # Daily report
    scheduler.add_job(
        _daily_report_job,
        "cron",
        hour=PROOF_SUBMIT_HOUR,
        id="liq_daily_report",
    )

    yield

    stop_scheduler()
    logger.info("liquidation_sentinel_stopped")


app = FastAPI(
    title="Liquidation Sentinel",
    description="AI agent that monitors DeFi lending positions on Avalanche for "
                "approaching liquidations, predicts outcomes, and proves accuracy on-chain.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.liquidation.main:app", host="0.0.0.0", port=8005, reload=True)
