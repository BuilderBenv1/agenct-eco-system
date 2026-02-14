from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DCAConfigCreate(BaseModel):
    wallet_address: str
    token_address: str
    token_symbol: str
    amount_usd: float
    frequency: str = "daily"
    buy_dips: bool = False
    dip_threshold_pct: float = 10.0
    take_profit_pct: float = 100.0
    take_profit_sell_pct: float = 25.0


class DCAConfigUpdate(BaseModel):
    amount_usd: Optional[float] = None
    frequency: Optional[str] = None
    buy_dips: Optional[bool] = None
    dip_threshold_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    take_profit_sell_pct: Optional[float] = None
    is_active: Optional[bool] = None


class DCAConfigResponse(BaseModel):
    id: int
    wallet_address: str
    token_address: str
    token_symbol: str
    amount_usd: float
    frequency: str
    buy_dips: bool
    dip_threshold_pct: float
    take_profit_pct: float
    take_profit_sell_pct: float
    is_active: bool
    next_execution_at: Optional[datetime]
    total_invested_usd: float
    total_tokens_bought: float
    avg_cost_basis: float

    model_config = {"from_attributes": True}


class DCAPurchaseResponse(BaseModel):
    id: int
    config_id: int
    amount_usd: float
    tokens_received: float
    price_at_buy: float
    tx_hash: Optional[str]
    was_dip_buy: bool
    executed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DCAStatsResponse(BaseModel):
    total_configs: int
    active_configs: int
    total_invested_usd: float
    total_purchases: int
    dip_buys: int
    avg_cost_basis: float


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "dca"
    version: str = "1.0.0"
    active_configs: int = 0
    total_purchases: int = 0
