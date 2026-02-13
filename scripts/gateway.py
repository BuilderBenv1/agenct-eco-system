"""
API Gateway — Unified entry point that mounts all agent routers on a single port.
Ideal for Railway (1 service, 1 port) or simple VPS deployments.

All agents accessible via their original paths:
  /api/v1/tipster/...
  /api/v1/whale/...
  /api/v1/narrative/...
  /api/v1/convergence/...
  /api/v1/auditor/...
  /api/v1/liquidation/...
  /api/v1/yield/...

Scheduled jobs from all agents run inside this single process.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.lightning import get_lightning
import structlog

logger = structlog.get_logger()

# Import all routers
from agents.tipster.routes.api import router as tipster_router
from agents.whale.routes.api import router as whale_router
from agents.narrative.routes.api import router as narrative_router
from agents.auditor.routes.api import router as auditor_router
from agents.liquidation.routes.api import router as liquidation_router
from agents.yield_oracle.routes.api import router as yield_router

# Import scheduled job functions
from agents.tipster.services.tracker import check_signal_prices
from agents.whale.services.analyzer import analyze_pending_transactions
from agents.narrative.services.analyzer import analyze_pending_items as narrative_analyze
from agents.narrative.services.trend_detector import detect_trends as narrative_detect_trends
from agents.auditor.services.analyzer import analyze_pending_scans
from agents.auditor.services.tracker import check_all_outcomes as auditor_check_outcomes
from agents.liquidation.services.position_monitor import scan_all_positions
from agents.liquidation.services.predictor import predict_at_risk_positions
from agents.liquidation.services.tracker import check_prediction_outcomes
from agents.yield_oracle.services.scraper import scrape_and_save
from agents.yield_oracle.services.scorer import score_all_opportunities


# Convergence detection
from shared.convergence import detect_convergence
from shared.config import settings


async def _safe_run(name, fn):
    try:
        await fn()
    except Exception as e:
        logger.error(f"{name}_job_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("gateway_starting", agents=7)
    start_scheduler()

    # Tipster jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("tipster_prices", check_signal_prices)),
        "interval", seconds=900, id="gw_tipster_prices"
    )

    # Whale jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("whale_analyze", analyze_pending_transactions)),
        "interval", seconds=300, id="gw_whale_analyze"
    )

    # Narrative jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("narrative_analyze", narrative_analyze)),
        "interval", seconds=600, id="gw_narrative_analyze"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("narrative_trends", narrative_detect_trends)),
        "interval", seconds=1800, id="gw_narrative_trends"
    )

    # Auditor jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("auditor_analyze", analyze_pending_scans)),
        "interval", seconds=120, id="gw_auditor_analyze"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("auditor_outcomes", auditor_check_outcomes)),
        "interval", seconds=21600, id="gw_auditor_outcomes"
    )

    # Liquidation jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("liq_scan", scan_all_positions)),
        "interval", seconds=120, id="gw_liq_scan"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("liq_predict", predict_at_risk_positions)),
        "interval", seconds=300, id="gw_liq_predict"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("liq_outcomes", check_prediction_outcomes)),
        "interval", seconds=3600, id="gw_liq_outcomes"
    )

    # Yield Oracle jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("yield_scrape", scrape_and_save)),
        "interval", seconds=900, id="gw_yield_scrape"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("yield_score", score_all_opportunities)),
        "interval", seconds=1800, id="gw_yield_score"
    )

    # Convergence detection
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("convergence", detect_convergence)),
        "interval", seconds=settings.CONVERGENCE_CHECK_INTERVAL, id="gw_convergence"
    )

    yield

    stop_scheduler()
    logger.info("gateway_stopped")


app = FastAPI(
    title="AgentProof Gateway",
    description="Unified API gateway for the AgentProof 7-agent intelligence network on Avalanche.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all agent routers
app.include_router(tipster_router)
app.include_router(whale_router)
app.include_router(narrative_router)
app.include_router(auditor_router)
app.include_router(liquidation_router)
app.include_router(yield_router)


@app.get("/health")
async def gateway_health():
    """Combined health check for all agents."""
    from shared.database import async_session
    from sqlalchemy import text

    db_ok = False
    db_error = None
    if async_session:
        try:
            async with async_session() as db:
                await db.execute(text("SELECT 1"))
                db_ok = True
        except Exception as e:
            db_error = str(e)[:200]
            logger.error("health_db_check_failed", error=db_error)
    else:
        db_error = "async_session is None (DATABASE_URL not set?)"

    return {
        "status": "ok" if db_ok else "degraded",
        "gateway": "agentproof",
        "version": "1.0.0",
        "agents": 7,
        "database": "connected" if db_ok else "disconnected",
        "db_error": db_error,
        "endpoints": [
            "/api/v1/tipster/health",
            "/api/v1/whale/health",
            "/api/v1/narrative/health",
            "/api/v1/auditor/health",
            "/api/v1/liquidation/health",
            "/api/v1/yield/health",
        ],
    }


@app.get("/")
async def root():
    return {
        "name": "AgentProof",
        "description": "7-agent AI intelligence network on Avalanche",
        "docs": "/docs",
        "health": "/health",
        "agents": {
            "tipster": "/api/v1/tipster/health",
            "whale": "/api/v1/whale/health",
            "narrative": "/api/v1/narrative/health",
            "auditor": "/api/v1/auditor/health",
            "liquidation": "/api/v1/liquidation/health",
            "yield_oracle": "/api/v1/yield/health",
        },
    }
