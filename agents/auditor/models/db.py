from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float,
    Boolean, DateTime, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from shared.models.base import Base, TimestampMixin


class ContractScan(Base, TimestampMixin):
    __tablename__ = "contract_scans"

    id = Column(Integer, primary_key=True)
    contract_address = Column(String(66), nullable=False, unique=True)
    token_symbol = Column(String(20))
    token_name = Column(String(100))
    deployer_address = Column(String(66))
    deployment_tx = Column(String(66))
    deployment_block = Column(BigInteger)

    # Red flag scores (0-100 each)
    honeypot_score = Column(Integer, default=0)
    ownership_concentration_score = Column(Integer, default=0)
    liquidity_lock_score = Column(Integer, default=0)
    code_similarity_rug_score = Column(Integer, default=0)
    tax_manipulation_score = Column(Integer, default=0)

    # Aggregated
    overall_risk_score = Column(Integer, default=0)
    risk_label = Column(String(20))  # safe, caution, danger, rug

    # Outcome tracking
    actual_outcome = Column(String(20))  # active, rugged, abandoned, unknown
    outcome_confirmed_at = Column(DateTime(timezone=True))

    # Details
    analysis_text = Column(Text)
    red_flags = Column(JSONB, default=[])
    liquidity_usd = Column(Float)
    holder_count = Column(Integer)
    top_holder_pct = Column(Float)  # % held by top holder

    scanned_at = Column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_scan_risk", overall_risk_score.desc()),
        Index("idx_scan_label", "risk_label"),
        Index("idx_scan_token", "token_symbol"),
        Index("idx_scan_deployer", "deployer_address"),
    )


class AuditReport(Base):
    __tablename__ = "audit_reports"

    id = Column(Integer, primary_key=True)
    report_type = Column(String(30), default="daily")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    total_scanned = Column(Integer, default=0)
    flagged_danger = Column(Integer, default=0)
    confirmed_rugs = Column(Integer, default=0)
    false_positives = Column(Integer, default=0)
    precision_pct = Column(Float)
    report_text = Column(Text)
    proof_hash = Column(String(66))
    proof_tx_hash = Column(String(66))
    proof_uri = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default="now()")
