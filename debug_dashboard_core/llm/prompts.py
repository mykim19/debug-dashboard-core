"""Prompt templates for LLM-based analysis.

GPT Risk #5 addressed: prompts include rich evidence context
(file/line/snippet, recent changes, regression diffs, env summary).
"""
import json
import platform
import sys
from typing import Dict, List


def build_analysis_prompt(checker_name: str, report: dict, config: dict,
                          evidence_context: dict = None) -> str:
    """Build a structured prompt for LLM root cause analysis.

    Includes:
      - Checker report summary
      - Failing checks with evidence (file, line, snippet)
      - Recent file changes (from agent memory)
      - Regression diffs (PASS→FAIL transitions)
      - Environment summary
    """
    checks = report.get("checks", [])
    failing = [c for c in checks if c["status"] in ("FAIL", "WARN")]
    passing = [c for c in checks if c["status"] == "PASS"]

    project_name = config.get('project', {}).get('name', 'Unknown')
    prompt = f"""당신은 소프트웨어 진단 전문가입니다. 프로젝트 "{project_name}"의 "{checker_name}" 체커 결과를 분석해주세요.
반드시 **한국어**로 답변하세요.

## 체커 리포트 요약
- 전체 검사: {len(checks)}개
- 통과: {len(passing)}개
- 실패/경고: {len(failing)}개
- 건강도: {report.get('health_pct', 0)}%

## 실패/경고 상세:
"""
    for c in failing:
        prompt += f"\n### {c['name']} [{c['status']}]\n"
        prompt += f"메시지: {c.get('message', '')}\n"
        if c.get("details"):
            details_str = json.dumps(c["details"], indent=2, default=str)
            if len(details_str) > 1500:
                details_str = details_str[:1500] + "\n... (truncated)"
            prompt += f"증거:\n```json\n{details_str}\n```\n"
        if c.get("fix_desc"):
            prompt += f"자동 수정 가능: {c['fix_desc']}\n"

    # GPT Risk #5: Include agent memory context
    if evidence_context:
        changes = evidence_context.get("recent_file_changes", [])
        if changes:
            prompt += "\n## 최근 파일 변경 (관련 가능성):\n"
            for batch in changes[:3]:
                for f in (batch if isinstance(batch, list) else [batch])[:5]:
                    if isinstance(f, dict):
                        prompt += f"- {f.get('path', '?')} ({f.get('change', '?')})\n"

        regressions = evidence_context.get("regressions", [])
        if regressions:
            prompt += "\n## 회귀 (이전 PASS → 현재 FAIL/WARN):\n"
            for r in regressions[:5]:
                prompt += f"- {r.get('check', '?')}: {r.get('was', '?')} → {r.get('now', '?')} — {r.get('message', '')}\n"

    prompt += f"""
## 환경
- Python: {sys.version.split()[0]}
- OS: {platform.system()} {platform.release()}
- 프로젝트 경로: {config.get('project', {}).get('root', '?')}

## 분석 요청사항
1. 증상이 아닌 **근본 원인**을 파악하세요
2. 여러 실패 간의 **상관관계**를 판단하세요
3. 영향도 순으로 **수정 방안**을 제시하세요
4. 수정 시 **주의사항**을 안내하세요
5. 증거의 구체적인 파일/라인을 참조하세요

## 응답 형식 (반드시 이 형식을 따르세요)
### Root Causes
- [원인 1 — 증거 참조 포함]
- [원인 2]

### Fix Plan
1. [최우선 수정 — 구체적 조치]
2. [차선 수정]

### Risks
- [주의사항 1]

### Summary
[한 문단 요약]
"""
    return prompt


