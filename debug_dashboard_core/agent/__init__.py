"""Debug Dashboard Agent — autonomous diagnostic agent.

Architecture: Observe → Reason → Act loop
- Tier 1 (free): File watcher + rule-based reasoning + existing checkers
- Tier 2 (on-demand): LLM deep analysis via LiteLLM

Agent is opt-in: only active when config has agent.enabled = true.
"""
from enum import Enum


class AgentState(Enum):
    IDLE = "idle"
    OBSERVING = "observing"
    REASONING = "reasoning"
    EXECUTING = "executing"
    WAITING_LLM = "waiting_llm"
    ERROR = "error"


__version__ = "0.1.0"
