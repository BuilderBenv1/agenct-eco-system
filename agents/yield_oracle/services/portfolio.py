"""
Portfolio Manager — Builds model portfolios (conservative/balanced/aggressive)
from scored yield opportunities and tracks performance vs AVAX staking benchmark.
"""
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from agents.yield_oracle.models.db import YieldOpportunity, YieldPortfolio, YieldReport
from agents.yield_oracle.config import PORTFOLIO_MODELS
import structlog

logger = structlog.get_logger()

# AVAX staking APY benchmark (approximate)
AVAX_STAKING_APY = 8.0


async def build_model_portfolios():
    """Build model portfolios from current yield opportunities."""
    if async_session is None:
        return

    now = datetime.now(timezone.utc)

    for model_type, constraints in PORTFOLIO_MODELS.items():
        async with async_session() as db:
            # Get opportunities matching this model's constraints
            result = await db.execute(
                select(YieldOpportunity)
                .where(
                    YieldOpportunity.is_active == True,
                    YieldOpportunity.risk_score <= constraints["max_risk"],
                    YieldOpportunity.tvl_usd >= constraints["min_tvl_usd"],
                    YieldOpportunity.apy > 0,
                )
                .order_by(YieldOpportunity.risk_adjusted_apy.desc())
                .limit(10)
            )
            opportunities = list(result.scalars().all())

            if not opportunities:
                continue

            # Build equal-weight portfolio from top opportunities
            weight = 1.0 / len(opportunities)
            allocations = []
            total_apy = 0.0
            total_risk = 0.0

            for opp in opportunities:
                allocations.append({
                    "pool_id": opp.id,
                    "pool_name": opp.pool_name,
                    "protocol": opp.protocol,
                    "weight": round(weight, 4),
                    "apy": opp.apy,
                    "risk_score": opp.risk_score,
                })
                total_apy += opp.apy * weight
                total_risk += opp.risk_score * weight

            alpha = total_apy - AVAX_STAKING_APY

            portfolio = YieldPortfolio(
                model_type=model_type,
                snapshot_date=now,
                allocations=allocations,
                total_positions=len(allocations),
                portfolio_apy=round(total_apy, 2),
                portfolio_risk=round(total_risk, 1),
                avax_benchmark_apy=AVAX_STAKING_APY,
                alpha_vs_benchmark=round(alpha, 2),
            )
            db.add(portfolio)
            await db.commit()

            logger.info(
                "portfolio_built",
                model=model_type,
                positions=len(allocations),
                apy=f"{total_apy:.2f}%",
                alpha=f"{alpha:+.2f}%",
            )


async def generate_daily_report() -> dict | None:
    """Generate daily yield oracle report."""
    if async_session is None:
        return None

    async with async_session() as db:
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=1)

        # Total active opportunities
        total_q = await db.execute(
            select(func.count()).select_from(YieldOpportunity)
            .where(YieldOpportunity.is_active == True)
        )
        total = total_q.scalar() or 0

        # Average APY
        avg_q = await db.execute(
            select(func.avg(YieldOpportunity.apy))
            .where(YieldOpportunity.is_active == True, YieldOpportunity.apy > 0)
        )
        avg_apy = avg_q.scalar() or 0

        # Top 5 risk-adjusted
        top_q = await db.execute(
            select(YieldOpportunity)
            .where(YieldOpportunity.is_active == True)
            .order_by(YieldOpportunity.risk_adjusted_apy.desc())
            .limit(5)
        )
        top_opps = list(top_q.scalars().all())
        best_risk_adjusted = [
            {
                "pool": o.pool_name,
                "protocol": o.protocol,
                "apy": o.apy,
                "risk_score": o.risk_score,
                "risk_adjusted_apy": o.risk_adjusted_apy,
                "recommendation": o.recommendation,
            }
            for o in top_opps
        ]

        # Latest portfolio performance
        portfolio_perf = {}
        for model_type in PORTFOLIO_MODELS:
            pf_q = await db.execute(
                select(YieldPortfolio)
                .where(YieldPortfolio.model_type == model_type)
                .order_by(YieldPortfolio.snapshot_date.desc())
                .limit(1)
            )
            pf = pf_q.scalar_one_or_none()
            if pf:
                portfolio_perf[model_type] = {
                    "apy": pf.portfolio_apy,
                    "risk": pf.portfolio_risk,
                    "alpha": pf.alpha_vs_benchmark,
                    "positions": pf.total_positions,
                }

        # Overall alpha (use balanced portfolio as default)
        alpha = portfolio_perf.get("balanced", {}).get("alpha", 0)

        # Score = alpha + 50 (so 0% alpha = 50 score, 10% alpha = 60, etc.)
        score = max(0, min(100, int(alpha + 50)))

        report_text = (
            f"Yield Oracle Daily Report\n"
            f"Period: {period_start.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
            f"Opportunities tracked: {total}\n"
            f"Average APY: {avg_apy:.1f}%\n"
            f"AVAX staking benchmark: {AVAX_STAKING_APY:.1f}%\n\n"
            f"Portfolio Performance:\n"
        )
        for model, perf in portfolio_perf.items():
            report_text += f"  {model.capitalize()}: {perf['apy']:.1f}% APY (alpha: {perf['alpha']:+.1f}%)\n"

        report_text += f"\nTop Risk-Adjusted Opportunities:\n"
        for i, opp in enumerate(best_risk_adjusted, 1):
            report_text += f"  {i}. {opp['pool']} — {opp['apy']:.1f}% APY (risk: {opp['risk_score']})\n"

        report_text += f"\nScore: {score}/100"

        proof_hash = hashlib.sha256(report_text.encode()).hexdigest()

        report = YieldReport(
            report_type="daily",
            period_start=period_start,
            period_end=now,
            total_opportunities=total,
            avg_apy=round(avg_apy, 2),
            best_risk_adjusted=best_risk_adjusted,
            portfolio_performance=portfolio_perf,
            alpha_vs_avax=round(alpha, 2),
            report_text=report_text,
            proof_hash=f"0x{proof_hash}",
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        logger.info("daily_report_generated", total=total, avg_apy=avg_apy, alpha=alpha)

        return {
            "report_id": report.id,
            "score": score,
        }
