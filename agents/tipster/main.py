"""
Crypto Tipster Verifier — FastAPI application (port 8001)

Monitors Telegram channels for crypto trading signals, parses them with Claude,
tracks price performance, generates weekly reports, and submits on-chain proofs.

Interfaces: HTTP API + Clawntenna encrypted messaging + Agent Lightning RL
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.clawntenna import get_bridge
from shared.lightning import get_lightning
from shared.config import settings
from agents.tipster.routes.api import router
from agents.tipster.services.monitor import poll_channels
from agents.tipster.services.tracker import check_signal_prices
from agents.tipster.services.reporter import generate_weekly_report
from agents.tipster.services.blockchain import submit_weekly_proof
from agents.tipster.services.clawntenna import handle_tipster_query
from agents.tipster.config import (
    AGENT_NAME,
    SIGNAL_POLL_INTERVAL,
    PRICE_CHECK_INTERVAL,
    PROOF_SUBMIT_DAY,
    PROOF_SUBMIT_HOUR,
)
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)
clawntenna = get_bridge(AGENT_NAME)


async def _poll_job():
    try:
        await poll_channels()
    except Exception as e:
        logger.error("poll_job_failed", error=str(e))
        lightning.log_failure(task="poll_channels", error=str(e))


async def _price_job():
    try:
        await check_signal_prices()
    except Exception as e:
        logger.error("price_job_failed", error=str(e))


async def _weekly_report_job():
    try:
        result = await generate_weekly_report()
        if result:
            tx = await submit_weekly_proof(result["report_id"])
            if tx:
                logger.info("weekly_proof_submitted", tx_hash=tx)
                lightning.log_success("weekly_proof", output={"tx": tx, "score": result["score"]})
    except Exception as e:
        logger.error("weekly_report_job_failed", error=str(e))
        lightning.log_failure(task="weekly_report", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("tipster_agent_starting", interfaces=["api", "clawntenna", "lightning"])
    start_scheduler()

    # Poll channels every 60s
    scheduler.add_job(
        _poll_job, "interval", seconds=SIGNAL_POLL_INTERVAL, id="tipster_poll"
    )
    # Check prices every 15 min
    scheduler.add_job(
        _price_job, "interval", seconds=PRICE_CHECK_INTERVAL, id="tipster_prices"
    )
    # Weekly report on Monday at noon UTC
    scheduler.add_job(
        _weekly_report_job,
        "cron",
        day_of_week=PROOF_SUBMIT_DAY,
        hour=PROOF_SUBMIT_HOUR,
        id="tipster_weekly_report",
    )

    # Start Clawntenna encrypted message listener
    clawntenna.on_message(handle_tipster_query)
    if settings.CLAWNTENNA_TIPSTER_TOPIC:
        clawntenna.set_topic(settings.CLAWNTENNA_TIPSTER_TOPIC)
        asyncio.create_task(clawntenna.start_listening())
        logger.info("clawntenna_listener_started", topic=settings.CLAWNTENNA_TIPSTER_TOPIC)

    yield

    clawntenna.stop_listening()
    stop_scheduler()
    logger.info("tipster_agent_stopped")


app = FastAPI(
    title="Crypto Tipster Verifier",
    description="AI agent that monitors, parses, and verifies crypto trading signals. Supports API, Clawntenna encrypted queries, and Agent Lightning self-improvement.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.tipster.main:app", host="0.0.0.0", port=8001, reload=True)
