"""
Liquidation Tracker — Monitors on-chain liquidation events to verify predictions
and calculate accuracy metrics for proof submission.
"""
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from agents.liquidation.models.db import LiquidationPosition, LiquidationEvent, LiquidationReport
import structlog

logger = structlog.get_logger()


async def check_prediction_outcomes():
    """Check if predicted liquidations actually occurred.
    Marks positions as inactive if their health factor recovered."""
    if async_session is None:
        return

    async with async_session() as db:
        # Find predicted positions older than 1 hour
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        result = await db.execute(
            select(LiquidationPosition)
            .where(
                LiquidationPosition.is_active == True,
                LiquidationPosition.predicted_at.isnot(None),
                LiquidationPosition.predicted_at <= cutoff,
            )
            .limit(20)
        )
        positions = list(result.scalars().all())

        for pos in positions:
            # Re-check the position's current health factor
            from agents.liquidation.services.position_monitor import (
                check_benqi_position, check_aave_position
            )

            if pos.protocol == "benqi":
                current = await check_benqi_position(pos.wallet_address)
            else:
                current = await check_aave_position(pos.wallet_address)

            if current is None:
                # Position no longer exists — likely liquidated
                if pos.predicted_liquidation:
                    # Correct prediction!
                    event = LiquidationEvent(
                        position_id=pos.id,
                        protocol=pos.protocol,
                        wallet_address=pos.wallet_address,
                        collateral_token=pos.collateral_token,
                        debt_token=pos.debt_token,
                        collateral_seized_usd=pos.collateral_amount_usd,
                        debt_repaid_usd=pos.debt_amount_usd,
                        was_predicted=True,
                        prediction_lead_time_min=int(
                            (datetime.now(timezone.utc) - pos.predicted_at).total_seconds() / 60
                        ) if pos.predicted_at else None,
                    )
                    db.add(event)
                    logger.info("liquidation_confirmed", wallet=pos.wallet_address[:10], predicted=True)
                else:
                    event = LiquidationEvent(
                        position_id=pos.id,
                        protocol=pos.protocol,
                        wallet_address=pos.wallet_address,
                        collateral_token=pos.collateral_token,
                        debt_token=pos.debt_token,
                        was_predicted=False,
                    )
                    db.add(event)
                    logger.info("liquidation_missed", wallet=pos.wallet_address[:10])

                # Mark position inactive
                pos.is_active = False

            elif current["health_factor"] > 1.5:
                # Position recovered — no liquidation needed
                if pos.predicted_liquidation:
                    # False positive
                    logger.info("false_positive", wallet=pos.wallet_address[:10])
                pos.is_active = False  # Mark resolved

            else:
                # Still at risk, update health factor
                pos.health_factor = current["health_factor"]
                pos.risk_level = current["risk_level"]

        if positions:
            await db.commit()
            logger.info("outcomes_checked", count=len(positions))


async def generate_daily_report() -> dict | None:
    """Generate daily liquidation monitoring report."""
    if async_session is None:
        return None

    async with async_session() as db:
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=1)

        # Positions monitored
        monitored_q = await db.execute(
            select(func.count()).select_from(LiquidationPosition)
            .where(LiquidationPosition.detected_at >= period_start)
        )
        positions_monitored = monitored_q.scalar() or 0

        # High risk positions
        high_risk_q = await db.execute(
            select(func.count()).select_from(LiquidationPosition)
            .where(
                LiquidationPosition.detected_at >= period_start,
                LiquidationPosition.risk_level.in_(["high", "critical"]),
            )
        )
        high_risk = high_risk_q.scalar() or 0

        # Liquidation events
        events_q = await db.execute(
            select(func.count()).select_from(LiquidationEvent)
            .where(LiquidationEvent.occurred_at >= period_start)
        )
        liquidations = events_q.scalar() or 0

        # Predicted correctly
        predicted_q = await db.execute(
            select(func.count()).select_from(LiquidationEvent)
            .where(
                LiquidationEvent.occurred_at >= period_start,
                LiquidationEvent.was_predicted == True,
            )
        )
        predicted = predicted_q.scalar() or 0

        # Total value liquidated
        value_q = await db.execute(
            select(func.sum(LiquidationEvent.collateral_seized_usd))
            .where(LiquidationEvent.occurred_at >= period_start)
        )
        total_value = value_q.scalar() or 0

        # Accuracy
        accuracy = (predicted / liquidations * 100) if liquidations > 0 else None

        report_text = (
            f"Liquidation Sentinel Daily Report\n"
            f"Period: {period_start.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
            f"Positions monitored: {positions_monitored}\n"
            f"High risk positions: {high_risk}\n"
            f"Liquidations occurred: {liquidations}\n"
            f"Correctly predicted: {predicted}\n"
            f"Prediction accuracy: {f'{accuracy:.1f}%' if accuracy is not None else 'N/A'}\n"
            f"Total value liquidated: ${total_value:,.0f}\n\n"
            f"Score: {int(accuracy) if accuracy is not None else 50}/100"
        )

        proof_hash = hashlib.sha256(report_text.encode()).hexdigest()

        report = LiquidationReport(
            report_type="daily",
            period_start=period_start,
            period_end=now,
            positions_monitored=positions_monitored,
            high_risk_positions=high_risk,
            liquidations_occurred=liquidations,
            liquidations_predicted=predicted,
            prediction_accuracy_pct=accuracy,
            total_value_liquidated_usd=total_value,
            report_text=report_text,
            proof_hash=f"0x{proof_hash}",
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        logger.info(
            "daily_report_generated",
            monitored=positions_monitored,
            liquidations=liquidations,
            accuracy=accuracy,
        )

        return {
            "report_id": report.id,
            "score": int(accuracy) if accuracy is not None else 50,
        }
