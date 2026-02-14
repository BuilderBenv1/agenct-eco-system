from sqlalchemy import (
    Column, Integer, String, Text, Float,
    Boolean, DateTime, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from shared.models.base import Base, TimestampMixin


class YieldOpportunity(Base, TimestampMixin):
    __tablename__ = "yield_opportunities"

    id = Column(Integer, primary_key=True)
    protocol = Column(String(50), nullable=False)
    pool_name = Column(String(255), nullable=False)
    pool_address = Column(String(66))
    pool_type = Column(String(30))  # 'lending', 'lp', 'staking', 'vault'

    # Tokens involved
    token_a = Column(String(20))
    token_b = Column(String(20))
    token_a_address = Column(String(66))
    token_b_address = Column(String(66))

    # Yield metrics
    apy = Column(Float, default=0.0)
    base_apy = Column(Float, default=0.0)       # From trading fees / interest
    reward_apy = Column(Float, default=0.0)      # From token incentives
    tvl_usd = Column(Float, default=0.0)

    # Risk scoring (0-100, lower = safer)
    risk_score = Column(Integer, default=50)
    risk_factors = Column(JSONB, default=[])

    # Risk-adjusted return
    risk_adjusted_apy = Column(Float, default=0.0)  # APY / risk_score * 100

    # Advanced risk metrics
    sharpe_ratio = Column(Float)
    sortino_ratio = Column(Float)
    max_drawdown = Column(Float)          # Percentage, e.g. -12.4
    volatility_30d = Column(Float)        # Annualized 30-day volatility
    var_95 = Column(Float)                # 95% Value at Risk (daily)
    profit_factor = Column(Float)

    # Recommendation
    recommendation = Column(String(20))  # 'strong_buy', 'buy', 'hold', 'avoid'
    analysis_text = Column(Text)

    # Tracking
    is_active = Column(Boolean, default=True)
    last_updated = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_yield_protocol", "protocol"),
        Index("idx_yield_apy", apy.desc()),
        Index("idx_yield_risk_adj", risk_adjusted_apy.desc()),
        Index("idx_yield_tvl", tvl_usd.desc()),
        Index("idx_yield_active", "is_active"),
    )


class YieldPortfolio(Base):
    __tablename__ = "yield_portfolios"

    id = Column(Integer, primary_key=True)
    model_type = Column(String(30), nullable=False)  # conservative, balanced, aggressive
    snapshot_date = Column(DateTime(timezone=True), nullable=False)

    # Portfolio composition
    allocations = Column(JSONB, default=[])  # [{pool_id, weight, apy, risk}]
    total_positions = Column(Integer, default=0)

    # Performance
    portfolio_apy = Column(Float, default=0.0)
    portfolio_risk = Column(Float, default=0.0)
    avax_benchmark_apy = Column(Float, default=0.0)  # AVAX staking yield
    alpha_vs_benchmark = Column(Float, default=0.0)   # Portfolio APY - benchmark

    created_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_portfolio_model", "model_type"),
        Index("idx_portfolio_date", snapshot_date.desc()),
    )


class YieldReport(Base):
    __tablename__ = "yield_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    total_opportunities = Column(Integer, default=0)
    avg_apy = Column(Float, default=0.0)
    best_risk_adjusted = Column(JSONB, default=[])  # Top 5 opportunities
    portfolio_performance = Column(JSONB, default={})  # By model type
    alpha_vs_avax = Column(Float, default=0.0)

    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
