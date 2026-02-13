"""
Agent Lightning Integration — wraps Microsoft's agentlightning framework
for RL-based self-improvement of all three agents.

The installed agentlightning SDK uses LitAgent subclassing and reward() for training.
This wrapper provides:
1. Failure logging to JSONL (immediate value — feeds APO training later)
2. Success/action tracing for reward signals
3. Clean interface that gracefully degrades when training isn't active
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import structlog

logger = structlog.get_logger()

# Check if agentlightning is installed
try:
    import agentlightning as agl
    AGL_AVAILABLE = True
except ImportError:
    AGL_AVAILABLE = False

FAILURE_LOG_DIR = Path(__file__).parent.parent / "data"
FAILURE_LOG_DIR.mkdir(exist_ok=True)


class AgentLightning:
    """
    Wrapper around Agent Lightning for a single agent.

    Provides:
    - emit_action: Record an agent decision/action
    - emit_observation: Record outcome with reward signal
    - log_failure: Persist failures for offline APO analysis
    - log_success: Record successful outcomes
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.failure_log_path = FAILURE_LOG_DIR / f"{agent_name}_failures.jsonl"
        self.success_log_path = FAILURE_LOG_DIR / f"{agent_name}_successes.jsonl"
        self._action_count = 0
        self._failure_count = 0
        self._success_count = 0

    def emit_action(self, action_name: str, data: dict[str, Any]):
        """Record an agent action/decision."""
        self._action_count += 1
        logger.debug("lightning_action", agent=self.agent_name, action=action_name)

    def emit_observation(self, observation_name: str, data: dict[str, Any], reward: float = 0.0):
        """Record an observation/outcome with reward signal."""
        logger.debug(
            "lightning_observation",
            agent=self.agent_name,
            observation=observation_name,
            reward=reward,
        )

    def log_failure(
        self,
        task: str,
        prompt_used: str = "",
        attempted_output: Any = None,
        expected_output: Any = None,
        error: str = "",
        context: dict | None = None,
    ):
        """
        Log a failure for Agent Lightning APO (Automatic Prompt Optimization).
        Persisted to JSONL for offline training.
        """
        self._failure_count += 1
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": self.agent_name,
            "task": task,
            "prompt_used": prompt_used[:500] if prompt_used else "",
            "attempted_output": _safe_serialize(attempted_output),
            "expected_output": _safe_serialize(expected_output),
            "error": error,
            "context": context or {},
        }

        try:
            with open(self.failure_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error("failure_log_write_failed", error=str(e))

        logger.info("failure_logged", agent=self.agent_name, task=task, error=error[:100])

    def log_success(self, task: str, output: Any = None, reward: float = 1.0):
        """Log a successful task execution."""
        self._success_count += 1
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": self.agent_name,
            "task": task,
            "output": _safe_serialize(output),
            "reward": reward,
        }

        try:
            with open(self.success_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error("success_log_write_failed", error=str(e))

    def get_failure_count(self) -> int:
        if not self.failure_log_path.exists():
            return 0
        with open(self.failure_log_path, "r") as f:
            return sum(1 for _ in f)

    def get_recent_failures(self, limit: int = 10) -> list[dict]:
        if not self.failure_log_path.exists():
            return []
        failures = []
        with open(self.failure_log_path, "r") as f:
            for line in f:
                try:
                    failures.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return failures[-limit:]

    def get_stats(self) -> dict:
        """Get runtime stats for this agent's Lightning instance."""
        return {
            "agent": self.agent_name,
            "actions": self._action_count,
            "successes": self._success_count,
            "failures": self._failure_count,
            "agl_available": AGL_AVAILABLE,
        }


def _safe_serialize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(x) for x in obj[:20]]
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in list(obj.items())[:20]}
    return str(obj)[:500]


# Singleton instances per agent
_instances: dict[str, AgentLightning] = {}


def get_lightning(agent_name: str) -> AgentLightning:
    """Get or create the AgentLightning instance for an agent."""
    if agent_name not in _instances:
        _instances[agent_name] = AgentLightning(agent_name)
    return _instances[agent_name]
