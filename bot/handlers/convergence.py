"""
/convergence command — Shows cross-agent convergence signals.
"""
from telegram import Update
from telegram.ext import ContextTypes
import httpx


async def convergence_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent cross-agent convergence signals."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "http://127.0.0.1:8000/api/v1/convergence/signals",
                params={"limit": 5},
                timeout=5.0,
            )
            signals = r.json()
    except Exception:
        await update.message.reply_text("Convergence service unavailable.")
        return

    if not signals:
        await update.message.reply_text(
            "No convergence signals detected yet.\n\n"
            "Convergence occurs when 2+ agents independently flag the same token."
        )
        return

    lines = ["*Cross-Agent Convergence Signals*\n"]
    for s in signals:
        emoji = "🔴" if s["agent_count"] == 3 else "🟡"
        direction = s.get("direction", "neutral")
        agreement = " ✓" if s.get("agreement") else ""
        lines.append(
            f"{emoji} *{s['token']}* — {s['agent_count']} agents ({s['multiplier']:.1f}x)\n"
            f"   Score: {s['score']:.0f} | Direction: {direction}{agreement}\n"
            f"   Agents: {', '.join(s['agents'])}\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
