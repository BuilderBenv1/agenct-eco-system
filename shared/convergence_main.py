"""
Convergence Oracle — FastAPI application (port 8000)

Cross-agent convergence detection service. Periodically scans all 3 agents'
data for overlapping token mentions, scores convergence, and submits
meta-proofs on-chain.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
from shared.utils.scheduler import start_scheduler, stop_scheduler, scheduler
from shared.convergence import (
    detect_convergence, get_recent_convergences, get_convergence_stats
)
from shared.config import settings
import structlog

logger = structlog.get_logger()


async def _convergence_job():
    try:
        results = await detect_convergence()
        if results:
            logger.info("convergence_detected", count=len(results))
    except Exception as e:
        logger.error("convergence_job_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("convergence_oracle_starting")
    start_scheduler()

    scheduler.add_job(
        _convergence_job,
        "interval",
        seconds=settings.CONVERGENCE_CHECK_INTERVAL,
        id="convergence_detector",
    )

    # Run once on startup after a short delay
    async def _initial_run():
        await asyncio.sleep(10)
        await _convergence_job()

    asyncio.create_task(_initial_run())

    yield

    stop_scheduler()
    logger.info("convergence_oracle_stopped")


app = FastAPI(
    title="Convergence Oracle",
    description="Cross-agent convergence detection. Identifies when multiple agents independently flag the same token, scores the convergence, and submits meta-proofs on-chain.",
    version="1.0.0",
    lifespan=lifespan,
)


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "convergence"
    version: str = "1.0.0"
    total_convergences: int = 0
    last_24h: int = 0
    three_agent_total: int = 0


@app.get("/api/v1/convergence/health", response_model=HealthResponse)
async def health():
    stats = await get_convergence_stats()
    return HealthResponse(**stats)


@app.get("/api/v1/convergence/signals")
async def list_convergences(limit: int = 20):
    return await get_recent_convergences(limit=limit)


@app.get("/api/v1/convergence/stats")
async def stats():
    return await get_convergence_stats()


@app.post("/api/v1/convergence/detect")
async def trigger_detection():
    """Manually trigger convergence detection (admin)."""
    results = await detect_convergence()
    return {
        "detected": len(results),
        "signals": [
            {"token": r.token_symbol, "agents": r.agents_involved, "score": r.convergence_score}
            for r in results
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("shared.convergence_main:app", host="0.0.0.0", port=8000, reload=True)