def build_report_prompt(scan_data: dict) -> str:
    """Generate a comprehensive Korean overview from scan data."""
    totals = scan_data.get("totals", {})
    phases = scan_data.get("phases", {})
    healthy = scan_data.get("healthy_phases", [])
    project = scan_data.get("project", "Unknown")

    # Build structured prompt instead of raw JSON dump
    prompt = f"""당신은 소프트웨어 진단 전문가입니다. 프로젝트 "{project}"의 **전체 스캔 결과**를 분석하여 종합 보고서를 작성해주세요.
반드시 **한국어**로, **상세하고 구체적으로** 답변하세요.

## 전체 현황
- 총 페이즈: {totals.get('total_phases', '?')}개
- 이슈 발생 페이즈: {totals.get('issue_phases', '?')}개
- 정상 페이즈: {totals.get('healthy_phases', '?')}개
- 전체 체크: {totals.get('pass', 0)} PASS / {totals.get('warn', 0)} WARN / {totals.get('fail', 0)} FAIL
- 건강도: {totals.get('health_pct', 0)}%

"""
    if healthy:
        prompt += f"## 정상 페이즈\n{', '.join(healthy)}\n\n"

    prompt += "## 이슈가 있는 페이즈 상세\n"
    for phase_name, phase_data in phases.items():
        prompt += f"\n### {phase_name} (PASS:{phase_data.get('pass',0)} WARN:{phase_data.get('warn',0)} FAIL:{phase_data.get('fail',0)})\n"
        for issue in phase_data.get("issues", []):
            status_icon = "❌" if issue["status"] == "FAIL" else "⚠️"
            prompt += f"- {status_icon} **{issue['name']}** [{issue['status']}]: {issue.get('message', '')}\n"
            if issue.get("details"):
                prompt += f"  증거: {issue['details']}\n"
            if issue.get("fix_desc"):
                prompt += f"  자동수정 가능: {issue['fix_desc']}\n"

    prompt += """
## 분석 요청 (각 항목을 **충분히 상세하게** 작성하세요)

**1. 전체 건강 상태 평가** — 현재 프로젝트의 전반적 건강 상태를 평가하고, 심각도를 CRITICAL/WARNING/ACCEPTABLE로 분류하세요.

**2. 페이즈별 심층 분석** — 이슈가 있는 각 페이즈에 대해:
   - 무엇이 문제인지 구체적으로 설명
   - 왜 이 문제가 발생했는지 원인 분석
   - 해당 이슈가 프로젝트에 미치는 영향

**3. 이슈 간 상관관계** — 여러 페이즈의 이슈들이 서로 연관되어 있는지 분석하세요. (예: 의존성 문제 → 보안 취약점 등)

**4. 우선순위별 조치 방안** — 가장 시급한 것부터 순서대로, 각각에 대해 구체적인 명령어나 수정 방법을 포함하세요.

**5. 자동수정 가능 항목 안내** — fixable 항목들을 정리하고, AUTO-FIX 사용 시 주의사항을 안내하세요.

## 응답 형식 (반드시 이 형식을 따르세요)

### Root Causes
- [원인 1 — 영향받는 페이즈 이름 포함]
- [원인 2]
- [원인 3]

### Fix Plan
1. [최우선: 구체적 명령어/파일 수정 포함]
2. [차선: 구체적 조치]
3. [그 다음]

### Risks
- [주의사항 1]
- [주의사항 2]

### Summary
[3~5문장의 전체 요약 — 현재 상태, 가장 심각한 문제, 권장 우선 조치를 포함]
"""
    return prompt


def parse_analysis_response(text: str) -> dict:
    """Parse LLM response into structured sections."""
    result = {
        "analysis": text,
        "root_causes": [],
        "fix_suggestions": [],
    }

    lines = text.split("\n")
    current_section = None

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        # Detect section headers
        if "root cause" in lower and stripped.startswith("#"):
            current_section = "root_causes"
            continue
        elif "fix plan" in lower and stripped.startswith("#"):
            current_section = "fix_suggestions"
            continue
        elif "risk" in lower and stripped.startswith("#"):
            current_section = "risks"
            continue
        elif "summary" in lower and stripped.startswith("#"):
            current_section = "summary"
            continue

        # Extract list items
        if current_section == "root_causes" and stripped.startswith("-"):
            text_clean = stripped.lstrip("- ").strip()
            if text_clean:
                result["root_causes"].append(text_clean)
        elif current_section == "fix_suggestions":
            if stripped.startswith("-") or (len(stripped) > 0 and stripped[0].isdigit()):
                text_clean = stripped.lstrip("-0123456789. ").strip()
                if text_clean:
                    result["fix_suggestions"].append({"action": text_clean})

    return result
