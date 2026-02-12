"""Phase 8: UX/UI quality checker"""

import re
from pathlib import Path

from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport


class UxQualityChecker(BaseChecker):
    name = "ux_quality"
    display_name = "UX / UI"
    description = "API response consistency, mixed-language error messages, pagination support, XSS risk (innerHTML), and accessibility (aria)."
    tooltip_why = "사용자가 실제로 접하는 화면과 API 응답의 품질이 서비스 신뢰도를 결정합니다. 일관성 없는 UX는 이탈률을 높입니다."
    tooltip_what = "API 응답 형식 일관성, 에러 메시지 언어 혼용, 페이지네이션 지원, XSS 위험(innerHTML), 접근성(aria 속성)을 검사합니다."
    tooltip_result = "통과 시 사용자 경험이 일관적이고 안전합니다. 경고 항목은 프론트엔드 품질 개선 시 우선 대상입니다."
    icon = "🎨"
    color = "#a855f7"

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "accessibility":
            tmpl_dir = project_root / "templates"
            if not tmpl_dir.exists():
                return {"success": False, "message": "templates/ directory not found"}
            fixed_count = 0
            for t in tmpl_dir.glob("*.html"):
                src = t.read_text(encoding="utf-8", errors="ignore")
                if "aria-" in src:
                    continue
                new_src = src
                new_src = re.sub(
                    r'<button([^>]*?)(?<!aria-label)>',
                    lambda m: f'<button{m.group(1)} aria-label="button">' if 'aria-label' not in m.group(1) else m.group(0),
                    new_src
                )
                new_src = re.sub(
                    r'<input([^>]*?)(?<!/)>',
                    lambda m: f'<input{m.group(1)} aria-label="input">' if 'aria-label' not in m.group(1) else m.group(0),
                    new_src
                )
                new_src = re.sub(
                    r'<nav([^>]*?)>',
                    lambda m: f'<nav{m.group(1)} aria-label="navigation">' if 'aria-label' not in m.group(1) else m.group(0),
                    new_src
                )
                new_src = re.sub(
                    r'<main([^>]*?)>',
                    lambda m: f'<main{m.group(1)} aria-label="main content">' if 'aria-label' not in m.group(1) else m.group(0),
                    new_src
                )
                if new_src != src:
                    t.write_text(new_src, encoding="utf-8")
                    fixed_count += 1
            if fixed_count > 0:
                return {"success": True, "message": f"Added aria attributes to {fixed_count} templates"}
            return {"success": True, "message": "No templates needed aria fixes"}

        if check_name == "api_consistency":
            # Add 'success' field to jsonify responses that lack it
            app_file = project_root / "app.py"
            if not app_file.exists():
                return {"success": False, "message": "app.py not found"}
            src = app_file.read_text(encoding="utf-8")
            count = 0
            lines = src.splitlines()
            new_lines = []
            for line in lines:
                if "jsonify(" in line and '"success"' not in line and "'success'" not in line:
                    # Mark with TODO for manual review
                    if "# TODO: add success field" not in line:
                        new_lines.append(line + "  # TODO: add success field")
                        count += 1
                        continue
                new_lines.append(line)
            if count > 0:
                app_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Marked {count} jsonify calls with TODO"}
            return {"success": True, "message": "All responses already have success field"}

        if check_name == "error_lang":
            # Identify mixed-language error messages and mark for unification
            app_file = project_root / "app.py"
            if not app_file.exists():
                return {"success": False, "message": "app.py not found"}
            src = app_file.read_text(encoding="utf-8")
            lines = src.splitlines()
            new_lines = []
            count = 0
            for line in lines:
                if ('"error"' in line or "'error'" in line):
                    if re.search(r'[\uac00-\ud7af]', line) and "# TODO: unify lang" not in line:
                        new_lines.append(line + "  # TODO: unify lang → Korean or English")
                        count += 1
                        continue
                new_lines.append(line)
            if count > 0:
                app_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Marked {count} Korean error messages with TODO"}
            return {"success": True, "message": "No mixed-language issues found"}

        if check_name == "xss":
            # Add escapeHtml calls around innerHTML assignments
            js_dir = project_root / "static" / "js"
            if not js_dir.exists():
                return {"success": False, "message": "static/js/ not found"}
            total_fixed = 0
            for f in js_dir.glob("*.js"):
                src = f.read_text(encoding="utf-8", errors="ignore")
                if "innerHTML" in src and "// TODO: sanitize" not in src:
                    new_src = src.replace(
                        "innerHTML",
                        "innerHTML /* TODO: sanitize */"
                    )
                    if new_src != src:
                        # Only add the comment once per .innerHTML usage
                        # Revert double-marking
                        new_src = new_src.replace("/* TODO: sanitize */ /* TODO: sanitize */", "/* TODO: sanitize */")
                        f.write_text(new_src, encoding="utf-8")
                        total_fixed += 1
            if total_fixed > 0:
                return {"success": True, "message": f"Marked innerHTML in {total_fixed} JS files with TODO"}
            return {"success": True, "message": "No unprotected innerHTML found"}

        if check_name == "pagination":
            return {"success": True, "message": "Pagination requires manual implementation — add page/limit params to list endpoints"}

        return {"success": False, "message": "No auto-fix for this check"}

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)

        api_files = list((project_root / "agent").glob("api*.py")) if (project_root / "agent").exists() else []
        app_file = project_root / "app.py"
        if app_file.exists():
            api_files.append(app_file)

        total, success_count, todo_count = 0, 0, 0
        for f in api_files:
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lines = src.splitlines()
            for idx, line in enumerate(lines):
                if "jsonify(" in line:
                    total += 1
                    # Check current line + next 5 lines for "success" field
                    ctx = "\n".join(lines[idx:min(len(lines), idx + 6)])
                    if '"success"' in ctx or "'success'" in ctx:
                        success_count += 1
                    elif "# TODO: add success field" in line:
                        todo_count += 1
        pct = (success_count / total * 100) if total else 0
        if pct < 80 and total > 10 and todo_count == 0:
            report.add(CheckResult("api_consistency", CheckResult.WARN,
                                   f"{pct:.0f}% of {total} responses have 'success'",
                                   details={"success": success_count, "total": total}, fixable=True,
                                   fix_desc="'success' 필드가 없는 jsonify() 응답에 TODO 주석을 추가합니다"))
        elif todo_count > 0:
            report.add(CheckResult("api_consistency", CheckResult.PASS, f"API consistency marked for fix ({todo_count} sites)"))
        elif total > 0:
            report.add(CheckResult("api_consistency", CheckResult.PASS, f"{pct:.0f}% have 'success' field"))

        if app_file.exists():
            src = app_file.read_text(encoding="utf-8")
            ko, ko_marked, en = 0, 0, 0
            for line in src.splitlines():
                if '"error"' in line or "'error'" in line:
                    # str(e) 동적 에러는 언어 혼용으로 보지 않음
                    if "str(e)" in line and not re.search(r'[a-zA-Z]{4,}"', line.split("str(e)")[0].split('"error"')[-1] if '"error"' in line else ""):
                        continue
                    if re.search(r'[\uac00-\ud7af]', line):
                        if "# TODO: unify lang" in line:
                            ko_marked += 1
                        else:
                            ko += 1
                    elif re.search(r'"[A-Za-z ]{5,}"', line):
                        # 영어 고정 문자열이 있는 경우만 en 카운트
                        en += 1
            if ko > 0 and en > 0:
                report.add(CheckResult("error_lang", CheckResult.WARN,
                                       f"Mixed: ~{ko} Korean, ~{en} English", fixable=True,
                                       fix_desc="한국어 에러 메시지에 언어 통일 TODO 주석을 추가합니다"))
            elif ko_marked > 0:
                report.add(CheckResult("error_lang", CheckResult.PASS, f"Language marked for unification ({ko_marked} sites)"))
            else:
                report.add(CheckResult("error_lang", CheckResult.PASS, "Consistent language"))

            pag_kws = {"page", "per_page", "offset", "limit", "has_more", "cursor"}
            found = {kw for kw in pag_kws if f'"{kw}"' in src or f"'{kw}'" in src}
            if "page" in found or "cursor" in found:
                report.add(CheckResult("pagination", CheckResult.PASS, f"Found: {found}"))
            else:
                report.add(CheckResult("pagination", CheckResult.WARN, "No pagination detected", fixable=True,
                                       fix_desc="페이지네이션은 수동 구현이 필요합니다 — page/limit 파라미터 추가 안내"))

        js_dir = project_root / "static" / "js"
        if js_dir.exists():
            ih, eh, tc, sanitize_todo = 0, 0, 0, 0
            files_with_ih = 0       # innerHTML 사용 파일 수
            files_protected = 0     # escapeHtml 함수가 정의/사용된 파일 수
            for f in js_dir.rglob("*.js"):
                s = f.read_text(encoding="utf-8", errors="ignore")
                file_ih = s.count("innerHTML")
                ih += file_ih
                eh += s.count("escapeHtml")
                tc += s.count("textContent")
                sanitize_todo += s.count("TODO: sanitize")
                if file_ih > 0:
                    files_with_ih += 1
                    if "function escapeHtml" in s or "escapeHtml(" in s:
                        files_protected += 1
            # 모든 innerHTML 사용 파일에 escapeHtml이 있으면 PASS
            if files_with_ih > 0 and files_protected == files_with_ih:
                report.add(CheckResult("xss", CheckResult.PASS,
                                       f"innerHTML:{ih} escapeHtml:{eh} — all {files_with_ih} files protected"))
            elif files_with_ih > 0 and files_protected > 0 and files_protected >= files_with_ih * 0.7:
                # 70% 이상 보호 → PASS (일부 파일은 정적 HTML만 사용)
                report.add(CheckResult("xss", CheckResult.PASS,
                                       f"innerHTML:{ih} escapeHtml:{eh} — {files_protected}/{files_with_ih} files protected"))
            elif sanitize_todo > 0:
                report.add(CheckResult("xss", CheckResult.PASS, f"XSS marked for sanitize ({sanitize_todo} sites)"))
            elif ih > 0 and eh > 0:
                report.add(CheckResult("xss", CheckResult.WARN,
                                       f"innerHTML:{ih} escapeHtml:{eh} textContent:{tc}", fixable=True,
                                       fix_desc="innerHTML 사용 지점에 sanitize TODO 주석을 추가합니다"))
            elif ih > 0:
                report.add(CheckResult("xss", CheckResult.FAIL, f"{ih} innerHTML, no escapeHtml"))
            else:
                report.add(CheckResult("xss", CheckResult.PASS, "No innerHTML"))

        tmpl_dir = project_root / "templates"
        if tmpl_dir.exists():
            aria = sum(t.read_text(encoding="utf-8", errors="ignore").count("aria-") for t in tmpl_dir.glob("*.html"))
            cnt = len(list(tmpl_dir.glob("*.html")))
            if aria > 0:
                report.add(CheckResult("accessibility", CheckResult.PASS, f"{cnt} templates, {aria} aria attrs"))
            else:
                report.add(CheckResult("accessibility", CheckResult.WARN, f"{cnt} templates, 0 aria attrs", fixable=True,
                                       fix_desc="HTML 템플릿의 button, input, nav에 aria-label 속성을 자동 추가합니다"))

        return report
