"""
Narrative Intelligence Scanner — FastAPI application (port 8003)

Monitors RSS feeds, Telegram channels, and CoinGecko trending data to detect
market narratives, analyze sentiment, track trends, and submit daily on-chain proofs.

Interfaces: HTTP API + Clawntenna encrypted messaging + Agent Lightning RL
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.clawntenna import get_bridge
from shared.lightning import get_lightning
from shared.config import settings
from agents.narrative.routes.api import router
from agents.narrative.services.monitor import poll_rss_sources, poll_coingecko_trending
from agents.narrative.services.telegram_scraper import poll_telegram_channels
from agents.narrative.services.analyzer import analyze_pending_items
from agents.narrative.services.trend_detector import detect_trends
from agents.narrative.services.reporter import generate_daily_report
from agents.narrative.services.blockchain import submit_daily_proof
from agents.narrative.services.clawntenna import handle_narrative_query
from agents.narrative.config import (
    AGENT_NAME,
    RSS_POLL_INTERVAL,
    TELEGRAM_POLL_INTERVAL,
    COINGECKO_TRENDING_INTERVAL,
    TREND_ANALYSIS_INTERVAL,
    PROOF_SUBMIT_HOUR,
)
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)
clawntenna = get_bridge(AGENT_NAME)


async def _rss_job():
    try:
        await poll_rss_sources()
        await analyze_pending_items()
    except Exception as e:
        logger.error("rss_job_failed", error=str(e))
        lightning.log_failure(task="rss_poll", error=str(e))


async def _telegram_job():
    try:
        await poll_telegram_channels()
        await analyze_pending_items()
    except Exception as e:
        logger.error("telegram_job_failed", error=str(e))


async def _trending_job():
    try:
        await poll_coingecko_trending()
        await analyze_pending_items()
    except Exception as e:
        logger.error("trending_job_failed", error=str(e))


async def _trend_detection_job():
    try:
        await detect_trends()
    except Exception as e:
        logger.error("trend_detection_failed", error=str(e))
        lightning.log_failure(task="trend_detection", error=str(e))


async def _daily_report_job():
    try:
        result = await generate_daily_report()
        if result:
            tx = await submit_daily_proof(result["report_id"])
            if tx:
                logger.info("narrative_proof_submitted", tx_hash=tx)
                lightning.log_success("daily_proof", output={"tx": tx, "score": result["score"]})
    except Exception as e:
        logger.error("daily_report_job_failed", error=str(e))
        lightning.log_failure(task="daily_report", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("narrative_agent_starting", interfaces=["api", "clawntenna", "lightning"])
    start_scheduler()

    scheduler.add_job(
        _rss_job, "interval", seconds=RSS_POLL_INTERVAL, id="narrative_rss"
    )
    scheduler.add_job(
        _telegram_job, "interval", seconds=TELEGRAM_POLL_INTERVAL, id="narrative_telegram"
    )
    scheduler.add_job(
        _trending_job, "interval", seconds=COINGECKO_TRENDING_INTERVAL, id="narrative_trending"
    )
    scheduler.add_job(
        _trend_detection_job, "interval", seconds=TREND_ANALYSIS_INTERVAL, id="narrative_trends"
    )
    scheduler.add_job(
        _daily_report_job, "cron", hour=PROOF_SUBMIT_HOUR, id="narrative_daily_report"
    )

    # Start Clawntenna encrypted message listener
    clawntenna.on_message(handle_narrative_query)
    if settings.CLAWNTENNA_NARRATIVE_TOPIC:
        clawntenna.set_topic(settings.CLAWNTENNA_NARRATIVE_TOPIC)
        asyncio.create_task(clawntenna.start_listening())
        logger.info("clawntenna_listener_started", topic=settings.CLAWNTENNA_NARRATIVE_TOPIC)

    yield

    clawntenna.stop_listening()
    stop_scheduler()
    logger.info("narrative_agent_stopped")


app = FastAPI(
    title="Narrative Intelligence Scanner",
    description="AI agent that monitors crypto news, social channels, and market data to detect narrative trends and market sentiment. Supports API, Clawntenna encrypted queries, and Agent Lightning self-improvement.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.narrative.main:app", host="0.0.0.0", port=8003, reload=True)
