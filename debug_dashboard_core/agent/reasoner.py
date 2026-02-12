"""Reasoner — decides which actions to take based on events and memory.

Tier 1 (always on): maps events to checker execution via rules.
Tier 2 (on-demand): decides when LLM analysis is needed.

GPT Risk #3 addressed: 2-stage reasoning (fast mapping → heuristic refine).
GPT Risk #6 addressed: scan-in-progress guard.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Set

from .events import AgentEvent, EventType
from .memory import AgentMemory

logger = logging.getLogger("agent.reasoner")


@dataclass
class Action:
    """An action the executor should perform."""
    action_type: str        # "run_checkers", "llm_analyze", "emit_insights"
    checker_names: List[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


class Reasoner:
    """Rule-based reasoning engine with 2-stage evaluation.

    Stage 1 — Fast mapping: event type → relevant checkers
    Stage 2 — Heuristic refine: cooldown, dedup, regression, correlation
    """

    def __init__(self, config: dict, checker_names: List[str]):
        self._config = config
        self._checker_names = set(checker_names)
        agent_cfg = config.get("agent", {})
        self._cooldown_seconds = agent_cfg.get("scan_cooldown_seconds", 30)
        self._auto_scan = agent_cfg.get("auto_scan_on_change", True)
        self._auto_llm_on_critical = agent_cfg.get("auto_llm_on_critical", False)
        # GPT Review #4-5: manual scans bypass cooldown (user intent) but have a
        # minimum interval to prevent button-mashing / script abuse
        self._manual_min_interval = agent_cfg.get("manual_scan_min_interval", 2)
        self._last_manual_scan: Optional[datetime] = None

    def evaluate(self, event: AgentEvent, memory: AgentMemory) -> List[Action]:
        """Evaluate an event and return a list of actions."""
        actions: List[Action] = []

        if event.type == EventType.FILE_CHANGED:
            actions.extend(self._handle_file_change(event, memory))

        elif event.type == EventType.SCAN_REQUESTED:
            # GPT Review #4-5: manual scans intentionally bypass auto-scan cooldown,
            # but enforce a shorter minimum interval to prevent rapid-fire abuse.
            # GPT Review #5-5: return an explicit rate_limited action so the UI can
            # display a clear message ("N초 후 다시 시도하세요").
            if self._last_manual_scan:
                elapsed = (datetime.now() - self._last_manual_scan).total_seconds()
                if elapsed < self._manual_min_interval:
                    remaining = self._manual_min_interval - elapsed
                    logger.debug(
                        f"Manual scan rate-limited: {elapsed:.1f}s < {self._manual_min_interval}s"
                    )
                    actions.append(Action(
                        "emit_insights",
                        data={"rate_limited": True, "retry_after": round(remaining, 1)},
                    ))
                    return actions
            self._last_manual_scan = datetime.now()

            checkers = event.data.get("checkers")
            if checkers:
                valid = [c for c in checkers if c in self._checker_names]
                if valid:
                    actions.append(Action("run_checkers", checker_names=valid))
            else:
                actions.append(Action(
                    "run_checkers",
                    checker_names=sorted(self._checker_names)
                ))

        elif event.type == EventType.LLM_ANALYSIS_REQUESTED:
            checker = event.data.get("checker", "")
            if checker:
                actions.append(Action("llm_analyze", data={"checker": checker}))

        elif event.type == EventType.SCAN_COMPLETED:
            # Cross-checker reasoning (post-scan)
            insights = self._cross_checker_insights(event, memory)
            if insights:
                actions.append(Action("emit_insights", data={"insights": insights}))

            # Auto-escalate to LLM on CRITICAL
            if (self._auto_llm_on_critical
                    and event.data.get("has_critical")
                    and event.data.get("failing_checkers")):
                for checker_name in event.data["failing_checkers"][:3]:
                    actions.append(Action(
                        "llm_analyze",
                        data={"checker": checker_name}
                    ))

        return actions

    def _handle_file_change(self, event: AgentEvent, memory: AgentMemory) -> List[Action]:
        """Stage 1: Fast mapping + Stage 2: Cooldown/dedup/refine."""
        if not self._auto_scan:
            return []

        # Stage 2a: Cooldown
        last_scan_time = memory.get_last_scan_time()
        if last_scan_time:
            elapsed = (datetime.now() - last_scan_time).total_seconds()
            if elapsed < self._cooldown_seconds:
                logger.debug(
                    f"Cooldown: {elapsed:.0f}s < {self._cooldown_seconds}s, skipping"
                )
                return []

        # Stage 1: Use observer's pre-computed affected_checkers
        affected = event.data.get("affected_checkers", [])
        valid = [c for c in affected if c in self._checker_names]

        if not valid:
            return []

        # Stage 2b: If too many checkers triggered, just run all
        # (avoids partial-scan confusion when many files change at once)
        if len(valid) > len(self._checker_names) * 0.6:
            logger.info("Many checkers affected, running full scan")
            return [Action("run_checkers", checker_names=sorted(self._checker_names))]

        logger.info(f"File change → running checkers: {valid}")
        return [Action("run_checkers", checker_names=valid)]

    def _cross_checker_insights(self, event: AgentEvent, memory: AgentMemory) -> List[dict]:
        """Post-scan analysis: detect regressions and correlations.

        This is Tier 1 (free, rule-based) cross-checker reasoning.
        """
        insights: List[dict] = []
        recent = memory.get_recent_scan_reports(limit=2)
        if len(recent) < 2:
            return insights

        current, previous = recent[0], recent[1]

        # 1. Regression detection: PASS → FAIL
        for checker_name, cur_report in current.items():
            prev_report = previous.get(checker_name)
            if not prev_report:
                continue
            cur_fails = {
                c["name"] for c in cur_report.get("checks", [])
                if c["status"] == "FAIL"
            }
            prev_fails = {
                c["name"] for c in prev_report.get("checks", [])
                if c["status"] == "FAIL"
            }
            new_fails = cur_fails - prev_fails
            if new_fails:
                insights.append({
                    "type": "regression",
                    "checker": checker_name,
                    "message": f"New failures: {', '.join(sorted(new_fails))}",
                    "severity": "high",
                    "details": {"new_fails": sorted(new_fails)},
                })

        # 2. Correlated failures: multiple checkers failing simultaneously
        failing_checkers = [
            name for name, report in current.items()
            if report.get("fail_count", 0) > 0
        ]
        if len(failing_checkers) >= 3:
            insights.append({
                "type": "correlation",
                "checkers": failing_checkers,
                "message": (
                    f"Multiple systems failing: {', '.join(failing_checkers)}"
                ),
                "severity": "critical",
            })

        # 3. Improvement detection: FAIL → PASS
        for checker_name, cur_report in current.items():
            prev_report = previous.get(checker_name)
            if not prev_report:
                continue
            cur_passes = {
                c["name"] for c in cur_report.get("checks", [])
                if c["status"] == "PASS"
            }
            prev_fails = {
                c["name"] for c in prev_report.get("checks", [])
                if c["status"] == "FAIL"
            }
            fixed = prev_fails & cur_passes
            if fixed:
                insights.append({
                    "type": "improvement",
                    "checker": checker_name,
                    "message": f"Fixed: {', '.join(sorted(fixed))}",
                    "severity": "info",
                })

        return insights
