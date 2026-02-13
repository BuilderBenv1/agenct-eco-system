"""
Initialize all Supabase database tables for the Avax Agents platform.

Usage:
    python -m scripts.init_db

Requires DATABASE_URL in .env pointing to Supabase PostgreSQL.
"""
import asyncio
from sqlalchemy import text
from shared.database import engine

SCHEMA_SQL = """
-- ============================================================
-- Extensions
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TIPSTER AGENT TABLES
-- ============================================================

-- Telegram channels monitored for crypto signals
CREATE TABLE IF NOT EXISTS tipster_channels (
    id SERIAL PRIMARY KEY,
    channel_id BIGINT NOT NULL UNIQUE,
    channel_name VARCHAR(255) NOT NULL,
    channel_username VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    reliability_score REAL DEFAULT 0.5,
    total_signals INTEGER DEFAULT 0,
    profitable_signals INTEGER DEFAULT 0,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Parsed crypto trading signals
CREATE TABLE IF NOT EXISTS tipster_signals (
    id SERIAL PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT,
    raw_text TEXT NOT NULL,
    token_symbol VARCHAR(20),
    token_name VARCHAR(100),
    token_address VARCHAR(66),
    chain VARCHAR(50) DEFAULT 'avalanche',
    signal_type VARCHAR(20) NOT NULL,  -- 'BUY', 'SELL', 'HOLD', 'AVOID'
    confidence REAL DEFAULT 0.5,
    entry_price NUMERIC(30, 18),
    target_prices JSONB DEFAULT '[]',
    stop_loss NUMERIC(30, 18),
    timeframe VARCHAR(30),
    parsed_at TIMESTAMPTZ DEFAULT NOW(),
    source_url TEXT,
    claude_analysis TEXT,
    is_valid BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tipster_signals_token ON tipster_signals(token_symbol);
CREATE INDEX IF NOT EXISTS idx_tipster_signals_type ON tipster_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_tipster_signals_created ON tipster_signals(created_at DESC);

-- Price tracking for signal verification
CREATE TABLE IF NOT EXISTS tipster_price_checks (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES tipster_signals(id) ON DELETE CASCADE,
    token_symbol VARCHAR(20) NOT NULL,
    coingecko_id VARCHAR(100),
    price_at_signal NUMERIC(30, 18),
    current_price NUMERIC(30, 18),
    price_change_pct REAL,
    checked_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tipster_price_signal ON tipster_price_checks(signal_id);

-- Weekly performance reports
CREATE TABLE IF NOT EXISTS tipster_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(30) DEFAULT 'weekly',
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    total_signals INTEGER DEFAULT 0,
    profitable_signals INTEGER DEFAULT 0,
    avg_return_pct REAL,
    best_signal_id INTEGER REFERENCES tipster_signals(id),
    worst_signal_id INTEGER REFERENCES tipster_signals(id),
    report_text TEXT,
    proof_hash VARCHAR(66),
    proof_tx_hash VARCHAR(66),
    proof_uri TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- WHALE AGENT TABLES
-- ============================================================

-- Tracked whale wallets
CREATE TABLE IF NOT EXISTS whale_wallets (
    id SERIAL PRIMARY KEY,
    address VARCHAR(66) NOT NULL UNIQUE,
    label VARCHAR(255),
    chain VARCHAR(50) DEFAULT 'avalanche',
    category VARCHAR(50),  -- 'dex_trader', 'vc', 'protocol', 'influencer', 'unknown'
    is_active BOOLEAN DEFAULT TRUE,
    total_tx_tracked INTEGER DEFAULT 0,
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_whale_wallets_chain ON whale_wallets(chain);
CREATE INDEX IF NOT EXISTS idx_whale_wallets_category ON whale_wallets(category);

-- Whale transactions detected
CREATE TABLE IF NOT EXISTS whale_transactions (
    id SERIAL PRIMARY KEY,
    wallet_id INTEGER REFERENCES whale_wallets(id) ON DELETE CASCADE,
    tx_hash VARCHAR(66) NOT NULL UNIQUE,
    block_number BIGINT,
    chain VARCHAR(50) DEFAULT 'avalanche',
    tx_type VARCHAR(30) NOT NULL,  -- 'transfer', 'swap', 'bridge', 'lp_add', 'lp_remove', 'stake', 'unstake'
    from_address VARCHAR(66),
    to_address VARCHAR(66),
    token_symbol VARCHAR(20),
    token_address VARCHAR(66),
    amount NUMERIC(40, 18),
    amount_usd NUMERIC(30, 2),
    gas_used BIGINT,
    gas_price_gwei NUMERIC(20, 9),
    decoded_method VARCHAR(100),
    raw_input TEXT,
    detected_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_whale_tx_wallet ON whale_transactions(wallet_id);
CREATE INDEX IF NOT EXISTS idx_whale_tx_type ON whale_transactions(tx_type);
CREATE INDEX IF NOT EXISTS idx_whale_tx_token ON whale_transactions(token_symbol);
CREATE INDEX IF NOT EXISTS idx_whale_tx_detected ON whale_transactions(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_whale_tx_amount_usd ON whale_transactions(amount_usd DESC);

-- Whale movement analysis (Claude-generated)
CREATE TABLE IF NOT EXISTS whale_analyses (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER REFERENCES whale_transactions(id) ON DELETE CASCADE,
    wallet_id INTEGER REFERENCES whale_wallets(id),
    significance VARCHAR(20) DEFAULT 'medium',  -- 'low', 'medium', 'high', 'critical'
    analysis_text TEXT,
    market_impact TEXT,
    pattern_detected VARCHAR(100),
    alert_sent BOOLEAN DEFAULT FALSE,
    alert_chat_ids JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_whale_analysis_sig ON whale_analyses(significance);

-- Daily whale summary reports
CREATE TABLE IF NOT EXISTS whale_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(30) DEFAULT 'daily',
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    total_transactions INTEGER DEFAULT 0,
    total_volume_usd NUMERIC(30, 2),
    top_movers JSONB DEFAULT '[]',
    notable_patterns JSONB DEFAULT '[]',
    report_text TEXT,
    proof_hash VARCHAR(66),
    proof_tx_hash VARCHAR(66),
    proof_uri TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- NARRATIVE AGENT TABLES
-- ============================================================

-- RSS/news feed sources
CREATE TABLE IF NOT EXISTS narrative_sources (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(30) NOT NULL,  -- 'rss', 'telegram', 'coingecko'
    name VARCHAR(255) NOT NULL,
    url TEXT,
    channel_id BIGINT,
    channel_username VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    category VARCHAR(50),  -- 'news', 'alpha', 'research', 'defi', 'nft'
    reliability_score REAL DEFAULT 0.5,
    last_fetched TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Raw content items from sources
CREATE TABLE IF NOT EXISTS narrative_items (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES narrative_sources(id) ON DELETE CASCADE,
    external_id VARCHAR(255),
    title TEXT,
    content TEXT NOT NULL,
    url TEXT,
    author VARCHAR(255),
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_narrative_items_source ON narrative_items(source_id);
CREATE INDEX IF NOT EXISTS idx_narrative_items_published ON narrative_items(published_at DESC);

-- Sentiment analysis results
CREATE TABLE IF NOT EXISTS narrative_sentiments (
    id SERIAL PRIMARY KEY,
    item_id INTEGER REFERENCES narrative_items(id) ON DELETE CASCADE,
    overall_sentiment VARCHAR(20),  -- 'very_bullish', 'bullish', 'neutral', 'bearish', 'very_bearish'
    sentiment_score REAL,  -- -1.0 to 1.0
    tokens_mentioned JSONB DEFAULT '[]',
    topics JSONB DEFAULT '[]',
    key_claims JSONB DEFAULT '[]',
    claude_reasoning TEXT,
    analyzed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_narrative_sentiment_score ON narrative_sentiments(sentiment_score);

-- Detected narrative trends
CREATE TABLE IF NOT EXISTS narrative_trends (
    id SERIAL PRIMARY KEY,
    narrative_name VARCHAR(255) NOT NULL,
    narrative_category VARCHAR(50),  -- 'defi', 'l1', 'l2', 'gaming', 'ai', 'meme', 'regulation', 'macro'
    description TEXT,
    strength REAL DEFAULT 0.0,  -- 0.0 to 1.0
    momentum VARCHAR(20),  -- 'emerging', 'growing', 'peaking', 'fading', 'dead'
    first_detected TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    mention_count INTEGER DEFAULT 1,
    related_tokens JSONB DEFAULT '[]',
    supporting_items JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_narrative_trends_category ON narrative_trends(narrative_category);
CREATE INDEX IF NOT EXISTS idx_narrative_trends_strength ON narrative_trends(strength DESC);
CREATE INDEX IF NOT EXISTS idx_narrative_trends_active ON narrative_trends(is_active);

-- Daily narrative reports
CREATE TABLE IF NOT EXISTS narrative_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(30) DEFAULT 'daily',
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    top_narratives JSONB DEFAULT '[]',
    market_sentiment VARCHAR(20),
    sentiment_score REAL,
    emerging_trends JSONB DEFAULT '[]',
    fading_trends JSONB DEFAULT '[]',
    report_text TEXT,
    proof_hash VARCHAR(66),
    proof_tx_hash VARCHAR(66),
    proof_uri TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SHARED TABLES
-- ============================================================

-- Telegram subscriber registrations
CREATE TABLE IF NOT EXISTS subscribers (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL UNIQUE,
    username VARCHAR(255),
    wallet_address VARCHAR(66),
    subscribed_agents JSONB DEFAULT '[]',  -- ['tipster', 'whale', 'narrative']
    alert_preferences JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscribers_wallet ON subscribers(wallet_address);

-- On-chain proof submissions log
CREATE TABLE IF NOT EXISTS proof_submissions (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(50) NOT NULL,  -- 'tipster', 'whale', 'narrative'
    agent_erc8004_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    score_decimals INTEGER DEFAULT 2,
    tag1 VARCHAR(32),
    tag2 VARCHAR(32),
    proof_uri TEXT,
    proof_hash VARCHAR(66),
    tx_hash VARCHAR(66),
    submitted_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_proofs_agent ON proof_submissions(agent_name);
CREATE INDEX IF NOT EXISTS idx_proofs_submitted ON proof_submissions(submitted_at DESC);

-- Alert delivery log
CREATE TABLE IF NOT EXISTS alert_log (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(50) NOT NULL,
    chat_id BIGINT NOT NULL,
    alert_type VARCHAR(50),
    message_preview TEXT,
    delivered BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    sent_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alerts_agent ON alert_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alert_log(sent_at DESC);

-- ============================================================
-- CONVERGENCE SYSTEM
-- ============================================================

-- Cross-agent convergence signals (2+ agents detect same token)
CREATE TABLE IF NOT EXISTS convergence_signals (
    id SERIAL PRIMARY KEY,
    token_symbol VARCHAR(20) NOT NULL,
    token_address VARCHAR(66),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    tipster_signal_id INTEGER REFERENCES tipster_signals(id),
    whale_tx_id INTEGER REFERENCES whale_transactions(id),
    narrative_sentiment_id INTEGER REFERENCES narrative_sentiments(id),
    agent_count INTEGER NOT NULL DEFAULT 1,
    agents_involved JSONB NOT NULL DEFAULT '[]',
    tipster_raw_score REAL,
    whale_raw_score REAL,
    narrative_raw_score REAL,
    convergence_multiplier REAL NOT NULL DEFAULT 1.0,
    convergence_score REAL NOT NULL DEFAULT 0.0,
    signal_direction VARCHAR(20),
    direction_agreement BOOLEAN DEFAULT FALSE,
    proof_hash VARCHAR(66),
    proof_tx_hash VARCHAR(66),
    proof_uri TEXT,
    convergence_analysis TEXT,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_convergence_token ON convergence_signals(token_symbol);
CREATE INDEX IF NOT EXISTS idx_convergence_agents ON convergence_signals(agent_count DESC);
CREATE INDEX IF NOT EXISTS idx_convergence_detected ON convergence_signals(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_convergence_score ON convergence_signals(convergence_score DESC);

-- Tracks how convergence boosted individual agent proof scores
CREATE TABLE IF NOT EXISTS convergence_boosts (
    id SERIAL PRIMARY KEY,
    convergence_signal_id INTEGER REFERENCES convergence_signals(id) ON DELETE CASCADE,
    agent_name VARCHAR(50) NOT NULL,
    original_score REAL NOT NULL,
    boosted_score REAL NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1.0,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conv_boosts_signal ON convergence_boosts(convergence_signal_id);
CREATE INDEX IF NOT EXISTS idx_conv_boosts_agent ON convergence_boosts(agent_name);

-- ============================================================
-- AUDITOR (RUG DETECTOR) AGENT TABLES
-- ============================================================

-- Scanned token contracts
CREATE TABLE IF NOT EXISTS contract_scans (
    id SERIAL PRIMARY KEY,
    contract_address VARCHAR(66) NOT NULL UNIQUE,
    token_symbol VARCHAR(20),
    token_name VARCHAR(100),
    deployer_address VARCHAR(66),
    deployment_tx VARCHAR(66),
    deployment_block BIGINT,
    honeypot_score INTEGER DEFAULT 0,
    ownership_concentration_score INTEGER DEFAULT 0,
    liquidity_lock_score INTEGER DEFAULT 0,
    code_similarity_rug_score INTEGER DEFAULT 0,
    tax_manipulation_score INTEGER DEFAULT 0,
    overall_risk_score INTEGER DEFAULT 0,
    risk_label VARCHAR(20),
    actual_outcome VARCHAR(20),
    outcome_confirmed_at TIMESTAMPTZ,
    analysis_text TEXT,
    red_flags JSONB DEFAULT '[]',
    liquidity_usd REAL,
    holder_count INTEGER,
    top_holder_pct REAL,
    scanned_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scan_risk ON contract_scans(overall_risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_scan_label ON contract_scans(risk_label);
CREATE INDEX IF NOT EXISTS idx_scan_token ON contract_scans(token_symbol);
CREATE INDEX IF NOT EXISTS idx_scan_deployer ON contract_scans(deployer_address);

-- Audit reports with precision tracking
CREATE TABLE IF NOT EXISTS audit_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(30) DEFAULT 'daily',
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    total_scanned INTEGER DEFAULT 0,
    flagged_danger INTEGER DEFAULT 0,
    confirmed_rugs INTEGER DEFAULT 0,
    false_positives INTEGER DEFAULT 0,
    precision_pct REAL,
    report_text TEXT,
    proof_hash VARCHAR(66),
    proof_tx_hash VARCHAR(66),
    proof_uri TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- LIQUIDATION SENTINEL AGENT TABLES
-- ============================================================

-- Monitored lending positions
CREATE TABLE IF NOT EXISTS liquidation_positions (
    id SERIAL PRIMARY KEY,
    protocol VARCHAR(30) NOT NULL,
    wallet_address VARCHAR(66) NOT NULL,
    health_factor REAL NOT NULL,
    risk_level VARCHAR(20),
    collateral_token VARCHAR(20),
    collateral_amount_usd REAL DEFAULT 0,
    collateral_address VARCHAR(66),
    debt_token VARCHAR(20),
    debt_amount_usd REAL DEFAULT 0,
    debt_address VARCHAR(66),
    ltv REAL,
    liquidation_threshold REAL,
    distance_to_liquidation_pct REAL,
    predicted_liquidation BOOLEAN DEFAULT FALSE,
    prediction_confidence REAL DEFAULT 0.0,
    predicted_at TIMESTAMPTZ,
    alert_sent BOOLEAN DEFAULT FALSE,
    alert_level VARCHAR(20),
    analysis_text TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_liq_pos_hf ON liquidation_positions(health_factor);
CREATE INDEX IF NOT EXISTS idx_liq_pos_risk ON liquidation_positions(risk_level);
CREATE INDEX IF NOT EXISTS idx_liq_pos_protocol ON liquidation_positions(protocol);
CREATE INDEX IF NOT EXISTS idx_liq_pos_wallet ON liquidation_positions(wallet_address);
CREATE INDEX IF NOT EXISTS idx_liq_pos_active ON liquidation_positions(is_active);

-- Actual liquidation events
CREATE TABLE IF NOT EXISTS liquidation_events (
    id SERIAL PRIMARY KEY,
    position_id INTEGER,
    protocol VARCHAR(30) NOT NULL,
    wallet_address VARCHAR(66) NOT NULL,
    tx_hash VARCHAR(66) UNIQUE,
    block_number BIGINT,
    collateral_token VARCHAR(20),
    debt_token VARCHAR(20),
    collateral_seized_usd REAL,
    debt_repaid_usd REAL,
    liquidator_address VARCHAR(66),
    was_predicted BOOLEAN DEFAULT FALSE,
    prediction_lead_time_min INTEGER,
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_liq_event_protocol ON liquidation_events(protocol);
CREATE INDEX IF NOT EXISTS idx_liq_event_predicted ON liquidation_events(was_predicted);
CREATE INDEX IF NOT EXISTS idx_liq_event_occurred ON liquidation_events(occurred_at DESC);

-- Liquidation reports
CREATE TABLE IF NOT EXISTS liquidation_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(30) DEFAULT 'daily',
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    positions_monitored INTEGER DEFAULT 0,
    high_risk_positions INTEGER DEFAULT 0,
    liquidations_occurred INTEGER DEFAULT 0,
    liquidations_predicted INTEGER DEFAULT 0,
    prediction_accuracy_pct REAL,
    total_value_liquidated_usd REAL DEFAULT 0,
    report_text TEXT,
    proof_hash VARCHAR(66),
    proof_tx_hash VARCHAR(66),
    proof_uri TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- YIELD ORACLE AGENT TABLES
-- ============================================================

-- DeFi yield opportunities
CREATE TABLE IF NOT EXISTS yield_opportunities (
    id SERIAL PRIMARY KEY,
    protocol VARCHAR(50) NOT NULL,
    pool_name VARCHAR(255) NOT NULL,
    pool_address VARCHAR(66),
    pool_type VARCHAR(30),
    token_a VARCHAR(20),
    token_b VARCHAR(20),
    token_a_address VARCHAR(66),
    token_b_address VARCHAR(66),
    apy REAL DEFAULT 0.0,
    base_apy REAL DEFAULT 0.0,
    reward_apy REAL DEFAULT 0.0,
    tvl_usd REAL DEFAULT 0.0,
    risk_score INTEGER DEFAULT 50,
    risk_factors JSONB DEFAULT '[]',
    risk_adjusted_apy REAL DEFAULT 0.0,
    recommendation VARCHAR(20),
    analysis_text TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_yield_protocol ON yield_opportunities(protocol);
CREATE INDEX IF NOT EXISTS idx_yield_apy ON yield_opportunities(apy DESC);
CREATE INDEX IF NOT EXISTS idx_yield_risk_adj ON yield_opportunities(risk_adjusted_apy DESC);
CREATE INDEX IF NOT EXISTS idx_yield_tvl ON yield_opportunities(tvl_usd DESC);
CREATE INDEX IF NOT EXISTS idx_yield_active ON yield_opportunities(is_active);

-- Model portfolio snapshots
CREATE TABLE IF NOT EXISTS yield_portfolios (
    id SERIAL PRIMARY KEY,
    model_type VARCHAR(30) NOT NULL,
    snapshot_date TIMESTAMPTZ NOT NULL,
    allocations JSONB DEFAULT '[]',
    total_positions INTEGER DEFAULT 0,
    portfolio_apy REAL DEFAULT 0.0,
    portfolio_risk REAL DEFAULT 0.0,
    avax_benchmark_apy REAL DEFAULT 0.0,
    alpha_vs_benchmark REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_portfolio_model ON yield_portfolios(model_type);
CREATE INDEX IF NOT EXISTS idx_portfolio_date ON yield_portfolios(snapshot_date DESC);

-- Yield reports
CREATE TABLE IF NOT EXISTS yield_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(30) DEFAULT 'daily',
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    total_opportunities INTEGER DEFAULT 0,
    avg_apy REAL DEFAULT 0.0,
    best_risk_adjusted JSONB DEFAULT '[]',
    portfolio_performance JSONB DEFAULT '{}',
    alpha_vs_avax REAL DEFAULT 0.0,
    report_text TEXT,
    proof_hash VARCHAR(66),
    proof_tx_hash VARCHAR(66),
    proof_uri TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


async def init_database():
    if engine is None:
        print("ERROR: DATABASE_URL not configured. Set it in .env")
        return

    print("Connecting to database...")
    async with engine.begin() as conn:
        print("Running schema migration...")
        for statement in SCHEMA_SQL.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))
        print("All tables created successfully.")

    print("Database initialization complete.")


if __name__ == "__main__":
    asyncio.run(init_database())
