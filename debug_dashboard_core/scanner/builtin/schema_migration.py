"""Builtin: Schema Migration checker — table count, missing columns, migration files.

Checks:
  - table_count: verify expected number of tables
  - column_check: specific tables have required columns
  - migration_files: migration scripts exist if configured

Applicable when: config has checks.schema_migration.enabled = true
"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class SchemaMigrationChecker(BaseChecker):
    name = "schema_migration"
    display_name = "DB SCHEMA"
    description = "Database table count, column presence, and migration file tracking."
    tooltip_why = "스키마 드리프트(예상과 다른 테이블 구조)는 런타임 에러와 데이터 손실을 유발합니다."
    tooltip_what = "테이블 수 확인, 필수 컬럼 존재 여부, migration 파일 존재를 검사합니다."
    tooltip_result = "PASS: 스키마 일관성 양호 · WARN: 컬럼 누락/migration 미비 · FAIL: 테이블 수 불일치"
    icon = "🗄️"
    color = "#78716c"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
        db_path = project_root / db_path_str
        expected_tables = phase_cfg.get("expected_table_count", 0)
        column_checks = phase_cfg.get("column_checks", {})
        # e.g.: {"golden_sentences": ["char_start", "match_type"], "documents": ["content_hash"]}
        migration_dir = phase_cfg.get("migration_dir", "migrations")

        if not db_path.is_file():
            report.add(CheckResult("table_count", CheckResult.SKIP,
                                   f"Database not found: {db_path_str}"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))

            # Get all tables
            all_tables = [row[0] for row in
                          conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                          if not row[0].startswith("sqlite_")]
            table_count = len(all_tables)

            # Check 1: Table count
            if expected_tables > 0:
                if table_count >= expected_tables:
                    report.add(CheckResult("table_count", CheckResult.PASS,
                                           f"{table_count} tables (expected ≥{expected_tables})"))
                elif table_count >= expected_tables * 0.8:
                    report.add(CheckResult("table_count", CheckResult.WARN,
                                           f"{table_count} tables (expected ≥{expected_tables})",
                                           details={"tables": sorted(all_tables)}))
                else:
                    report.add(CheckResult("table_count", CheckResult.FAIL,
                                           f"Only {table_count} tables (expected ≥{expected_tables})",
                                           details={"tables": sorted(all_tables)}))
            else:
                report.add(CheckResult("table_count", CheckResult.PASS,
                                       f"{table_count} tables in database"))

            # Check 2: Column checks
            if column_checks:
                missing_cols = []
                checked = 0
                for table_name, required_cols in column_checks.items():
                    if table_name not in all_tables:
                        missing_cols.append({"table": table_name, "issue": "table not found"})
                        continue

                    existing_cols = {row[1] for row in
                                     conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()}
                    for col in required_cols:
                        checked += 1
                        if col not in existing_cols:
                            missing_cols.append({"table": table_name, "column": col})

                if missing_cols:
                    report.add(CheckResult("column_check", CheckResult.WARN,
                                           f"{len(missing_cols)} missing column(s) across checked tables",
                                           details=missing_cols[:15]))
                else:
                    report.add(CheckResult("column_check", CheckResult.PASS,
                                           f"All {checked} required columns present"))
            else:
                report.add(CheckResult("column_check", CheckResult.SKIP,
                                       "No column_checks configured"))

            # Check 3: Migration files
            mig_path = project_root / migration_dir
            if mig_path.is_dir():
                mig_files = list(mig_path.glob("*.py")) + list(mig_path.glob("*.sql"))
                if mig_files:
                    report.add(CheckResult("migration_files", CheckResult.PASS,
                                           f"{len(mig_files)} migration file(s) in {migration_dir}/"))
                else:
                    report.add(CheckResult("migration_files", CheckResult.WARN,
                                           f"{migration_dir}/ exists but no migration files"))
            else:
                # Check if there's a migrations directory anywhere
                alt_paths = ["db/migrations", "alembic/versions", "database/migrations"]
                found = None
                for alt in alt_paths:
                    if (project_root / alt).is_dir():
                        found = alt
                        break
                if found:
                    mig_files = list((project_root / found).rglob("*.py"))
                    report.add(CheckResult("migration_files", CheckResult.PASS,
                                           f"{len(mig_files)} migration files in {found}/"))
                else:
                    report.add(CheckResult("migration_files", CheckResult.SKIP,
                                           "No migration directory found"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("table_count", CheckResult.FAIL, f"DB error: {e}"))

        return report
