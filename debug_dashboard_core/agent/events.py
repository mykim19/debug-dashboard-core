"""Agent event types and data classes."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(Enum):
    FILE_CHANGED = "file_changed"
    FILE_CREATED = "file_created"
    FILE_DELETED = "file_deleted"
    SCAN_REQUESTED = "scan_requested"
    SCAN_COMPLETED = "scan_completed"
    CRITICAL_DETECTED = "critical_detected"
    LLM_ANALYSIS_REQUESTED = "llm_analysis_requested"
    LLM_ANALYSIS_COMPLETED = "llm_analysis_completed"
    FIX_REQUESTED = "fix_requested"
    FIX_COMPLETED = "fix_completed"
    AGENT_STATE_CHANGED = "agent_state_changed"
    INSIGHT_GENERATED = "insight_generated"


@dataclass
class AgentEvent:
    """Core event flowing through the agent pipeline."""
    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""          # "watcher", "user", "reasoner", "executor"
    workspace_id: str = ""    # GPT 리스크 #2: 모든 이벤트에 workspace_id 포함


@dataclass
class FileChangeEvent:
    """Detail of a single file change detected by the observer."""
    path: str
    change_type: str          # "modified", "created", "deleted"
    extension: str
    relative_to_root: str


@dataclass
class LLMAnalysis:
    """Result of an LLM deep analysis (Tier 2)."""
    request_id: str
    checker_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    model_used: str
    analysis_text: str
    root_causes: List[str]
    fix_suggestions: List[Dict]
    # GPT 리스크 #5: evidence traceability
    evidence_summary: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
