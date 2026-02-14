from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class GridConfigCreate(BaseModel):
    wallet_address: str
    token_symbol: str
    token_address: str
    lower_price: float
    upper_price: float
    grid_levels: int = 10
    amount_per_grid: float


class GridConfigUpdate(BaseModel):
    lower_price: Optional[float] = None
    upper_price: Optional[float] = None
    grid_levels: Optional[int] = None
    amount_per_grid: Optional[float] = None
    is_active: Optional[bool] = None


class GridConfigResponse(BaseModel):
    id: int
    wallet_address: str
    token_symbol: str
    token_address: str
    lower_price: float
    upper_price: float
    grid_levels: int
    amount_per_grid: float
    is_active: bool
    total_profit_usd: float
    completed_cycles: int

    model_config = {"from_attributes": True}


class GridOrderResponse(BaseModel):
    id: int
    config_id: int
    level_index: int
    order_type: str
    price: float
    amount: float
    amount_usd: float
    status: str
    fill_tx_hash: Optional[str]
    filled_at: Optional[datetime]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class GridStatsResponse(BaseModel):
    active_grids: int
    total_cycles: int
    total_profit_usd: float
    orders_pending: int
    orders_filled: int


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "grid"
    version: str = "1.0.0"
    active_grids: int = 0
    total_cycles: int = 0
