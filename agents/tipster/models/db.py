from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float, Numeric,
    Boolean, DateTime, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from shared.models.base import Base, TimestampMixin


class TipsterChannel(Base, TimestampMixin):
    __tablename__ = "tipster_channels"

    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, nullable=False, unique=True)
    channel_name = Column(String(255), nullable=False)
    channel_username = Column(String(255))
    is_active = Column(Boolean, default=True)
    reliability_score = Column(Float, default=0.5)
    total_signals = Column(Integer, default=0)
    profitable_signals = Column(Integer, default=0)

    signals = relationship("TipsterSignal", back_populates="channel")


class TipsterSignal(Base):
    __tablename__ = "tipster_signals"

    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, ForeignKey("tipster_channels.channel_id"), nullable=False)
    message_id = Column(BigInteger)
    raw_text = Column(Text, nullable=False)
    token_symbol = Column(String(20))
    token_name = Column(String(100))
    token_address = Column(String(66))
    chain = Column(String(50), default="avalanche")
    signal_type = Column(String(20), nullable=False)
    confidence = Column(Float, default=0.5)
    entry_price = Column(Numeric(30, 18))
    target_prices = Column(JSONB, default=[])
    stop_loss = Column(Numeric(30, 18))
    timeframe = Column(String(30))
    parsed_at = Column(DateTime(timezone=True))
    source_url = Column(Text)
    claude_analysis = Column(Text)
    is_valid = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default="now()")

    channel = relationship("TipsterChannel", back_populates="signals")
    price_checks = relationship("TipsterPriceCheck", back_populates="signal")

    __table_args__ = (
        Index("idx_tipster_signals_token", "token_symbol"),
        Index("idx_tipster_signals_type", "signal_type"),
        Index("idx_tipster_signals_created", created_at.desc()),
    )


class TipsterPriceCheck(Base):
    __tablename__ = "tipster_price_checks"

    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, ForeignKey("tipster_signals.id", ondelete="CASCADE"))
    token_symbol = Column(String(20), nullable=False)
    coingecko_id = Column(String(100))
    price_at_signal = Column(Numeric(30, 18))
    current_price = Column(Numeric(30, 18))
    price_change_pct = Column(Float)
    checked_at = Column(DateTime(timezone=True), server_default="now()")

    signal = relationship("TipsterSignal", back_populates="price_checks")


class TipsterReport(Base):
    __tablename__ = "tipster_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="weekly")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    total_signals = Column(Integer, default=0)
    profitable_signals = Column(Integer, default=0)
    avg_return_pct = Column(Float)
    best_signal_id = Column(Integer, ForeignKey("tipster_signals.id"))
    worst_signal_id = Column(Integer, ForeignKey("tipster_signals.id"))
    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
