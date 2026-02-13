"""
Signal Parser — Uses Claude to extract structured trading signals from raw Telegram messages.
"""
import json
from pathlib import Path
from shared.claude_client import ask_claude_json
from shared.lightning import get_lightning
from agents.tipster.models.schemas import SignalParsed
from agents.tipster.config import MIN_CONFIDENCE, AGENT_NAME
import structlog

logger = structlog.get_logger()
lightning = get_lightning(AGENT_NAME)

PROMPT_PATH = Path(__file__).parent.parent / "templates" / "signal_parse_prompt.txt"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    return _system_prompt


def parse_signal(raw_text: str) -> SignalParsed | None:
    """
    Parse a raw Telegram message into a structured signal.
    Returns None if the message is not a valid signal.
    """
    lightning.emit_action("parse_signal", {"text": raw_text[:200]})

    try:
        result = ask_claude_json(
            system_prompt=_get_system_prompt(),
            user_message=raw_text,
            max_tokens=512,
        )
    except Exception as e:
        logger.error("signal_parse_failed", error=str(e), text=raw_text[:100])
        lightning.log_failure(task="parse_signal", prompt_used=_get_system_prompt()[:200], error=str(e))
        return None

    if not result.get("is_signal", False):
        logger.debug("not_a_signal", reasoning=result.get("reasoning", ""))
        return None

    confidence = result.get("confidence", 0.0)
    if confidence < MIN_CONFIDENCE:
        logger.debug("low_confidence_signal", confidence=confidence, token=result.get("token_symbol"))
        return None

    try:
        signal = SignalParsed(
            token_symbol=result["token_symbol"],
            token_name=result.get("token_name"),
            token_address=result.get("token_address"),
            chain=result.get("chain", "avalanche"),
            signal_type=result["signal_type"],
            confidence=confidence,
            entry_price=result.get("entry_price"),
            target_prices=result.get("target_prices", []),
            stop_loss=result.get("stop_loss"),
            timeframe=result.get("timeframe"),
            reasoning=result.get("reasoning", ""),
        )
        lightning.log_success("parse_signal", output={"token": signal.token_symbol, "type": signal.signal_type})
        logger.info(
            "signal_parsed",
            token=signal.token_symbol,
            type=signal.signal_type,
            confidence=signal.confidence,
        )
        return signal
    except Exception as e:
        logger.error("signal_validation_failed", error=str(e), result=result)
        lightning.log_failure(task="parse_signal", attempted_output=result, error=str(e))
        return None
