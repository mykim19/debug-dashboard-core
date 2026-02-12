"""Builtin: Whisper Health checker — model availability, disk, transcription pattern.

Checks:
  - whisper_import: whisper module importable
  - model_disk: sufficient disk for model files (~3GB for medium)
  - transcribe_pattern: code uses whisper.load_audio() path (not raw str)

Applicable when: config has checks.whisper_health.enabled = true
"""

import re
import shutil
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class WhisperHealthChecker(BaseChecker):
    name = "whisper_health"
    display_name = "WHISPER"
    description = "OpenAI Whisper model availability, disk space, and transcription pattern safety."
    tooltip_why = "Whisper 모델 미설치 시 음성 전사가 실패하고, 잘못된 API 호출은 텐서 에러를 유발합니다."
    tooltip_what = "whisper 패키지 설치, 모델 캐시 디스크 여유, load_audio() 패턴 사용 여부를 검사합니다."
    tooltip_result = "PASS: Whisper 정상 · WARN: 디스크 부족 우려 · FAIL: 패키지 미설치"
    icon = "🎙️"
    color = "#a855f7"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        model_name = phase_cfg.get("model", "medium")
        scan_dirs = phase_cfg.get("scan_dirs", ["."])

        # Model size estimates (GB)
        model_sizes = {
            "tiny": 0.08, "base": 0.15, "small": 0.5,
            "medium": 1.5, "large": 3.0, "large-v2": 3.0, "large-v3": 3.0,
        }

        # Check 1: whisper import
        try:
            import whisper
            report.add(CheckResult("whisper_import", CheckResult.PASS,
                                   f"whisper {getattr(whisper, '__version__', 'installed')}"))
        except ImportError:
            report.add(CheckResult("whisper_import", CheckResult.FAIL,
                                   "openai-whisper not installed",
                                   fixable=True,
                                   fix_desc="pip install openai-whisper"))
            # If whisper not installed, remaining checks are moot
            report.add(CheckResult("model_disk", CheckResult.SKIP, "whisper not installed"))
            report.add(CheckResult("transcribe_pattern", CheckResult.SKIP, "whisper not installed"))
            return report

        # Check 2: Disk space for model cache
        cache_dir = Path.home() / ".cache" / "whisper"
        required_gb = model_sizes.get(model_name, 1.5)
        try:
            if cache_dir.exists():
                disk = shutil.disk_usage(str(cache_dir))
            else:
                disk = shutil.disk_usage(str(Path.home()))
            free_gb = disk.free / (1024 ** 3)

            # Check if model file already cached
            model_file = cache_dir / f"{model_name}.pt"
            cached = model_file.exists()

            if cached:
                report.add(CheckResult("model_disk", CheckResult.PASS,
                                       f"{model_name} model cached ({free_gb:.1f}GB free)"))
            elif free_gb > required_gb * 2:
                report.add(CheckResult("model_disk", CheckResult.PASS,
                                       f"{free_gb:.1f}GB free (model needs ~{required_gb}GB)"))
            elif free_gb > required_gb:
                report.add(CheckResult("model_disk", CheckResult.WARN,
                                       f"Low disk: {free_gb:.1f}GB free ({model_name} needs ~{required_gb}GB)"))
            else:
                report.add(CheckResult("model_disk", CheckResult.FAIL,
                                       f"Insufficient disk: {free_gb:.1f}GB free ({model_name} needs ~{required_gb}GB)"))
        except Exception as e:
            report.add(CheckResult("model_disk", CheckResult.WARN, f"Disk check error: {e}"))

        # Check 3: Transcribe pattern — should use whisper.load_audio(), not str(path)
        # Bad: model.transcribe(str(file_path))  → tensor error on live recordings
        # Good: audio = whisper.load_audio(path); model.transcribe(audio)
        bad_pattern = re.compile(r"model\.transcribe\s*\(\s*str\s*\(")
        good_pattern = re.compile(r"whisper\.load_audio\s*\(|load_audio\s*\(")

        bad_usages = []
        has_good = False

        for scan_dir in scan_dirs:
            base = project_root / scan_dir.rstrip("/")
            if not base.exists():
                continue
            for py_file in base.rglob("*.py"):
                parts = py_file.relative_to(project_root).parts
                if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv") for p in parts):
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if bad_pattern.search(line):
                        bad_usages.append({
                            "file": str(py_file.relative_to(project_root)),
                            "line": i,
                        })
                    if good_pattern.search(line):
                        has_good = True

        if bad_usages:
            report.add(CheckResult("transcribe_pattern", CheckResult.WARN,
                                   f"model.transcribe(str(...)) found — use load_audio() instead",
                                   details=bad_usages[:5],
                                   fixable=True,
                                   fix_desc="# TODO: use whisper.load_audio() 마커 추가"))
        elif has_good:
            report.add(CheckResult("transcribe_pattern", CheckResult.PASS,
                                   "Using whisper.load_audio() pattern ✓"))
        else:
            report.add(CheckResult("transcribe_pattern", CheckResult.SKIP,
                                   "No whisper transcribe calls found"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "transcribe_pattern":
            phase_cfg = config.get("checks", {}).get(self.name, {})
            scan_dirs = phase_cfg.get("scan_dirs", ["."])
            bad_pattern = re.compile(r"model\.transcribe\s*\(\s*str\s*\(")
            fixed = 0

            for scan_dir in scan_dirs:
                base = project_root / scan_dir.rstrip("/")
                if not base.exists():
                    continue
                for py_file in base.rglob("*.py"):
                    parts = py_file.relative_to(project_root).parts
                    if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv") for p in parts):
                        continue
                    try:
                        text = py_file.read_text(encoding="utf-8")
                        lines = text.splitlines()
                        changed = False
                        for i, line in enumerate(lines):
                            if bad_pattern.search(line) and "# TODO:" not in line:
                                lines[i] = line + "  # TODO: use whisper.load_audio() instead of str()"
                                changed = True
                                fixed += 1
                        if changed:
                            py_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    except Exception:
                        continue

            if fixed:
                return {"success": True, "message": f"Added TODO markers to {fixed} line(s)"}
            return {"success": True, "message": "No unsafe patterns to mark"}

        return {"success": False, "message": "No auto-fix for this check"}
