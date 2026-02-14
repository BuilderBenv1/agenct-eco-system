"""
DCA Bot Agent — FastAPI application (port 8007)

Automated Dollar-Cost Averaging into Avalanche tokens via Trader Joe DEX.
Supports dip detection (2x buy), take-profit exits, and on-chain proof submission.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
from agents.dca.routes.api import router
from agents.dca.services.executor import execute_due_dcas
from agents.dca.services.dip_detector import check_dip_buys
from agents.dca.services.tracker import generate_daily_report
from agents.dca.services.blockchain import submit_daily_proof
from agents.dca.config import AGENT_NAME, DCA_CHECK_INTERVAL, DIP_CHECK_INTERVAL, PROOF_SUBMIT_HOUR
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def _dca_job():
    try:
        await execute_due_dcas()
    except Exception as e:
        logger.error("dca_job_failed", error=str(e))
        lightning.log_failure(task="execute_dcas", error=str(e))


async def _dip_job():
    try:
        await check_dip_buys()
    except Exception as e:
        logger.error("dip_job_failed", error=str(e))


async def _daily_report_job():
    try:
        result = await generate_daily_report()
        if result:
            tx = await submit_daily_proof(result["report_id"])
            if tx:
                lightning.log_success("daily_proof", output={"tx": tx, "score": result["score"]})
    except Exception as e:
        logger.error("dca_report_job_failed", error=str(e))
        lightning.log_failure(task="daily_report", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("dca_bot_starting")
    start_scheduler()

    scheduler.add_job(_dca_job, "interval", seconds=DCA_CHECK_INTERVAL, id="dca_execute")
    scheduler.add_job(_dip_job, "interval", seconds=DIP_CHECK_INTERVAL, id="dca_dip_check")
    scheduler.add_job(_daily_report_job, "cron", hour=PROOF_SUBMIT_HOUR, id="dca_daily_report")

    yield

    stop_scheduler()
    logger.info("dca_bot_stopped")


app = FastAPI(
    title="DCA Bot",
    description="Automated Dollar-Cost Averaging bot for Avalanche tokens with dip detection and on-chain proofs.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.dca.main:app", host="0.0.0.0", port=8007, reload=True)
