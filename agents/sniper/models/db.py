from sqlalchemy import (
    Column, Integer, String, Text, Float,
    Boolean, DateTime, Index, ForeignKey
)
from shared.models.base import Base, TimestampMixin


class SniperConfig(Base, TimestampMixin):
    __tablename__ = "sniper_configs"

    id = Column(Integer, primary_key=True)
    wallet_address = Column(String(66), nullable=False)
    max_buy_amount_usd = Column(Float, default=50.0)
    min_liquidity_usd = Column(Float, default=5000.0)
    max_buy_tax_pct = Column(Float, default=10.0)
    require_renounced = Column(Boolean, default=False)
    require_lp_burned = Column(Boolean, default=False)
    take_profit_multiplier = Column(Float, default=2.0)
    stop_loss_pct = Column(Float, default=50.0)
    is_active = Column(Boolean, default=True)

    # Stats
    total_trades = Column(Integer, default=0)
    profitable_trades = Column(Integer, default=0)
    total_pnl_usd = Column(Float, default=0.0)

    __table_args__ = (
        Index("idx_sniper_configs_wallet", "wallet_address"),
        Index("idx_sniper_configs_active", "is_active"),
    )


class SniperTrade(Base):
    __tablename__ = "sniper_trades"

    id = Column(Integer, primary_key=True)
    config_id = Column(Integer, ForeignKey("sniper_configs.id"), nullable=False)
    token_address = Column(String(66), nullable=False)
    token_symbol = Column(String(20))

    # Buy
    buy_price = Column(Float)
    buy_amount_usd = Column(Float)
    buy_tx_hash = Column(String(66))
    bought_at = Column(DateTime(timezone=True), server_default="now()")

    # Sell
    sell_price = Column(Float)
    sell_amount_usd = Column(Float)
    sell_tx_hash = Column(String(66))
    sold_at = Column(DateTime(timezone=True))

    # P&L
    pnl_usd = Column(Float)
    pnl_pct = Column(Float)
    status = Column(String(20), default="open")  # open, closed, stopped_out

    # Safety
    safety_score = Column(Integer)  # From Rug Auditor cross-check

    __table_args__ = (
        Index("idx_sniper_trades_config", "config_id"),
        Index("idx_sniper_trades_status", "status"),
        Index("idx_sniper_trades_token", "token_address"),
    )


class SniperLaunch(Base):
    __tablename__ = "sniper_launches"

    id = Column(Integer, primary_key=True)
    token_address = Column(String(66), nullable=False)
    token_symbol = Column(String(20))
    pair_address = Column(String(66))
    initial_liquidity_usd = Column(Float)
    deployer_address = Column(String(66))
    passed_filters = Column(Boolean, default=False)
    reason_rejected = Column(Text)
    detected_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_sniper_launches_token", "token_address"),
        Index("idx_sniper_launches_detected", "detected_at"),
    )


class SniperReport(Base):
    __tablename__ = "sniper_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    launches_detected = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)
    profitable_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_pnl_usd = Column(Float, default=0.0)

    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
