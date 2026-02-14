from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SniperConfigCreate(BaseModel):
    wallet_address: str
    max_buy_amount_usd: float = 50.0
    min_liquidity_usd: float = 5000.0
    max_buy_tax_pct: float = 10.0
    require_renounced: bool = False
    require_lp_burned: bool = False
    take_profit_multiplier: float = 2.0
    stop_loss_pct: float = 50.0


class SniperConfigUpdate(BaseModel):
    max_buy_amount_usd: Optional[float] = None
    min_liquidity_usd: Optional[float] = None
    max_buy_tax_pct: Optional[float] = None
    require_renounced: Optional[bool] = None
    require_lp_burned: Optional[bool] = None
    take_profit_multiplier: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    is_active: Optional[bool] = None


class SniperConfigResponse(BaseModel):
    id: int
    wallet_address: str
    max_buy_amount_usd: float
    min_liquidity_usd: float
    max_buy_tax_pct: float
    require_renounced: bool
    require_lp_burned: bool
    take_profit_multiplier: float
    stop_loss_pct: float
    is_active: bool
    total_trades: int
    profitable_trades: int
    total_pnl_usd: float

    model_config = {"from_attributes": True}


class SniperTradeResponse(BaseModel):
    id: int
    config_id: int
    token_address: str
    token_symbol: Optional[str]
    buy_price: Optional[float]
    buy_amount_usd: Optional[float]
    buy_tx_hash: Optional[str]
    bought_at: Optional[datetime]
    sell_price: Optional[float]
    sell_amount_usd: Optional[float]
    pnl_usd: Optional[float]
    pnl_pct: Optional[float]
    status: str
    safety_score: Optional[int]

    model_config = {"from_attributes": True}


class SniperLaunchResponse(BaseModel):
    id: int
    token_address: str
    token_symbol: Optional[str]
    pair_address: Optional[str]
    initial_liquidity_usd: Optional[float]
    deployer_address: Optional[str]
    passed_filters: bool
    reason_rejected: Optional[str]
    detected_at: Optional[datetime]

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "sniper"
    version: str = "1.0.0"
    active_configs: int = 0
    launches_detected: int = 0
    open_trades: int = 0
    win_rate: float = 0
