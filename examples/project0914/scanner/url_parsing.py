"""Phase 2: URL Parsing checker — YouTube URL pattern validation"""

import sys
import os
from pathlib import Path

from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport


class UrlParsingChecker(BaseChecker):
    name = "url_parsing"
    display_name = "URL PARSE"
    description = "YouTube URL patterns (watch, shorts, live, embed, youtu.be), function sync between modules, and content hash consistency."
    tooltip_why = "YouTube 영상을 수집하려면 다양한 URL 형식(watch, shorts, live, embed 등)에서 영상 ID를 정확히 추출해야 합니다."
    tooltip_what = "7가지 URL 패턴 인식률, 모듈 간 추출 함수 동기화 여부, 동일 영상의 해시값 일관성을 점검합니다."
    tooltip_result = "통과 시 어떤 형태의 YouTube 링크든 정확하게 처리됩니다. 실패 시 특정 URL이 무시되어 콘텐츠 수집이 누락됩니다."
    icon = "🔗"
    color = "#3b82f6"

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)

        sys.path.insert(0, str(project_root))
        try:
            _orig = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                from app import get_video_id_from_url
            finally:
                sys.stdout.close()
                sys.stdout = _orig
            from utils.content_hash import _normalize_youtube_url, compute_url_hash
            report.add(CheckResult("import_functions", CheckResult.PASS, "URL functions imported"))
        except Exception as e:
            sys.stdout = _orig if '_orig' in dir() else sys.__stdout__
            report.add(CheckResult("import_functions", CheckResult.FAIL, str(e)))
            return report

        test_cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLxxx", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ?t=60", "dQw4w9WgXcQ"),
        ]

        fail_details = []
        for url, expected_id in test_cases:
            app_id = get_video_id_from_url(url)
            normalized = _normalize_youtube_url(url)
            hash_id = normalized.split("v=")[1].split("&")[0] if "v=" in normalized else None
            if app_id != expected_id or hash_id != expected_id:
                fail_details.append({"url": url, "expected": expected_id, "app": app_id, "hash": hash_id})

        if not fail_details:
            report.add(CheckResult("standard_patterns", CheckResult.PASS, f"All {len(test_cases)} patterns OK"))
        else:
            report.add(CheckResult("standard_patterns", CheckResult.FAIL,
                                   f"{len(fail_details)}/{len(test_cases)} failed", details=fail_details))

        app_src = (project_root / "app.py").read_text(encoding="utf-8")
        hash_src = (project_root / "utils" / "content_hash.py").read_text(encoding="utf-8")
        patterns = ["/live/", "/shorts/", "/embed/"]
        app_has = {p for p in patterns if p in app_src}
        hash_has = {p for p in patterns if p in hash_src}
        if app_has == hash_has:
            report.add(CheckResult("pattern_sync", CheckResult.PASS, "Functions in sync"))
        else:
            report.add(CheckResult("pattern_sync", CheckResult.FAIL, "Pattern mismatch",
                                   details={"app_only": list(app_has - hash_has), "hash_only": list(hash_has - app_has)}))

        hashes = {compute_url_hash(url) for url, _ in test_cases}
        if len(hashes) == 1:
            report.add(CheckResult("hash_consistency", CheckResult.PASS, "All variants produce same hash"))
        else:
            report.add(CheckResult("hash_consistency", CheckResult.WARN, f"{len(hashes)} different hashes"))

        return report
