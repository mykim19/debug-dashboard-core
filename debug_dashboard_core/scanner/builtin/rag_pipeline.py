"""Builtin: RAG Pipeline checker — LLM API connectivity, embedding config, service health.

Checks:
  - api_key: LLM API key configured (Gemini/OpenAI)
  - embedding_config: embedding dimension consistency
  - service_modules: required service files exist

Applicable when: config has checks.rag_pipeline.enabled = true
"""

import os
import re
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class RAGPipelineChecker(BaseChecker):
    name = "rag_pipeline"
    display_name = "RAG PIPE"
    description = "LLM API key, embedding configuration, and RAG service module availability."
    tooltip_why = "RAG 파이프라인의 핵심 설정(API 키, 임베딩 차원)이 잘못되면 검색·생성이 모두 실패합니다."
    tooltip_what = "LLM API 키 설정, 임베딩 차원 일관성, 필수 서비스 모듈 존재를 검사합니다."
    tooltip_result = "PASS: RAG 파이프라인 정상 · WARN: 부분 설정 누락 · FAIL: API 키 미설정"
    icon = "🔍"
    color = "#7c3aed"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        api_key_names = phase_cfg.get("api_key_names", [
            "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        ])
        required_services = phase_cfg.get("required_services", [])
        embedding_dim = phase_cfg.get("embedding_dim", 768)

        # Check 1: API key configured
        found_keys = []
        env_path = project_root / ".env"
        env_vars = {}
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()
            except Exception:
                pass

        for key_name in api_key_names:
            val = os.environ.get(key_name, "") or env_vars.get(key_name, "")
            if val and val != "CHANGE_ME" and not val.startswith("your-"):
                found_keys.append(key_name)

        if found_keys:
            report.add(CheckResult("api_key", CheckResult.PASS,
                                   f"API key(s) configured: {', '.join(found_keys)}"))
        else:
            report.add(CheckResult("api_key", CheckResult.FAIL,
                                   f"No LLM API key found (checked: {', '.join(api_key_names)})",
                                   fixable=True,
                                   fix_desc=".env에 API 키 placeholder를 추가합니다"))

        # Check 2: Embedding dimension consistency
        # Scan for dimension references in code
        dim_pattern = re.compile(r"(?:embed(?:ding)?_dim(?:ension)?|n_dim|vector_size)\s*[=:]\s*(\d+)")
        dim_values = {}  # {file: [dims]}

        for py_file in project_root.rglob("*.py"):
            parts = py_file.relative_to(project_root).parts
            if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv", "node_modules",
                                               "chroma_db") for p in parts):
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                for m in dim_pattern.finditer(text):
                    val = int(m.group(1))
                    if 64 <= val <= 4096:  # reasonable embedding dim range
                        rel = str(py_file.relative_to(project_root))
                        dim_values.setdefault(rel, []).append(val)
            except Exception:
                continue

        all_dims = set()
        for dims in dim_values.values():
            all_dims.update(dims)

        if len(all_dims) > 1:
            report.add(CheckResult("embedding_config", CheckResult.WARN,
                                   f"Multiple embedding dimensions: {sorted(all_dims)}",
                                   details={"dimensions": {k: v for k, v in list(dim_values.items())[:5]}}))
        elif all_dims:
            dim = next(iter(all_dims))
            if dim == embedding_dim:
                report.add(CheckResult("embedding_config", CheckResult.PASS,
                                       f"Embedding dimension consistent: {dim}"))
            else:
                report.add(CheckResult("embedding_config", CheckResult.WARN,
                                       f"Embedding dimension {dim} ≠ expected {embedding_dim}"))
        else:
            report.add(CheckResult("embedding_config", CheckResult.SKIP,
                                   "No embedding dimension references found in code"))

        # Check 3: Required service modules
        if required_services:
            missing = []
            found = []
            for svc in required_services:
                svc_path = project_root / svc
                if svc_path.is_file():
                    found.append(svc)
                else:
                    missing.append(svc)

            if missing:
                report.add(CheckResult("service_modules", CheckResult.WARN,
                                       f"{len(missing)} service module(s) missing",
                                       details={"missing": missing, "found": found}))
            else:
                report.add(CheckResult("service_modules", CheckResult.PASS,
                                       f"All {len(found)} service modules present"))
        else:
            # Auto-detect common RAG service files
            rag_indicators = [
                "backend/services/gemini_service.py",
                "backend/services/unified_search.py",
                "backend/services/lightrag_service.py",
                "backend/services/text_processor.py",
                "backend/services/golden_extractor.py",
            ]
            found = [f for f in rag_indicators if (project_root / f).is_file()]
            if found:
                report.add(CheckResult("service_modules", CheckResult.PASS,
                                       f"{len(found)} RAG service modules detected"))
            else:
                report.add(CheckResult("service_modules", CheckResult.SKIP,
                                       "No RAG service modules detected"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "api_key":
            phase_cfg = config.get("checks", {}).get(self.name, {})
            api_key_names = phase_cfg.get("api_key_names", ["GOOGLE_API_KEY"])

            env_path = project_root / ".env"
            existing = ""
            if env_path.is_file():
                existing = env_path.read_text(encoding="utf-8")

            added = []
            lines = [existing.rstrip()]
            if lines[0]:
                lines.append("")
            lines.append("# LLM API keys (auto-added):")

            for key in api_key_names[:2]:
                if key not in existing:
                    lines.append(f"{key}=CHANGE_ME")
                    added.append(key)

            if added:
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Added placeholder(s): {', '.join(added)}"}
            return {"success": True, "message": "API key entries already in .env"}

        return {"success": False, "message": "No auto-fix for this check"}
