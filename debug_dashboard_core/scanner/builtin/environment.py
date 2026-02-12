"""Builtin: Environment checker — Python, packages, disk, .env"""

import sys
import os
import shutil
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class EnvironmentChecker(BaseChecker):
    name = "environment"
    display_name = "ENVIRONMENT"
    description = "Python version, required packages, disk space, .env file — checks that the runtime environment is correctly configured."
    tooltip_why = "서비스가 정상 작동하려면 Python, 필수 패키지, 디스크 공간, 환경변수 파일(.env)이 모두 갖추어져야 합니다."
    tooltip_what = "Python 버전, 핵심 패키지 설치 여부, 디스크 여유 공간, .env 파일 존재 여부를 자동 검증합니다."
    tooltip_result = "모두 통과하면 서버를 안전하게 기동할 수 있는 상태이며, 경고 발생 시 특정 기능이 작동하지 않을 수 있습니다."
    icon = "🖥"
    color = "#22c55e"

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        phase_cfg = config.get("checks", {}).get("environment", {})

        if check_name == "env_file":
            env_path = project_root / ".env"
            if env_path.exists():
                return {"success": True, "message": ".env already exists"}
            # Use template from config (configurable per project)
            template = phase_cfg.get("env_template",
                "# Auto-generated .env template\n"
                "# Fill in your actual values\n"
                "\n"
                "FLASK_SECRET_KEY=change-me-to-random-string\n"
            )
            env_path.write_text(template, encoding="utf-8")
            return {"success": True, "message": "Created .env template — edit values before use"}

        if check_name == "disk_space":
            cleanup_dir = phase_cfg.get("cleanup_dir", "downloads")
            dl_dir = project_root / cleanup_dir
            if not dl_dir.exists():
                return {"success": True, "message": f"No {cleanup_dir} directory to clean"}
            removed = 0
            for pattern in ["*.part", "*.tmp", "*.temp"]:
                for f in dl_dir.glob(pattern):
                    try:
                        f.unlink()
                        removed += 1
                    except Exception:
                        pass
            if removed > 0:
                return {"success": True, "message": f"Removed {removed} temp files from {cleanup_dir}/"}
            return {"success": True, "message": "No temp files to clean — consider manual cleanup"}

        return {"success": False, "message": "No auto-fix for this check"}

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get("environment", {})

        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        report.add(CheckResult("python_version", CheckResult.PASS, f"Python {py_ver}"))

        packages = phase_cfg.get("packages", ["flask"])
        for pkg in packages:
            try:
                __import__(pkg)
                report.add(CheckResult(f"pkg_{pkg}", CheckResult.PASS, f"{pkg} available"))
            except ImportError:
                report.add(CheckResult(f"pkg_{pkg}", CheckResult.FAIL, f"{pkg} not installed"))

        # Disk space check — cleanup_dir from config
        cleanup_dir = phase_cfg.get("cleanup_dir", "downloads")
        dl_dir = project_root / cleanup_dir
        if dl_dir.exists():
            try:
                disk = shutil.disk_usage(str(dl_dir))
                free_gb = disk.free / (1024**3)
                status = CheckResult.PASS if free_gb > 10 else (CheckResult.WARN if free_gb > 2 else CheckResult.FAIL)
                report.add(CheckResult("disk_space", status, f"Free: {free_gb:.1f}GB",
                                       fixable=True if status != CheckResult.PASS else False,
                                       fix_desc=f"{cleanup_dir}/ 폴더의 임시 파일(.part, .tmp)을 정리합니다" if status != CheckResult.PASS else ""))
            except Exception as e:
                report.add(CheckResult("disk_space", CheckResult.WARN, str(e)))
        else:
            report.add(CheckResult("disk_space", CheckResult.PASS, f"No {cleanup_dir}/ directory"))

        env_path = project_root / ".env"
        if env_path.exists():
            report.add(CheckResult("env_file", CheckResult.PASS, ".env file exists"))
        else:
            report.add(CheckResult("env_file", CheckResult.WARN, ".env file not found", fixable=True,
                                   fix_desc="기본 환경변수 템플릿 .env 파일을 자동 생성합니다"))

        return report
