"""
Base classes for the debug scanner plugin system.

Agent Protocol (4-stage):
    Inspector(run) → Evidence(details) → Recommendation(message/fix_desc) → Fixer(fix)

CheckResult, PhaseReport, BaseChecker — all plugins inherit from BaseChecker.

Evidence standard (recommended keys for CheckResult.details):
    {
        "file": "path/to/file.py",
        "line_start": 42,
        "line_end": 45,
        "snippet": "the problematic code",
        "rule_id": "sql_injection",
        "evidence": { ... }   # checker-specific evidence data
    }
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


class CheckResult:
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"

    def __init__(self, name: str, status: str, message: str = "", details: Any = None,
                 fixable: bool = False, fix_desc: str = ""):
        self.name = name
        self.status = status
        self.message = message
        self.details = details
        self.fixable = fixable
        self.fix_desc = fix_desc

    def to_dict(self) -> dict:
        d = {"name": self.name, "status": self.status, "message": self.message}
        if self.details is not None:
            d["details"] = self.details
        if self.fixable:
            d["fixable"] = True
        if self.fix_desc:
            d["fix_desc"] = self.fix_desc
        return d


class PhaseReport:
    def __init__(self, name: str):
        self.name = name
        self.checks: List[CheckResult] = []
        self.duration_ms: int = 0  # measured by core (app.py), not by checker

    def add(self, result: CheckResult) -> CheckResult:
        self.checks.append(result)
        return result

    @property
    def pass_count(self):
        return sum(1 for c in self.checks if c.status == CheckResult.PASS)

    @property
    def fail_count(self):
        return sum(1 for c in self.checks if c.status == CheckResult.FAIL)

    @property
    def warn_count(self):
        return sum(1 for c in self.checks if c.status == CheckResult.WARN)

    @property
    def skip_count(self):
        return sum(1 for c in self.checks if c.status == CheckResult.SKIP)

    @property
    def total_active(self):
        return len(self.checks) - self.skip_count

    @property
    def health_pct(self) -> float:
        total = self.total_active
        if total == 0:
            return 100.0
        return (self.pass_count / total) * 100

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "warn_count": self.warn_count,
            "skip_count": self.skip_count,
            "total_active": self.total_active,
            "health_pct": round(self.health_pct, 1),
            "duration_ms": self.duration_ms,
            "checks": [c.to_dict() for c in self.checks],
        }


class BaseChecker(ABC):
    """Base class for all checkers (both builtin and plugin).

    Subclass contract:
        - name: unique identifier (the single source of truth for identity)
        - display_name: shown in UI cards
        - run(): Inspector — READ-only diagnosis, returns PhaseReport
        - fix(): Fixer — SAFE_FIX level only (TODO markers, config edits, cache clear)
    """
    name: str = ""
    display_name: str = ""
    description: str = ""
    tooltip_why: str = ""
    tooltip_what: str = ""
    tooltip_result: str = ""
    icon: str = ""
    color: str = "#6366f1"
    depends_on: List[str] = []   # names of checkers that must run before this one

    def is_applicable(self, config: dict) -> bool:
        checks = config.get("checks", {})
        phase_cfg = checks.get(self.name, {})
        return phase_cfg.get("enabled", True)

    @abstractmethod
    def run(self, project_root: Path, config: dict) -> PhaseReport:
        """Inspector: diagnose project state (READ-only)."""
        pass

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        """Fixer: auto-fix a specific check (SAFE_FIX level).
        Returns {success: bool, message: str}."""
        return {"success": False, "message": "No auto-fix available for this check"}

    def get_meta(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "tooltip_why": self.tooltip_why,
            "tooltip_what": self.tooltip_what,
            "tooltip_result": self.tooltip_result,
            "icon": self.icon,
            "color": self.color,
        }
