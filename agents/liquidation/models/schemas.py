from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class PositionResponse(BaseModel):
    id: int
    protocol: str
    wallet_address: str
    health_factor: float
    risk_level: Optional[str]
    collateral_token: Optional[str]
    collateral_amount_usd: Optional[float]
    debt_token: Optional[str]
    debt_amount_usd: Optional[float]
    ltv: Optional[float]
    distance_to_liquidation_pct: Optional[float]
    predicted_liquidation: bool = False
    prediction_confidence: float = 0.0
    is_active: bool = True
    detected_at: Optional[datetime]

    model_config = {"from_attributes": True}


class LiquidationEventResponse(BaseModel):
    id: int
    protocol: str
    wallet_address: str
    collateral_token: Optional[str]
    debt_token: Optional[str]
    collateral_seized_usd: Optional[float]
    debt_repaid_usd: Optional[float]
    was_predicted: bool = False
    prediction_lead_time_min: Optional[int]
    occurred_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ReportResponse(BaseModel):
    id: int
    report_type: str
    positions_monitored: int
    high_risk_positions: int
    liquidations_occurred: int
    liquidations_predicted: int
    prediction_accuracy_pct: Optional[float]
    total_value_liquidated_usd: float = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "liquidation"
    version: str = "1.0.0"
    positions_monitored: int = 0
    high_risk_count: int = 0
    liquidations_predicted: int = 0
