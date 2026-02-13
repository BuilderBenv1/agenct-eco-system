"""
Liquidation Predictor — Uses Claude + on-chain data to predict which positions
will be liquidated based on health factors, price trends, and whale behavior.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select, update
from shared.database import async_session
from shared.claude_client import ask_claude_json
from shared.lightning import get_lightning
from shared.telegram_bot import send_alert
from agents.liquidation.models.db import LiquidationPosition
from agents.liquidation.config import (
    AGENT_NAME, HEALTH_FACTOR_DANGER, HEALTH_FACTOR_CRITICAL, ALERT_MIN_RISK,
)
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)

PROMPT_PATH = Path(__file__).parent.parent / "templates" / "prediction_prompt.txt"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    return _system_prompt


RISK_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _should_alert(risk_level: str) -> bool:
    return RISK_RANK.get(risk_level, 0) >= RISK_RANK.get(ALERT_MIN_RISK, 3)


async def predict_at_risk_positions():
    """Analyze positions with low health factors and predict liquidations."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(LiquidationPosition)
            .where(
                LiquidationPosition.is_active == True,
                LiquidationPosition.health_factor < HEALTH_FACTOR_DANGER,
                LiquidationPosition.analysis_text.is_(None),
            )
            .order_by(LiquidationPosition.health_factor)
            .limit(10)
        )
        positions = list(result.scalars().all())

    for pos in positions:
        await analyze_position(pos)

    if positions:
        logger.info("predictions_complete", count=len(positions))


async def analyze_position(pos: LiquidationPosition) -> LiquidationPosition | None:
    """Run Claude analysis on an at-risk lending position."""
    pos_data = {
        "protocol": pos.protocol,
        "wallet": pos.wallet_address,
        "health_factor": pos.health_factor,
        "risk_level": pos.risk_level,
        "collateral_token": pos.collateral_token or "unknown",
        "collateral_usd": pos.collateral_amount_usd or 0,
        "debt_token": pos.debt_token or "unknown",
        "debt_usd": pos.debt_amount_usd or 0,
        "ltv": pos.ltv,
        "distance_to_liquidation_pct": pos.distance_to_liquidation_pct,
    }

    lightning.emit_action("predict_liquidation", {
        "wallet": pos.wallet_address[:10],
        "hf": pos.health_factor,
    })

    try:
        result = ask_claude_json(
            system_prompt=_get_system_prompt(),
            user_message=json.dumps(pos_data, default=str),
            max_tokens=512,
        )
    except Exception as e:
        logger.error("prediction_failed", error=str(e), wallet=pos.wallet_address[:10])
        lightning.log_failure(task="predict_liquidation", error=str(e), context=pos_data)
        return None

    predicted = result.get("likely_liquidation", False)
    confidence = result.get("confidence", 0.0)
    analysis = result.get("analysis", "")

    if async_session is None:
        return None

    async with async_session() as db:
        await db.execute(
            update(LiquidationPosition)
            .where(LiquidationPosition.id == pos.id)
            .values(
                predicted_liquidation=predicted,
                prediction_confidence=confidence,
                predicted_at=datetime.now(timezone.utc),
                analysis_text=analysis,
            )
        )
        await db.commit()

        refreshed = await db.execute(
            select(LiquidationPosition).where(LiquidationPosition.id == pos.id)
        )
        pos = refreshed.scalar_one()

    lightning.log_success("predict_liquidation", output={
        "predicted": predicted,
        "confidence": confidence,
        "hf": pos.health_factor,
    })

    # Send alert for high/critical risk
    if _should_alert(pos.risk_level or "low"):
        await _send_liquidation_alert(pos)

    return pos


def _format_alert(pos: LiquidationPosition) -> str:
    """Format a liquidation risk alert for Telegram."""
    risk = (pos.risk_level or "unknown").upper()
    emoji = {"CRITICAL": "🚨", "HIGH": "⚠️"}.get(risk, "📊")
    predicted = "YES" if pos.predicted_liquidation else "NO"

    return (
        f"{emoji} *Liquidation Alert — {risk}*\n\n"
        f"Protocol: `{pos.protocol}`\n"
        f"Wallet: `{pos.wallet_address[:10]}...{pos.wallet_address[-6:]}`\n"
        f"Health Factor: *{pos.health_factor:.3f}*\n"
        f"Collateral: ${pos.collateral_amount_usd or 0:,.0f} ({pos.collateral_token or '?'})\n"
        f"Debt: ${pos.debt_amount_usd or 0:,.0f} ({pos.debt_token or '?'})\n"
        f"Distance to liquidation: {pos.distance_to_liquidation_pct or 0:.1f}%\n\n"
        f"Predicted liquidation: *{predicted}*\n"
        f"Confidence: {pos.prediction_confidence:.0%}\n\n"
        f"{'_' + (pos.analysis_text or '') + '_' if pos.analysis_text else ''}"
    )


async def _send_liquidation_alert(pos: LiquidationPosition):
    """Send Telegram alerts to subscribers."""
    if async_session is None:
        return

    async with async_session() as db:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT chat_id FROM subscribers WHERE is_active = true AND subscribed_agents::jsonb ? 'liquidation'")
        )
        chat_ids = [row[0] for row in result.fetchall()]
        if not chat_ids:
            return

        msg = _format_alert(pos)
        sent = 0
        for chat_id in chat_ids:
            try:
                await send_alert(chat_id, msg)
                sent += 1
            except Exception as e:
                logger.debug("alert_send_failed", chat_id=chat_id, error=str(e))

        # Mark alert as sent
        await db.execute(
            update(LiquidationPosition)
            .where(LiquidationPosition.id == pos.id)
            .values(alert_sent=True, alert_level=pos.risk_level)
        )
        await db.commit()

        logger.info("liquidation_alerts_sent", count=sent, risk=pos.risk_level)
