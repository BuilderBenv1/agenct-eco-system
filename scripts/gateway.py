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
  /api/v1/dca/...
  /api/v1/grid/...
  /api/v1/sos/...
  /api/v1/sniper/...

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
from agents.dca.routes.api import router as dca_router
from agents.grid.routes.api import router as grid_router
from agents.sos.routes.api import router as sos_router
from agents.sniper.routes.api import router as sniper_router

# Import scheduled job functions
from agents.tipster.services.tracker import check_signal_prices
from agents.tipster.services.monitor import poll_channels as tipster_poll_channels
from agents.whale.services.analyzer import analyze_pending_transactions
from agents.whale.services.monitor import poll_whale_transactions
from agents.narrative.services.analyzer import analyze_pending_items as narrative_analyze
from agents.narrative.services.trend_detector import detect_trends as narrative_detect_trends
from agents.auditor.services.analyzer import analyze_pending_scans
from agents.auditor.services.tracker import check_all_outcomes as auditor_check_outcomes
from agents.auditor.services.scanner import scan_and_save as auditor_scan_contracts
from agents.liquidation.services.position_monitor import scan_all_positions
from agents.liquidation.services.predictor import predict_at_risk_positions
from agents.liquidation.services.tracker import check_prediction_outcomes
from agents.yield_oracle.services.scraper import scrape_and_save
from agents.yield_oracle.services.scorer import score_all_opportunities

# Trading bot job functions
from agents.dca.services.executor import execute_due_dcas
from agents.dca.services.dip_detector import check_dip_buys
from agents.grid.services.engine import check_and_fill_orders as grid_check_orders
from agents.grid.services.rebalancer import rebalance_grids
from agents.sos.services.monitor import check_crash_conditions, check_health_factors
from agents.sniper.services.scanner import scan_new_launches
from agents.sniper.services.filter import run_safety_filters
from agents.sniper.services.executor import execute_snipe
from agents.sniper.services.exit_manager import check_exits as sniper_check_exits


# Convergence detection + API
from shared.convergence import detect_convergence, get_recent_convergences, get_convergence_stats
from shared.config import settings
from fastapi import APIRouter, Query
from datetime import datetime, timezone, timedelta

convergence_router = APIRouter(prefix="/api/v1/convergence", tags=["convergence"])


@convergence_router.get("/health")
async def convergence_health():
    stats = await get_convergence_stats()
    return {"status": "ok", "agent": "convergence", "version": "1.0.0", **stats}


@convergence_router.get("/signals")
async def convergence_signals(
    limit: int = 20,
    since: str | None = Query(None, pattern="^(1d|7d|30d|90d|365d)$"),
):
    return await get_recent_convergences(limit=limit)


@convergence_router.get("/stats")
async def convergence_stats():
    return await get_convergence_stats()


@convergence_router.post("/detect")
async def convergence_trigger():
    results = await detect_convergence()
    return {
        "detected": len(results),
        "signals": [
            {"token": r.token_symbol, "agents": r.agents_involved, "score": r.convergence_score}
            for r in results
        ],
    }


# ---------- Analytics Router (whale PnL, correlation, journal) ----------
from shared.database import async_session as _async_session
from sqlalchemy import select as _select, func as _func, text as _text

analytics_router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@analytics_router.get("/whale/summary")
async def whale_summary(since: str = Query("30d", pattern="^(1d|7d|30d|90d|365d)$")):
    """Whale PnL summary: volume, tx counts, top tokens, win/loss by token."""
    if _async_session is None:
        return {"error": "no db"}

    from agents.whale.models.db import WhaleTransaction, WhaleAnalysis

    mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
    cutoff = datetime.now(timezone.utc) - timedelta(days=mapping.get(since, 30))

    async with _async_session() as db:
        # Total volume and count
        agg = await db.execute(
            _select(
                _func.count().label("total_txns"),
                _func.coalesce(_func.sum(WhaleTransaction.amount_usd), 0).label("total_volume"),
                _func.count(_func.distinct(WhaleTransaction.token_symbol)).label("unique_tokens"),
            ).where(WhaleTransaction.detected_at >= cutoff)
        )
        row = agg.first()

        # Top tokens by volume
        top_tokens = await db.execute(
            _select(
                WhaleTransaction.token_symbol,
                _func.count().label("tx_count"),
                _func.coalesce(_func.sum(WhaleTransaction.amount_usd), 0).label("volume"),
            )
            .where(WhaleTransaction.detected_at >= cutoff, WhaleTransaction.token_symbol.isnot(None))
            .group_by(WhaleTransaction.token_symbol)
            .order_by(_func.sum(WhaleTransaction.amount_usd).desc())
            .limit(10)
        )

        # Significance distribution
        sig_dist = await db.execute(
            _select(
                WhaleAnalysis.significance,
                _func.count().label("count"),
            )
            .where(WhaleAnalysis.created_at >= cutoff)
            .group_by(WhaleAnalysis.significance)
        )

        return {
            "period": since,
            "total_transactions": row.total_txns if row else 0,
            "total_volume_usd": float(row.total_volume) if row else 0,
            "unique_tokens": row.unique_tokens if row else 0,
            "top_tokens": [
                {"token": t.token_symbol, "tx_count": t.tx_count, "volume_usd": float(t.volume)}
                for t in top_tokens
            ],
            "significance_distribution": {
                s.significance: s.count for s in sig_dist
            },
        }


