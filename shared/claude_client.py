import json
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from shared.config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY) if settings.ANTHROPIC_API_KEY else None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
def ask_claude(
    system_prompt: str,
    user_message: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> str:
    """Send a prompt to Claude and return the text response."""
    if not client:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def ask_claude_json(
    system_prompt: str,
    user_message: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 2048,
) -> dict:
    """Send a prompt to Claude and parse JSON response."""
    text = ask_claude(
        system_prompt=system_prompt + "\n\nRespond ONLY with valid JSON, no markdown fences.",
        user_message=user_message,
        model=model,
        max_tokens=max_tokens,
        temperature=0.1,
    )
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text)
