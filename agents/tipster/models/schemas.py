from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class SignalParsed(BaseModel):
    token_symbol: str
    token_name: Optional[str] = None
    token_address: Optional[str] = None
    chain: str = "avalanche"
    signal_type: str = Field(..., pattern="^(BUY|SELL|HOLD|AVOID)$")
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    entry_price: Optional[float] = None
    target_prices: list[float] = []
    stop_loss: Optional[float] = None
    timeframe: Optional[str] = None
    reasoning: str = ""


class SignalResponse(BaseModel):
    id: int
    token_symbol: Optional[str]
    signal_type: str
    confidence: float
    entry_price: Optional[float]
    target_prices: list
    claude_analysis: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ChannelResponse(BaseModel):
    channel_id: int
    channel_name: str
    channel_username: Optional[str]
    is_active: bool
    reliability_score: float
    total_signals: int
    profitable_signals: int

    model_config = {"from_attributes": True}


class PriceCheckResponse(BaseModel):
    signal_id: int
    token_symbol: str
    price_at_signal: Optional[float]
    current_price: Optional[float]
    price_change_pct: Optional[float]
    checked_at: datetime

    model_config = {"from_attributes": True}


class ReportResponse(BaseModel):
    id: int
    report_type: str
    period_start: datetime
    period_end: datetime
    total_signals: int
    profitable_signals: int
    avg_return_pct: Optional[float]
    report_text: Optional[str]
    proof_tx_hash: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "tipster"
    version: str = "1.0.0"
    channels_active: int = 0
    signals_today: int = 0


class AddChannelRequest(BaseModel):
    channel_id: int
    channel_name: str
    channel_username: Optional[str] = None
