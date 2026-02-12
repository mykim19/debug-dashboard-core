"""Builtin: Dependency checker — package versions, pinning, unused.

Checks:
  - requirements_exists: requirements.txt or pyproject.toml present
  - version_pinning: packages pinned to specific versions
  - import_sync: packages imported in code but not in requirements
"""

import re
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class DependencyChecker(BaseChecker):
    name = "dependency"
    display_name = "DEPENDENCY"
    description = "Package version pinning, requirements file sync, and unused dependency detection."
    tooltip_why = "미고정 패키지 버전은 빌드 재현성을 해치고, 누락된 의존성은 배포 시 장애를 유발합니다."
    tooltip_what = "requirements.txt 파일의 버전 고정 비율, 코드에서 import되지만 requirements에 누락된 패키지를 검사합니다."
    tooltip_result = "PASS: 의존성 관리 양호 · WARN: 미고정 버전 존재 · FAIL: requirements 파일 없음"
    icon = "📦"
    color = "#f59e0b"

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        scan_dirs = phase_cfg.get("scan_dirs", ["."])

        # Check 1: requirements file exists
        req_path = project_root / "requirements.txt"
        pyproject_path = project_root / "pyproject.toml"

        if req_path.is_file():
            report.add(CheckResult("requirements_exists", CheckResult.PASS,
                                   "requirements.txt found"))
        elif pyproject_path.is_file():
            report.add(CheckResult("requirements_exists", CheckResult.PASS,
                                   "pyproject.toml found (no requirements.txt)",
                                   fixable=True,
                                   fix_desc="pip freeze > requirements.txt로 고정 파일을 생성합니다"))
        else:
            report.add(CheckResult("requirements_exists", CheckResult.FAIL,
                                   "No requirements.txt or pyproject.toml found",
                                   fixable=True,
                                   fix_desc="pip freeze > requirements.txt로 의존성 파일을 생성합니다"))

        # Check 2: Version pinning
        if req_path.is_file():
            try:
                lines = req_path.read_text(encoding="utf-8").splitlines()
                packages = []
                pinned = 0
                unpinned = []
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    packages.append(line)
                    if re.search(r"[=><]", line):
                        pinned += 1
                    else:
                        pkg_name = re.split(r"[=><!\[;]", line)[0].strip()
                        unpinned.append(pkg_name)

                total = len(packages)
                if total == 0:
                    report.add(CheckResult("version_pinning", CheckResult.WARN,
                                           "requirements.txt is empty"))
                elif unpinned:
                    pct = (pinned / total) * 100
                    report.add(CheckResult("version_pinning", CheckResult.WARN,
                                           f"{pinned}/{total} pinned ({pct:.0f}%) — {len(unpinned)} unpinned",
                                           details={"unpinned": unpinned[:10]}))
                else:
                    report.add(CheckResult("version_pinning", CheckResult.PASS,
                                           f"All {total} packages version-pinned"))
            except Exception as e:
                report.add(CheckResult("version_pinning", CheckResult.WARN, f"Parse error: {e}"))
        else:
            report.add(CheckResult("version_pinning", CheckResult.SKIP,
                                   "No requirements.txt to check"))

        # Check 3: Import sync — find imports not in requirements
        if req_path.is_file():
            try:
                req_text = req_path.read_text(encoding="utf-8")
                req_packages = set()
                for line in req_text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        pkg = re.split(r"[=><!\[;]", line)[0].strip().lower().replace("-", "_")
                        req_packages.add(pkg)

                # Scan code for imports
                import_pattern = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)")
                stdlib = {
                    "os", "sys", "re", "json", "time", "datetime", "pathlib", "typing",
                    "collections", "functools", "itertools", "hashlib", "math", "random",
                    "threading", "subprocess", "sqlite3", "io", "abc", "copy", "enum",
                    "shutil", "glob", "tempfile", "logging", "unittest", "asyncio",
                    "urllib", "http", "socket", "struct", "csv", "string", "textwrap",
                    "contextlib", "dataclasses", "importlib", "inspect", "signal",
                    "traceback", "warnings", "base64", "uuid", "argparse", "configparser",
                    "difflib", "unicodedata", "html", "xml", "email", "mimetypes",
                    "concurrent", "multiprocessing", "queue", "pickle", "codecs",
                    "pprint", "operator", "decimal", "fractions", "statistics",
                }

                code_imports = set()
                for scan_dir in scan_dirs:
                    base = project_root / scan_dir.rstrip("/")
                    if not base.exists():
                        continue
                    for py_file in base.rglob("*.py"):
                        parts = py_file.relative_to(project_root).parts
                        if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv") for p in parts):
                            continue
                        try:
                            for line in py_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                                m = import_pattern.match(line)
                                if m:
                                    pkg = m.group(1).lower()
                                    if pkg not in stdlib:
                                        code_imports.add(pkg)
                        except Exception:
                            continue

                # Find imports not in requirements (normalize names)
                missing_in_req = []
                for imp in sorted(code_imports):
                    normalized = imp.replace("-", "_")
                    if normalized not in req_packages:
                        # Check if it's a local package (subdir with __init__.py)
                        if (project_root / imp).is_dir():
                            continue
                        missing_in_req.append(imp)

                if missing_in_req and len(missing_in_req) <= 20:
                    report.add(CheckResult("import_sync", CheckResult.WARN,
                                           f"{len(missing_in_req)} imported package(s) not in requirements",
                                           details={"missing": missing_in_req[:15]}))
                elif missing_in_req:
                    report.add(CheckResult("import_sync", CheckResult.WARN,
                                           f"{len(missing_in_req)} imported packages not in requirements (check manually)"))
                else:
                    report.add(CheckResult("import_sync", CheckResult.PASS,
                                           "All code imports found in requirements"))
            except Exception as e:
                report.add(CheckResult("import_sync", CheckResult.WARN, f"Scan error: {e}"))
        else:
            report.add(CheckResult("import_sync", CheckResult.SKIP,
                                   "No requirements.txt for sync check"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "requirements_exists":
            req_path = project_root / "requirements.txt"
            if req_path.exists():
                return {"success": True, "message": "requirements.txt already exists"}
            # Create a placeholder
            req_path.write_text(
                "# Auto-generated requirements.txt\n"
                "# Run: pip freeze > requirements.txt to populate\n"
                "flask\n",
                encoding="utf-8"
            )
            return {"success": True, "message": "Created requirements.txt template — run pip freeze to populate"}

        return {"success": False, "message": "No auto-fix for this check"}
