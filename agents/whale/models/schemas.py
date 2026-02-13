from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class TransactionResponse(BaseModel):
    id: int
    tx_hash: str
    tx_type: str
    from_address: Optional[str]
    to_address: Optional[str]
    token_symbol: Optional[str]
    amount_usd: Optional[float]
    decoded_method: Optional[str]
    detected_at: datetime

    model_config = {"from_attributes": True}


class WalletResponse(BaseModel):
    id: int
    address: str
    label: Optional[str]
    chain: str
    category: Optional[str]
    is_active: bool
    total_tx_tracked: int

    model_config = {"from_attributes": True}


class AnalysisResponse(BaseModel):
    id: int
    transaction_id: int
    significance: str
    analysis_text: Optional[str]
    market_impact: Optional[str]
    pattern_detected: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class WhaleReportResponse(BaseModel):
    id: int
    report_type: str
    period_start: datetime
    period_end: datetime
    total_transactions: int
    total_volume_usd: Optional[float]
    top_movers: list
    report_text: Optional[str]
    proof_tx_hash: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "whale"
    version: str = "1.0.0"
    wallets_tracked: int = 0
    transactions_today: int = 0


class AddWalletRequest(BaseModel):
    address: str = Field(..., min_length=42, max_length=66)
    label: Optional[str] = None
    category: Optional[str] = None
    chain: str = "avalanche"
