from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from shared.models.base import Base


class ConvergenceSignal(Base):
    __tablename__ = "convergence_signals"

    id = Column(Integer, primary_key=True)
    token_symbol = Column(String(20), nullable=False)
    token_address = Column(String(66))
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    tipster_signal_id = Column(Integer, ForeignKey("tipster_signals.id"))
    whale_tx_id = Column(Integer, ForeignKey("whale_transactions.id"))
    narrative_sentiment_id = Column(Integer, ForeignKey("narrative_sentiments.id"))

    agent_count = Column(Integer, nullable=False, default=1)
    agents_involved = Column(JSONB, default=[])

    tipster_raw_score = Column(Float)
    whale_raw_score = Column(Float)
    narrative_raw_score = Column(Float)

    convergence_multiplier = Column(Float, nullable=False, default=1.0)
    convergence_score = Column(Float, nullable=False, default=0.0)

    signal_direction = Column(String(20))
    direction_agreement = Column(Boolean, default=False)

    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    convergence_analysis = Column(Text)

    detected_at = Column(DateTime(timezone=True), server_default="now()")
    created_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_convergence_token", "token_symbol"),
        Index("idx_convergence_detected", detected_at.desc()),
        Index("idx_convergence_score", convergence_score.desc()),
    )


class ConvergenceBoost(Base):
    __tablename__ = "convergence_boosts"

    id = Column(Integer, primary_key=True)
    convergence_signal_id = Column(
        Integer, ForeignKey("convergence_signals.id", ondelete="CASCADE")
    )
    agent_name = Column(String(50), nullable=False)
    original_score = Column(Float, nullable=False)
    boosted_score = Column(Float, nullable=False)
    multiplier = Column(Float, nullable=False, default=1.0)
    applied_at = Column(DateTime(timezone=True), server_default="now()")
