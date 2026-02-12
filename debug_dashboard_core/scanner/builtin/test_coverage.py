"""Builtin: Test Coverage checker — test files, pytest results, coverage gaps.

Checks:
  - test_files_exist: presence of test directory and test files
  - test_ratio: ratio of test files to source files
  - module_coverage: source modules that lack corresponding test files
"""

from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class TestCoverageChecker(BaseChecker):
    name = "test_coverage"
    display_name = "TEST STATUS"
    description = "Test file existence, test-to-source ratio, and module coverage gaps."
    tooltip_why = "테스트 없는 코드는 리팩터링과 배포 시 회귀 버그 위험이 급증합니다."
    tooltip_what = "테스트 디렉토리 존재, 소스 대비 테스트 파일 비율, 테스트 누락 모듈을 검사합니다."
    tooltip_result = "PASS: 테스트 커버리지 양호 · WARN: 테스트 미비 모듈 존재 · FAIL: 테스트 파일 없음"
    icon = "🧪"
    color = "#10b981"

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        test_dirs = phase_cfg.get("test_dirs", ["tests", "test"])
        source_dirs = phase_cfg.get("source_dirs", [])  # auto-detect if empty
        min_ratio = phase_cfg.get("min_ratio", 0.3)  # test files / source files

        skip_dirs = {
            "__pycache__", "venv", ".venv", "node_modules", ".git",
            "downloads", "chroma_db", "backups", "logs", ".debugger",
        }

        # Check 1: Test directory exists
        found_test_dir = None
        test_files = []
        for td in test_dirs:
            test_path = project_root / td
            if test_path.is_dir():
                found_test_dir = td
                for f in test_path.rglob("test_*.py"):
                    test_files.append(str(f.relative_to(project_root)))
                for f in test_path.rglob("*_test.py"):
                    rel = str(f.relative_to(project_root))
                    if rel not in test_files:
                        test_files.append(rel)
                break

        # Also check for test files in project root
        for f in project_root.glob("test_*.py"):
            rel = str(f.relative_to(project_root))
            if rel not in test_files:
                test_files.append(rel)

        if not test_files:
            report.add(CheckResult("test_files_exist", CheckResult.FAIL,
                                   "No test files found (test_*.py / *_test.py)"))
        elif found_test_dir:
            report.add(CheckResult("test_files_exist", CheckResult.PASS,
                                   f"{len(test_files)} test files in {found_test_dir}/"))
        else:
            report.add(CheckResult("test_files_exist", CheckResult.PASS,
                                   f"{len(test_files)} test files found"))

        # Count source files
        source_files = []
        if source_dirs:
            dirs_to_scan = source_dirs
        else:
            # Auto-detect: Python dirs with __init__.py, plus top-level .py
            dirs_to_scan = ["."]
            for child in sorted(project_root.iterdir()):
                if (child.is_dir()
                        and child.name not in skip_dirs
                        and not child.name.startswith(".")
                        and child.name not in test_dirs
                        and (child / "__init__.py").exists()):
                    dirs_to_scan.append(child.name)

        for sd in dirs_to_scan:
            base = project_root / sd.rstrip("/")
            if not base.exists():
                continue
            pattern = "*.py" if sd == "." else "**/*.py"
            for f in base.glob(pattern):
                parts = f.relative_to(project_root).parts
                if any(p in skip_dirs or p.startswith(".") for p in parts):
                    continue
                if any(p in test_dirs for p in parts):
                    continue
                fname = f.name
                if fname.startswith("test_") or fname.endswith("_test.py") or fname == "__init__.py":
                    continue
                source_files.append(str(f.relative_to(project_root)))

        # Check 2: Test ratio
        if source_files and test_files:
            ratio = len(test_files) / len(source_files)
            if ratio >= min_ratio:
                report.add(CheckResult("test_ratio", CheckResult.PASS,
                                       f"Ratio: {len(test_files)}/{len(source_files)} = {ratio:.0%}"))
            else:
                report.add(CheckResult("test_ratio", CheckResult.WARN,
                                       f"Ratio: {len(test_files)}/{len(source_files)} = {ratio:.0%} (target ≥{min_ratio:.0%})",
                                       details={"test_count": len(test_files),
                                                "source_count": len(source_files),
                                                "ratio": round(ratio, 2)}))
        elif source_files:
            report.add(CheckResult("test_ratio", CheckResult.WARN,
                                   f"0 test files for {len(source_files)} source files"))
        else:
            report.add(CheckResult("test_ratio", CheckResult.SKIP,
                                   "No source files detected"))

        # Check 3: Module coverage — source modules without matching test_<module>.py
        if test_files and source_files:
            test_stems = set()
            for tf in test_files:
                stem = Path(tf).stem
                # test_foo.py → foo
                if stem.startswith("test_"):
                    test_stems.add(stem[5:])
                elif stem.endswith("_test"):
                    test_stems.add(stem[:-5])

            uncovered = []
            for sf in source_files:
                stem = Path(sf).stem
                if stem not in test_stems and stem not in ("__init__", "setup", "conftest"):
                    uncovered.append(sf)

            if uncovered and len(uncovered) <= len(source_files) * 0.8:
                report.add(CheckResult("module_coverage", CheckResult.WARN,
                                       f"{len(uncovered)}/{len(source_files)} modules without test files",
                                       details={"uncovered": uncovered[:15]}))
            elif uncovered:
                report.add(CheckResult("module_coverage", CheckResult.WARN,
                                       f"Most modules lack test files ({len(uncovered)}/{len(source_files)})"))
            else:
                report.add(CheckResult("module_coverage", CheckResult.PASS,
                                       "All source modules have test files"))
        else:
            report.add(CheckResult("module_coverage", CheckResult.SKIP,
                                   "Not enough data for coverage analysis"))

        return report
