"""
Grid Trading Bot REST API routes.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.grid.models.db import GridConfig, GridOrder
from agents.grid.models.schemas import (
    GridConfigCreate, GridConfigUpdate, GridConfigResponse,
    GridOrderResponse, GridStatsResponse, HealthResponse,
)

router = APIRouter(prefix="/api/v1/grid", tags=["grid"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            active = await db.execute(
                select(func.count()).select_from(GridConfig).where(GridConfig.is_active == True)
            )
            cycles = await db.execute(
                select(func.coalesce(func.sum(GridConfig.completed_cycles), 0))
            )
            resp.active_grids = active.scalar() or 0
            resp.total_cycles = cycles.scalar() or 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


@router.get("/configs", response_model=list[GridConfigResponse])
async def list_configs(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(GridConfig)
    if active_only:
        q = q.where(GridConfig.is_active == True)
    q = q.order_by(GridConfig.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/configs", response_model=GridConfigResponse)
async def create_config(
    body: GridConfigCreate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    config = GridConfig(
        wallet_address=body.wallet_address,
        token_symbol=body.token_symbol,
        token_address=body.token_address,
        lower_price=body.lower_price,
        upper_price=body.upper_price,
        grid_levels=body.grid_levels,
        amount_per_grid=body.amount_per_grid,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    # Initialize grid orders
    from agents.grid.services.engine import initialize_grid_orders
    await initialize_grid_orders(config.id)

    return config


@router.put("/configs/{config_id}", response_model=GridConfigResponse)
async def update_config(
    config_id: int,
    body: GridConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await db.execute(
            update(GridConfig).where(GridConfig.id == config_id).values(**updates)
        )
        await db.commit()
    result = await db.execute(select(GridConfig).where(GridConfig.id == config_id))
    return result.scalar_one_or_none()


@router.delete("/configs/{config_id}")
async def deactivate_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    # Cancel pending orders
    await db.execute(
        update(GridOrder)
        .where(GridOrder.config_id == config_id, GridOrder.status == "pending")
        .values(status="cancelled")
    )
    await db.execute(
        update(GridConfig).where(GridConfig.id == config_id).values(is_active=False)
    )
    await db.commit()
    return {"status": "deactivated", "config_id": config_id}


@router.get("/orders", response_model=list[GridOrderResponse])
async def list_orders(
    config_id: int | None = None,
    status: str | None = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(GridOrder)
    if config_id:
        q = q.where(GridOrder.config_id == config_id)
    if status:
        q = q.where(GridOrder.status == status)
    q = q.order_by(GridOrder.created_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/trigger")
async def trigger_check(
    _key: bool = Depends(verify_api_key),
):
    """Manually trigger the grid order check cycle. Returns what happened."""
    from agents.grid.services.engine import check_and_fill_orders
    from shared.price_feed import get_price_by_symbol

    # First, check what price we're getting
    price = await get_price_by_symbol("AVAX")
    try:
        await check_and_fill_orders()
        return {"status": "ok", "avax_price": price, "message": "check_and_fill_orders completed"}
    except Exception as e:
        return {"status": "error", "avax_price": price, "error": str(e)}


@router.get("/stats", response_model=GridStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    active = await db.execute(
        select(func.count()).select_from(GridConfig).where(GridConfig.is_active == True)
    )
    cycles = await db.execute(
        select(func.coalesce(func.sum(GridConfig.completed_cycles), 0))
    )
    profit = await db.execute(
        select(func.coalesce(func.sum(GridConfig.total_profit_usd), 0))
    )
    pending = await db.execute(
        select(func.count()).select_from(GridOrder).where(GridOrder.status == "pending")
    )
    filled = await db.execute(
        select(func.count()).select_from(GridOrder).where(GridOrder.status == "filled")
    )
    return GridStatsResponse(
        active_grids=active.scalar() or 0,
        total_cycles=cycles.scalar() or 0,
        total_profit_usd=float(profit.scalar() or 0),
        orders_pending=pending.scalar() or 0,
        orders_filled=filled.scalar() or 0,
    )
