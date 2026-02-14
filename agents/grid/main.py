"""
Grid Trading Bot Agent — FastAPI application (port 8008)

Automated grid trading on Avalanche via Trader Joe DEX.
Places buy/sell orders at preset price levels and profits from range-bound markets.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
from agents.grid.routes.api import router
from agents.grid.services.engine import check_and_fill_orders
from agents.grid.services.rebalancer import rebalance_grids
from agents.grid.services.tracker import generate_daily_report
from agents.grid.services.blockchain import submit_daily_proof
from agents.grid.config import AGENT_NAME, PRICE_CHECK_INTERVAL, PROOF_SUBMIT_HOUR
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def _check_orders_job():
    try:
        await check_and_fill_orders()
    except Exception as e:
        logger.error("grid_check_failed", error=str(e))
        lightning.log_failure(task="check_orders", error=str(e))


async def _rebalance_job():
    try:
        await rebalance_grids()
    except Exception as e:
        logger.error("grid_rebalance_failed", error=str(e))


async def _daily_report_job():
    try:
        result = await generate_daily_report()
        if result:
            tx = await submit_daily_proof(result["report_id"])
            if tx:
                lightning.log_success("daily_proof", output={"tx": tx, "score": result["score"]})
    except Exception as e:
        logger.error("grid_report_failed", error=str(e))
        lightning.log_failure(task="daily_report", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("grid_bot_starting")
    start_scheduler()

    scheduler.add_job(_check_orders_job, "interval", seconds=PRICE_CHECK_INTERVAL, id="grid_check")
    scheduler.add_job(_rebalance_job, "interval", seconds=3600, id="grid_rebalance")
    scheduler.add_job(_daily_report_job, "cron", hour=PROOF_SUBMIT_HOUR, id="grid_daily_report")

    yield

    stop_scheduler()
    logger.info("grid_bot_stopped")


app = FastAPI(
    title="Grid Trading Bot",
    description="Automated grid trading bot for Avalanche with auto-rebalancing and on-chain proofs.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.grid.main:app", host="0.0.0.0", port=8008, reload=True)
