"""
Liquidation Sentinel REST API routes.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.liquidation.models.db import LiquidationPosition, LiquidationEvent, LiquidationReport
from agents.liquidation.models.schemas import (
    PositionResponse, LiquidationEventResponse, ReportResponse, HealthResponse
)

router = APIRouter(prefix="/api/v1/liquidation", tags=["liquidation"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            total = await db.execute(
                select(func.count()).select_from(LiquidationPosition)
                .where(LiquidationPosition.is_active == True)
            )
            high_risk = await db.execute(
                select(func.count()).select_from(LiquidationPosition)
                .where(
                    LiquidationPosition.is_active == True,
                    LiquidationPosition.risk_level.in_(["high", "critical"]),
                )
            )
            predicted = await db.execute(
                select(func.count()).select_from(LiquidationEvent)
                .where(LiquidationEvent.was_predicted == True)
            )
            resp.positions_monitored = total.scalar() or 0
            resp.high_risk_count = high_risk.scalar() or 0
            resp.liquidations_predicted = predicted.scalar() or 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = mapping.get(since)
    return datetime.now(timezone.utc) - timedelta(days=days) if days else None


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    risk_level: str | None = None,
    protocol: str | None = None,
    active_only: bool = True,
    since: str | None = Query(None, pattern="^(1d|7d|30d|90d|365d)$"),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """List monitored lending positions."""
    q = select(LiquidationPosition)
    cutoff = _parse_since(since)
    if cutoff:
        q = q.where(LiquidationPosition.last_checked >= cutoff)
    if active_only:
        q = q.where(LiquidationPosition.is_active == True)
    if risk_level:
        q = q.where(LiquidationPosition.risk_level == risk_level)
    if protocol:
        q = q.where(LiquidationPosition.protocol == protocol)
    q = q.order_by(LiquidationPosition.health_factor).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/positions/at-risk", response_model=list[PositionResponse])
async def at_risk_positions(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """Get all positions at high/critical risk of liquidation."""
    result = await db.execute(
        select(LiquidationPosition)
        .where(
            LiquidationPosition.is_active == True,
            LiquidationPosition.risk_level.in_(["high", "critical"]),
        )
        .order_by(LiquidationPosition.health_factor)
    )
    return list(result.scalars().all())


@router.get("/events", response_model=list[LiquidationEventResponse])
async def list_events(
    limit: int = Query(20, le=100),
    predicted_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """List liquidation events."""
    q = select(LiquidationEvent)
    if predicted_only:
        q = q.where(LiquidationEvent.was_predicted == True)
    q = q.order_by(LiquidationEvent.occurred_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/reports", response_model=list[ReportResponse])
async def list_reports(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(LiquidationReport).order_by(LiquidationReport.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.post("/scan", status_code=202)
async def trigger_scan(
    _key: bool = Depends(verify_api_key),
):
    """Manually trigger a position scan."""
    from agents.liquidation.services.position_monitor import scan_all_positions
    import asyncio
    asyncio.create_task(scan_all_positions())
    return {"status": "scan_started"}
