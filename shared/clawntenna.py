"""
Clawntenna Integration — Python bridge to the Clawntenna encrypted messaging protocol.

Clawntenna SDK is TypeScript-only (npm install clawntenna). This module provides:
1. A Node.js subprocess bridge for sending/receiving encrypted messages
2. Direct smart contract interaction via web3.py for on-chain queries
3. A message handler abstraction that agents implement

Architecture:
  Python Agent → ClawntennaBridge → Node.js subprocess (clawntenna SDK)
  Python Agent → ClawntennaBridge → web3.py (direct contract calls)
"""
import asyncio
import json
import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable
from pathlib import Path
from shared.config import settings
import structlog

logger = structlog.get_logger()

BRIDGE_SCRIPT = Path(__file__).parent.parent / "clawntenna_bridge" / "bridge.js"


class ClawntennMessage:
    """Represents an incoming Clawntenna message."""

    def __init__(
        self,
        topic_id: str,
        sender: str,
        text: str,
        payment_avax: float = 0.0,
        timestamp: datetime | None = None,
        encrypted: bool = True,
    ):
        self.topic_id = topic_id
        self.sender = sender
        self.text = text
        self.payment_avax = payment_avax
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.encrypted = encrypted

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "sender": self.sender,
            "text": self.text,
            "payment_avax": self.payment_avax,
            "timestamp": self.timestamp.isoformat(),
        }


class ClawntennaBridge:
    """
    Bridge between Python agents and the Clawntenna TypeScript SDK.

    Modes:
    - subprocess: Runs bridge.js via Node.js for full SDK functionality
    - mock: In-memory mode for development/testing
    """

    def __init__(self, agent_name: str, chain: str = "avalanche"):
        self.agent_name = agent_name
        self.chain = chain
        self.topic_id: str | None = None
        self._handlers: list[Callable[[ClawntennMessage], Awaitable[str | None]]] = []
        self._running = False

        # Pricing per agent (AVAX per query)
        self.query_prices = {
            "tipster": 0.01,
            "whale": 0.02,
            "narrative": 0.05,
        }

    def set_topic(self, topic_id: str):
        """Set the Clawntenna topic ID for this agent's feed."""
        self.topic_id = topic_id

    def on_message(self, handler: Callable[[ClawntennMessage], Awaitable[str | None]]):
        """Register a message handler. Handler returns response text or None."""
        self._handlers.append(handler)

    async def send_response(self, topic_id: str, text: str):
        """Send an encrypted response to a topic."""
        if BRIDGE_SCRIPT.exists():
            await self._call_bridge("send", {
                "topicId": topic_id,
                "text": text,
                "chain": self.chain,
            })
        else:
            logger.info("clawntenna_response_mock", topic=topic_id, text=text[:100])

    async def handle_incoming(self, raw_message: dict) -> str | None:
        """
        Process an incoming Clawntenna message through all registered handlers.
        Returns the response text or None.
        """
        msg = ClawntennMessage(
            topic_id=raw_message.get("topic_id", ""),
            sender=raw_message.get("sender", ""),
            text=raw_message.get("text", ""),
            payment_avax=raw_message.get("payment_avax", 0.0),
        )

        # Validate payment
        min_price = self.query_prices.get(self.agent_name, 0.01)
        if msg.payment_avax < min_price:
            return f"Insufficient payment. Minimum {min_price} AVAX required for {self.agent_name} queries."

        # Process through handlers
        for handler in self._handlers:
            try:
                response = await handler(msg)
                if response:
                    logger.info(
                        "clawntenna_query_handled",
                        agent=self.agent_name,
                        sender=msg.sender[:10],
                        payment=msg.payment_avax,
                    )
                    return response
            except Exception as e:
                logger.error("clawntenna_handler_error", error=str(e))

        return None

    async def start_listening(self):
        """Start polling for new Clawntenna messages (via bridge.js)."""
        if not self.topic_id:
            logger.warning("clawntenna_no_topic_set", agent=self.agent_name)
            return

        if not BRIDGE_SCRIPT.exists():
            logger.info("clawntenna_bridge_not_found", agent=self.agent_name)
            return

        self._running = True
        logger.info("clawntenna_listening", agent=self.agent_name, topic=self.topic_id)

        while self._running:
            try:
                messages = await self._call_bridge("read", {
                    "topicId": self.topic_id,
                    "chain": self.chain,
                })
                if messages:
                    for raw_msg in messages:
                        response = await self.handle_incoming(raw_msg)
                        if response:
                            await self.send_response(self.topic_id, response)
            except Exception as e:
                logger.error("clawntenna_poll_error", error=str(e))

            await asyncio.sleep(5)

    def stop_listening(self):
        self._running = False

    async def _call_bridge(self, action: str, data: dict) -> Any:
        """Call the Node.js bridge script."""
        try:
            payload = json.dumps({"action": action, **data})
            proc = await asyncio.create_subprocess_exec(
                "node", str(BRIDGE_SCRIPT), payload,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                logger.error("bridge_error", stderr=stderr.decode()[:200])
                return None
            return json.loads(stdout.decode()) if stdout else None
        except asyncio.TimeoutError:
            logger.error("bridge_timeout", action=action)
            return None
        except FileNotFoundError:
            logger.warning("node_not_found")
            return None


# Singleton instances
_bridges: dict[str, ClawntennaBridge] = {}


def get_bridge(agent_name: str) -> ClawntennaBridge:
    """Get or create the Clawntenna bridge for an agent."""
    if agent_name not in _bridges:
        _bridges[agent_name] = ClawntennaBridge(agent_name)
    return _bridges[agent_name]
