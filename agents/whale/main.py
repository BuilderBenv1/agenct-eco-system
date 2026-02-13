"""
Whale Movement Alerts — FastAPI application (port 8002)

Monitors Avalanche C-Chain for whale wallet transactions, decodes them,
analyzes with Claude, sends real-time alerts, and submits daily on-chain proofs.

Interfaces: HTTP API + Clawntenna encrypted messaging + Agent Lightning RL
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.clawntenna import get_bridge
from shared.lightning import get_lightning
from shared.config import settings
from agents.whale.routes.api import router
from agents.whale.services.monitor import poll_whale_transactions
from agents.whale.services.analyzer import analyze_pending_transactions
from agents.whale.services.reporter import generate_daily_report
from agents.whale.services.blockchain import submit_daily_proof
from agents.whale.services.clawntenna import handle_whale_query
from agents.whale.config import AGENT_NAME, TX_POLL_INTERVAL, PROOF_SUBMIT_HOUR
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)
clawntenna = get_bridge(AGENT_NAME)


async def _monitor_job():
    try:
        new_txns = await poll_whale_transactions()
        if new_txns:
            await analyze_pending_transactions()
    except Exception as e:
        logger.error("monitor_job_failed", error=str(e))
        lightning.log_failure(task="monitor_whales", error=str(e))


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
    logger.info("whale_agent_starting", interfaces=["api", "clawntenna", "lightning"])
    start_scheduler()

    scheduler.add_job(
        _monitor_job, "interval", seconds=TX_POLL_INTERVAL, id="whale_monitor"
    )
    scheduler.add_job(
        _daily_report_job, "cron", hour=PROOF_SUBMIT_HOUR, id="whale_daily_report"
    )

    # Start Clawntenna encrypted message listener
    clawntenna.on_message(handle_whale_query)
    if settings.CLAWNTENNA_WHALE_TOPIC:
        clawntenna.set_topic(settings.CLAWNTENNA_WHALE_TOPIC)
        asyncio.create_task(clawntenna.start_listening())
        logger.info("clawntenna_listener_started", topic=settings.CLAWNTENNA_WHALE_TOPIC)

    yield

    clawntenna.stop_listening()
    stop_scheduler()
    logger.info("whale_agent_stopped")


app = FastAPI(
    title="Whale Movement Alerts",
    description="AI agent that monitors, decodes, and analyzes whale transactions on Avalanche C-Chain. Supports API, Clawntenna encrypted queries, and Agent Lightning self-improvement.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.whale.main:app", host="0.0.0.0", port=8002, reload=True)
