"""
DCA Bot REST API routes.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.dca.models.db import DCAConfig, DCAPurchase
from agents.dca.models.schemas import (
    DCAConfigCreate, DCAConfigUpdate, DCAConfigResponse,
    DCAPurchaseResponse, DCAStatsResponse, HealthResponse,
)

router = APIRouter(prefix="/api/v1/dca", tags=["dca"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            active = await db.execute(
                select(func.count()).select_from(DCAConfig).where(DCAConfig.is_active == True)
            )
            purchases = await db.execute(select(func.count()).select_from(DCAPurchase))
            resp.active_configs = active.scalar() or 0
            resp.total_purchases = purchases.scalar() or 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = mapping.get(since)
    return datetime.now(timezone.utc) - timedelta(days=days) if days else None


@router.get("/configs", response_model=list[DCAConfigResponse])
async def list_configs(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(DCAConfig)
    if active_only:
        q = q.where(DCAConfig.is_active == True)
    q = q.order_by(DCAConfig.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/configs", response_model=DCAConfigResponse)
async def create_config(
    body: DCAConfigCreate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    freq_deltas = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}
    next_exec = datetime.now(timezone.utc) + timedelta(days=freq_deltas.get(body.frequency, 1))

    config = DCAConfig(
        wallet_address=body.wallet_address,
        token_address=body.token_address,
        token_symbol=body.token_symbol,
        amount_usd=body.amount_usd,
        frequency=body.frequency,
        buy_dips=body.buy_dips,
        dip_threshold_pct=body.dip_threshold_pct,
        take_profit_pct=body.take_profit_pct,
        take_profit_sell_pct=body.take_profit_sell_pct,
        next_execution_at=next_exec,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.put("/configs/{config_id}", response_model=DCAConfigResponse)
async def update_config(
    config_id: int,
    body: DCAConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await db.execute(
            update(DCAConfig).where(DCAConfig.id == config_id).values(**updates)
        )
        await db.commit()

    result = await db.execute(select(DCAConfig).where(DCAConfig.id == config_id))
    config = result.scalar_one_or_none()
    return config


@router.delete("/configs/{config_id}")
async def deactivate_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    await db.execute(
        update(DCAConfig).where(DCAConfig.id == config_id).values(is_active=False)
    )
    await db.commit()
    return {"status": "deactivated", "config_id": config_id}


@router.get("/purchases", response_model=list[DCAPurchaseResponse])
async def list_purchases(
    config_id: int | None = None,
    limit: int = Query(50, le=200),
    since: str | None = Query(None, pattern="^(1d|7d|30d|90d|365d)$"),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(DCAPurchase)
    cutoff = _parse_since(since)
    if cutoff:
        q = q.where(DCAPurchase.executed_at >= cutoff)
    if config_id:
        q = q.where(DCAPurchase.config_id == config_id)
    q = q.order_by(DCAPurchase.executed_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/stats", response_model=DCAStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    from agents.dca.services.tracker import get_dca_stats
    stats = await get_dca_stats()
    return DCAStatsResponse(
        total_configs=stats.get("total_configs", 0),
        active_configs=stats.get("active_configs", 0),
        total_invested_usd=stats.get("total_invested_usd", 0),
        total_purchases=stats.get("total_purchases", 0),
        dip_buys=stats.get("dip_buys", 0),
        avg_cost_basis=0,
    )


@router.post("/execute")
async def trigger_execute(
    config_id: int,
    _key: bool = Depends(verify_api_key),
):
    from agents.dca.services.executor import execute_manual
    result = await execute_manual(config_id)
    return result
