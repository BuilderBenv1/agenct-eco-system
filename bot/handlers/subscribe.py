"""
/subscribe handler — Show subscription info and on-chain subscription link.
"""
from telegram import Update
from telegram.ext import ContextTypes

SUBSCRIBE_MSG = """
*AgentProof Subscriptions* 💳

Subscribe on-chain to access premium agent features:

*Plans:*
📊 *Tipster Verifier* — Real-time signal alerts
   - Price: Set by agent owner
   - Features: Instant alerts, full signal history, weekly reports

🐋 *Whale Tracker* — Real-time whale alerts
   - Price: Set by agent owner
   - Features: Live whale alerts (high significance), daily reports

📰 *Narrative Scanner* — Daily narrative intelligence
   - Price: Set by agent owner
   - Features: Trend alerts, daily sentiment reports

*How to Subscribe:*
1. Register your wallet: /register <address>
2. Visit our dApp to subscribe on-chain
3. Your subscription is verified automatically via smart contract

*Contract:* `0x52Fd16FA8d676351c7FEEf7564968D3bD58126a3`
_SubscriptionManager on Avalanche C-Chain_

Once subscribed, you'll receive real-time alerts automatically.
"""


async def subscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(SUBSCRIBE_MSG, parse_mode="Markdown")
