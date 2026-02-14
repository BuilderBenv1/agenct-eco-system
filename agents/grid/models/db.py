from sqlalchemy import (
    Column, Integer, String, Text, Float,
    Boolean, DateTime, Index, ForeignKey
)
from shared.models.base import Base, TimestampMixin


class GridConfig(Base, TimestampMixin):
    __tablename__ = "grid_configs"

    id = Column(Integer, primary_key=True)
    wallet_address = Column(String(66), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    token_address = Column(String(66), nullable=False)

    # Grid params
    lower_price = Column(Float, nullable=False)
    upper_price = Column(Float, nullable=False)
    grid_levels = Column(Integer, default=10)
    amount_per_grid = Column(Float, nullable=False)  # USD per grid level

    # State
    is_active = Column(Boolean, default=True)
    total_profit_usd = Column(Float, default=0.0)
    completed_cycles = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_grid_configs_wallet", "wallet_address"),
        Index("idx_grid_configs_active", "is_active"),
    )


class GridOrder(Base):
    __tablename__ = "grid_orders"

    id = Column(Integer, primary_key=True)
    config_id = Column(Integer, ForeignKey("grid_configs.id"), nullable=False)
    level_index = Column(Integer, nullable=False)  # 0-based grid level
    order_type = Column(String(10), nullable=False)  # 'buy' or 'sell'
    price = Column(Float, nullable=False)
    amount = Column(Float, default=0.0)  # Token amount
    amount_usd = Column(Float, default=0.0)
    status = Column(String(20), default="pending")  # pending, filled, cancelled
    fill_tx_hash = Column(String(66))
    filled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_grid_orders_config", "config_id"),
        Index("idx_grid_orders_status", "status"),
    )


class GridReport(Base):
    __tablename__ = "grid_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    active_grids = Column(Integer, default=0)
    cycles_completed = Column(Integer, default=0)
    profit_per_cycle = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    orders_filled = Column(Integer, default=0)

    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
