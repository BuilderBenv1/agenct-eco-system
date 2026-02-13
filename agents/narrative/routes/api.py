"""
Narrative Agent REST API routes.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.narrative.models.db import (
    NarrativeSource, NarrativeTrend, NarrativeSentiment, NarrativeReport
)
from agents.narrative.models.schemas import (
    SourceResponse, TrendResponse, SentimentResponse,
    NarrativeReportResponse, HealthResponse, AddSourceRequest
)

router = APIRouter(prefix="/api/v1/narrative", tags=["narrative"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            sources = await db.execute(
                select(func.count()).select_from(NarrativeSource).where(NarrativeSource.is_active == True)
            )
            trends = await db.execute(
                select(func.count()).select_from(NarrativeTrend).where(NarrativeTrend.is_active == True)
            )
            resp.sources_active = sources.scalar() or 0
            resp.trends_active = trends.scalar() or 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


@router.get("/trends", response_model=list[TrendResponse])
async def list_trends(
    category: str | None = None,
    momentum: str | None = None,
    active_only: bool = True,
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(NarrativeTrend)
    if active_only:
        q = q.where(NarrativeTrend.is_active == True)
    if category:
        q = q.where(NarrativeTrend.narrative_category == category)
    if momentum:
        q = q.where(NarrativeTrend.momentum == momentum)
    q = q.order_by(NarrativeTrend.strength.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/trends/{trend_id}", response_model=TrendResponse)
async def get_trend(
    trend_id: int,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(select(NarrativeTrend).where(NarrativeTrend.id == trend_id))
    trend = result.scalar_one_or_none()
    if not trend:
        raise HTTPException(status_code=404, detail="Trend not found")
    return trend


@router.get("/sentiment/recent", response_model=list[SentimentResponse])
async def recent_sentiments(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(NarrativeSentiment)
        .order_by(NarrativeSentiment.analyzed_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(
    source_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(NarrativeSource).where(NarrativeSource.is_active == True)
    if source_type:
        q = q.where(NarrativeSource.source_type == source_type)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def add_source(
    req: AddSourceRequest,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    src = NarrativeSource(
        source_type=req.source_type,
        name=req.name,
        url=req.url,
        channel_id=req.channel_id,
        channel_username=req.channel_username,
        category=req.category,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


@router.get("/reports", response_model=list[NarrativeReportResponse])
async def list_reports(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(NarrativeReport).order_by(NarrativeReport.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/reports/latest", response_model=NarrativeReportResponse)
async def latest_report(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(NarrativeReport).order_by(NarrativeReport.created_at.desc()).limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="No reports yet")
    return report
