"""Builtin: Security checker — SQL injection, command injection, path traversal, etc."""

import re
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class SecurityChecker(BaseChecker):
    name = "security"
    display_name = "SECURITY"
    description = "SQL injection via f-strings, command injection (shell=True), path traversal, CORS policy, Flask debug mode, and secrets exposure."
    tooltip_why = "보안 취약점은 사용자 데이터 유출과 서비스 장애의 직접적 원인입니다. 외부 공격 표면을 사전에 차단해야 합니다."
    tooltip_what = "SQL 인젝션(f-string), 명령어 인젝션(shell=True), 경로 탈출, CORS 정책, Flask 디버그 모드, 시크릿 노출을 스캔합니다."
    tooltip_result = "통과 시 알려진 주요 취약점이 없습니다. 경고/실패 항목은 배포 전 반드시 수정해야 할 보안 이슈입니다."
    icon = "🔒"
    color = "#ec4899"

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        phase_cfg = config.get("checks", {}).get("security", {})
        main_file = phase_cfg.get("main_file", "app.py")

        if check_name == "sql_injection":
            scan_dirs = phase_cfg.get("scan_dirs", ["."])
            py_files = []
            for d in scan_dirs:
                target = project_root / d
                if target.is_dir():
                    py_files.extend(target.glob("*.py"))
                elif target.is_file():
                    py_files.append(target)
            total_marked = 0
            for f in py_files:
                try:
                    src = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                lines = src.splitlines()
                new_lines = []
                changed = False
                for i, line in enumerate(lines):
                    if "execute(" in line:
                        ctx = "\n".join(lines[max(0, i - 2):min(len(lines), i + 3)])
                        if ('f"""' in ctx or "f'''" in ctx or 'f"' in ctx) and "{" in ctx and "?" not in line:
                            if "# TODO: parameterize" not in line:
                                new_lines.append(line + "  # TODO: parameterize — avoid f-string SQL")
                                total_marked += 1
                                changed = True
                                continue
                    new_lines.append(line)
                if changed:
                    f.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            if total_marked > 0:
                return {"success": True, "message": f"Marked {total_marked} SQL lines with TODO comments"}
            return {"success": True, "message": "No unmarked SQL injection points found"}

        if check_name == "path_traversal":
            app_py = project_root / main_file
            if not app_py.exists():
                return {"success": False, "message": f"{main_file} not found"}
            src = app_py.read_text(encoding="utf-8")
            if "def sanitize_filename" in src:
                idx = src.find("def sanitize_filename")
                block = src[idx:idx + 500]
                if ".." not in block:
                    fn_end = src.find("\n\n", idx)
                    if fn_end == -1:
                        fn_end = idx + 500
                    fn_block = src[idx:fn_end]
                    lines = fn_block.splitlines()
                    new_lines = []
                    inserted = False
                    for line in lines:
                        if line.strip().startswith("return") and not inserted:
                            indent = len(line) - len(line.lstrip())
                            spaces = " " * indent
                            new_lines.append(f"{spaces}# Prevent path traversal")
                            new_lines.append(f'{spaces}filename = filename.replace("..", "")')
                            inserted = True
                        new_lines.append(line)
                    new_block = "\n".join(new_lines)
                    src = src[:idx] + new_block + src[fn_end:]
                    app_py.write_text(src, encoding="utf-8")
                    return {"success": True, "message": "Added .. filter to sanitize_filename"}
                return {"success": True, "message": "sanitize_filename already has .. protection"}
            else:
                func = '''
def sanitize_filename(filename):
    """Remove path traversal and dangerous characters from filename."""
    filename = filename.replace("..", "")
    filename = re.sub(r'[<>:"/\\\\|?*]', '_', filename)
    return filename.strip('. ')

'''
                import_end = 0
                for i, line in enumerate(src.splitlines()):
                    if line.startswith("import ") or line.startswith("from "):
                        import_end = src.find("\n", src.find(line)) + 1
                if "import re" not in src:
                    src = src[:import_end] + "import re\n" + src[import_end:]
                    import_end += len("import re\n")
                src = src[:import_end] + func + src[import_end:]
                app_py.write_text(src, encoding="utf-8")
                return {"success": True, "message": "Added sanitize_filename() function with path traversal protection"}

        if check_name == "secrets":
            gi = project_root / ".gitignore"
            if gi.exists():
                content = gi.read_text(encoding="utf-8")
                if ".env" in content:
                    return {"success": True, "message": ".env already in .gitignore"}
                with open(gi, "a", encoding="utf-8") as f:
                    f.write("\n# Environment secrets\n.env\n")
                return {"success": True, "message": "Added .env to .gitignore"}
            else:
                gi.write_text("# Auto-generated by Debug Dashboard\n.env\n__pycache__/\n*.pyc\n", encoding="utf-8")
                return {"success": True, "message": "Created .gitignore with .env entry"}

        if check_name == "error_swallowing":
            app_py = project_root / main_file
            if not app_py.exists():
                return {"success": False, "message": f"{main_file} not found"}
            src = app_py.read_text(encoding="utf-8")
            count = 0
            new_lines = []
            for line in src.splitlines(keepends=True):
                if line.strip().startswith("except:"):
                    new_lines.append(line.replace("except:", "except Exception:"))
                    count += 1
                else:
                    new_lines.append(line)
            if count > 0:
                app_py.write_text("".join(new_lines), encoding="utf-8")
                return {"success": True, "message": f"Replaced {count} bare except → except Exception"}
            return {"success": True, "message": "No bare except found"}

        if check_name == "cors":
            app_py = project_root / main_file
            if not app_py.exists():
                return {"success": False, "message": f"{main_file} not found"}
            src = app_py.read_text(encoding="utf-8")
            changed = False
            if 'origins="*"' in src:
                src = src.replace('origins="*"', 'origins="http://localhost:*"')
                changed = True
            if "origins='*'" in src:
                src = src.replace("origins='*'", "origins='http://localhost:*'")
                changed = True
            if changed:
                app_py.write_text(src, encoding="utf-8")
                return {"success": True, "message": "Restricted CORS to localhost only"}
            return {"success": True, "message": "No wildcard CORS found"}

        if check_name == "flask_debug":
            app_py = project_root / main_file
            if not app_py.exists():
                return {"success": False, "message": f"{main_file} not found"}
            src = app_py.read_text(encoding="utf-8")
            changed = False
            if "debug=True" in src:
                src = src.replace("debug=True", "debug=False")
                changed = True
            if "DEBUG = True" in src:
                src = src.replace("DEBUG = True", "DEBUG = False")
                changed = True
            if changed:
                app_py.write_text(src, encoding="utf-8")
                return {"success": True, "message": f"Set debug=False in {main_file}"}
            return {"success": True, "message": "No debug=True found"}

        return {"success": False, "message": "No auto-fix for this check"}

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get("security", {})
        scan_dirs = phase_cfg.get("scan_dirs", ["."])
        main_file = phase_cfg.get("main_file", "app.py")

        py_files = []
        for d in scan_dirs:
            target = project_root / d
            if target.is_dir():
                py_files.extend(target.glob("*.py"))
            elif target.is_file():
                py_files.append(target)

        # SQL injection
        sqli = []
        sqli_marked = 0
        for f in py_files:
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lines = src.splitlines()
            for i, line in enumerate(lines, 1):
                stripped = line.lstrip()
                if "execute(" in line and ("cursor.execute" in line or "conn.execute" in line or stripped.startswith(".execute(")):
                    ctx = "\n".join(lines[max(0, i - 3):min(len(lines), i + 3)])
                    if ('f"""' in ctx or "f'''" in ctx or 'f"' in ctx) and "{" in ctx and "?" not in ctx:
                        if "# TODO: parameterize" in line:
                            sqli_marked += 1
                        else:
                            sqli.append({"file": f.name, "line": i, "code": line.strip()[:80]})
        unique = {f"{x['file']}:{x['line']}": x for x in sqli}
        if not unique and sqli_marked == 0:
            report.add(CheckResult("sql_injection", CheckResult.PASS, "No f-string SQL"))
        elif not unique and sqli_marked > 0:
            report.add(CheckResult("sql_injection", CheckResult.PASS, f"SQL injection marked for fix ({sqli_marked} sites)"))
        else:
            report.add(CheckResult("sql_injection", CheckResult.WARN,
                                   f"{len(unique)} potential SQL injection points",
                                   details=list(unique.values())[:10], fixable=True,
                                   fix_desc="f-string SQL 사용 지점에 TODO 주석을 추가하고, 파라미터 바인딩(?) 전환을 안내합니다"))

        # Command injection
        cmd = []
        for f in py_files:
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(src.splitlines(), 1):
                if "subprocess" in line and "shell=True" in line:
                    cmd.append({"file": f.name, "line": i})
        if not cmd:
            report.add(CheckResult("command_injection", CheckResult.PASS, "No shell=True calls"))
        else:
            report.add(CheckResult("command_injection", CheckResult.FAIL, f"{len(cmd)} shell=True", details=cmd))

        # Path traversal — uses main_file from config
        app_py = project_root / main_file
        if app_py.exists():
            src = app_py.read_text(encoding="utf-8")
            if "sanitize_filename" in src:
                idx = src.find("def sanitize_filename")
                block = src[idx:idx + 500] if idx >= 0 else ""
                if ".." in block or "path" in block.lower():
                    report.add(CheckResult("path_traversal", CheckResult.PASS, "Path traversal protected"))
                else:
                    report.add(CheckResult("path_traversal", CheckResult.WARN, "sanitize_filename may lack .. filter", fixable=True,
                                           fix_desc="sanitize_filename()에 '..' 경로 제거 코드를 자동 삽입합니다"))
            else:
                report.add(CheckResult("path_traversal", CheckResult.WARN, "No sanitize_filename", fixable=True,
                                       fix_desc=f"경로 탈출 방지 sanitize_filename() 함수를 {main_file}에 자동 생성합니다"))

            # bare except
            bare = sum(1 for l in src.splitlines() if l.strip().startswith("except:"))
            if bare == 0:
                report.add(CheckResult("error_swallowing", CheckResult.PASS, "No bare except"))
            else:
                report.add(CheckResult("error_swallowing", CheckResult.WARN, f"{bare} bare except blocks", fixable=True,
                                       fix_desc="bare except: → except Exception: 으로 교체하여 에러 추적을 활성화합니다"))

            # Flask debug
            if "debug=True" in src or "DEBUG = True" in src:
                report.add(CheckResult("flask_debug", CheckResult.WARN, "DEBUG mode may be enabled", fixable=True,
                                       fix_desc=f"{main_file}의 debug=True를 debug=False로 변경합니다"))
            else:
                report.add(CheckResult("flask_debug", CheckResult.PASS, "DEBUG not hardcoded"))

            # CORS
            if "CORS" in src or "cors" in src:
                if 'origins="*"' in src or "origins='*'" in src:
                    report.add(CheckResult("cors", CheckResult.WARN, "CORS allows all origins", fixable=True,
                                           fix_desc="origins='*'를 localhost 전용으로 제한합니다"))
                else:
                    report.add(CheckResult("cors", CheckResult.PASS, "CORS configured"))
            else:
                report.add(CheckResult("cors", CheckResult.PASS, "No CORS (localhost only)"))

        # gitignore
        gi = project_root / ".gitignore"
        if gi.exists():
            if ".env" in gi.read_text(encoding="utf-8"):
                report.add(CheckResult("secrets", CheckResult.PASS, ".env in .gitignore"))
            else:
                report.add(CheckResult("secrets", CheckResult.FAIL, ".env NOT in .gitignore", fixable=True,
                                       fix_desc=".gitignore에 .env 항목을 추가하여 시크릿 유출을 방지합니다"))
        else:
            report.add(CheckResult("secrets", CheckResult.WARN, "No .gitignore", fixable=True,
                                   fix_desc=".env 포함 .gitignore 파일을 자동 생성합니다"))

        return report
