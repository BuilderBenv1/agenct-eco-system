from sqlalchemy import (
    Column, Integer, String, Text, Float,
    Boolean, DateTime, Index, ForeignKey
)
from sqlalchemy.dialects.postgresql import JSONB
from shared.models.base import Base, TimestampMixin


class SOSConfig(Base, TimestampMixin):
    __tablename__ = "sos_configs"

    id = Column(Integer, primary_key=True)
    wallet_address = Column(String(66), nullable=False)
    tokens_to_protect = Column(JSONB, default=[])  # [{"symbol": "AVAX", "address": "0x..."}]

    # Thresholds
    crash_threshold_pct = Column(Float, default=15.0)  # % drop in 1 hour
    protocol_tvl_threshold_pct = Column(Float, default=50.0)  # % TVL drop
    health_factor_threshold = Column(Float, default=1.05)
    exit_to_token = Column(String(66), default="USDC")

    # State
    is_active = Column(Boolean, default=True)
    triggers_fired = Column(Integer, default=0)
    total_value_saved_usd = Column(Float, default=0.0)

    __table_args__ = (
        Index("idx_sos_configs_wallet", "wallet_address"),
        Index("idx_sos_configs_active", "is_active"),
    )


class SOSEvent(Base):
    __tablename__ = "sos_events"

    id = Column(Integer, primary_key=True)
    config_id = Column(Integer, ForeignKey("sos_configs.id"), nullable=False)
    trigger_type = Column(String(30), nullable=False)  # crash, hack, health, volatility
    trigger_details = Column(JSONB, default={})
    tokens_exited = Column(JSONB, default=[])
    total_value_saved_usd = Column(Float, default=0.0)
    exit_tx_hashes = Column(JSONB, default=[])
    triggered_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_sos_events_config", "config_id"),
        Index("idx_sos_events_type", "trigger_type"),
        Index("idx_sos_events_triggered", "triggered_at"),
    )


class SOSReport(Base):
    __tablename__ = "sos_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    active_configs = Column(Integer, default=0)
    events_triggered = Column(Integer, default=0)
    total_value_saved = Column(Float, default=0.0)
    triggers_by_type = Column(JSONB, default={})

    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
