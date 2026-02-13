from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ScanResponse(BaseModel):
    id: int
    contract_address: str
    token_symbol: Optional[str]
    token_name: Optional[str]
    deployer_address: Optional[str]
    overall_risk_score: int
    risk_label: Optional[str]
    honeypot_score: int
    ownership_concentration_score: int
    liquidity_lock_score: int
    code_similarity_rug_score: int
    tax_manipulation_score: int
    red_flags: list
    actual_outcome: Optional[str]
    scanned_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ScanRequest(BaseModel):
    contract_address: str


class AuditReportResponse(BaseModel):
    id: int
    report_type: str
    total_scanned: int
    flagged_danger: int
    confirmed_rugs: int
    precision_pct: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "auditor"
    version: str = "1.0.0"
    total_scanned: int = 0
    flagged_danger: int = 0
    confirmed_rugs: int = 0
