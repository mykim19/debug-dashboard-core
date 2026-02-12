"""Phase 3: yt-dlp environment checker"""

import os
import subprocess
from pathlib import Path

from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport


class YtdlpChecker(BaseChecker):
    name = "ytdlp"
    display_name = "YT-DLP"
    description = "yt-dlp binary version, Node.js runtime for YouTube challenge, ejs package, and call-site consistency across the codebase."
    tooltip_why = "YouTube 영상의 오디오/자막을 다운로드하는 핵심 도구(yt-dlp)가 최신 YouTube 보안 인증을 통과할 수 있어야 합니다."
    tooltip_what = "yt-dlp 바이너리 버전, YouTube JS 챌린지용 Node.js 런타임, ejs 패키지, 코드 내 4개 호출 지점의 일관성을 확인합니다."
    tooltip_result = "통과 시 YouTube 다운로드가 정상 작동합니다. 실패 시 '이미지만 가용' 오류가 발생하여 콘텐츠 처리가 중단됩니다."
    icon = "📺"
    color = "#ef4444"

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)

        env_path = project_root / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

        yt_dlp_path = os.environ.get("YT_DLP_PATH", "/opt/anaconda3/bin/yt-dlp")
        yt_js_runtime = os.environ.get("YT_JS_RUNTIME", "node:/opt/homebrew/bin/node")

        if Path(yt_dlp_path).exists():
            try:
                ver = subprocess.check_output([yt_dlp_path, "--version"], text=True, timeout=10).strip()
                report.add(CheckResult("binary", CheckResult.PASS, f"yt-dlp {ver}"))
            except Exception as e:
                report.add(CheckResult("binary", CheckResult.FAIL, str(e)))
        else:
            report.add(CheckResult("binary", CheckResult.FAIL, f"Not found: {yt_dlp_path}"))

        parts = yt_js_runtime.split(":", 1)
        js_path = parts[1] if len(parts) == 2 else yt_js_runtime
        if Path(js_path).exists():
            try:
                nv = subprocess.check_output([js_path, "--version"], text=True, timeout=10).strip()
                report.add(CheckResult("js_runtime", CheckResult.PASS, f"Node {nv}"))
            except Exception as e:
                report.add(CheckResult("js_runtime", CheckResult.FAIL, str(e)))
        else:
            report.add(CheckResult("js_runtime", CheckResult.FAIL, f"Not found: {js_path}"))

        try:
            subprocess.check_output(["pip", "show", "yt-dlp-ejs"], text=True, timeout=10, stderr=subprocess.DEVNULL)
            report.add(CheckResult("ejs_package", CheckResult.PASS, "yt-dlp-ejs installed"))
        except Exception:
            report.add(CheckResult("ejs_package", CheckResult.WARN, "yt-dlp-ejs not found"))

        app_file = project_root / "app.py"
        if app_file.exists():
            src = app_file.read_text(encoding="utf-8")
            lines = src.splitlines()
            calls = []
            for i, line in enumerate(lines, 1):
                if "YT_DLP_PATH" in line and "[" in line:
                    ctx = lines[max(0, i - 3):min(len(lines), i + 5)]
                    has_js = any("js-runtimes" in c or "js_runtimes" in c.lower() for c in ctx)
                    calls.append({"line": i, "has_js": has_js})
            missing = [c for c in calls if not c["has_js"]]
            if not missing:
                report.add(CheckResult("call_sites", CheckResult.PASS, f"All {len(calls)} calls OK"))
            else:
                report.add(CheckResult("call_sites", CheckResult.FAIL,
                                       f"{len(missing)} missing --js-runtimes", details=missing))

        return report
