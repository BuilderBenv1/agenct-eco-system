from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float,
    Boolean, DateTime, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from shared.models.base import Base, TimestampMixin


class NarrativeSource(Base, TimestampMixin):
    __tablename__ = "narrative_sources"

    id = Column(Integer, primary_key=True)
    source_type = Column(String(30), nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(Text)
    channel_id = Column(BigInteger)
    channel_username = Column(String(255))
    is_active = Column(Boolean, default=True)
    category = Column(String(50))
    reliability_score = Column(Float, default=0.5)
    last_fetched = Column(DateTime(timezone=True))

    items = relationship("NarrativeItem", back_populates="source")


class NarrativeItem(Base):
    __tablename__ = "narrative_items"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("narrative_sources.id", ondelete="CASCADE"))
    external_id = Column(String(255))
    title = Column(Text)
    content = Column(Text, nullable=False)
    url = Column(Text)
    author = Column(String(255))
    published_at = Column(DateTime(timezone=True))
    fetched_at = Column(DateTime(timezone=True), server_default="now()")

    source = relationship("NarrativeSource", back_populates="items")
    sentiment = relationship("NarrativeSentiment", back_populates="item", uselist=False)

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_external"),
    )


class NarrativeSentiment(Base):
    __tablename__ = "narrative_sentiments"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("narrative_items.id", ondelete="CASCADE"), unique=True)
    overall_sentiment = Column(String(20))
    sentiment_score = Column(Float)
    tokens_mentioned = Column(JSONB, default=[])
    topics = Column(JSONB, default=[])
    key_claims = Column(JSONB, default=[])
    claude_reasoning = Column(Text)
    analyzed_at = Column(DateTime(timezone=True), server_default="now()")

    item = relationship("NarrativeItem", back_populates="sentiment")


class NarrativeTrend(Base, TimestampMixin):
    __tablename__ = "narrative_trends"

    id = Column(Integer, primary_key=True)
    narrative_name = Column(String(255), nullable=False)
    narrative_category = Column(String(50))
    description = Column(Text)
    strength = Column(Float, default=0.0)
    momentum = Column(String(20))
    first_detected = Column(DateTime(timezone=True), server_default="now()")
    last_seen = Column(DateTime(timezone=True), server_default="now()")
    mention_count = Column(Integer, default=1)
    related_tokens = Column(JSONB, default=[])
    supporting_items = Column(JSONB, default=[])
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("idx_narrative_trends_category", "narrative_category"),
        Index("idx_narrative_trends_strength", strength.desc()),
    )


class NarrativeReport(Base):
    __tablename__ = "narrative_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    top_narratives = Column(JSONB, default=[])
    market_sentiment = Column(String(20))
    sentiment_score = Column(Float)
    emerging_trends = Column(JSONB, default=[])
    fading_trends = Column(JSONB, default=[])
    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
