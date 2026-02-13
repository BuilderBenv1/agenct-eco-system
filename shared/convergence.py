"""
Cross-Agent Convergence Detection — detects when 2+ agents independently
flag the same token within a time window, scores the convergence, and
submits meta-proofs on-chain.

The scoring formula:
  2 agents = 1.5x multiplier
  3 agents = 2.0x multiplier
  + 0.2x bonus if all agents agree on direction
  convergence_score = avg(raw_scores) * multiplier
"""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.config import settings
from shared.models.convergence import ConvergenceSignal, ConvergenceBoost
import structlog

logger = structlog.get_logger()

MULTIPLIERS = {1: 1.0, 2: 1.5, 3: 2.0}
DIRECTION_BONUS = 0.2

WHALE_SIGNIFICANCE_SCORES = {
    "low": 25, "medium": 50, "high": 75, "critical": 100
}


async def detect_convergence():
    """
    Main convergence detection loop. Queries all 3 agents' tables
    for overlapping token mentions within the configured time window.
    """
    if async_session is None:
        return []

    now = datetime.now(timezone.utc)
    window_hours = settings.CONVERGENCE_WINDOW_HOURS
    cutoff = now - timedelta(hours=window_hours)

    async with async_session() as db:
        overlaps = await _find_token_overlaps(db, cutoff, now)

        new_convergences = []
        for overlap in overlaps:
            if overlap["agent_count"] < 2:
                continue

            # Deduplicate: skip if we already recorded this token+window
            existing = await db.execute(
                select(ConvergenceSignal).where(
                    ConvergenceSignal.token_symbol == overlap["token_symbol"],
                    ConvergenceSignal.detected_at >= cutoff,
                )
            )
            if existing.scalar_one_or_none():
                continue

            convergence = _build_convergence(overlap, cutoff, now)
            db.add(convergence)
            new_convergences.append(convergence)

        if new_convergences:
            await db.commit()

            # Submit meta-proofs for 3-agent convergences
            for conv in new_convergences:
                if conv.agent_count == 3:
                    await _submit_meta_proof(db, conv)

        logger.info(
            "convergence_check_complete",
            new_signals=len(new_convergences),
            three_agent=sum(1 for c in new_convergences if c.agent_count == 3),
        )
        return new_convergences


async def _find_token_overlaps(
    db: AsyncSession, cutoff: datetime, now: datetime
) -> list[dict]:
    """
    Query all 3 agents' tables for tokens mentioned in the time window.
    Returns tokens that appear in 2+ agents' data.
    """
    # Tipster: recent valid signals
    tipster_q = await db.execute(text("""
        SELECT UPPER(token_symbol) as token, id, confidence, signal_type
        FROM tipster_signals
        WHERE created_at >= :cutoff AND is_valid = true AND token_symbol IS NOT NULL
        ORDER BY confidence DESC
    """), {"cutoff": cutoff})
    tipster_data: dict[str, dict] = {}
    for row in tipster_q.fetchall():
        token = row[0]
        if token not in tipster_data:
            tipster_data[token] = {
                "signal_id": row[1], "confidence": row[2], "signal_type": row[3]
            }

    # Whale: recent transactions
    whale_q = await db.execute(text("""
        SELECT UPPER(token_symbol) as token, wt.id, wa.significance, wt.tx_type, wt.amount_usd
        FROM whale_transactions wt
        LEFT JOIN whale_analyses wa ON wa.transaction_id = wt.id
        WHERE wt.detected_at >= :cutoff AND wt.token_symbol IS NOT NULL
        ORDER BY wt.amount_usd DESC NULLS LAST
    """), {"cutoff": cutoff})
    whale_data: dict[str, dict] = {}
    for row in whale_q.fetchall():
        token = row[0]
        if token not in whale_data:
            whale_data[token] = {
                "tx_id": row[1], "significance": row[2] or "medium",
                "tx_type": row[3], "amount_usd": float(row[4] or 0)
            }

    # Narrative: recent sentiments with tokens mentioned
    narrative_q = await db.execute(text("""
        SELECT UPPER(elem::text) as token, ns.id, ns.sentiment_score, ns.overall_sentiment
        FROM narrative_sentiments ns,
             jsonb_array_elements_text(ns.tokens_mentioned) elem
        WHERE ns.analyzed_at >= :cutoff
    """), {"cutoff": cutoff})
    narrative_data: dict[str, dict] = {}
    for row in narrative_q.fetchall():
        token = row[0].strip('"').upper()
        if token not in narrative_data:
            narrative_data[token] = {
                "sentiment_id": row[1], "sentiment_score": row[2],
                "overall_sentiment": row[3]
            }

    # Find overlaps: tokens in 2+ agents
    all_tokens = set(tipster_data) | set(whale_data) | set(narrative_data)
    overlaps = []

    for token in all_tokens:
        agents = []
        if token in tipster_data:
            agents.append("tipster")
        if token in whale_data:
            agents.append("whale")
        if token in narrative_data:
            agents.append("narrative")

        if len(agents) >= 2:
            overlaps.append({
                "token_symbol": token,
                "agent_count": len(agents),
                "agents": agents,
                "tipster": tipster_data.get(token),
                "whale": whale_data.get(token),
                "narrative": narrative_data.get(token),
            })

    overlaps.sort(key=lambda x: x["agent_count"], reverse=True)
    return overlaps


