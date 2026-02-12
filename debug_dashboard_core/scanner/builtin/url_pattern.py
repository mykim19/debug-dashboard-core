"""Builtin: URL Pattern checker — video_id extraction coverage, code sync.

Checks:
  - pattern_coverage: all known YouTube URL formats handled
  - file_sync: same patterns present in all relevant files
  - regex_quality: patterns compile without errors

Applicable when: config has checks.url_pattern.enabled = true
"""

import re
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class URLPatternChecker(BaseChecker):
    name = "url_pattern"
    display_name = "URL PARSE"
    description = "YouTube URL pattern coverage and cross-file synchronization."
    tooltip_why = "URL 패턴 누락 시 video_id 추출 실패 → 전체 다운로드/전사 파이프라인이 작동하지 않습니다."
    tooltip_what = "watch/youtu.be/embed/live/shorts 패턴 커버리지, 파일 간 동기화 상태를 검사합니다."
    tooltip_result = "PASS: 모든 URL 패턴 커버 · WARN: 일부 패턴 누락 · FAIL: 핵심 패턴 미구현"
    icon = "🔗"
    color = "#0ea5e9"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        # Files that should contain URL parsing logic
        url_files = phase_cfg.get("url_files", [
            "app.py",
            "utils/content_hash.py",
        ])

        # Required patterns
        required_patterns = phase_cfg.get("required_patterns", [
            "watch",        # youtube.com/watch?v=
            "youtu.be",     # youtu.be/ID
            "embed",        # youtube.com/embed/ID
            "live",         # youtube.com/live/ID
            "shorts",       # youtube.com/shorts/ID
        ])

        # Check each file
        file_coverage = {}  # {file: set of found patterns}
        existing_files = []

        for rel_file in url_files:
            fpath = project_root / rel_file
            if not fpath.is_file():
                file_coverage[rel_file] = set()
                continue

            existing_files.append(rel_file)
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                found = set()
                for pat in required_patterns:
                    if pat in text:
                        found.add(pat)
                file_coverage[rel_file] = found
            except Exception:
                file_coverage[rel_file] = set()

        # Check 1: Overall pattern coverage (union of all files)
        all_found = set()
        for found in file_coverage.values():
            all_found |= found

        missing = set(required_patterns) - all_found
        if not missing:
            report.add(CheckResult("pattern_coverage", CheckResult.PASS,
                                   f"All {len(required_patterns)} URL patterns covered"))
        elif len(missing) <= 2:
            report.add(CheckResult("pattern_coverage", CheckResult.WARN,
                                   f"Missing patterns: {', '.join(sorted(missing))}",
                                   details={"missing": sorted(missing), "found": sorted(all_found)}))
        else:
            report.add(CheckResult("pattern_coverage", CheckResult.FAIL,
                                   f"{len(missing)} URL patterns missing: {', '.join(sorted(missing))}"))

        # Check 2: Cross-file sync — all url_files should have same patterns
        if len(existing_files) >= 2:
            desync = []
            reference = file_coverage.get(existing_files[0], set())
            for rel_file in existing_files[1:]:
                other = file_coverage.get(rel_file, set())
                diff = reference.symmetric_difference(other)
                if diff:
                    desync.append({
                        "file": rel_file,
                        "missing": sorted(reference - other),
                        "extra": sorted(other - reference),
                    })

            if desync:
                report.add(CheckResult("file_sync", CheckResult.WARN,
                                       f"{len(desync)} file(s) out of sync with {existing_files[0]}",
                                       details=desync))
            else:
                report.add(CheckResult("file_sync", CheckResult.PASS,
                                       f"All {len(existing_files)} files in sync"))
        else:
            report.add(CheckResult("file_sync", CheckResult.SKIP,
                                   f"Only {len(existing_files)} URL file(s) found"))

        # Check 3: Regex quality — find and validate regex patterns
        regex_errors = []
        url_regex_pattern = re.compile(r"""re\.compile\(\s*r?["'](.*?)["']\s*""")

        for rel_file in existing_files:
            fpath = project_root / rel_file
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                for m in url_regex_pattern.finditer(text):
                    try:
                        re.compile(m.group(1))
                    except re.error as e:
                        regex_errors.append({
                            "file": rel_file,
                            "pattern": m.group(1)[:60],
                            "error": str(e),
                        })
            except Exception:
                continue

        if regex_errors:
            report.add(CheckResult("regex_quality", CheckResult.FAIL,
                                   f"{len(regex_errors)} invalid regex pattern(s)",
                                   details=regex_errors))
        else:
            report.add(CheckResult("regex_quality", CheckResult.PASS,
                                   "All regex patterns compile successfully"))

        return report
