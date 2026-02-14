"""
SOS Emergency Bot Agent — FastAPI application (port 8009)

Emergency exit bot that monitors for market crashes, protocol hacks,
and critical health factors. Auto-sells to stables when triggers fire.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
from agents.sos.routes.api import router
from agents.sos.services.monitor import check_crash_conditions, check_health_factors
from agents.sos.services.tracker import generate_daily_report
from agents.sos.services.blockchain import submit_daily_proof
from agents.sos.config import (
    AGENT_NAME, CRASH_CHECK_INTERVAL, HEALTH_CHECK_INTERVAL, PROOF_SUBMIT_HOUR,
)
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def _crash_job():
    try:
        await check_crash_conditions()
    except Exception as e:
        logger.error("sos_crash_job_failed", error=str(e))
        lightning.log_failure(task="crash_check", error=str(e))


async def _health_job():
    try:
        await check_health_factors()
    except Exception as e:
        logger.error("sos_health_job_failed", error=str(e))


async def _daily_report_job():
    try:
        result = await generate_daily_report()
        if result:
            tx = await submit_daily_proof(result["report_id"])
            if tx:
                lightning.log_success("daily_proof", output={"tx": tx, "score": result["score"]})
    except Exception as e:
        logger.error("sos_report_failed", error=str(e))
        lightning.log_failure(task="daily_report", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("sos_bot_starting")
    start_scheduler()

    scheduler.add_job(_crash_job, "interval", seconds=CRASH_CHECK_INTERVAL, id="sos_crash")
    scheduler.add_job(_health_job, "interval", seconds=HEALTH_CHECK_INTERVAL, id="sos_health")
    scheduler.add_job(_daily_report_job, "cron", hour=PROOF_SUBMIT_HOUR, id="sos_daily_report")

    yield

    stop_scheduler()
    logger.info("sos_bot_stopped")


app = FastAPI(
    title="SOS Emergency Bot",
    description="Emergency exit bot for Avalanche. Monitors crashes, hacks, and health factors.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.sos.main:app", host="0.0.0.0", port=8009, reload=True)
