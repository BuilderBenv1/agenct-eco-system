"""
Whale Analyzer — Uses Claude to analyze whale transactions and assess market impact.
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import async_session
from shared.claude_client import ask_claude_json
from shared.lightning import get_lightning
from shared.telegram_bot import send_alert
from agents.whale.models.db import WhaleTransaction, WhaleAnalysis, WhaleWallet
from agents.whale.config import SIGNIFICANCE_THRESHOLDS, ALERT_MIN_SIGNIFICANCE, AGENT_NAME
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)

PROMPT_PATH = Path(__file__).parent.parent / "templates" / "analysis_prompt.txt"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    return _system_prompt


def _determine_significance(amount_usd: float) -> str:
    for level, threshold in sorted(SIGNIFICANCE_THRESHOLDS.items(), key=lambda x: x[1], reverse=True):
        if amount_usd >= threshold:
            return level
    return "low"


async def analyze_transaction(
    db: AsyncSession,
    tx: WhaleTransaction,
    wallet: WhaleWallet,
) -> WhaleAnalysis | None:
    """Analyze a single whale transaction using Claude."""
    tx_data = {
        "tx_hash": tx.tx_hash,
        "tx_type": tx.tx_type,
        "from": tx.from_address,
        "to": tx.to_address,
        "token": tx.token_symbol or "AVAX",
        "amount": str(tx.amount),
        "amount_usd": float(tx.amount_usd) if tx.amount_usd else 0,
        "method": tx.decoded_method,
        "wallet_label": wallet.label or "Unknown",
        "wallet_category": wallet.category or "unknown",
    }

    # Skip Claude for low-value transactions — just store with basic info
    amount_usd = float(tx.amount_usd) if tx.amount_usd else 0
    significance = _determine_significance(amount_usd)

    if significance == "low":
        analysis = WhaleAnalysis(
            transaction_id=tx.id,
            wallet_id=wallet.id,
            significance=significance,
            analysis_text=f"{wallet.label or 'Whale'} {tx.tx_type} of {tx.token_symbol or 'AVAX'} (${amount_usd:,.0f})",
            pattern=tx.tx_type,
        )
        db.add(analysis)
        return analysis

    lightning.emit_action("analyze_tx", {"tx_hash": tx.tx_hash[:16], "amount_usd": amount_usd})

    try:
        result = ask_claude_json(
            system_prompt=_get_system_prompt(),
            user_message=json.dumps(tx_data, default=str),
            max_tokens=512,
        )
    except Exception as e:
        logger.error("analysis_failed", error=str(e), tx_hash=tx.tx_hash)
        lightning.log_failure(task="analyze_tx", error=str(e), context=tx_data)
        return None

    analysis = WhaleAnalysis(
        transaction_id=tx.id,
        wallet_id=wallet.id,
        significance=result.get("significance", significance),
        analysis_text=result.get("analysis", ""),
        market_impact=result.get("market_impact", ""),
        pattern_detected=result.get("pattern", "unknown"),
    )
    db.add(analysis)

    lightning.log_success("analyze_tx", output={"significance": analysis.significance, "pattern": analysis.pattern_detected})
    logger.info(
        "tx_analyzed",
        tx_hash=tx.tx_hash[:10],
        significance=analysis.significance,
        pattern=analysis.pattern_detected,
    )
    return analysis


SIGNIFICANCE_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _should_alert(significance: str) -> bool:
    return SIGNIFICANCE_RANK.get(significance, 0) >= SIGNIFICANCE_RANK.get(ALERT_MIN_SIGNIFICANCE, 3)


def _format_alert(tx: WhaleTransaction, wallet: WhaleWallet, analysis: WhaleAnalysis) -> str:
    amount_usd = float(tx.amount_usd) if tx.amount_usd else 0
    emoji = {"critical": "🚨", "high": "⚠️"}.get(analysis.significance, "📊")
    return (
        f"{emoji} *Whale Alert — {analysis.significance.upper()}*\n\n"
        f"*{wallet.label or wallet.address[:10]}* ({wallet.category or 'unknown'})\n"
        f"Type: `{tx.tx_type}` | Token: `{tx.token_symbol or 'AVAX'}`\n"
        f"Amount: *${amount_usd:,.0f}*\n\n"
        f"{analysis.analysis_text or ''}\n\n"
        f"{'_' + analysis.market_impact + '_' if analysis.market_impact else ''}"
    )


async def _send_whale_alerts(db: AsyncSession, tx: WhaleTransaction, wallet: WhaleWallet, analysis: WhaleAnalysis):
    """Send Telegram alerts to subscribers for significant whale movements."""
    from sqlalchemy import text
    result = await db.execute(
        text("SELECT chat_id FROM subscribers WHERE is_active = true AND subscribed_agents::jsonb ? 'whale'")
    )
    chat_ids = [row[0] for row in result.fetchall()]
    if not chat_ids:
        return

    msg = _format_alert(tx, wallet, analysis)
    sent = 0
    for chat_id in chat_ids:
        try:
            await send_alert(chat_id, msg)
            sent += 1
        except Exception as e:
            logger.debug("alert_send_failed", chat_id=chat_id, error=str(e))

    # Mark alert as sent
    analysis.alert_sent = True
    analysis.alert_chat_ids = chat_ids
    logger.info("whale_alerts_sent", count=sent, significance=analysis.significance)


async def analyze_pending_transactions():
    """Analyze all transactions that don't have an analysis yet."""
    if async_session is None:
        return

    async with async_session() as db:
        # Find transactions without analysis
        subq = select(WhaleAnalysis.transaction_id)
        result = await db.execute(
            select(WhaleTransaction)
            .where(WhaleTransaction.id.notin_(subq))
            .order_by(WhaleTransaction.detected_at.desc())
            .limit(20)
        )
        txns = list(result.scalars().all())

        for tx in txns:
            wallet_q = await db.execute(
                select(WhaleWallet).where(WhaleWallet.id == tx.wallet_id)
            )
            wallet = wallet_q.scalar_one_or_none()
            if wallet:
                analysis = await analyze_transaction(db, tx, wallet)
                if analysis and _should_alert(analysis.significance):
                    await _send_whale_alerts(db, tx, wallet, analysis)

        if txns:
            await db.commit()
            logger.info("batch_analysis_complete", count=len(txns))