@analytics_router.get("/correlation")
async def token_correlation():
    """Token co-occurrence matrix from convergence data."""
    if _async_session is None:
        return {"pairs": []}

    from shared.models.convergence import ConvergenceSignal

    async with _async_session() as db:
        # Get all convergence signals to build co-occurrence
        result = await db.execute(
            _select(ConvergenceSignal)
            .order_by(ConvergenceSignal.detected_at.desc())
            .limit(200)
        )
        signals = result.scalars().all()

    # Build token-agent co-occurrence from agents_involved
    token_agents: dict[str, list[str]] = {}
    for s in signals:
        token_agents.setdefault(s.token_symbol, []).extend(s.agents_involved or [])

    # Build token-token co-occurrence from whale + tipster overlap
    # For now, return token-to-agent frequency
    return {
        "tokens": [
            {
                "token": token,
                "agent_mentions": len(agents),
                "agents": list(set(agents)),
                "convergence_count": sum(1 for s in signals if s.token_symbol == token),
            }
            for token, agents in sorted(token_agents.items(), key=lambda x: -len(x[1]))[:20]
        ],
        "total_signals": len(signals),
    }


@analytics_router.get("/accuracy")
async def agent_accuracy():
    """Agent accuracy dashboard: track prediction outcomes across all agents."""
    if _async_session is None:
        return {"agents": []}

    agents_data = []

    async with _async_session() as db:
        # Auditor accuracy: flagged as danger/rug vs actual outcome
        from agents.auditor.models.db import ContractScan
        total_scans = await db.execute(_select(_func.count()).select_from(ContractScan))
        flagged = await db.execute(
            _select(_func.count()).select_from(ContractScan)
            .where(ContractScan.risk_label.in_(["danger", "rug"]))
        )
        confirmed = await db.execute(
            _select(_func.count()).select_from(ContractScan)
            .where(ContractScan.actual_outcome == "rugged")
        )
        correct_flags = await db.execute(
            _select(_func.count()).select_from(ContractScan)
            .where(
                ContractScan.risk_label.in_(["danger", "rug"]),
                ContractScan.actual_outcome == "rugged",
            )
        )
        ts = total_scans.scalar() or 0
        fl = flagged.scalar() or 0
        cf = confirmed.scalar() or 0
        co = correct_flags.scalar() or 0
        agents_data.append({
            "agent": "Rug Auditor",
            "total_predictions": ts,
            "flagged": fl,
            "confirmed_outcomes": cf,
            "correct_predictions": co,
            "accuracy": round(co / fl * 100, 1) if fl > 0 else 0,
        })

        # Liquidation accuracy
        from agents.liquidation.models.db import LiquidationEvent
        total_events = await db.execute(_select(_func.count()).select_from(LiquidationEvent))
        predicted_events = await db.execute(
            _select(_func.count()).select_from(LiquidationEvent)
            .where(LiquidationEvent.was_predicted == True)
        )
        te = total_events.scalar() or 0
        pe = predicted_events.scalar() or 0
        agents_data.append({
            "agent": "Liquidation Sentinel",
            "total_predictions": te,
            "correct_predictions": pe,
            "accuracy": round(pe / te * 100, 1) if te > 0 else 0,
        })

        # Yield Oracle stats
        from agents.yield_oracle.models.db import YieldOpportunity
        total_opps = await db.execute(
            _select(_func.count()).select_from(YieldOpportunity)
            .where(YieldOpportunity.is_active == True)
        )
        avg_sharpe = await db.execute(
            _select(_func.avg(YieldOpportunity.sharpe_ratio))
            .where(YieldOpportunity.is_active == True, YieldOpportunity.sharpe_ratio.isnot(None))
        )
        strong_buys = await db.execute(
            _select(_func.count()).select_from(YieldOpportunity)
            .where(YieldOpportunity.recommendation == "strong_buy")
        )
        agents_data.append({
            "agent": "Yield Oracle",
            "total_opportunities": total_opps.scalar() or 0,
            "avg_sharpe_ratio": round(avg_sharpe.scalar() or 0, 2),
            "strong_buy_count": strong_buys.scalar() or 0,
        })

    return {"agents": agents_data}


