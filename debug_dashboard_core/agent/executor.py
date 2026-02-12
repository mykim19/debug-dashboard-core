"""Executor — runs checkers with dependency ordering and optional LLM analysis.

GPT Risk #6 addressed: execution lock prevents concurrent checker runs.
Agent auto-fix scope limited to "none" or "todo_markers" (never destructive).

Lock Policy (GPT Review #3F):
  - ONE scan at a time per workspace (full serialization via threading.Lock)
  - If a scan is in progress, new scan requests return immediately with skipped=True
  - LLM analysis runs outside the scan lock (can overlap with next scan)
  - This is the simplest/safest policy — prevents race conditions at cost of latency
  - Future: per-checker locking if fine-grained concurrency is needed
"""
import re
import time
import hashlib
import json
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..scanner.base import BaseChecker, CheckResult, PhaseReport
from .events import AgentEvent, EventType, LLMAnalysis
from .graph import CheckerDependencyGraph
from .reasoner import Action

logger = logging.getLogger("agent.executor")


class Executor:
    """Executes actions decided by the Reasoner.

    - run_checkers: run a set of checkers in dependency order
    - llm_analyze: Tier 2 deep analysis via LLMProvider
    - emit_insights: forward insights to event stream
    """

    def __init__(
        self,
        checkers: Dict[str, BaseChecker],
        project_root: Path,
        config: dict,
        dep_graph: CheckerDependencyGraph,
        llm_provider=None,
        workspace_id: str = "",
    ):
        self._checkers = checkers
        self._project_root = project_root
        self._config = config
        self._dep_graph = dep_graph
        self._llm = llm_provider
        self._workspace_id = workspace_id
        # GPT Risk #6: execution lock — prevents concurrent checker runs
        self._execution_lock = threading.Lock()
        self._executing = False

    @property
    def is_executing(self) -> bool:
        return self._executing

    def execute(self, action: Action) -> AgentEvent:
        """Execute a single action and return a result event."""
        if action.action_type == "run_checkers":
            return self._run_checkers(action.checker_names)
        elif action.action_type == "llm_analyze":
            return self._execute_llm_analysis(
                action.data.get("checker", ""),
                action.data.get("report"),
            )
        elif action.action_type == "emit_insights":
            return AgentEvent(
                type=EventType.INSIGHT_GENERATED,
                data=action.data,
                source="executor",
                workspace_id=self._workspace_id,
            )
        else:
            logger.warning(f"Unknown action type: {action.action_type}")
            return AgentEvent(
                type=EventType.AGENT_STATE_CHANGED,
                data={"error": f"Unknown action: {action.action_type}"},
                source="executor",
                workspace_id=self._workspace_id,
            )

    def _run_checkers(self, checker_names: List[str]) -> AgentEvent:
        """Run checkers in dependency order with execution lock."""
        # GPT Risk #6: prevent concurrent checker runs
        if not self._execution_lock.acquire(blocking=False):
            logger.info("Scan already in progress, skipping")
            return AgentEvent(
                type=EventType.SCAN_COMPLETED,
                data={"skipped": True, "reason": "scan_in_progress"},
                source="executor",
                workspace_id=self._workspace_id,
            )

        try:
            self._executing = True
            # Resolve execution order via dependency graph
            # Filter to only available checkers
            available_names = [n for n in checker_names if n in self._checkers]
            ordered = self._dep_graph.resolve_order(available_names)
            # Only run checkers that are actually available
            ordered = [n for n in ordered if n in self._checkers]

            reports: Dict[str, dict] = {}
            total_pass = total_warn = total_fail = 0
            failing_checkers: List[str] = []
            scan_start = time.time()
            # GPT Review #4-6: monotonic scan_id for snapshot tracking
            scan_id = f"scan_{int(scan_start * 1000)}"

            for name in ordered:
                checker = self._checkers[name]
                t0 = time.time()
                try:
                    report = checker.run(self._project_root, self._config)
                except Exception as e:
                    logger.error(f"Checker {name} error: {e}")
                    report = PhaseReport(name)
                    report.add(CheckResult("error", CheckResult.FAIL, str(e)))
                report.duration_ms = int((time.time() - t0) * 1000)

                rd = report.to_dict()
                rd["meta"] = checker.get_meta()
                reports[name] = rd

                total_pass += report.pass_count
                total_warn += report.warn_count
                total_fail += report.fail_count
                if report.fail_count > 0:
                    failing_checkers.append(name)

            total_active = total_pass + total_warn + total_fail
            health_pct = (total_pass / total_active * 100) if total_active else 100
            overall = (
                "CRITICAL" if total_fail > 0
                else ("DEGRADED" if total_warn > 0 else "HEALTHY")
            )
            duration_ms = int((time.time() - scan_start) * 1000)

            return AgentEvent(
                type=EventType.SCAN_COMPLETED,
                data={
                    "scan_id": scan_id,
                    "scan_timestamp": datetime.now().isoformat(),
                    "reports": reports,
                    "overall": overall,
                    "total_pass": total_pass,
                    "total_warn": total_warn,
                    "total_fail": total_fail,
                    "health_pct": round(health_pct, 1),
                    "has_critical": total_fail > 0,
                    "failing_checkers": failing_checkers,
                    "checker_names": ordered,
                    "duration_ms": duration_ms,
                },
                source="executor",
                workspace_id=self._workspace_id,
            )
        finally:
            self._executing = False
            self._execution_lock.release()

    # GPT Review #5-6: key names that typically hold secrets
    _SECRET_KEYS = re.compile(
        r'(?i)'
        r'(api[_-]?key|secret[_-]?key|token|password|passwd|auth[_-]?token'
        r'|access[_-]?key|private[_-]?key|credentials?|secret)',
    )

    # GPT Review #6-6: well-known secret prefixes (value-based, no key needed)
    _SECRET_PREFIX_PATTERN = re.compile(
        r'(?:sk-[a-zA-Z0-9_-]{20,})'       # OpenAI API keys (sk-proj-..., sk-...)
        r'|(?:AIza[a-zA-Z0-9_-]{30,})'     # Google API keys
        r'|(?:Bearer\s+[a-zA-Z0-9._-]{20,})'  # Bearer tokens
        r'|(?:ghp_[a-zA-Z0-9]{36,})'       # GitHub PAT
        r'|(?:gho_[a-zA-Z0-9]{36,})'       # GitHub OAuth
        r'|(?:xoxb-[a-zA-Z0-9-]{20,})'     # Slack bot tokens
        r'|(?:xoxp-[a-zA-Z0-9-]{20,})',    # Slack user tokens
    )

    @staticmethod
    def _redact_secrets(text: str) -> str:
        """GPT Review #5-6 + #6-6: redact secret-like values from text before hashing.

        Two-layer strategy:
          Layer 1 (key-based): known key names (api_key, password, token...) → redact value
          Layer 2 (prefix-based): known secret prefixes (sk-, AIza, Bearer...) → redact anywhere

        Note on hash collision (GPT Review #6-6):
          Redaction makes different secrets produce the same hash. This is intentional—
          the hash identifies *diagnostic state*, not *secret values*. The 16-char SHA-256
          prefix has ~2^64 collision space, which is sufficient for identifying report snapshots.
          This hash is NOT a security token.
        """
        # Layer 1: key-based — secret_key_name + separator(s) + value (8+ chars)
        result = re.sub(
            r'(?i)'
            r'((?:api[_-]?key|secret[_-]?key|token|password|passwd|auth[_-]?token'
            r'|access[_-]?key|private[_-]?key|credentials?|secret)'
            r'(?:\\"|"|\'|=|:|\s)*)'   # key + separators (inc. escaped quotes)
            r'([^\s",}{\\]{8,})',       # value: 8+ non-delimiter chars
            r'\1[REDACTED]',
            text,
        )
        # Layer 2: prefix-based — catch secrets anywhere by known prefix patterns
        result = Executor._SECRET_PREFIX_PATTERN.sub('[REDACTED]', result)
        return result

    @staticmethod
    def _compute_report_hash(report: dict) -> str:
        """GPT Review #4-6: compute a stable hash of a checker report for snapshot tracking.

        GPT Review #5-6: redacts secret-like values (API keys, tokens, passwords)
        before hashing to prevent sensitive data from leaking into hash inputs.
        The hash itself is one-way, but the raw JSON input passed to json.dumps
        could theoretically be logged or inspected.
        """
        # Strip timing data that changes every run, keep only diagnostic content
        stripped = {k: v for k, v in report.items() if k not in ("duration_ms", "timestamp")}
        raw = json.dumps(stripped, sort_keys=True, ensure_ascii=False, default=str)
        # Redact secret-like patterns before hashing
        raw = Executor._redact_secrets(raw)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _execute_llm_analysis(
        self, checker_name: str, report: Optional[dict] = None
    ) -> AgentEvent:
        """Tier 2: LLM deep analysis of a checker's results.

        GPT Review #4-6: each analysis includes snapshot context (report_hash,
        analysis_timestamp) so stale analyses can be detected when the underlying
        checker state changes after the analysis was produced.
        """
        if not self._llm:
            logger.warning("LLM analysis requested but no provider configured")
            return AgentEvent(
                type=EventType.LLM_ANALYSIS_COMPLETED,
                data={"error": "No LLM provider configured", "checker": checker_name},
                source="executor",
                workspace_id=self._workspace_id,
            )

        # If no report provided, run the checker first
        report_was_fresh = False
        if report is None and checker_name:
            checker = self._checkers.get(checker_name)
            if checker:
                try:
                    r = checker.run(self._project_root, self._config)
                    report = r.to_dict()
                    report_was_fresh = True
                except Exception as e:
                    return AgentEvent(
                        type=EventType.LLM_ANALYSIS_COMPLETED,
                        data={"error": f"Checker run failed: {e}", "checker": checker_name},
                        source="executor",
                        workspace_id=self._workspace_id,
                    )

        if not report:
            return AgentEvent(
                type=EventType.LLM_ANALYSIS_COMPLETED,
                data={"error": "No report data", "checker": checker_name},
                source="executor",
                workspace_id=self._workspace_id,
            )

        # GPT Review #4-6: snapshot context for traceability
        report_hash = self._compute_report_hash(report)
        analysis_ts = datetime.now().isoformat()

        try:
            analysis = self._llm.analyze_report(checker_name, report, self._config)

            return AgentEvent(
                type=EventType.LLM_ANALYSIS_COMPLETED,
                data={
                    "checker": checker_name,
                    "analysis": analysis.analysis_text,
                    "root_causes": analysis.root_causes,
                    "fix_suggestions": analysis.fix_suggestions,
                    "model": analysis.model_used,
                    "cost_usd": analysis.cost_usd,
                    "tokens": {
                        "prompt": analysis.prompt_tokens,
                        "completion": analysis.completion_tokens,
                    },
                    "evidence": analysis.evidence_summary,
                    # GPT Review #4-6: snapshot tracking fields
                    "report_hash": report_hash,
                    "analysis_timestamp": analysis_ts,
                    "report_was_fresh": report_was_fresh,
                },
                source="executor",
                workspace_id=self._workspace_id,
            )
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return AgentEvent(
                type=EventType.LLM_ANALYSIS_COMPLETED,
                data={"error": str(e), "checker": checker_name},
                source="executor",
                workspace_id=self._workspace_id,
            )
