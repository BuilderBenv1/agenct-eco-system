from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float, Numeric,
    Boolean, DateTime, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from shared.models.base import Base, TimestampMixin


class WhaleWallet(Base, TimestampMixin):
    __tablename__ = "whale_wallets"

    id = Column(Integer, primary_key=True)
    address = Column(String(66), nullable=False, unique=True)
    label = Column(String(255))
    chain = Column(String(50), default="avalanche")
    category = Column(String(50))
    is_active = Column(Boolean, default=True)
    total_tx_tracked = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True), server_default="now()")

    transactions = relationship("WhaleTransaction", back_populates="wallet")


class WhaleTransaction(Base):
    __tablename__ = "whale_transactions"

    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey("whale_wallets.id", ondelete="CASCADE"))
    tx_hash = Column(String(66), nullable=False, unique=True)
    block_number = Column(BigInteger)
    chain = Column(String(50), default="avalanche")
    tx_type = Column(String(30), nullable=False)
    from_address = Column(String(66))
    to_address = Column(String(66))
    token_symbol = Column(String(20))
    token_address = Column(String(66))
    amount = Column(Numeric(40, 18))
    amount_usd = Column(Numeric(30, 2))
    gas_used = Column(BigInteger)
    gas_price_gwei = Column(Numeric(20, 9))
    decoded_method = Column(String(100))
    raw_input = Column(Text)
    detected_at = Column(DateTime(timezone=True), server_default="now()")

    wallet = relationship("WhaleWallet", back_populates="transactions")
    analyses = relationship("WhaleAnalysis", back_populates="transaction")

    __table_args__ = (
        Index("idx_whale_tx_wallet", "wallet_id"),
        Index("idx_whale_tx_type", "tx_type"),
        Index("idx_whale_tx_token", "token_symbol"),
        Index("idx_whale_tx_detected", detected_at.desc()),
    )


class WhaleAnalysis(Base):
    __tablename__ = "whale_analyses"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("whale_transactions.id", ondelete="CASCADE"))
    wallet_id = Column(Integer, ForeignKey("whale_wallets.id"))
    significance = Column(String(20), default="medium")
    analysis_text = Column(Text)
    market_impact = Column(Text)
    pattern_detected = Column(String(100))
    alert_sent = Column(Boolean, default=False)
    alert_chat_ids = Column(JSONB, default=[])
    created_at = Column(DateTime(timezone=True), server_default="now()")

    transaction = relationship("WhaleTransaction", back_populates="analyses")


class WhaleReport(Base):
    __tablename__ = "whale_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    total_transactions = Column(Integer, default=0)
    total_volume_usd = Column(Numeric(30, 2))
    top_movers = Column(JSONB, default=[])
    notable_patterns = Column(JSONB, default=[])
    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
