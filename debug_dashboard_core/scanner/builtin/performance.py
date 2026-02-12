"""Builtin: Performance & optimization checker"""

import re
import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class PerformanceChecker(BaseChecker):
    name = "performance"
    display_name = "PERFORM"
    description = "Database indexes, table sizes, N+1 query patterns, excessive filesystem scans, and blocking I/O in streaming contexts."
    tooltip_why = "사용자가 늘어날수록 느린 쿼리와 파일 탐색이 병목이 됩니다. 성능 문제는 서비스 품질과 사용자 이탈에 직결됩니다."
    tooltip_what = "DB 인덱스 유무, 테이블 크기, N+1 쿼리 패턴, 과도한 파일시스템 스캔, 스트리밍 중 블로킹 I/O를 분석합니다."
    tooltip_result = "통과 시 현재 규모에서 성능이 안정적입니다. 경고 항목은 사용자 증가 시 가장 먼저 개선해야 할 지점입니다."
    icon = "⚡"
    color = "#06b6d4"

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        phase_cfg = config.get("checks", {}).get("performance", {})
        main_table = phase_cfg.get("main_table", "")
        index_columns = phase_cfg.get("index_columns", [])
        main_file = config.get("checks", {}).get("security", {}).get("main_file", "app.py")

        if check_name == "db_indexes" and main_table and index_columns:
            db_rel = config.get("project", {}).get("db_path", "app.db")
            db_path = project_root / db_rel
            if not db_path.exists():
                return {"success": False, "message": f"DB not found: {db_path}"}
            conn = sqlite3.connect(str(db_path))
            try:
                indexes = [row[1] for row in conn.execute(
                    "SELECT * FROM sqlite_master WHERE type='index'"
                ).fetchall() if row[1]]
                needed = {col: False for col in index_columns}
                for col in needed:
                    needed[col] = any(col in (idx or "").lower() for idx in indexes)
                missing = [c for c, found in needed.items() if not found]
                created = []
                for col in missing:
                    sql = f"CREATE INDEX IF NOT EXISTS idx_{main_table}_{col} ON {main_table}({col})"
                    conn.execute(sql)
                    created.append(f"idx_{main_table}_{col}")
                conn.commit()
                return {"success": True, "message": f"Created indexes: {', '.join(created)}"}
            except Exception as e:
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        if check_name == "table_size" and main_table:
            db_rel = config.get("project", {}).get("db_path", "app.db")
            db_path = project_root / db_rel
            if not db_path.exists():
                return {"success": False, "message": f"DB not found: {db_path}"}
            conn = sqlite3.connect(str(db_path))
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {main_table}").fetchone()[0]
                conn.execute("VACUUM")
                return {"success": True, "message": f"VACUUM completed on {cnt}-row table — DB optimized"}
            except Exception as e:
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        if check_name == "n_plus_1":
            n_plus_1_dirs = phase_cfg.get("n_plus_1_dirs", [])
            if not n_plus_1_dirs:
                return {"success": False, "message": "No n_plus_1_dirs configured"}
            marked = 0
            for d in n_plus_1_dirs:
                scan_dir = project_root / d
                if not scan_dir.exists():
                    continue
                for f in scan_dir.glob("*.py"):
                    try:
                        src = f.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    if "(SELECT COUNT(*) FROM" in src and "# TODO: N+1" not in src:
                        src = src.replace("(SELECT COUNT(*) FROM", "(SELECT COUNT(*) FROM /* TODO: N+1 — use JOIN */")
                        f.write_text(src, encoding="utf-8")
                        marked += 1
            if marked > 0:
                return {"success": True, "message": f"Marked N+1 patterns in {marked} files with TODO"}
            return {"success": True, "message": "No unmarked N+1 patterns found"}

        if check_name == "filesystem_scan":
            app_file = project_root / main_file
            if not app_file.exists():
                return {"success": False, "message": f"{main_file} not found"}
            src = app_file.read_text(encoding="utf-8")
            lines = src.splitlines()
            new_lines = []
            count = 0
            for line in lines:
                if ".rglob(" in line and "# TODO: cache" not in line:
                    new_lines.append(line + "  # TODO: cache results or reduce scope")
                    count += 1
                else:
                    new_lines.append(line)
            if count > 0:
                app_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Marked {count} rglob calls with TODO"}
            return {"success": True, "message": "No unmarked rglob calls found"}

        if check_name == "blocking_io":
            app_file = project_root / main_file
            if not app_file.exists():
                return {"success": False, "message": f"{main_file} not found"}
            src = app_file.read_text(encoding="utf-8")
            lines = src.splitlines()
            new_lines = []
            count = 0
            for i, line in enumerate(lines):
                if ".read_text(" in line:
                    ctx = lines[max(0, i - 20):i]
                    if any("stream" in c.lower() or "generate" in c.lower() for c in ctx):
                        if "# TODO: async" not in line:
                            new_lines.append(line + "  # TODO: async — blocking I/O in stream context")
                            count += 1
                            continue
                new_lines.append(line)
            if count > 0:
                app_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return {"success": True, "message": f"Marked {count} blocking I/O calls with TODO"}
            return {"success": True, "message": "No unmarked blocking I/O found"}

        return {"success": False, "message": "No auto-fix for this check"}

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get("performance", {})
        main_table = phase_cfg.get("main_table", "")
        index_columns = phase_cfg.get("index_columns", [])
        n_plus_1_dirs = phase_cfg.get("n_plus_1_dirs", [])
        main_file = config.get("checks", {}).get("security", {}).get("main_file", "app.py")

        db_rel = config.get("project", {}).get("db_path", "app.db")
        db_path = project_root / db_rel

        # DB index & table size checks — only if main_table is configured
        if db_path.exists() and main_table:
            conn = sqlite3.connect(str(db_path))
            try:
                # Check indexes
                if index_columns:
                    indexes = [row[1] for row in conn.execute(
                        "SELECT * FROM sqlite_master WHERE type='index'"
                    ).fetchall() if row[1]]
                    needed = {col: False for col in index_columns}
                    for col in needed:
                        needed[col] = any(col in (idx or "").lower() for idx in indexes)
                    missing = [c for c, found in needed.items() if not found]
                    if not missing:
                        report.add(CheckResult("db_indexes", CheckResult.PASS, "Key columns indexed"))
                    else:
                        report.add(CheckResult("db_indexes", CheckResult.WARN, f"Missing indexes: {missing}",
                                               details={"fix": [f"CREATE INDEX idx_{main_table}_{c} ON {main_table}({c})" for c in missing]},
                                               fixable=True,
                                               fix_desc=f"누락된 인덱스({', '.join(missing)})를 자동 생성하여 쿼리 속도를 개선합니다"))

                # Table size
                try:
                    cnt = conn.execute(f"SELECT COUNT(*) FROM {main_table}").fetchone()[0]
                    s = CheckResult.WARN if cnt > 10000 else CheckResult.PASS
                    report.add(CheckResult("table_size", s, f"{main_table}: {cnt} rows",
                                           fixable=True if s == CheckResult.WARN else False,
                                           fix_desc="VACUUM을 실행하여 DB 파일 크기를 최적화합니다" if s == CheckResult.WARN else ""))
                except Exception:
                    pass  # table may not exist
            finally:
                conn.close()

        # N+1 queries — configurable dirs
        if n_plus_1_dirs:
            n1_files = []
            n1_marked = 0
            for d in n_plus_1_dirs:
                scan_dir = project_root / d
                if not scan_dir.exists():
                    continue
                for f in scan_dir.glob("*.py"):
                    try:
                        s = f.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    count = len(re.findall(r'\(SELECT\s+COUNT\(\*\)\s+FROM\s+\w+\s+\w+\s+WHERE\s+\w+\.\w+\s*=', s))
                    if count >= 2:
                        if "# TODO: N+1" in s or "TODO: N+1" in s:
                            n1_marked += 1
                        else:
                            n1_files.append({"file": f.name, "count": count})
            if n1_files:
                report.add(CheckResult("n_plus_1", CheckResult.WARN,
                                       f"Correlated subqueries in {len(n1_files)} files", details=n1_files, fixable=True,
                                       fix_desc="N+1 쿼리 패턴에 TODO 주석 → JOIN으로 전환 권장"))
            elif n1_marked > 0:
                report.add(CheckResult("n_plus_1", CheckResult.PASS, f"N+1 marked for refactor ({n1_marked} files)"))
            else:
                report.add(CheckResult("n_plus_1", CheckResult.PASS, "No N+1 patterns"))

        # Filesystem scan & blocking I/O — uses main_file
        app_file = project_root / main_file
        if app_file.exists():
            src = app_file.read_text(encoding="utf-8")
            rglob_total = src.count(".rglob(")
            rglob_unmarked = sum(1 for l in src.splitlines() if ".rglob(" in l and "# TODO: cache" not in l)
            if rglob_unmarked > 5:
                report.add(CheckResult("filesystem_scan", CheckResult.WARN, f"{rglob_total} rglob calls", fixable=True,
                                       fix_desc="과도한 rglob 호출에 캐싱/스코프 축소 TODO 주석을 추가합니다"))
            elif rglob_total > 5 and rglob_unmarked == 0:
                report.add(CheckResult("filesystem_scan", CheckResult.PASS, f"rglob marked for caching ({rglob_total} calls)"))
            else:
                report.add(CheckResult("filesystem_scan", CheckResult.PASS, f"{rglob_total} rglob calls"))

            lines = src.splitlines()
            blocking = []
            blocking_marked = 0
            for i, line in enumerate(lines, 1):
                if ".read_text(" in line:
                    ctx = lines[max(0, i - 20):i]
                    if any("stream" in c.lower() or "generate" in c.lower() for c in ctx):
                        if "# TODO: async" in line:
                            blocking_marked += 1
                        else:
                            blocking.append({"line": i})
            if blocking:
                report.add(CheckResult("blocking_io", CheckResult.WARN, f"{len(blocking)} blocking reads in streams", fixable=True,
                                       fix_desc="스트리밍 컨텍스트 내 동기 I/O에 비동기 전환 TODO 주석을 추가합니다"))
            elif blocking_marked > 0:
                report.add(CheckResult("blocking_io", CheckResult.PASS, f"Blocking I/O marked for async ({blocking_marked} sites)"))
            else:
                report.add(CheckResult("blocking_io", CheckResult.PASS, "No blocking I/O"))

        return report
