"""
Auditor Analyzer — Uses Claude to perform deep rug-pull analysis on scanned contracts.
Refines initial on-chain scores with AI-driven pattern recognition.
"""
import json
from pathlib import Path
from sqlalchemy import select, update
from shared.database import async_session
from shared.claude_client import ask_claude_json
from shared.lightning import get_lightning
from shared.telegram_bot import send_alert
from agents.auditor.models.db import ContractScan
from agents.auditor.config import AGENT_NAME, ALERT_MIN_RISK, RISK_LABELS
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)

PROMPT_PATH = Path(__file__).parent.parent / "templates" / "audit_prompt.txt"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    return _system_prompt


def _get_risk_label(score: int) -> str:
    """Convert numeric risk score to label."""
    for label, (low, high) in RISK_LABELS.items():
        if low <= score <= high:
            return label
    return "rug" if score > 75 else "safe"


async def analyze_scan(scan: ContractScan) -> ContractScan | None:
    """Run Claude analysis on a scan that has initial on-chain scores."""
    scan_data = {
        "contract_address": scan.contract_address,
        "token_symbol": scan.token_symbol or "UNKNOWN",
        "token_name": scan.token_name or "Unknown Token",
        "deployer_address": scan.deployer_address or "unknown",
        "initial_scores": {
            "honeypot_score": scan.honeypot_score,
            "ownership_concentration_score": scan.ownership_concentration_score,
            "liquidity_lock_score": scan.liquidity_lock_score,
            "code_similarity_rug_score": scan.code_similarity_rug_score,
            "tax_manipulation_score": scan.tax_manipulation_score,
        },
        "red_flags": scan.red_flags or [],
        "top_holder_pct": scan.top_holder_pct,
        "holder_count": scan.holder_count,
        "liquidity_usd": scan.liquidity_usd,
    }

    lightning.emit_action("analyze_contract", {
        "address": scan.contract_address[:16],
        "initial_risk": scan.overall_risk_score,
    })

    try:
        result = ask_claude_json(
            system_prompt=_get_system_prompt(),
            user_message=json.dumps(scan_data, default=str),
            max_tokens=1024,
        )
    except Exception as e:
        logger.error("claude_analysis_failed", error=str(e), address=scan.contract_address)
        lightning.log_failure(task="analyze_contract", error=str(e), context=scan_data)
        return None

    # Update scan with Claude's refined scores
    if async_session is None:
        return None

    async with async_session() as db:
        new_overall = result.get("overall_risk_score", scan.overall_risk_score)
        new_label = result.get("risk_label", _get_risk_label(new_overall))

        await db.execute(
            update(ContractScan)
            .where(ContractScan.id == scan.id)
            .values(
                honeypot_score=result.get("honeypot_score", scan.honeypot_score),
                ownership_concentration_score=result.get("ownership_concentration_score", scan.ownership_concentration_score),
                liquidity_lock_score=result.get("liquidity_lock_score", scan.liquidity_lock_score),
                code_similarity_rug_score=result.get("code_similarity_rug_score", scan.code_similarity_rug_score),
                tax_manipulation_score=result.get("tax_manipulation_score", scan.tax_manipulation_score),
                overall_risk_score=new_overall,
                risk_label=new_label,
                red_flags=result.get("red_flags", scan.red_flags),
                analysis_text=result.get("analysis", ""),
            )
        )
        await db.commit()

        # Refresh the scan object
        refreshed = await db.execute(
            select(ContractScan).where(ContractScan.id == scan.id)
        )
        scan = refreshed.scalar_one()

    lightning.log_success("analyze_contract", output={
        "risk_label": new_label,
        "overall_score": new_overall,
        "flags": len(result.get("red_flags", [])),
    })

    logger.info(
        "contract_analyzed",
        address=scan.contract_address[:10],
        risk_label=new_label,
        score=new_overall,
    )

    return scan


def _should_alert(risk_score: int) -> bool:
    """Determine if a scan warrants a Telegram alert."""
    return risk_score >= ALERT_MIN_RISK


def _format_alert(scan: ContractScan) -> str:
    """Format a rug alert for Telegram."""
    label = (scan.risk_label or "unknown").upper()
    emoji = {"DANGER": "⚠️", "RUG": "🚨"}.get(label, "🔍")
    flags = scan.red_flags or []
    flags_text = "\n".join(f"  • {f}" for f in flags[:5]) if flags else "  None detected"

    return (
        f"{emoji} *Rug Detector Alert — {label}*\n\n"
        f"Token: `{scan.token_symbol or 'UNKNOWN'}` ({scan.token_name or 'Unknown'})\n"
        f"Contract: `{scan.contract_address[:10]}...{scan.contract_address[-6:]}`\n"
        f"Risk Score: *{scan.overall_risk_score}/100*\n\n"
        f"*Scores:*\n"
        f"  Honeypot: {scan.honeypot_score}\n"
        f"  Ownership: {scan.ownership_concentration_score}\n"
        f"  Liquidity: {scan.liquidity_lock_score}\n"
        f"  Code Pattern: {scan.code_similarity_rug_score}\n"
        f"  Tax Risk: {scan.tax_manipulation_score}\n\n"
        f"*Red Flags:*\n{flags_text}\n\n"
        f"{'_' + (scan.analysis_text or '') + '_' if scan.analysis_text else ''}"
    )


async def _send_rug_alerts(scan: ContractScan):
    """Send Telegram alerts to subscribers for dangerous token detections."""
    if async_session is None:
        return

    async with async_session() as db:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT chat_id FROM subscribers WHERE is_active = true AND subscribed_agents::jsonb ? 'auditor'")
        )
        chat_ids = [row[0] for row in result.fetchall()]
        if not chat_ids:
            return

        msg = _format_alert(scan)
        sent = 0
        for chat_id in chat_ids:
            try:
                await send_alert(chat_id, msg)
                sent += 1
            except Exception as e:
                logger.debug("alert_send_failed", chat_id=chat_id, error=str(e))

        logger.info("rug_alerts_sent", count=sent, address=scan.contract_address[:10])


async def analyze_pending_scans():
    """Analyze all scans that don't have Claude analysis yet."""
    if async_session is None:
        return

    async with async_session() as db:
        result = await db.execute(
            select(ContractScan)
            .where(ContractScan.analysis_text.is_(None))
            .order_by(ContractScan.overall_risk_score.desc())
            .limit(10)
        )
        scans = list(result.scalars().all())

    for scan in scans:
        analyzed = await analyze_scan(scan)
        if analyzed and _should_alert(analyzed.overall_risk_score):
            await _send_rug_alerts(analyzed)

    if scans:
        logger.info("batch_analysis_complete", count=len(scans))
