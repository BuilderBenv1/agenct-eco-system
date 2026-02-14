"""
Whale Agent REST API routes.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.whale.models.db import (
    WhaleWallet, WhaleTransaction, WhaleAnalysis, WhaleReport
)
from agents.whale.models.schemas import (
    TransactionResponse, WalletResponse, AnalysisResponse,
    WhaleReportResponse, HealthResponse, AddWalletRequest
)

router = APIRouter(prefix="/api/v1/whale", tags=["whale"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            wallets = await db.execute(
                select(func.count()).select_from(WhaleWallet).where(WhaleWallet.is_active == True)
            )
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            txns = await db.execute(
                select(func.count()).select_from(WhaleTransaction).where(WhaleTransaction.detected_at >= today_start)
            )
            resp.wallets_tracked = wallets.scalar() or 0
            resp.transactions_today = txns.scalar() or 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


def _parse_since(since: str | None) -> datetime | None:
    """Parse a 'since' param like '7d', '30d', '90d' into a cutoff datetime."""
    if not since:
        return None
    mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = mapping.get(since)
    if days:
        return datetime.now(timezone.utc) - timedelta(days=days)
    return None


@router.get("/transactions", response_model=list[TransactionResponse])
async def list_transactions(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    tx_type: str | None = None,
    min_usd: float = Query(0, ge=0),
    wallet_address: str | None = None,
    since: str | None = Query(None, pattern="^(1d|7d|30d|90d|365d)$"),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(WhaleTransaction)
    cutoff = _parse_since(since)
    if cutoff:
        q = q.where(WhaleTransaction.detected_at >= cutoff)
    if tx_type:
        q = q.where(WhaleTransaction.tx_type == tx_type)
    if min_usd > 0:
        q = q.where(WhaleTransaction.amount_usd >= min_usd)
    if wallet_address:
        wq = await db.execute(
            select(WhaleWallet.id).where(WhaleWallet.address == wallet_address)
        )
        wid = wq.scalar_one_or_none()
        if wid:
            q = q.where(WhaleTransaction.wallet_id == wid)
    q = q.order_by(WhaleTransaction.detected_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/transactions/{tx_id}/analysis", response_model=AnalysisResponse)
async def get_analysis(
    tx_id: int,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(WhaleAnalysis).where(WhaleAnalysis.transaction_id == tx_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


@router.get("/wallets", response_model=list[WalletResponse])
async def list_wallets(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    q = select(WhaleWallet).where(WhaleWallet.is_active == True)
    if category:
        q = q.where(WhaleWallet.category == category)
    q = q.order_by(WhaleWallet.total_tx_tracked.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/wallets", response_model=WalletResponse, status_code=201)
async def add_wallet(
    req: AddWalletRequest,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    existing = await db.execute(
        select(WhaleWallet).where(WhaleWallet.address == req.address)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Wallet already tracked")
    w = WhaleWallet(
        address=req.address,
        label=req.label,
        chain=req.chain,
        category=req.category,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


@router.get("/reports", response_model=list[WhaleReportResponse])
async def list_reports(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(WhaleReport).order_by(WhaleReport.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/reports/latest", response_model=WhaleReportResponse)
async def latest_report(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    result = await db.execute(
        select(WhaleReport).order_by(WhaleReport.created_at.desc()).limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="No reports yet")
    return report
