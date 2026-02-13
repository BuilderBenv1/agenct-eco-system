from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float,
    Boolean, DateTime, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from shared.models.base import Base, TimestampMixin


class LiquidationPosition(Base, TimestampMixin):
    __tablename__ = "liquidation_positions"

    id = Column(Integer, primary_key=True)
    protocol = Column(String(30), nullable=False)  # 'benqi', 'aave_v3'
    wallet_address = Column(String(66), nullable=False)
    health_factor = Column(Float, nullable=False)
    risk_level = Column(String(20))  # low, medium, high, critical

    # Collateral
    collateral_token = Column(String(20))
    collateral_amount_usd = Column(Float, default=0)
    collateral_address = Column(String(66))

    # Debt
    debt_token = Column(String(20))
    debt_amount_usd = Column(Float, default=0)
    debt_address = Column(String(66))

    # Position details
    ltv = Column(Float)  # loan-to-value ratio
    liquidation_threshold = Column(Float)
    distance_to_liquidation_pct = Column(Float)  # % price drop to trigger liquidation

    # Prediction
    predicted_liquidation = Column(Boolean, default=False)
    prediction_confidence = Column(Float, default=0.0)
    predicted_at = Column(DateTime(timezone=True))

    # Alert tracking
    alert_sent = Column(Boolean, default=False)
    alert_level = Column(String(20))

    # Analysis
    analysis_text = Column(Text)
    is_active = Column(Boolean, default=True)

    detected_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_liq_pos_hf", health_factor),
        Index("idx_liq_pos_risk", "risk_level"),
        Index("idx_liq_pos_protocol", "protocol"),
        Index("idx_liq_pos_wallet", "wallet_address"),
        Index("idx_liq_pos_active", "is_active"),
    )


class LiquidationEvent(Base):
    __tablename__ = "liquidation_events"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer)  # FK to liquidation_positions
    protocol = Column(String(30), nullable=False)
    wallet_address = Column(String(66), nullable=False)
    tx_hash = Column(String(66), unique=True)
    block_number = Column(BigInteger)

    # Liquidation details
    collateral_token = Column(String(20))
    debt_token = Column(String(20))
    collateral_seized_usd = Column(Float)
    debt_repaid_usd = Column(Float)
    liquidator_address = Column(String(66))

    # Prediction tracking
    was_predicted = Column(Boolean, default=False)
    prediction_lead_time_min = Column(Integer)  # Minutes between prediction and liquidation

    occurred_at = Column(DateTime(timezone=True), server_default="now()")
    created_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_liq_event_protocol", "protocol"),
        Index("idx_liq_event_predicted", "was_predicted"),
        Index("idx_liq_event_occurred", occurred_at.desc()),
    )


class LiquidationReport(Base):
    __tablename__ = "liquidation_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    positions_monitored = Column(Integer, default=0)
    high_risk_positions = Column(Integer, default=0)
    liquidations_occurred = Column(Integer, default=0)
    liquidations_predicted = Column(Integer, default=0)
    prediction_accuracy_pct = Column(Float)
    total_value_liquidated_usd = Column(Float, default=0)

    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
