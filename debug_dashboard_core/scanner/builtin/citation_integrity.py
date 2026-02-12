"""Builtin: Citation Integrity checker — fingerprint dupes, missing fields, format validity.

Checks:
  - citation_dupes: duplicate fingerprints in citations table
  - required_fields: citations missing author/year/title
  - total_stats: citation count and format distribution

Applicable when: config has checks.citation_integrity.enabled = true
"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class CitationIntegrityChecker(BaseChecker):
    name = "citation_integrity"
    display_name = "CITATION"
    description = "Citation fingerprint deduplication, required field completeness, and format distribution."
    tooltip_why = "중복 인용은 참고문헌 목록을 오염시키고, 필수 필드 누락은 APA7/BibTeX 출력을 무효화합니다."
    tooltip_what = "fingerprint 중복, author/year/title 누락 비율, 인용 포맷(APA7/BibTeX/RIS) 분포를 검사합니다."
    tooltip_result = "PASS: 인용 정합성 양호 · WARN: 중복/누락 필드 존재 · FAIL: 테이블 누락"
    icon = "📚"
    color = "#6366f1"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
        db_path = project_root / db_path_str

        if not db_path.is_file():
            report.add(CheckResult("total_stats", CheckResult.SKIP,
                                   f"Database not found: {db_path_str}"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))
            tables = {row[0] for row in
                      conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            if "citations" not in tables:
                report.add(CheckResult("total_stats", CheckResult.SKIP,
                                       "citations table not found"))
                conn.close()
                return report

            cols = [row[1] for row in conn.execute("PRAGMA table_info(citations)").fetchall()]
            total = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]

            if total == 0:
                report.add(CheckResult("total_stats", CheckResult.SKIP,
                                       "No citations in database"))
                conn.close()
                return report

            # Check 1: Total stats
            report.add(CheckResult("total_stats", CheckResult.PASS,
                                   f"{total} citations in database"))

            # Check 2: Duplicate fingerprints
            if "fingerprint" in cols:
                dupes = conn.execute("""
                    SELECT fingerprint, COUNT(*) as cnt
                    FROM citations
                    WHERE fingerprint IS NOT NULL
                    GROUP BY fingerprint
                    HAVING cnt > 1
                """).fetchall()

                if dupes:
                    dupe_count = sum(r[1] - 1 for r in dupes)  # extra copies
                    report.add(CheckResult("citation_dupes", CheckResult.WARN,
                                           f"{len(dupes)} duplicate fingerprint(s) ({dupe_count} extra copies)",
                                           details=[{"fingerprint": r[0][:20], "count": r[1]} for r in dupes[:10]],
                                           fixable=True,
                                           fix_desc="중복 fingerprint의 여분 레코드를 삭제합니다"))
                else:
                    report.add(CheckResult("citation_dupes", CheckResult.PASS,
                                           "No duplicate fingerprints"))
            else:
                report.add(CheckResult("citation_dupes", CheckResult.SKIP,
                                       "No fingerprint column"))

            # Check 3: Required fields
            check_fields = []
            for f in ["author", "year", "title"]:
                if f in cols:
                    check_fields.append(f)

            if check_fields:
                missing_counts = {}
                for f in check_fields:
                    cnt = conn.execute(f"""
                        SELECT COUNT(*) FROM citations
                        WHERE {f} IS NULL OR TRIM({f}) = ''
                    """).fetchone()[0]
                    if cnt > 0:
                        missing_counts[f] = cnt

                if missing_counts:
                    details = {f: f"{c}/{total} ({c/total*100:.0f}%)" for f, c in missing_counts.items()}
                    worst = max(missing_counts.values())
                    worst_pct = (worst / total) * 100
                    status = CheckResult.WARN if worst_pct < 30 else CheckResult.WARN
                    report.add(CheckResult("required_fields", status,
                                           f"Missing fields: {', '.join(f'{k}({v})' for k,v in missing_counts.items())}",
                                           details=details))
                else:
                    report.add(CheckResult("required_fields", CheckResult.PASS,
                                           f"All required fields populated ({', '.join(check_fields)})"))
            else:
                report.add(CheckResult("required_fields", CheckResult.SKIP,
                                       "No author/year/title columns"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("total_stats", CheckResult.FAIL, f"DB error: {e}"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "citation_dupes":
            db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
            db_path = project_root / db_path_str

            if not db_path.is_file():
                return {"success": False, "message": "Database not found"}

            try:
                conn = sqlite3.connect(str(db_path))
                deleted = conn.execute("""
                    DELETE FROM citations
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid) FROM citations
                        GROUP BY fingerprint
                    ) AND fingerprint IS NOT NULL
                """).rowcount
                conn.commit()
                conn.close()
                return {"success": True, "message": f"Removed {deleted} duplicate citation(s)"}
            except Exception as e:
                return {"success": False, "message": f"Fix error: {e}"}

        return {"success": False, "message": "No auto-fix for this check"}
