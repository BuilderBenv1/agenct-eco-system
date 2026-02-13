"""
Yield Oracle Agent — FastAPI application (port 8006)

Scrapes DeFi yield opportunities across Avalanche, scores them by
risk-adjusted return, builds model portfolios, and proves alpha on-chain.

Interfaces: HTTP API + Agent Lightning RL
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
from agents.yield_oracle.routes.api import router
from agents.yield_oracle.services.scraper import scrape_and_save
from agents.yield_oracle.services.scorer import score_all_opportunities, analyze_top_opportunities
from agents.yield_oracle.services.portfolio import build_model_portfolios, generate_daily_report
from agents.yield_oracle.services.blockchain import submit_daily_proof
from agents.yield_oracle.config import (
    AGENT_NAME,
    YIELD_SCRAPE_INTERVAL,
    PORTFOLIO_REBALANCE_INTERVAL,
    PROOF_SUBMIT_HOUR,
)
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)


async def _scrape_job():
    try:
        count = await scrape_and_save()
        if count:
            await score_all_opportunities()
    except Exception as e:
        logger.error("scrape_job_failed", error=str(e))
        lightning.log_failure(task="scrape_yields", error=str(e))


async def _analyze_job():
    try:
        await analyze_top_opportunities()
    except Exception as e:
        logger.error("analyze_job_failed", error=str(e))


async def _portfolio_job():
    try:
        await build_model_portfolios()
    except Exception as e:
        logger.error("portfolio_job_failed", error=str(e))


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
    logger.info("yield_oracle_starting", interfaces=["api", "lightning"])
    start_scheduler()

    # Scrape yields every 15 minutes
    scheduler.add_job(
        _scrape_job, "interval", seconds=YIELD_SCRAPE_INTERVAL, id="yield_scrape"
    )

    # Claude analysis every 30 minutes
    scheduler.add_job(
        _analyze_job, "interval", seconds=1800, id="yield_analyze"
    )

    # Rebalance portfolios every 6 hours
    scheduler.add_job(
        _portfolio_job, "interval", seconds=PORTFOLIO_REBALANCE_INTERVAL, id="yield_portfolio"
    )

    # Daily report
    scheduler.add_job(
        _daily_report_job,
        "cron",
        hour=PROOF_SUBMIT_HOUR,
        id="yield_daily_report",
    )

    yield

    stop_scheduler()
    logger.info("yield_oracle_stopped")


app = FastAPI(
    title="Yield Oracle",
    description="AI agent that discovers, scores, and ranks DeFi yield opportunities "
                "on Avalanche by risk-adjusted return. Proves alpha on-chain.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.yield_oracle.main:app", host="0.0.0.0", port=8006, reload=True)
