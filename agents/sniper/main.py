"""
Sniper Bot Agent — FastAPI application (port 8010)

Monitors Trader Joe Factory for new token launches, runs safety filters
(cross-checks with Rug Auditor), executes fast buys, and manages TP/SL exits.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
from agents.sniper.routes.api import router
from agents.sniper.services.scanner import scan_new_launches
from agents.sniper.services.filter import run_safety_filters
from agents.sniper.services.executor import execute_snipe
from agents.sniper.services.exit_manager import check_exits
from agents.sniper.services.tracker import generate_daily_report
from agents.sniper.services.blockchain import submit_daily_proof
from agents.sniper.config import AGENT_NAME, SCAN_INTERVAL, EXIT_CHECK_INTERVAL, PROOF_SUBMIT_HOUR
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def _scan_job():
    try:
        launches = await scan_new_launches()
        if launches:
            approved = await run_safety_filters(launches)
            for item in approved:
                await execute_snipe(item["config"], item["launch"])
    except Exception as e:
        logger.error("sniper_scan_failed", error=str(e))
        lightning.log_failure(task="scan_launches", error=str(e))


async def _exit_job():
    try:
        await check_exits()
    except Exception as e:
        logger.error("sniper_exit_check_failed", error=str(e))


async def _daily_report_job():
    try:
        result = await generate_daily_report()
        if result:
            tx = await submit_daily_proof(result["report_id"])
            if tx:
                lightning.log_success("daily_proof", output={"tx": tx, "score": result["score"]})
    except Exception as e:
        logger.error("sniper_report_failed", error=str(e))
        lightning.log_failure(task="daily_report", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("sniper_bot_starting")
    start_scheduler()

    scheduler.add_job(_scan_job, "interval", seconds=SCAN_INTERVAL, id="sniper_scan")
    scheduler.add_job(_exit_job, "interval", seconds=EXIT_CHECK_INTERVAL, id="sniper_exits")
    scheduler.add_job(_daily_report_job, "cron", hour=PROOF_SUBMIT_HOUR, id="sniper_daily_report")

    yield

    stop_scheduler()
    logger.info("sniper_bot_stopped")


app = FastAPI(
    title="Sniper Bot",
    description="Token launch sniper bot for Avalanche with safety filters and auto TP/SL.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.sniper.main:app", host="0.0.0.0", port=8010, reload=True)
