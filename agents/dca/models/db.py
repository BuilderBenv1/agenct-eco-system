from sqlalchemy import (
    Column, Integer, String, Text, Float,
    Boolean, DateTime, Index, ForeignKey
)
from shared.models.base import Base, TimestampMixin


class DCAConfig(Base, TimestampMixin):
    __tablename__ = "dca_configs"

    id = Column(Integer, primary_key=True)
    wallet_address = Column(String(66), nullable=False)
    token_address = Column(String(66), nullable=False)
    token_symbol = Column(String(20), nullable=False)

    # Strategy params
    amount_usd = Column(Float, nullable=False)  # USD per purchase
    frequency = Column(String(20), default="daily")  # daily, weekly, biweekly, monthly
    buy_dips = Column(Boolean, default=False)
    dip_threshold_pct = Column(Float, default=10.0)  # % drop to trigger 2x buy
    take_profit_pct = Column(Float, default=100.0)  # % gain to trigger sell
    take_profit_sell_pct = Column(Float, default=25.0)  # % of holdings to sell at TP

    # State
    is_active = Column(Boolean, default=True)
    next_execution_at = Column(DateTime(timezone=True))

    # Tracking
    total_invested_usd = Column(Float, default=0.0)
    total_tokens_bought = Column(Float, default=0.0)
    avg_cost_basis = Column(Float, default=0.0)

    __table_args__ = (
        Index("idx_dca_configs_wallet", "wallet_address"),
        Index("idx_dca_configs_active", "is_active"),
    )


class DCAPurchase(Base):
    __tablename__ = "dca_purchases"

    id = Column(Integer, primary_key=True)
    config_id = Column(Integer, ForeignKey("dca_configs.id"), nullable=False)
    amount_usd = Column(Float, nullable=False)
    tokens_received = Column(Float, default=0.0)
    price_at_buy = Column(Float, default=0.0)
    tx_hash = Column(String(66))
    was_dip_buy = Column(Boolean, default=False)
    executed_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_dca_purchases_config", "config_id"),
        Index("idx_dca_purchases_executed", "executed_at"),
    )


class DCAReport(Base):
    __tablename__ = "dca_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    total_configs = Column(Integer, default=0)
    total_invested = Column(Float, default=0.0)
    current_value = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    purchases_made = Column(Integer, default=0)
    dip_buys_made = Column(Integer, default=0)

    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
