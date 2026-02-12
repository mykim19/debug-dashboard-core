"""Builtin: Code Quality checker — file size, function length, TODO/FIXME tracking.

Checks:
  - large_files: Python files exceeding line threshold
  - long_functions: functions exceeding length threshold
  - todo_count: TODO/FIXME/HACK marker inventory
"""

import re
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class CodeQualityChecker(BaseChecker):
    name = "code_quality"
    display_name = "CODE QUALITY"
    description = "File size limits, function length, and TODO/FIXME marker tracking."
    tooltip_why = "과대 파일과 긴 함수는 유지보수를 어렵게 하고, 방치된 TODO는 기술 부채로 누적됩니다."
    tooltip_what = "Python 파일 크기(행 수), 함수 길이, TODO/FIXME/HACK 마커 개수를 집계합니다."
    tooltip_result = "PASS: 코드 품질 양호 · WARN: 대형 파일/긴 함수 존재 · FAIL: 임계값 초과"
    icon = "📐"
    color = "#8b5cf6"

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        scan_dirs = phase_cfg.get("scan_dirs", ["."])
        file_limit = phase_cfg.get("file_line_limit", 500)
        func_limit = phase_cfg.get("func_line_limit", 80)
        todo_warn_threshold = phase_cfg.get("todo_warn_threshold", 10)

        large_files = []
        long_functions = []
        todo_items = []  # (file, line_no, marker, text)

        func_pattern = re.compile(r"^(\s*)def\s+(\w+)\s*\(")
        todo_pattern = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)", re.IGNORECASE)

        for scan_dir in scan_dirs:
            base = project_root / scan_dir.rstrip("/")
            if not base.exists():
                continue
            for py_file in base.rglob("*.py"):
                parts = py_file.relative_to(project_root).parts
                if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv", "node_modules",
                                                   "downloads", "chroma_db") for p in parts):
                    continue

                try:
                    lines = py_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    continue

                rel_path = str(py_file.relative_to(project_root))

                # Large file check
                if len(lines) > file_limit:
                    large_files.append({"file": rel_path, "lines": len(lines)})

                # Function length + TODO scanning
                current_func = None
                func_start = 0
                func_indent = 0

                for i, line in enumerate(lines, 1):
                    # TODO check
                    m_todo = todo_pattern.search(line)
                    if m_todo:
                        todo_items.append({
                            "file": rel_path, "line": i,
                            "marker": m_todo.group(1).upper(),
                            "text": m_todo.group(2).strip()[:80],
                        })

                    # Function tracking
                    m_func = func_pattern.match(line)
                    if m_func:
                        # Close previous function
                        if current_func:
                            func_len = i - func_start
                            if func_len > func_limit:
                                long_functions.append({
                                    "file": rel_path, "function": current_func,
                                    "line": func_start, "length": func_len,
                                })
                        current_func = m_func.group(2)
                        func_start = i
                        func_indent = len(m_func.group(1))

                # Close last function
                if current_func:
                    func_len = len(lines) - func_start + 1
                    if func_len > func_limit:
                        long_functions.append({
                            "file": rel_path, "function": current_func,
                            "line": func_start, "length": func_len,
                        })

        # Check 1: Large files
        if large_files:
            large_files.sort(key=lambda x: x["lines"], reverse=True)
            report.add(CheckResult("large_files", CheckResult.WARN,
                                   f"{len(large_files)} file(s) over {file_limit} lines",
                                   details=large_files[:10]))
        else:
            report.add(CheckResult("large_files", CheckResult.PASS,
                                   f"All files under {file_limit} lines"))

        # Check 2: Long functions
        if long_functions:
            long_functions.sort(key=lambda x: x["length"], reverse=True)
            report.add(CheckResult("long_functions", CheckResult.WARN,
                                   f"{len(long_functions)} function(s) over {func_limit} lines",
                                   details=long_functions[:10]))
        else:
            report.add(CheckResult("long_functions", CheckResult.PASS,
                                   f"All functions under {func_limit} lines"))

        # Check 3: TODO/FIXME inventory
        if len(todo_items) > todo_warn_threshold:
            by_marker = {}
            for t in todo_items:
                by_marker[t["marker"]] = by_marker.get(t["marker"], 0) + 1
            summary = ", ".join(f"{k}:{v}" for k, v in sorted(by_marker.items()))
            report.add(CheckResult("todo_count", CheckResult.WARN,
                                   f"{len(todo_items)} markers ({summary})",
                                   details=todo_items[:15]))
        elif todo_items:
            report.add(CheckResult("todo_count", CheckResult.PASS,
                                   f"{len(todo_items)} TODO markers (within threshold)"))
        else:
            report.add(CheckResult("todo_count", CheckResult.PASS,
                                   "No TODO/FIXME markers"))

        return report
