from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SOSConfigCreate(BaseModel):
    wallet_address: str
    tokens_to_protect: list[dict] = []
    crash_threshold_pct: float = 15.0
    protocol_tvl_threshold_pct: float = 50.0
    health_factor_threshold: float = 1.05
    exit_to_token: str = "USDC"


class SOSConfigUpdate(BaseModel):
    tokens_to_protect: Optional[list[dict]] = None
    crash_threshold_pct: Optional[float] = None
    protocol_tvl_threshold_pct: Optional[float] = None
    health_factor_threshold: Optional[float] = None
    exit_to_token: Optional[str] = None
    is_active: Optional[bool] = None


class SOSConfigResponse(BaseModel):
    id: int
    wallet_address: str
    tokens_to_protect: list
    crash_threshold_pct: float
    protocol_tvl_threshold_pct: float
    health_factor_threshold: float
    exit_to_token: str
    is_active: bool
    triggers_fired: int
    total_value_saved_usd: float

    model_config = {"from_attributes": True}


class SOSEventResponse(BaseModel):
    id: int
    config_id: int
    trigger_type: str
    trigger_details: dict
    tokens_exited: list
    total_value_saved_usd: float
    exit_tx_hashes: list
    triggered_at: Optional[datetime]

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "sos"
    version: str = "1.0.0"
    active_configs: int = 0
    events_triggered: int = 0
    total_value_saved_usd: float = 0
