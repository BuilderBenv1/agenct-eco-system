"""
SOS Emergency Bot REST API routes.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.sos.models.db import SOSConfig, SOSEvent
from agents.sos.models.schemas import (
    SOSConfigCreate, SOSConfigUpdate, SOSConfigResponse,
    SOSEventResponse, HealthResponse,
)

router = APIRouter(prefix="/api/v1/sos", tags=["sos"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            active = await db.execute(
                select(func.count()).select_from(SOSConfig).where(SOSConfig.is_active == True)
            )
            events = await db.execute(select(func.count()).select_from(SOSEvent))
            saved = await db.execute(
                select(func.coalesce(func.sum(SOSConfig.total_value_saved_usd), 0))
            )
            resp.active_configs = active.scalar() or 0
            resp.events_triggered = events.scalar() or 0
            resp.total_value_saved_usd = float(saved.scalar() or 0)
    except Exception:
        resp.status = "ok (no db)"
    return resp


@router.get("/configs", response_model=list[SOSConfigResponse])
async def list_configs(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(SOSConfig)
    if active_only:
        q = q.where(SOSConfig.is_active == True)
    q = q.order_by(SOSConfig.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/configs", response_model=SOSConfigResponse)
async def create_config(
    body: SOSConfigCreate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    config = SOSConfig(
        wallet_address=body.wallet_address,
        tokens_to_protect=body.tokens_to_protect,
        crash_threshold_pct=body.crash_threshold_pct,
        protocol_tvl_threshold_pct=body.protocol_tvl_threshold_pct,
        health_factor_threshold=body.health_factor_threshold,
        exit_to_token=body.exit_to_token,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.put("/configs/{config_id}", response_model=SOSConfigResponse)
async def update_config(
    config_id: int,
    body: SOSConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await db.execute(
            update(SOSConfig).where(SOSConfig.id == config_id).values(**updates)
        )
        await db.commit()
    result = await db.execute(select(SOSConfig).where(SOSConfig.id == config_id))
    return result.scalar_one_or_none()


@router.delete("/configs/{config_id}")
async def deactivate_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    await db.execute(
        update(SOSConfig).where(SOSConfig.id == config_id).values(is_active=False)
    )
    await db.commit()
    return {"status": "deactivated", "config_id": config_id}


@router.get("/events", response_model=list[SOSEventResponse])
async def list_events(
    config_id: int | None = None,
    trigger_type: str | None = None,
    limit: int = Query(50, le=200),
    since: str | None = Query(None, pattern="^(1d|7d|30d|90d|365d)$"),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(SOSEvent)
    if config_id:
        q = q.where(SOSEvent.config_id == config_id)
    if trigger_type:
        q = q.where(SOSEvent.trigger_type == trigger_type)
    if since:
        mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
        days = mapping.get(since)
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            q = q.where(SOSEvent.triggered_at >= cutoff)
    q = q.order_by(SOSEvent.triggered_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())
