"""
Auditor Agent REST API routes.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_db, async_session
from shared.auth import verify_api_key
from agents.auditor.models.db import ContractScan, AuditReport
from agents.auditor.models.schemas import (
    ScanResponse, ScanRequest, AuditReportResponse, HealthResponse
)

router = APIRouter(prefix="/api/v1/auditor", tags=["auditor"])


@router.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse()
    if async_session is None:
        resp.status = "ok (no db)"
        return resp
    try:
        async with async_session() as db:
            total = await db.execute(
                select(func.count()).select_from(ContractScan)
            )
            flagged = await db.execute(
                select(func.count()).select_from(ContractScan)
                .where(ContractScan.risk_label.in_(["danger", "rug"]))
            )
            confirmed = await db.execute(
                select(func.count()).select_from(ContractScan)
                .where(ContractScan.actual_outcome == "rugged")
            )
            resp.total_scanned = total.scalar() or 0
            resp.flagged_danger = flagged.scalar() or 0
            resp.confirmed_rugs = confirmed.scalar() or 0
    except Exception:
        resp.status = "ok (no db)"
    return resp


@router.post("/scan", response_model=ScanResponse, status_code=201)
async def scan_contract(
    req: ScanRequest,
    _key: bool = Depends(verify_api_key),
):
    """Scan a contract address for rug pull indicators."""
    from agents.auditor.services.scanner import scan_and_save
    from agents.auditor.services.analyzer import analyze_scan

    scan = await scan_and_save(req.contract_address)
    if not scan:
        raise HTTPException(status_code=400, detail="Failed to scan contract. It may already be scanned or invalid.")

    # Run Claude analysis
    analyzed = await analyze_scan(scan)
    final = analyzed or scan

    return ScanResponse(
        id=final.id,
        contract_address=final.contract_address,
        token_symbol=final.token_symbol,
        token_name=final.token_name,
        deployer_address=final.deployer_address,
        overall_risk_score=final.overall_risk_score,
        risk_label=final.risk_label,
        honeypot_score=final.honeypot_score,
        ownership_concentration_score=final.ownership_concentration_score,
        liquidity_lock_score=final.liquidity_lock_score,
        code_similarity_rug_score=final.code_similarity_rug_score,
        tax_manipulation_score=final.tax_manipulation_score,
        red_flags=final.red_flags or [],
        actual_outcome=final.actual_outcome,
        scanned_at=final.scanned_at,
    )


@router.get("/scans", response_model=list[ScanResponse])
async def list_scans(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    risk_label: str | None = None,
    min_risk: int = Query(0, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """List scanned contracts, optionally filtered by risk."""
    q = select(ContractScan)
    if risk_label:
        q = q.where(ContractScan.risk_label == risk_label)
    if min_risk > 0:
        q = q.where(ContractScan.overall_risk_score >= min_risk)
    q = q.order_by(ContractScan.overall_risk_score.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    scans = result.scalars().all()
    return [
        ScanResponse(
            id=s.id,
            contract_address=s.contract_address,
            token_symbol=s.token_symbol,
            token_name=s.token_name,
            deployer_address=s.deployer_address,
            overall_risk_score=s.overall_risk_score,
            risk_label=s.risk_label,
            honeypot_score=s.honeypot_score,
            ownership_concentration_score=s.ownership_concentration_score,
            liquidity_lock_score=s.liquidity_lock_score,
            code_similarity_rug_score=s.code_similarity_rug_score,
            tax_manipulation_score=s.tax_manipulation_score,
            red_flags=s.red_flags or [],
            actual_outcome=s.actual_outcome,
            scanned_at=s.scanned_at,
        )
        for s in scans
    ]


@router.get("/scans/{contract_address}", response_model=ScanResponse)
async def get_scan(
    contract_address: str,
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """Get scan results for a specific contract."""
    result = await db.execute(
        select(ContractScan).where(ContractScan.contract_address == contract_address)
    )
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=404, detail="Contract not scanned")
    return ScanResponse(
        id=scan.id,
        contract_address=scan.contract_address,
        token_symbol=scan.token_symbol,
        token_name=scan.token_name,
        deployer_address=scan.deployer_address,
        overall_risk_score=scan.overall_risk_score,
        risk_label=scan.risk_label,
        honeypot_score=scan.honeypot_score,
        ownership_concentration_score=scan.ownership_concentration_score,
        liquidity_lock_score=scan.liquidity_lock_score,
        code_similarity_rug_score=scan.code_similarity_rug_score,
        tax_manipulation_score=scan.tax_manipulation_score,
        red_flags=scan.red_flags or [],
        actual_outcome=scan.actual_outcome,
        scanned_at=scan.scanned_at,
    )


@router.get("/reports", response_model=list[AuditReportResponse])
async def list_reports(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """List audit reports."""
    result = await db.execute(
        select(AuditReport).order_by(AuditReport.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/reports/latest", response_model=AuditReportResponse)
async def latest_report(
    db: AsyncSession = Depends(get_db),
    _key: bool = Depends(verify_api_key),
):
    """Get the latest audit report."""
    result = await db.execute(
        select(AuditReport).order_by(AuditReport.created_at.desc()).limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="No reports yet")
    return report
