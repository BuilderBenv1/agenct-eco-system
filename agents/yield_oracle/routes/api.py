"""
Yield Oracle REST API routes.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.yield_oracle.models.db import YieldOpportunity, YieldPortfolio, YieldReport
from agents.yield_oracle.models.schemas import (
    YieldResponse, PortfolioResponse, ReportResponse, HealthResponse
)

router = APIRouter(prefix="/api/v1/yield", tags=["yield_oracle"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            total = await db.execute(
                select(func.count()).select_from(YieldOpportunity)
                .where(YieldOpportunity.is_active == True)
            )
            avg = await db.execute(
                select(func.avg(YieldOpportunity.apy))
                .where(YieldOpportunity.is_active == True, YieldOpportunity.apy > 0)
            )
            best = await db.execute(
                select(func.max(YieldOpportunity.risk_adjusted_apy))
                .where(YieldOpportunity.is_active == True)
            )
            resp.opportunities_tracked = total.scalar() or 0
            resp.avg_apy = round(avg.scalar() or 0, 2)
            resp.best_risk_adjusted_apy = round(best.scalar() or 0, 2)
    except Exception:
        resp.status = "ok (no db)"
    return resp


@router.get("/opportunities", response_model=list[YieldResponse])
async def list_opportunities(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    protocol: str | None = None,
    pool_type: str | None = None,
    min_apy: float = Query(0, ge=0),
    max_risk: int = Query(100, ge=0, le=100),
    sort_by: str = Query("risk_adjusted_apy", pattern="^(apy|risk_adjusted_apy|tvl_usd|risk_score)$"),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """List yield opportunities with filtering and sorting."""
    q = select(YieldOpportunity).where(YieldOpportunity.is_active == True)

    if protocol:
        q = q.where(YieldOpportunity.protocol == protocol)
    if pool_type:
        q = q.where(YieldOpportunity.pool_type == pool_type)
    if min_apy > 0:
        q = q.where(YieldOpportunity.apy >= min_apy)
    if max_risk < 100:
        q = q.where(YieldOpportunity.risk_score <= max_risk)

    sort_col = getattr(YieldOpportunity, sort_by)
    q = q.order_by(sort_col.desc()).offset(offset).limit(limit)

    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/opportunities/top", response_model=list[YieldResponse])
async def top_opportunities(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """Get top 10 risk-adjusted yield opportunities."""
    result = await db.execute(
        select(YieldOpportunity)
        .where(YieldOpportunity.is_active == True, YieldOpportunity.risk_adjusted_apy > 0)
        .order_by(YieldOpportunity.risk_adjusted_apy.desc())
        .limit(10)
    )
    return list(result.scalars().all())


@router.get("/portfolios", response_model=list[PortfolioResponse])
async def list_portfolios(
    model_type: str | None = None,
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """List model portfolio snapshots."""
    q = select(YieldPortfolio)
    if model_type:
        q = q.where(YieldPortfolio.model_type == model_type)
    q = q.order_by(YieldPortfolio.snapshot_date.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/reports", response_model=list[ReportResponse])
async def list_reports(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(YieldReport).order_by(YieldReport.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.post("/scrape", status_code=202)
async def trigger_scrape(
    _key: bool = Depends(verify_api_key),
):
    """Manually trigger a yield scrape."""
    from agents.yield_oracle.services.scraper import scrape_and_save
    import asyncio
    asyncio.create_task(scrape_and_save())
    return {"status": "scrape_started"}