def _build_convergence(
    overlap: dict, window_start: datetime, window_end: datetime
) -> ConvergenceSignal:
    """Score and build a ConvergenceSignal from overlap data."""
    agents = overlap["agents"]
    agent_count = overlap["agent_count"]

    # Calculate raw scores per agent
    tipster_score = None
    whale_score = None
    narrative_score = None

    if overlap.get("tipster"):
        tipster_score = overlap["tipster"]["confidence"] * 100

    if overlap.get("whale"):
        sig = overlap["whale"]["significance"]
        whale_score = WHALE_SIGNIFICANCE_SCORES.get(sig, 50)

    if overlap.get("narrative"):
        narrative_score = abs(overlap["narrative"]["sentiment_score"] or 0) * 100

    # Average of available scores
    scores = [s for s in [tipster_score, whale_score, narrative_score] if s is not None]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Direction analysis
    direction, agreement = _determine_direction(
        overlap.get("tipster", {}).get("signal_type"),
        overlap.get("whale", {}).get("tx_type"),
        overlap.get("narrative", {}).get("sentiment_score"),
    )

    # Multiplier
    multiplier = MULTIPLIERS.get(agent_count, 1.0)
    if agreement and agent_count >= 2:
        multiplier += DIRECTION_BONUS

    convergence_score = avg_score * multiplier

    return ConvergenceSignal(
        token_symbol=overlap["token_symbol"],
        window_start=window_start,
        window_end=window_end,
        tipster_signal_id=overlap.get("tipster", {}).get("signal_id"),
        whale_tx_id=overlap.get("whale", {}).get("tx_id"),
        narrative_sentiment_id=overlap.get("narrative", {}).get("sentiment_id"),
        agent_count=agent_count,
        agents_involved=agents,
        tipster_raw_score=tipster_score,
        whale_raw_score=whale_score,
        narrative_raw_score=narrative_score,
        convergence_multiplier=multiplier,
        convergence_score=convergence_score,
        signal_direction=direction,
        direction_agreement=agreement,
        detected_at=datetime.now(timezone.utc),
    )


def _determine_direction(
    tipster_signal_type: str | None,
    whale_tx_type: str | None,
    narrative_sentiment: float | None,
) -> tuple[str, bool]:
    """Determine if agents agree on bullish/bearish direction."""
    directions = []

    if tipster_signal_type:
        if tipster_signal_type in ("BUY", "HOLD"):
            directions.append("bullish")
        elif tipster_signal_type in ("SELL", "AVOID"):
            directions.append("bearish")

    if whale_tx_type:
        # Accumulation patterns = bullish, distribution = bearish
        if whale_tx_type in ("swap", "stake", "lp_add"):
            directions.append("bullish")
        elif whale_tx_type in ("transfer", "unstake", "lp_remove"):
            directions.append("bearish")

    if narrative_sentiment is not None:
        if narrative_sentiment > 0.2:
            directions.append("bullish")
        elif narrative_sentiment < -0.2:
            directions.append("bearish")

    if not directions:
        return "neutral", False

    unique = set(directions)
    if len(unique) == 1 and len(directions) >= 2:
        return directions[0], True
    elif "bullish" in unique and "bearish" in unique:
        return "mixed", False
    else:
        return directions[0], False


