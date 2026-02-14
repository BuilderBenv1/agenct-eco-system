"""
Sniper Bot REST API routes.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.sniper.models.db import SniperConfig, SniperTrade, SniperLaunch
from agents.sniper.models.schemas import (
    SniperConfigCreate, SniperConfigUpdate, SniperConfigResponse,
    SniperTradeResponse, SniperLaunchResponse, HealthResponse,
)

router = APIRouter(prefix="/api/v1/sniper", tags=["sniper"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            active = await db.execute(
                select(func.count()).select_from(SniperConfig).where(SniperConfig.is_active == True)
            )
            launches = await db.execute(select(func.count()).select_from(SniperLaunch))
            open_trades = await db.execute(
                select(func.count()).select_from(SniperTrade).where(SniperTrade.status == "open")
            )
            total_closed = await db.execute(
                select(func.count()).select_from(SniperTrade).where(SniperTrade.status != "open")
            )
            profitable = await db.execute(
                select(func.count()).select_from(SniperTrade).where(SniperTrade.pnl_usd > 0, SniperTrade.status != "open")
            )
            closed = total_closed.scalar() or 0
            prof = profitable.scalar() or 0
            resp.active_configs = active.scalar() or 0
            resp.launches_detected = launches.scalar() or 0
            resp.open_trades = open_trades.scalar() or 0
            resp.win_rate = round(prof / closed * 100, 1) if closed > 0 else 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


@router.get("/configs", response_model=list[SniperConfigResponse])
async def list_configs(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(SniperConfig)
    if active_only:
        q = q.where(SniperConfig.is_active == True)
    result = await db.execute(q.order_by(SniperConfig.created_at.desc()))
    return list(result.scalars().all())


@router.post("/configs", response_model=SniperConfigResponse)
async def create_config(
    body: SniperConfigCreate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    config = SniperConfig(
        wallet_address=body.wallet_address,
        max_buy_amount_usd=body.max_buy_amount_usd,
        min_liquidity_usd=body.min_liquidity_usd,
        max_buy_tax_pct=body.max_buy_tax_pct,
        require_renounced=body.require_renounced,
        require_lp_burned=body.require_lp_burned,
        take_profit_multiplier=body.take_profit_multiplier,
        stop_loss_pct=body.stop_loss_pct,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.put("/configs/{config_id}", response_model=SniperConfigResponse)
async def update_config(
    config_id: int,
    body: SniperConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await db.execute(
            update(SniperConfig).where(SniperConfig.id == config_id).values(**updates)
        )
        await db.commit()
    result = await db.execute(select(SniperConfig).where(SniperConfig.id == config_id))
    return result.scalar_one_or_none()


@router.delete("/configs/{config_id}")
async def deactivate_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    await db.execute(
        update(SniperConfig).where(SniperConfig.id == config_id).values(is_active=False)
    )
    await db.commit()
    return {"status": "deactivated", "config_id": config_id}


@router.get("/trades", response_model=list[SniperTradeResponse])
async def list_trades(
    config_id: int | None = None,
    status: str | None = None,
    limit: int = Query(50, le=200),
    since: str | None = Query(None, pattern="^(1d|7d|30d|90d|365d)$"),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(SniperTrade)
    if config_id:
        q = q.where(SniperTrade.config_id == config_id)
    if status:
        q = q.where(SniperTrade.status == status)
    if since:
        mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
        days = mapping.get(since)
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            q = q.where(SniperTrade.bought_at >= cutoff)
    q = q.order_by(SniperTrade.bought_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/launches", response_model=list[SniperLaunchResponse])
async def list_launches(
    passed_only: bool = False,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(SniperLaunch)
    if passed_only:
        q = q.where(SniperLaunch.passed_filters == True)
    q = q.order_by(SniperLaunch.detected_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())
