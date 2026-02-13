"""
Tipster Agent REST API routes.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key, require_subscription
from agents.tipster.config import AGENT_ERC8004_ID
from agents.tipster.models.db import (
    TipsterChannel, TipsterSignal, TipsterPriceCheck, TipsterReport
)
from agents.tipster.models.schemas import (
    SignalResponse, ChannelResponse, ReportResponse, HealthResponse, AddChannelRequest
)

router = APIRouter(prefix="/api/v1/tipster", tags=["tipster"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            channels = await db.execute(
                select(func.count()).select_from(TipsterChannel).where(TipsterChannel.is_active == True)
            )
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            signals = await db.execute(
                select(func.count()).select_from(TipsterSignal).where(TipsterSignal.created_at >= today_start)
            )
            resp.channels_active = channels.scalar() or 0
            resp.signals_today = signals.scalar() or 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


@router.get("/signals", response_model=list[SignalResponse])
async def list_signals(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    signal_type: str | None = None,
    token: str | None = None,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(TipsterSignal).where(TipsterSignal.is_valid == True)
    if signal_type:
        q = q.where(TipsterSignal.signal_type == signal_type.upper())
    if token:
        q = q.where(TipsterSignal.token_symbol == token.upper())
    if min_confidence > 0:
        q = q.where(TipsterSignal.confidence >= min_confidence)
    q = q.order_by(TipsterSignal.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    signals = result.scalars().all()
    return [
        SignalResponse(
            id=s.id,
            token_symbol=s.token_symbol,
            signal_type=s.signal_type,
            confidence=s.confidence,
            entry_price=float(s.entry_price) if s.entry_price else None,
            target_prices=s.target_prices or [],
            claude_analysis=s.claude_analysis,
            created_at=s.created_at,
        )
        for s in signals
    ]


@router.get("/signals/{signal_id}", response_model=SignalResponse)
async def get_signal(
    signal_id: int,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(select(TipsterSignal).where(TipsterSignal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return SignalResponse(
        id=signal.id,
        token_symbol=signal.token_symbol,
        signal_type=signal.signal_type,
        confidence=signal.confidence,
        entry_price=float(signal.entry_price) if signal.entry_price else None,
        target_prices=signal.target_prices or [],
        claude_analysis=signal.claude_analysis,
        created_at=signal.created_at,
    )


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(TipsterChannel).order_by(TipsterChannel.reliability_score.desc())
    )
    return list(result.scalars().all())


@router.post("/channels", response_model=ChannelResponse, status_code=201)
async def add_channel(
    req: AddChannelRequest,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    existing = await db.execute(
        select(TipsterChannel).where(TipsterChannel.channel_id == req.channel_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Channel already exists")
    ch = TipsterChannel(
        channel_id=req.channel_id,
        channel_name=req.channel_name,
        channel_username=req.channel_username,
    )
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return ch


@router.get("/reports", response_model=list[ReportResponse])
async def list_reports(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(TipsterReport).order_by(TipsterReport.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/reports/latest", response_model=ReportResponse)
async def latest_report(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(TipsterReport).order_by(TipsterReport.created_at.desc()).limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="No reports yet")
    return report
