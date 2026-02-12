"""Phase 5: Code duplication checker"""

import re
from pathlib import Path

from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport


class DuplicationChecker(BaseChecker):
    name = "duplication"
    display_name = "DUPLICATE"
    description = "Repeated URL extraction logic, yt-dlp command construction, glob patterns, bare except blocks, and duplicated DB queries."
    tooltip_why = "코드 중복은 버그 수정 시 한 곳만 고치고 다른 곳을 놓치게 만듭니다. 유지보수 비용이 기하급수적으로 증가합니다."
    tooltip_what = "URL 추출 로직 중복(3개 파일), yt-dlp 명령어 반복 구성, glob 패턴 남용, bare except, DB 쿼리 반복을 탐지합니다."
    tooltip_result = "경고가 적을수록 코드베이스가 건강합니다. 중복이 많으면 리팩토링 우선순위가 높다는 신호입니다."
    icon = "📋"
    color = "#f59e0b"

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "bare_except":
            phase_cfg = config.get("checks", {}).get("duplication", {})
            scan_files = phase_cfg.get("scan_files", ["app.py"])
            main_file = project_root / scan_files[0] if scan_files else None
            if not main_file or not main_file.exists():
                return {"success": False, "message": "Scan target not found"}
            src = main_file.read_text(encoding="utf-8")
            count = 0
            new_lines = []
            for line in src.splitlines(keepends=True):
                if line.strip().startswith("except:"):
                    new_lines.append(line.replace("except:", "except Exception:"))
                    count += 1
                else:
                    new_lines.append(line)
            if count > 0:
                main_file.write_text("".join(new_lines), encoding="utf-8")
                return {"success": True, "message": f"Replaced {count} bare except → except Exception"}
            return {"success": True, "message": "No bare except found"}

        if check_name == "url_dup":
            # Add TODO comments to duplicated URL extraction files
            marked = 0
            for fpath in [
                project_root / "utils" / "content_hash.py",
                project_root / "mobile" / "app_mobile.py",
            ]:
                if not fpath.exists():
                    continue
                src = fpath.read_text(encoding="utf-8", errors="ignore")
                if "_normalize_youtube_url" in src and "# TODO: refactor to shared" not in src:
                    src = src.replace(
                        "def _normalize_youtube_url",
                        "# TODO: refactor to shared url_utils module\ndef _normalize_youtube_url"
                    )
                    fpath.write_text(src, encoding="utf-8")
                    marked += 1
            if marked > 0:
                return {"success": True, "message": f"Marked {marked} files with refactor TODO"}
            return {"success": True, "message": "Already marked or no duplicates found"}

        if check_name == "ytdlp_cmd":
            # Mark duplicated yt-dlp command constructions with TODO
            phase_cfg = config.get("checks", {}).get("duplication", {})
            scan_files = phase_cfg.get("scan_files", ["app.py"])
            main_file = project_root / scan_files[0] if scan_files else None
            if not main_file or not main_file.exists():
                return {"success": False, "message": "Scan target not found"}
            src = main_file.read_text(encoding="utf-8")
            lines = src.splitlines()
            new_lines = []
            count = 0
            for i, line in enumerate(lines):
                if "YT_DLP_PATH" in line and "[" in line and "# TODO: extract" not in line:
                    new_lines.append(line + "  # TODO: extract to build_ytdlp_cmd()")
                    count += 1
                else:
                    new_lines.append(line)
            if count > 0:
                main_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Marked {count} yt-dlp constructions with TODO"}
            return {"success": True, "message": "Already marked or no duplicates"}

        if check_name == "file_search":
            # Mark excessive glob patterns with TODO
            phase_cfg = config.get("checks", {}).get("duplication", {})
            scan_files = phase_cfg.get("scan_files", ["app.py"])
            main_file = project_root / scan_files[0] if scan_files else None
            if not main_file or not main_file.exists():
                return {"success": False, "message": "Scan target not found"}
            src = main_file.read_text(encoding="utf-8")
            lines = src.splitlines()
            new_lines = []
            count = 0
            for line in lines:
                if (".glob(" in line or ".rglob(" in line) and "# TODO: cache" not in line:
                    new_lines.append(line + "  # TODO: cache or consolidate glob")
                    count += 1
                else:
                    new_lines.append(line)
            if count > 0:
                main_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Marked {count} glob calls with TODO"}
            return {"success": True, "message": "Already marked or no excess globs"}

        if check_name == "db_query_dup":
            # Mark repeated DB queries with TODO
            phase_cfg = config.get("checks", {}).get("duplication", {})
            scan_files = phase_cfg.get("scan_files", ["app.py"])
            main_file = project_root / scan_files[0] if scan_files else None
            if not main_file or not main_file.exists():
                return {"success": False, "message": "Scan target not found"}
            src = main_file.read_text(encoding="utf-8")
            lines = src.splitlines()
            new_lines = []
            count = 0
            for line in lines:
                if "FROM videos WHERE video_id" in line and "# TODO: extract" not in line:
                    new_lines.append(line + "  # TODO: extract to get_video()")
                    count += 1
                else:
                    new_lines.append(line)
            if count > 0:
                main_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Marked {count} repeated queries with TODO"}
            return {"success": True, "message": "Already marked or no duplicates"}

        return {"success": False, "message": "No auto-fix for this check"}

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get("duplication", {})
        scan_files = phase_cfg.get("scan_files", ["app.py"])

        main_file = project_root / scan_files[0] if scan_files else None
        if not main_file or not main_file.exists():
            report.add(CheckResult("main_file", CheckResult.SKIP, "No scan target"))
            return report

        src = main_file.read_text(encoding="utf-8")
        lines = src.splitlines()

        # URL extraction duplication
        url_files = []
        url_marked = 0
        for fpath, label in [
            (project_root / "app.py", "app.py"),
            (project_root / "utils" / "content_hash.py", "content_hash.py"),
            (project_root / "mobile" / "app_mobile.py", "mobile/app_mobile.py"),
        ]:
            if fpath.exists():
                s = fpath.read_text(encoding="utf-8", errors="ignore")
                if "get_video_id_from_url" in s or "_normalize_youtube_url" in s:
                    url_files.append(label)
                    if "# TODO: refactor to shared" in s:
                        url_marked += 1
        url_fix_desc = "중복 URL 추출 로직에 리팩토링 TODO 주석을 추가합니다 → 공통 url_utils 모듈로 통합 권장"
        if len(url_files) > 1 and url_marked == 0:
            report.add(CheckResult("url_dup", CheckResult.WARN, f"URL logic in {len(url_files)} files",
                                   details={"files": url_files}, fixable=True, fix_desc=url_fix_desc))
        elif url_marked > 0:
            report.add(CheckResult("url_dup", CheckResult.PASS, f"URL dup marked for refactor ({url_marked} files)"))
        else:
            report.add(CheckResult("url_dup", CheckResult.PASS, f"URL logic in {len(url_files)} files"))

        # yt-dlp command duplication
        cmd_lines = [i for i, l in enumerate(lines, 1) if "YT_DLP_PATH" in l and "[" in l]
        cmd_unmarked = [i for i, l in enumerate(lines, 1) if "YT_DLP_PATH" in l and "[" in l and "# TODO: extract" not in l]
        if len(cmd_unmarked) > 2:
            report.add(CheckResult("ytdlp_cmd", CheckResult.WARN, f"{len(cmd_lines)} yt-dlp constructions", fixable=True,
                                   fix_desc="반복되는 yt-dlp 명령 구성에 TODO 주석 → build_ytdlp_cmd() 함수로 통합 권장"))
        elif len(cmd_lines) > 2 and len(cmd_unmarked) == 0:
            report.add(CheckResult("ytdlp_cmd", CheckResult.PASS, f"yt-dlp dup marked for refactor ({len(cmd_lines)} sites)"))
        else:
            report.add(CheckResult("ytdlp_cmd", CheckResult.PASS, f"{len(cmd_lines)} yt-dlp constructions"))

        # glob pattern duplication
        glob_count = sum(1 for l in lines if ".glob(" in l or ".rglob(" in l)
        glob_unmarked = sum(1 for l in lines if (".glob(" in l or ".rglob(" in l) and "# TODO: cache" not in l)
        apple_count = sum(1 for l in lines if "startswith('._')" in l)
        if glob_unmarked > 8:
            report.add(CheckResult("file_search", CheckResult.WARN,
                                   f"{glob_count} glob calls, {apple_count} AppleDouble filters", fixable=True,
                                   fix_desc="과도한 glob/rglob 호출에 캐싱 TODO 주석을 추가합니다"))
        elif glob_count > 8 and glob_unmarked == 0:
            report.add(CheckResult("file_search", CheckResult.PASS, f"glob dup marked for caching ({glob_count} calls)"))
        else:
            report.add(CheckResult("file_search", CheckResult.PASS, f"{glob_count} glob calls"))

        # bare except
        bare = [{"line": i, "code": l.strip()[:60]}
                for i, l in enumerate(lines, 1) if l.strip().startswith("except:")]
        if bare:
            report.add(CheckResult("bare_except", CheckResult.WARN, f"{len(bare)} bare except blocks",
                                   details=bare[:5], fixable=True,
                                   fix_desc="bare except: → except Exception: 으로 교체하여 디버깅 가능하게 합니다"))
        else:
            report.add(CheckResult("bare_except", CheckResult.PASS, "No bare except"))

        # repeated DB queries
        db_q = sum(1 for l in lines if "FROM videos WHERE video_id" in l)
        db_unmarked = sum(1 for l in lines if "FROM videos WHERE video_id" in l and "# TODO: extract" not in l)
        if db_unmarked > 3:
            report.add(CheckResult("db_query_dup", CheckResult.WARN, f"Video query repeated {db_q} times", fixable=True,
                                   fix_desc="반복 쿼리에 TODO 주석 → get_video() 헬퍼 함수로 통합 권장"))
        elif db_q > 3 and db_unmarked == 0:
            report.add(CheckResult("db_query_dup", CheckResult.PASS, f"DB dup marked for refactor ({db_q} queries)"))
        else:
            report.add(CheckResult("db_query_dup", CheckResult.PASS, f"Video query: {db_q} times"))

        return report
