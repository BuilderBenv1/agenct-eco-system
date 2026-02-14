from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class YieldResponse(BaseModel):
    id: int
    protocol: str
    pool_name: str
    pool_type: Optional[str]
    token_a: Optional[str]
    token_b: Optional[str]
    apy: float = 0.0
    base_apy: float = 0.0
    reward_apy: float = 0.0
    tvl_usd: float = 0.0
    risk_score: int = 50
    risk_adjusted_apy: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    volatility_30d: Optional[float] = None
    var_95: Optional[float] = None
    profit_factor: Optional[float] = None
    recommendation: Optional[str]
    is_active: bool = True
    last_updated: Optional[datetime]

    model_config = {"from_attributes": True}


class PortfolioResponse(BaseModel):
    id: int
    model_type: str
    snapshot_date: datetime
    allocations: list = []
    total_positions: int = 0
    portfolio_apy: float = 0.0
    portfolio_risk: float = 0.0
    avax_benchmark_apy: float = 0.0
    alpha_vs_benchmark: float = 0.0
    created_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class ReportResponse(BaseModel):
    id: int
    report_type: str
    total_opportunities: int
    avg_apy: float
    alpha_vs_avax: float
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "yield_oracle"
    version: str = "1.0.0"
    opportunities_tracked: int = 0
    avg_apy: float = 0.0
    best_risk_adjusted_apy: float = 0.0