async def get_daily_stats(
    db: AsyncSession,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> dict:
    """Get daily aggregated stats for reporting."""
    if period_end is None:
        period_end = datetime.now(timezone.utc)
    if period_start is None:
        period_start = period_end - timedelta(days=1)

    result = await db.execute(
        select(WhaleTransaction)
        .where(
            WhaleTransaction.detected_at >= period_start,
            WhaleTransaction.detected_at <= period_end,
        )
    )
    txns = list(result.scalars().all())

    total_volume = sum(float(t.amount_usd or 0) for t in txns)

    # Top movers by volume
    wallet_volumes: dict[int, float] = {}
    for t in txns:
        wid = t.wallet_id
        wallet_volumes[wid] = wallet_volumes.get(wid, 0) + float(t.amount_usd or 0)

    top_wallet_ids = sorted(wallet_volumes, key=wallet_volumes.get, reverse=True)[:5]
    top_movers = []
    for wid in top_wallet_ids:
        wq = await db.execute(select(WhaleWallet).where(WhaleWallet.id == wid))
        w = wq.scalar_one_or_none()
        if w:
            top_movers.append({
                "label": w.label or w.address[:10],
                "address": w.address,
                "volume_usd": wallet_volumes[wid],
            })

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_transactions": len(txns),
        "total_volume_usd": total_volume,
        "top_movers": top_movers,
        "tx_types": _count_types(txns),
    }


def _count_types(txns: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in txns:
        counts[t.tx_type] = counts.get(t.tx_type, 0) + 1
    return counts
