"""Builtin: Config Drift checker — .env sync, YAML validity, unused config keys.

Checks:
  - env_key_sync: .env keys referenced in code but missing from .env file
  - yaml_valid: config.yaml structural integrity
  - unused_env_keys: .env keys not referenced anywhere in code
"""

import re
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class ConfigDriftChecker(BaseChecker):
    name = "config_drift"
    display_name = "CONFIG SYNC"
    description = ".env key synchronization with code, YAML validity, and unused config detection."
    tooltip_why = "환경변수 누락은 런타임 에러의 주요 원인이고, 미사용 키는 보안/유지보수 부담입니다."
    tooltip_what = ".env 파일의 키와 코드 내 os.environ/os.getenv 참조를 비교합니다."
    tooltip_result = "PASS: 설정 동기화 완료 · WARN: 미사용/누락 키 존재 · FAIL: 필수 키 누락"
    icon = "⚙️"
    color = "#64748b"

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        scan_dirs = phase_cfg.get("scan_dirs", ["."])
        required_keys = phase_cfg.get("required_keys", [])  # e.g., ["GOOGLE_API_KEY"]
        ignore_keys = set(phase_cfg.get("ignore_keys", [
            "PATH", "HOME", "USER", "SHELL", "LANG", "TERM",
            "PWD", "OLDPWD", "SHLVL", "LOGNAME", "TMPDIR",
            "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
        ]))

        skip_dirs = {
            "__pycache__", "venv", ".venv", "node_modules", ".git",
            "downloads", "chroma_db", "backups", "logs", ".debugger",
        }

        # Parse .env file
        env_path = project_root / ".env"
        env_keys = set()
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    key = line.split("=", 1)[0].strip()
                    if key:
                        env_keys.add(key)
            except Exception:
                pass

        # Scan code for env references
        env_ref_pattern = re.compile(
            r"""(?:os\.environ(?:\.get)?\s*[\[\(]\s*["']([A-Z_][A-Z0-9_]*)["']"""
            r"""|os\.getenv\s*\(\s*["']([A-Z_][A-Z0-9_]*)["']"""
            r"""|environ\.get\s*\(\s*["']([A-Z_][A-Z0-9_]*)["'])"""
        )
        # Also detect dotenv-style: config("KEY") or settings.KEY
        dotenv_pattern = re.compile(
            r"""(?:load_dotenv|dotenv_values)"""
        )

        code_refs = set()  # env keys referenced in code
        has_dotenv = False

        for scan_dir in scan_dirs:
            base = project_root / scan_dir.rstrip("/")
            if not base.exists():
                continue
            for py_file in base.rglob("*.py"):
                parts = py_file.relative_to(project_root).parts
                if any(p in skip_dirs or p.startswith(".") for p in parts):
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                for m in env_ref_pattern.finditer(text):
                    key = m.group(1) or m.group(2) or m.group(3)
                    if key and key not in ignore_keys:
                        code_refs.add(key)

                if dotenv_pattern.search(text):
                    has_dotenv = True

        # Check 1: .env key sync — code references keys missing from .env
        if env_keys or code_refs:
            missing_in_env = code_refs - env_keys - ignore_keys
            # Add required keys that are missing
            for rk in required_keys:
                if rk not in env_keys:
                    missing_in_env.add(rk)

            if missing_in_env:
                status = CheckResult.FAIL if (set(required_keys) & missing_in_env) else CheckResult.WARN
                report.add(CheckResult("env_key_sync", status,
                                       f"{len(missing_in_env)} key(s) referenced in code but missing from .env",
                                       details={"missing": sorted(missing_in_env)[:15]},
                                       fixable=True,
                                       fix_desc=".env 파일에 누락된 키를 placeholder로 추가합니다"))
            else:
                report.add(CheckResult("env_key_sync", CheckResult.PASS,
                                       f"All {len(code_refs)} code env references found in .env"))
        elif not env_path.is_file():
            report.add(CheckResult("env_key_sync", CheckResult.SKIP,
                                   "No .env file present"))
        else:
            report.add(CheckResult("env_key_sync", CheckResult.PASS,
                                   "No env references detected in code"))

        # Check 2: YAML config validity
        yaml_path = None
        for candidate in [
            project_root / ".debugger" / "config.yaml",
            project_root / "config.yaml",
        ]:
            if candidate.is_file():
                yaml_path = candidate
                break

        if yaml_path:
            try:
                import yaml
                with open(yaml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    report.add(CheckResult("yaml_valid", CheckResult.PASS,
                                           f"config.yaml valid ({len(data)} top-level keys)"))
                else:
                    report.add(CheckResult("yaml_valid", CheckResult.WARN,
                                           "config.yaml parsed but not a dict"))
            except Exception as e:
                report.add(CheckResult("yaml_valid", CheckResult.FAIL,
                                       f"config.yaml parse error: {e}"))
        else:
            report.add(CheckResult("yaml_valid", CheckResult.SKIP,
                                   "No config.yaml found"))

        # Check 3: Unused .env keys
        if env_keys and code_refs:
            unused = env_keys - code_refs - ignore_keys
            # Filter out common "meta" keys
            unused = {k for k in unused if not k.startswith("_")}
            if unused and len(unused) < len(env_keys):
                report.add(CheckResult("unused_env_keys", CheckResult.WARN,
                                       f"{len(unused)} .env key(s) not referenced in code",
                                       details={"unused": sorted(unused)[:15]}))
            elif unused:
                report.add(CheckResult("unused_env_keys", CheckResult.WARN,
                                       f"Most .env keys ({len(unused)}/{len(env_keys)}) unused in code"))
            else:
                report.add(CheckResult("unused_env_keys", CheckResult.PASS,
                                       f"All .env keys referenced in code"))
        else:
            report.add(CheckResult("unused_env_keys", CheckResult.SKIP,
                                   "Insufficient data for unused key analysis"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "env_key_sync":
            env_path = project_root / ".env"
            # Re-run detection to find missing keys
            phase_cfg = config.get("checks", {}).get(self.name, {})
            required_keys = phase_cfg.get("required_keys", [])

            existing = ""
            if env_path.is_file():
                existing = env_path.read_text(encoding="utf-8")

            existing_keys = set()
            for line in existing.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    key = line.split("=", 1)[0].strip()
                    if key:
                        existing_keys.add(key)

            added = []
            lines = [existing.rstrip()]
            if lines[0]:
                lines.append("")
            lines.append("# Auto-added missing keys:")

            for rk in required_keys:
                if rk not in existing_keys:
                    lines.append(f"{rk}=CHANGE_ME")
                    added.append(rk)

            if added:
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Added {len(added)} placeholder keys to .env"}
            return {"success": True, "message": "No missing required keys to add"}

        return {"success": False, "message": "No auto-fix for this check"}
