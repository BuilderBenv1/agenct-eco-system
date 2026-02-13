from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SourceResponse(BaseModel):
    id: int
    source_type: str
    name: str
    url: Optional[str]
    is_active: bool
    category: Optional[str]
    reliability_score: float
    last_fetched: Optional[datetime]

    model_config = {"from_attributes": True}


class SentimentResponse(BaseModel):
    id: int
    item_id: int
    overall_sentiment: Optional[str]
    sentiment_score: Optional[float]
    tokens_mentioned: list
    topics: list
    key_claims: list
    analyzed_at: datetime

    model_config = {"from_attributes": True}


class TrendResponse(BaseModel):
    id: int
    narrative_name: str
    narrative_category: Optional[str]
    description: Optional[str]
    strength: float
    momentum: Optional[str]
    mention_count: int
    related_tokens: list
    is_active: bool

    model_config = {"from_attributes": True}


class NarrativeReportResponse(BaseModel):
    id: int
    report_type: str
    period_start: datetime
    period_end: datetime
    top_narratives: list
    market_sentiment: Optional[str]
    sentiment_score: Optional[float]
    emerging_trends: list
    fading_trends: list
    report_text: Optional[str]
    proof_tx_hash: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    agent: str = "narrative"
    version: str = "1.0.0"
    sources_active: int = 0
    trends_active: int = 0


class AddSourceRequest(BaseModel):
    source_type: str  # 'rss', 'telegram', 'coingecko'
    name: str
    url: Optional[str] = None
    channel_id: Optional[int] = None
    channel_username: Optional[str] = None
    category: Optional[str] = None
