"""
SOS Tracker — Track saves and generate reports.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from shared.database import async_session
from agents.sos.models.db import SOSConfig, SOSEvent, SOSReport
import hashlib
import structlog

logger = structlog.get_logger()


async def generate_daily_report() -> dict | None:
    if async_session is None:
        return None

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    async with async_session() as db:
        active = await db.execute(
            select(func.count()).select_from(SOSConfig).where(SOSConfig.is_active == True)
        )
        active_count = active.scalar() or 0

        events_today = await db.execute(
            select(func.count()).select_from(SOSEvent)
            .where(SOSEvent.triggered_at >= day_ago)
        )
        events = events_today.scalar() or 0

        value_saved = await db.execute(
            select(func.coalesce(func.sum(SOSEvent.total_value_saved_usd), 0))
            .where(SOSEvent.triggered_at >= day_ago)
        )
        saved = float(value_saved.scalar() or 0)

        # Triggers by type
        type_dist = await db.execute(
            select(SOSEvent.trigger_type, func.count())
            .where(SOSEvent.triggered_at >= day_ago)
            .group_by(SOSEvent.trigger_type)
        )
        triggers_by_type = {row[0]: row[1] for row in type_dist}

        proof_data = f"sos-daily-{now.date()}-configs:{active_count}-events:{events}-saved:{saved:.2f}"
        proof_hash = "0x" + hashlib.sha256(proof_data.encode()).hexdigest()

        report = SOSReport(
            report_type="daily",
            period_start=day_ago,
            period_end=now,
            active_configs=active_count,
            events_triggered=events,
            total_value_saved=saved,
            triggers_by_type=triggers_by_type,
            report_text=f"SOS Daily: {active_count} configs, {events} triggers, ${saved:.0f} saved",
            proof_hash=proof_hash,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        # Score: value saved / total monitored * 100
        total_monitored = await db.execute(
            select(func.coalesce(func.sum(SOSConfig.total_value_saved_usd), 0))
        )
        total = float(total_monitored.scalar() or 1)
        score = min(100, int(saved / total * 100)) if total > 0 else 50
        return {"report_id": report.id, "score": score}
