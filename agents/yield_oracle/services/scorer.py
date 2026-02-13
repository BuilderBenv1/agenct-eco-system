"""
Yield Scorer — Calculates risk-adjusted returns and recommendations
for DeFi yield opportunities on Avalanche.
"""
import json
from pathlib import Path
from sqlalchemy import select, update
from shared.database import async_session
from shared.claude_client import ask_claude_json
from shared.lightning import get_lightning
from agents.yield_oracle.models.db import YieldOpportunity
from agents.yield_oracle.config import AGENT_NAME, RISK_WEIGHTS, STABLECOINS
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)

PROMPT_PATH = Path(__file__).parent.parent / "templates" / "scoring_prompt.txt"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    return _system_prompt


def compute_base_risk(opp: YieldOpportunity) -> int:
    """Compute a baseline risk score from objective metrics."""
    risk = 50  # Start neutral

    # Protocol risk - established protocols are safer
    protocol_risk = {
        "benqi": 20, "aave_v3": 15, "trader_joe": 25,
        "yield_yak": 35, "pangolin": 30,
    }
    risk = protocol_risk.get(opp.protocol, 50)

    # TVL adjustment: higher TVL = lower risk
    tvl = opp.tvl_usd or 0
    if tvl > 100_000_000:
        risk -= 10
    elif tvl > 10_000_000:
        risk -= 5
    elif tvl < 100_000:
        risk += 20
    elif tvl < 1_000_000:
        risk += 10

    # APY adjustment: extremely high APYs are suspicious
    apy = opp.apy or 0
    if apy > 500:
        risk += 30  # Very suspicious
    elif apy > 100:
        risk += 15
    elif apy > 50:
        risk += 5

    # Pool type adjustment
    if opp.pool_type == "lending":
        risk -= 5  # Lending is generally safer than LPing
    elif opp.pool_type == "vault":
        risk += 5  # Extra smart contract risk

    # Stablecoin adjustment
    tokens = {opp.token_a, opp.token_b} - {None}
    if tokens and tokens.issubset(STABLECOINS):
        risk -= 15  # Stablecoin-only = low IL risk

    return max(0, min(100, risk))


def compute_risk_adjusted_apy(apy: float, risk_score: int) -> float:
    """Risk-adjusted APY: higher is better. Penalizes high risk."""
    if risk_score == 0:
        return apy
    return round(apy * (100 - risk_score) / 100, 2)


def get_recommendation(risk_adjusted_apy: float, risk_score: int, apy: float) -> str:
    """Generate recommendation based on risk-adjusted metrics."""
    if risk_score > 75:
        return "avoid"
    if risk_adjusted_apy > 20 and risk_score < 30:
        return "strong_buy"
    if risk_adjusted_apy > 10 and risk_score < 50:
        return "buy"
    if risk_adjusted_apy > 5:
        return "hold"
    return "avoid"


async def score_all_opportunities():
    """Score all active opportunities with risk metrics."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(YieldOpportunity)
            .where(YieldOpportunity.is_active == True)
            .order_by(YieldOpportunity.apy.desc())
        )
        opportunities = list(result.scalars().all())

    scored = 0
    for opp in opportunities:
        risk_score = compute_base_risk(opp)
        risk_adjusted = compute_risk_adjusted_apy(opp.apy or 0, risk_score)
        recommendation = get_recommendation(risk_adjusted, risk_score, opp.apy or 0)

        if async_session:
            async with async_session() as db:
                await db.execute(
                    update(YieldOpportunity)
                    .where(YieldOpportunity.id == opp.id)
                    .values(
                        risk_score=risk_score,
                        risk_adjusted_apy=risk_adjusted,
                        recommendation=recommendation,
                    )
                )
                await db.commit()
        scored += 1

    logger.info("opportunities_scored", count=scored)


async def analyze_top_opportunities():
    """Use Claude to provide deeper analysis of top yield opportunities."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(YieldOpportunity)
            .where(
                YieldOpportunity.is_active == True,
                YieldOpportunity.analysis_text.is_(None),
                YieldOpportunity.risk_adjusted_apy > 0,
            )
            .order_by(YieldOpportunity.risk_adjusted_apy.desc())
            .limit(5)
        )
        opportunities = list(result.scalars().all())

    for opp in opportunities:
        opp_data = {
            "protocol": opp.protocol,
            "pool_name": opp.pool_name,
            "pool_type": opp.pool_type,
            "tokens": [opp.token_a, opp.token_b],
            "apy": opp.apy,
            "base_apy": opp.base_apy,
            "reward_apy": opp.reward_apy,
            "tvl_usd": opp.tvl_usd,
            "risk_score": opp.risk_score,
            "risk_adjusted_apy": opp.risk_adjusted_apy,
            "recommendation": opp.recommendation,
        }

        lightning.emit_action("analyze_yield", {"pool": opp.pool_name, "apy": opp.apy})

        try:
            result = ask_claude_json(
                system_prompt=_get_system_prompt(),
                user_message=json.dumps(opp_data, default=str),
                max_tokens=512,
            )

            analysis = result.get("analysis", "")
            refined_risk = result.get("risk_score", opp.risk_score)
            risk_factors = result.get("risk_factors", [])

            if async_session:
                async with async_session() as db:
                    await db.execute(
                        update(YieldOpportunity)
                        .where(YieldOpportunity.id == opp.id)
                        .values(
                            analysis_text=analysis,
                            risk_score=refined_risk,
                            risk_factors=risk_factors,
                            risk_adjusted_apy=compute_risk_adjusted_apy(opp.apy or 0, refined_risk),
                        )
                    )
                    await db.commit()

            lightning.log_success("analyze_yield", output={
                "pool": opp.pool_name,
                "risk": refined_risk,
            })

        except Exception as e:
            logger.error("yield_analysis_failed", pool=opp.pool_name, error=str(e))
            lightning.log_failure(task="analyze_yield", error=str(e))

    if opportunities:
        logger.info("top_opportunities_analyzed", count=len(opportunities))