async def _submit_meta_proof(db: AsyncSession, conv: ConvergenceSignal):
    """Submit a convergence meta-proof on-chain."""
    if not settings.CONVERGENCE_ERC8004_ID:
        logger.debug("convergence_nft_not_minted", skip="meta-proof")
        return

    try:
        from shared.contracts import proof_oracle

        proof_data = json.dumps({
            "token": conv.token_symbol,
            "agents": conv.agents_involved,
            "score": conv.convergence_score,
            "direction": conv.signal_direction,
            "agreement": conv.direction_agreement,
        }, default=str)

        proof_hash = hashlib.sha256(proof_data.encode()).digest()

        tx_hash = proof_oracle.submit_proof(
            agent_id=settings.CONVERGENCE_ERC8004_ID,
            score=int(conv.convergence_score * 100),
            score_decimals=2,
            tag1="convergence",
            tag2=f"{conv.agent_count}-agent",
            proof_uri=f"convergence://signal/{conv.id}",
            proof_hash=proof_hash,
        )

        conv.proof_hash = hashlib.sha256(proof_data.encode()).hexdigest()
        conv.proof_tx_hash = tx_hash
        await db.commit()

        logger.info(
            "convergence_meta_proof_submitted",
            token=conv.token_symbol,
            agents=conv.agent_count,
            tx_hash=tx_hash,
        )
    except Exception as e:
        logger.error("meta_proof_failed", error=str(e))


async def get_convergence_boost(agent_name: str, token_symbol: str) -> float:
    """
    Called by individual agents before submitting proofs.
    Returns the multiplier if this agent participated in a convergence event.
    """
    if async_session is None:
        return 1.0

    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.CONVERGENCE_WINDOW_HOURS
        )
        result = await db.execute(
            select(ConvergenceSignal).where(
                ConvergenceSignal.token_symbol == token_symbol.upper(),
                ConvergenceSignal.detected_at >= cutoff,
            ).order_by(ConvergenceSignal.convergence_score.desc()).limit(1)
        )
        conv = result.scalar_one_or_none()

        if conv and agent_name in (conv.agents_involved or []):
            return conv.convergence_multiplier
        return 1.0


async def get_recent_convergences(limit: int = 10) -> list[dict]:
    """Get recent convergence signals for API/bot display."""
    if async_session is None:
        return []

    async with async_session() as db:
        result = await db.execute(
            select(ConvergenceSignal)
            .order_by(ConvergenceSignal.detected_at.desc())
            .limit(limit)
        )
        signals = result.scalars().all()
        return [
            {
                "id": s.id,
                "token": s.token_symbol,
                "agents": s.agents_involved,
                "agent_count": s.agent_count,
                "score": s.convergence_score,
                "multiplier": s.convergence_multiplier,
                "direction": s.signal_direction,
                "agreement": s.direction_agreement,
                "detected_at": s.detected_at.isoformat() if s.detected_at else None,
                "proof_tx": s.proof_tx_hash,
            }
            for s in signals
        ]


async def get_convergence_stats() -> dict:
    """Get convergence system stats."""
    if async_session is None:
        return {"status": "no db"}

    async with async_session() as db:
        total = await db.execute(
            select(func.count()).select_from(ConvergenceSignal)
        )
        recent = await db.execute(
            select(func.count()).select_from(ConvergenceSignal).where(
                ConvergenceSignal.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            )
        )
        three_agent = await db.execute(
            select(func.count()).select_from(ConvergenceSignal).where(
                ConvergenceSignal.agent_count == 3
            )
        )
        return {
            "total_convergences": total.scalar() or 0,
            "last_24h": recent.scalar() or 0,
            "three_agent_total": three_agent.scalar() or 0,
        }