async def _safe_run(name, fn):
    try:
        await fn()
    except Exception as e:
        logger.error(f"{name}_job_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("gateway_starting", agents=11)
    start_scheduler()

    # Tipster jobs — poll channels first (detects signals), then track prices
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("tipster_poll", tipster_poll_channels)),
        "interval", seconds=300, id="gw_tipster_poll"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("tipster_prices", check_signal_prices)),
        "interval", seconds=900, id="gw_tipster_prices"
    )

    # Whale jobs — poll first (detects txns), then analyze
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("whale_poll", poll_whale_transactions)),
        "interval", seconds=30, id="gw_whale_poll"
    )
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

    # Auditor jobs — scan contracts first (detects issues), then analyze with Claude
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("auditor_scan", auditor_scan_contracts)),
        "interval", seconds=600, id="gw_auditor_scan"
    )
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

    # DCA Bot jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("dca_execute", execute_due_dcas)),
        "interval", seconds=60, id="gw_dca_execute"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("dca_dip", check_dip_buys)),
        "interval", seconds=300, id="gw_dca_dip"
    )

    # Grid Trading Bot jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("grid_check", grid_check_orders)),
        "interval", seconds=30, id="gw_grid_check"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("grid_rebalance", rebalance_grids)),
        "interval", seconds=3600, id="gw_grid_rebalance"
    )

    # SOS Emergency Bot jobs
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("sos_crash", check_crash_conditions)),
        "interval", seconds=60, id="gw_sos_crash"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("sos_health", check_health_factors)),
        "interval", seconds=120, id="gw_sos_health"
    )

    # Sniper Bot jobs
    async def _sniper_scan():
        launches = await scan_new_launches()
        if launches:
            approved = await run_safety_filters(launches)
            for item in approved:
                await execute_snipe(item["config"], item["launch"])

    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("sniper_scan", _sniper_scan)),
        "interval", seconds=15, id="gw_sniper_scan"
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(_safe_run("sniper_exits", sniper_check_exits)),
        "interval", seconds=30, id="gw_sniper_exits"
    )

    yield

    stop_scheduler()
    logger.info("gateway_stopped")


app = FastAPI(
    title="AgentProof Gateway",
    description="Unified API gateway for the AgentProof 11-agent intelligence + trading network on Avalanche.",
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
app.include_router(convergence_router)
app.include_router(analytics_router)
app.include_router(dca_router)
app.include_router(grid_router)
app.include_router(sos_router)
app.include_router(sniper_router)


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
        "agents": 11,
        "database": "connected" if db_ok else "disconnected",
        "db_error": db_error,
        "endpoints": [
            "/api/v1/tipster/health",
            "/api/v1/whale/health",
            "/api/v1/narrative/health",
            "/api/v1/auditor/health",
            "/api/v1/liquidation/health",
            "/api/v1/yield/health",
            "/api/v1/convergence/health",
            "/api/v1/dca/health",
            "/api/v1/grid/health",
            "/api/v1/sos/health",
            "/api/v1/sniper/health",
        ],
    }


@app.get("/")
async def root():
    return {
        "name": "AgentProof",
        "description": "11-agent AI intelligence + trading network on Avalanche",
        "docs": "/docs",
        "health": "/health",
        "agents": {
            "tipster": "/api/v1/tipster/health",
            "whale": "/api/v1/whale/health",
            "narrative": "/api/v1/narrative/health",
            "auditor": "/api/v1/auditor/health",
            "liquidation": "/api/v1/liquidation/health",
            "yield_oracle": "/api/v1/yield/health",
            "dca": "/api/v1/dca/health",
            "grid": "/api/v1/grid/health",
            "sos": "/api/v1/sos/health",
            "sniper": "/api/v1/sniper/health",
        },
    }
