"""Builtin: Database integrity checker — generic (integrity, tables, FK only)"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class DatabaseChecker(BaseChecker):
    name = "database"
    display_name = "DATABASE"
    description = "SQLite integrity, required/optional table presence, and foreign key violations."
    tooltip_why = "데이터베이스 무결성이 깨지면 서비스의 데이터 신뢰성이 보장되지 않습니다."
    tooltip_what = "DB 구조 무결성(PRAGMA integrity_check), 필수/선택 테이블 존재 여부, 외래키 관계 검증을 점검합니다."
    tooltip_result = "통과 시 데이터의 신뢰성이 보장됩니다. 경고 시 일부 데이터 관계가 깨져 있어 분석 정확도에 영향을 줄 수 있습니다."
    icon = "🗄"
    color = "#8b5cf6"

    def _get_db(self, project_root, config):
        db_rel = config.get("project", {}).get("db_path", "app.db")
        return project_root / db_rel

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        db_path = self._get_db(project_root, config)
        if not db_path.exists():
            return {"success": False, "message": f"DB not found: {db_path}"}

        if check_name == "fk_check":
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("PRAGMA foreign_keys = ON")
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if not violations:
                    return {"success": True, "message": "No FK violations found"}
                tables_affected = {}
                for v in violations:
                    tbl = v[0] if hasattr(v, '__getitem__') else str(v)
                    tables_affected[tbl] = tables_affected.get(tbl, 0) + 1
                deleted = 0
                for tbl, cnt in tables_affected.items():
                    try:
                        fk_list = conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall()
                        for fk in fk_list:
                            parent = fk[2]
                            from_col = fk[3]
                            to_col = fk[4]
                            sql = f"DELETE FROM [{tbl}] WHERE [{from_col}] NOT IN (SELECT [{to_col}] FROM [{parent}])"
                            cur = conn.execute(sql)
                            deleted += cur.rowcount
                    except Exception:
                        continue
                conn.commit()
                return {"success": True, "message": f"Removed {deleted} orphan rows from {len(tables_affected)} tables"}
            except Exception as e:
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        return {"success": False, "message": "No auto-fix for this check"}

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get("database", {})

        db_path = self._get_db(project_root, config)

        if not db_path.exists():
            report.add(CheckResult("db_exists", CheckResult.FAIL, f"Not found: {db_path}"))
            return report

        sz = db_path.stat().st_size
        report.add(CheckResult("db_size", CheckResult.PASS, f"{sz / 1024 / 1024:.1f}MB"))

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Integrity check
            r = conn.execute("PRAGMA integrity_check").fetchone()
            if r[0] == "ok":
                report.add(CheckResult("integrity", CheckResult.PASS, "PRAGMA integrity_check: ok"))
            else:
                report.add(CheckResult("integrity", CheckResult.FAIL, f"Integrity: {r[0]}"))

            # Table presence
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

            req = phase_cfg.get("required_tables", [])
            if req:
                missing = [t for t in req if t not in tables]
                if not missing:
                    report.add(CheckResult("required_tables", CheckResult.PASS, f"All {len(req)} present"))
                else:
                    report.add(CheckResult("required_tables", CheckResult.FAIL, f"Missing: {missing}"))

            opt = phase_cfg.get("optional_tables", [])
            if opt:
                missing_opt = [t for t in opt if t not in tables]
                if not missing_opt:
                    report.add(CheckResult("optional_tables", CheckResult.PASS, f"All {len(opt)} present"))
                else:
                    report.add(CheckResult("optional_tables", CheckResult.WARN, f"Missing: {missing_opt}"))

            # Foreign key check
            conn.execute("PRAGMA foreign_keys = ON")
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            if not fk:
                report.add(CheckResult("fk_check", CheckResult.PASS, "No FK violations"))
            else:
                report.add(CheckResult("fk_check", CheckResult.WARN, f"{len(fk)} FK violations",
                                       details=[dict(row) if hasattr(row, 'keys') else list(row) for row in fk[:5]],
                                       fixable=True,
                                       fix_desc="외래키 위반 행을 자동 삭제하여 참조 무결성을 복원합니다"))

        finally:
            conn.close()

        return report
