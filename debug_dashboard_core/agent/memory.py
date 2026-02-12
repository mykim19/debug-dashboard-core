"""AgentMemory — persistent agent context stored in SQLite.

Tracks: recent events, scan reports, LLM analyses, insights.
Uses the same SQLite DB as storage.py (extended tables).
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from .. import storage
from .events import AgentEvent


class AgentMemory:
    """In-memory + SQLite-backed agent memory.

    - In-memory: fast access for the Reasoner (recent events, scan diffs)
    - SQLite: persistence for history, LLM analyses, insights
    """

    def __init__(self, workspace_id: str = "", max_memory_events: int = 500):
        self._workspace_id = workspace_id
        self._recent_events: List[dict] = []
        self._max = max_memory_events
        self._last_scan_time: Optional[datetime] = None
        self._scan_reports: List[Dict] = []  # last N scan report snapshots

    def record_event(self, event: AgentEvent):
        """Record event to in-memory buffer and SQLite."""
        entry = {
            "type": event.type.value,
            "timestamp": event.timestamp.isoformat(),
            "source": event.source,
            "data": event.data,
        }
        self._recent_events.append(entry)
        if len(self._recent_events) > self._max:
            self._recent_events = self._recent_events[-self._max:]

        # Persist to SQLite
        try:
            storage.save_agent_event(
                event_type=event.type.value,
                source=event.source,
                data_json=json.dumps(event.data, ensure_ascii=False, default=str),
                workspace_id=self._workspace_id,
            )
        except Exception:
            pass  # Non-critical: don't break agent loop on storage error

    def record_scan_reports(self, reports: Dict[str, dict]):
        """Record a scan result snapshot for diff/regression analysis."""
        self._scan_reports.insert(0, reports)
        if len(self._scan_reports) > 10:
            self._scan_reports = self._scan_reports[:10]
        self._last_scan_time = datetime.now()

    def get_last_scan_time(self) -> Optional[datetime]:
        return self._last_scan_time

    def get_recent_scan_reports(self, limit: int = 2) -> List[Dict]:
        return self._scan_reports[:limit]

    def get_recent_events(self, limit: int = 50) -> List[dict]:
        return self._recent_events[-limit:]

    def get_recent_file_changes(self, limit: int = 20) -> List[dict]:
        """Get recent file change events (for LLM evidence context)."""
        changes = []
        for e in reversed(self._recent_events):
            if e.get("type") == "file_changed":
                changes.append(e)
                if len(changes) >= limit:
                    break
        return changes

    def get_context_for_llm(self, checker_name: str) -> dict:
        """GPT Risk #5: Build rich evidence context for LLM prompt.

        Includes: recent reports, file changes, regression diffs, env summary.
        """
        # Recent reports for this checker
        recent_for_checker = []
        for reports in self._scan_reports[:3]:
            if checker_name in reports:
                recent_for_checker.append(reports[checker_name])

        # Regression detection: PASS→FAIL diff
        regressions = []
        if len(self._scan_reports) >= 2:
            current = self._scan_reports[0].get(checker_name, {})
            previous = self._scan_reports[1].get(checker_name, {})
            cur_checks = {c["name"]: c for c in current.get("checks", [])}
            prev_checks = {c["name"]: c for c in previous.get("checks", [])}
            for name, cur_c in cur_checks.items():
                prev_c = prev_checks.get(name)
                if prev_c and prev_c["status"] == "PASS" and cur_c["status"] in ("FAIL", "WARN"):
                    regressions.append({
                        "check": name,
                        "was": prev_c["status"],
                        "now": cur_c["status"],
                        "message": cur_c.get("message", ""),
                    })

        # Recent file changes
        file_changes = self.get_recent_file_changes(10)

        return {
            "checker": checker_name,
            "workspace_id": self._workspace_id,
            "recent_reports": recent_for_checker,
            "regressions": regressions,
            "recent_file_changes": [
                fc.get("data", {}).get("files", [])[:5]
                for fc in file_changes[:3]
            ],
            "total_events_in_memory": len(self._recent_events),
        }
