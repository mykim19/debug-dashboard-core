"""Builtin: yt-dlp Pipeline checker — binary, JS runtime, config validation.

Checks:
  - ytdlp_binary: yt-dlp binary exists and is executable
  - js_runtime: YT_JS_RUNTIME env set (required for YouTube n-challenge)
  - url_patterns: video_id extraction covers all known URL formats
  - output_dir: download output directory exists and is writable

Applicable when: config has checks.ytdlp_pipeline.enabled = true
"""

import os
import re
import subprocess
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class YtdlpPipelineChecker(BaseChecker):
    name = "ytdlp_pipeline"
    display_name = "YT-DLP PIPE"
    description = "yt-dlp binary, JS runtime for n-challenge, URL patterns, and output directory."
    tooltip_why = "yt-dlp 바이너리 누락이나 JS 런타임 미설정 시 YouTube 다운로드 전체 파이프라인이 중단됩니다."
    tooltip_what = "yt-dlp 실행 가능 여부, YT_JS_RUNTIME 환경변수, URL 패턴 커버리지, 출력 디렉토리를 검사합니다."
    tooltip_result = "PASS: 파이프라인 정상 · WARN: 부분 설정 누락 · FAIL: 핵심 컴포넌트 미설치"
    icon = "📹"
    color = "#ef4444"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        ytdlp_path = phase_cfg.get("ytdlp_path", "yt-dlp")
        output_dir = phase_cfg.get("output_dir", "downloads")

        # Check 1: yt-dlp binary
        try:
            result = subprocess.run(
                [ytdlp_path, "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                report.add(CheckResult("ytdlp_binary", CheckResult.PASS,
                                       f"yt-dlp {version}"))
            else:
                report.add(CheckResult("ytdlp_binary", CheckResult.FAIL,
                                       f"yt-dlp returned error: {result.stderr.strip()[:100]}"))
        except FileNotFoundError:
            report.add(CheckResult("ytdlp_binary", CheckResult.FAIL,
                                   f"yt-dlp not found at: {ytdlp_path}",
                                   fixable=True,
                                   fix_desc="pip install yt-dlp 또는 brew install yt-dlp"))
        except subprocess.TimeoutExpired:
            report.add(CheckResult("ytdlp_binary", CheckResult.WARN,
                                   "yt-dlp --version timed out"))
        except Exception as e:
            report.add(CheckResult("ytdlp_binary", CheckResult.FAIL, str(e)))

        # Check 2: JS runtime (required for YouTube n-challenge since yt-dlp 2026+)
        js_runtime = os.environ.get("YT_JS_RUNTIME", "")
        if not js_runtime:
            # Check .env file
            env_path = project_root / ".env"
            if env_path.is_file():
                try:
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("YT_JS_RUNTIME="):
                            js_runtime = line.split("=", 1)[1].strip()
                            break
                except Exception:
                    pass

        if js_runtime:
            # Verify the node binary exists
            parts = js_runtime.split(":", 1)
            node_path = parts[1] if len(parts) > 1 else parts[0]
            if Path(node_path).exists():
                report.add(CheckResult("js_runtime", CheckResult.PASS,
                                       f"JS runtime: {js_runtime}"))
            else:
                report.add(CheckResult("js_runtime", CheckResult.WARN,
                                       f"YT_JS_RUNTIME set but binary not found: {node_path}"))
        else:
            report.add(CheckResult("js_runtime", CheckResult.WARN,
                                   "YT_JS_RUNTIME not set — YouTube n-challenge may fail",
                                   fixable=True,
                                   fix_desc=".env에 YT_JS_RUNTIME=node:/path/to/node 추가"))

        # Check 3: URL pattern coverage — check get_video_id_from_url
        main_file = phase_cfg.get("main_file", "app.py")
        url_helper = phase_cfg.get("url_helper_file", "utils/content_hash.py")

        required_patterns = {"watch", "youtu.be", "embed", "live", "shorts"}
        found_patterns = set()

        for fpath in [project_root / main_file, project_root / url_helper]:
            if not fpath.is_file():
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                for pat in required_patterns:
                    if pat in text:
                        found_patterns.add(pat)
            except Exception:
                continue

        missing = required_patterns - found_patterns
        if not missing:
            report.add(CheckResult("url_patterns", CheckResult.PASS,
                                   f"All {len(required_patterns)} URL patterns covered"))
        elif missing:
            report.add(CheckResult("url_patterns", CheckResult.WARN,
                                   f"Missing URL patterns: {', '.join(sorted(missing))}",
                                   details={"missing": sorted(missing), "found": sorted(found_patterns)}))

        # Check 4: Output directory
        out_path = project_root / output_dir
        if out_path.is_dir():
            if os.access(str(out_path), os.W_OK):
                report.add(CheckResult("output_dir", CheckResult.PASS,
                                       f"{output_dir}/ exists and writable"))
            else:
                report.add(CheckResult("output_dir", CheckResult.FAIL,
                                       f"{output_dir}/ not writable"))
        else:
            report.add(CheckResult("output_dir", CheckResult.WARN,
                                   f"{output_dir}/ directory not found",
                                   fixable=True,
                                   fix_desc=f"{output_dir}/ 디렉토리를 생성합니다"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        phase_cfg = config.get("checks", {}).get(self.name, {})

        if check_name == "output_dir":
            output_dir = phase_cfg.get("output_dir", "downloads")
            out_path = project_root / output_dir
            out_path.mkdir(parents=True, exist_ok=True)
            return {"success": True, "message": f"Created {output_dir}/ directory"}

        if check_name == "js_runtime":
            env_path = project_root / ".env"
            # Try to find node
            node_candidates = [
                "/opt/homebrew/bin/node",
                "/usr/local/bin/node",
                "/usr/bin/node",
            ]
            node_path = None
            for c in node_candidates:
                if Path(c).exists():
                    node_path = c
                    break

            if not node_path:
                return {"success": False, "message": "node binary not found — install Node.js first"}

            line = f"YT_JS_RUNTIME=node:{node_path}"
            if env_path.is_file():
                existing = env_path.read_text(encoding="utf-8")
                if "YT_JS_RUNTIME" in existing:
                    return {"success": True, "message": "YT_JS_RUNTIME already in .env"}
                env_path.write_text(existing.rstrip() + f"\n{line}\n", encoding="utf-8")
            else:
                env_path.write_text(f"# Auto-added\n{line}\n", encoding="utf-8")
            return {"success": True, "message": f"Added {line} to .env"}

        return {"success": False, "message": "No auto-fix for this check"}
