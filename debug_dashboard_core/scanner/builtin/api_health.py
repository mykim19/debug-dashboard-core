"""Builtin: API Health checker — Flask route registration & availability.

Checks:
  - route_count: number of registered Flask routes
  - duplicate_routes: same path registered by multiple blueprints
  - blueprint_registration: all expected blueprints loaded
"""

import re
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class APIHealthChecker(BaseChecker):
    name = "api_health"
    display_name = "API HEALTH"
    description = "Flask route registration integrity, endpoint count, and duplicate detection."
    tooltip_why = "API 라우트 등록 누락이나 충돌은 서비스 장애의 주요 원인입니다."
    tooltip_what = "Flask 소스에서 라우트 정의를 정적 분석하여 등록 수, 중복, 블루프린트 상태를 진단합니다."
    tooltip_result = "PASS: 라우트 정상 등록 · WARN: 중복 경로 감지 · FAIL: 예상 라우트 미달"
    icon = "🌐"
    color = "#3b82f6"

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        scan_dirs = phase_cfg.get("scan_dirs", ["."])
        main_file = phase_cfg.get("main_file", "app.py")
        min_routes = phase_cfg.get("min_routes", 0)  # 0 = no threshold

        # Collect route definitions
        route_pattern = re.compile(
            r"""@\w*\.route\(\s*["']([^"']+)["']"""
        )
        routes = []         # (path, file, line_no)
        route_files = set()

        for scan_dir in scan_dirs:
            base = project_root / scan_dir.rstrip("/")
            if not base.exists():
                continue
            for py_file in base.rglob("*.py"):
                # Skip hidden, venv, pycache
                parts = py_file.relative_to(project_root).parts
                if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv", "node_modules") for p in parts):
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    m = route_pattern.search(line)
                    if m:
                        routes.append((m.group(1), str(py_file.relative_to(project_root)), i))
                        route_files.add(str(py_file.relative_to(project_root)))

        # Check 1: Route count
        count = len(routes)
        if count == 0:
            report.add(CheckResult("route_count", CheckResult.WARN,
                                   "No Flask routes detected in scan_dirs"))
        elif min_routes > 0 and count < min_routes:
            report.add(CheckResult("route_count", CheckResult.WARN,
                                   f"{count} routes found (expected ≥{min_routes})",
                                   details={"count": count, "min": min_routes}))
        else:
            report.add(CheckResult("route_count", CheckResult.PASS,
                                   f"{count} routes across {len(route_files)} files"))

        # Check 2: Duplicate routes (same path in different files)
        from collections import Counter
        path_counter = Counter(r[0] for r in routes)
        dupes = {p: c for p, c in path_counter.items() if c > 1}
        if dupes:
            dupe_details = []
            for path, cnt in sorted(dupes.items()):
                files = [r[1] for r in routes if r[0] == path]
                dupe_details.append({"path": path, "count": cnt, "files": files})
            report.add(CheckResult("duplicate_routes", CheckResult.WARN,
                                   f"{len(dupes)} duplicate route path(s)",
                                   details=dupe_details))
        else:
            report.add(CheckResult("duplicate_routes", CheckResult.PASS,
                                   "No duplicate route paths"))

        # Check 3: Blueprint registration (check if main file imports blueprints)
        expected_blueprints = phase_cfg.get("expected_blueprints", [])
        if expected_blueprints:
            main_path = project_root / main_file
            main_text = ""
            if main_path.exists():
                try:
                    main_text = main_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass

            missing = []
            for bp in expected_blueprints:
                if bp not in main_text:
                    missing.append(bp)

            if missing:
                report.add(CheckResult("blueprint_registration", CheckResult.WARN,
                                       f"{len(missing)} blueprint(s) not found in {main_file}",
                                       details={"missing": missing}))
            else:
                report.add(CheckResult("blueprint_registration", CheckResult.PASS,
                                       f"All {len(expected_blueprints)} expected blueprints registered"))
        else:
            report.add(CheckResult("blueprint_registration", CheckResult.SKIP,
                                   "No expected_blueprints configured"))

        return report
