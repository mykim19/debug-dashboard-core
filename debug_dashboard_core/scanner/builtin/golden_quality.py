"""Builtin: Golden Sentence Quality checker — match type distribution, provenance.

Checks:
  - match_distribution: EXACT/FUZZY/NOT_FOUND ratio
  - provenance_coverage: golden sentences with char_start/char_end filled
  - empty_sentences: blank or very short golden sentences

Applicable when: config has checks.golden_quality.enabled = true
"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class GoldenQualityChecker(BaseChecker):
    name = "golden_quality"
    display_name = "GOLDEN QA"
    description = "Golden sentence match type distribution, provenance coverage, and quality metrics."
    tooltip_why = "골든문장의 매칭 품질이 낮으면 인용 신뢰도와 증거 기반 분석의 정확도가 떨어집니다."
    tooltip_what = "match_type 분포(EXACT/FUZZY/NOT_FOUND), 위치정보(provenance) 비율, 빈 문장을 검사합니다."
    tooltip_result = "PASS: 매칭 품질 양호(EXACT ≥70%) · WARN: FUZZY/NOT_FOUND 비율 높음 · FAIL: 데이터 부재"
    icon = "✨"
    color = "#f59e0b"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
        db_path = project_root / db_path_str
        exact_threshold = phase_cfg.get("exact_min_pct", 70)  # EXACT ≥70% = PASS

        if not db_path.is_file():
            report.add(CheckResult("match_distribution", CheckResult.SKIP,
                                   f"Database not found: {db_path_str}"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))
            tables = {row[0] for row in
                      conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            if "golden_sentences" not in tables:
                report.add(CheckResult("match_distribution", CheckResult.SKIP,
                                       "golden_sentences table not found"))
                conn.close()
                return report

            cols = [row[1] for row in conn.execute("PRAGMA table_info(golden_sentences)").fetchall()]
            total = conn.execute("SELECT COUNT(*) FROM golden_sentences").fetchone()[0]

            if total == 0:
                report.add(CheckResult("match_distribution", CheckResult.SKIP,
                                       "No golden sentences"))
                conn.close()
                return report

            # Check 1: Match type distribution
            if "match_type" in cols:
                rows = conn.execute("""
                    SELECT COALESCE(match_type, 'NULL') as mt, COUNT(*) as cnt
                    FROM golden_sentences
                    GROUP BY mt
                """).fetchall()

                dist = {r[0]: r[1] for r in rows}
                exact_count = dist.get("exact", 0) + dist.get("EXACT", 0)
                fuzzy_count = sum(v for k, v in dist.items()
                                  if k.upper() in ("FUZZY", "FUZZY_HIGH", "FUZZY_LOW"))
                not_found = dist.get("NOT_FOUND", 0) + dist.get("not_found", 0) + dist.get("failed", 0)
                null_count = dist.get("NULL", 0) + dist.get("pending", 0)

                exact_pct = (exact_count / total) * 100 if total > 0 else 0

                details = {
                    "total": total,
                    "exact": exact_count,
                    "fuzzy": fuzzy_count,
                    "not_found": not_found,
                    "null_pending": null_count,
                }

                if exact_pct >= exact_threshold:
                    report.add(CheckResult("match_distribution", CheckResult.PASS,
                                           f"EXACT: {exact_pct:.0f}% ({exact_count}/{total})",
                                           details=details))
                elif exact_pct >= exact_threshold * 0.5:
                    report.add(CheckResult("match_distribution", CheckResult.WARN,
                                           f"EXACT: {exact_pct:.0f}% (target ≥{exact_threshold}%)",
                                           details=details))
                else:
                    report.add(CheckResult("match_distribution", CheckResult.WARN,
                                           f"Low EXACT: {exact_pct:.0f}% — review matching logic",
                                           details=details))
            else:
                report.add(CheckResult("match_distribution", CheckResult.SKIP,
                                       "match_type column not present"))

            # Check 2: Provenance coverage (char_start/char_end)
            if "char_start" in cols:
                with_loc = conn.execute(
                    "SELECT COUNT(*) FROM golden_sentences WHERE char_start IS NOT NULL"
                ).fetchone()[0]
                pct = (with_loc / total) * 100
                if pct >= 80:
                    report.add(CheckResult("provenance_coverage", CheckResult.PASS,
                                           f"Provenance: {with_loc}/{total} ({pct:.0f}%)"))
                elif pct >= 40:
                    report.add(CheckResult("provenance_coverage", CheckResult.WARN,
                                           f"Partial provenance: {with_loc}/{total} ({pct:.0f}%)"))
                else:
                    report.add(CheckResult("provenance_coverage", CheckResult.WARN,
                                           f"Low provenance: {with_loc}/{total} ({pct:.0f}%)"))
            else:
                report.add(CheckResult("provenance_coverage", CheckResult.SKIP,
                                       "char_start column not present"))

            # Check 3: Empty/very short sentences
            sentence_col = "sentence" if "sentence" in cols else "text" if "text" in cols else None
            if sentence_col:
                empty = conn.execute(f"""
                    SELECT COUNT(*) FROM golden_sentences
                    WHERE {sentence_col} IS NULL OR LENGTH(TRIM({sentence_col})) < 5
                """).fetchone()[0]

                if empty > 0:
                    pct = (empty / total) * 100
                    report.add(CheckResult("empty_sentences", CheckResult.WARN,
                                           f"{empty}/{total} empty/very short sentences ({pct:.0f}%)",
                                           fixable=True,
                                           fix_desc="5자 미만의 빈 문장 레코드를 삭제합니다"))
                else:
                    report.add(CheckResult("empty_sentences", CheckResult.PASS,
                                           f"All {total} sentences have content"))
            else:
                report.add(CheckResult("empty_sentences", CheckResult.SKIP,
                                       "No sentence column found"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("match_distribution", CheckResult.FAIL, f"DB error: {e}"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "empty_sentences":
            db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
            db_path = project_root / db_path_str

            if not db_path.is_file():
                return {"success": False, "message": "Database not found"}

            try:
                conn = sqlite3.connect(str(db_path))
                cols = [row[1] for row in conn.execute("PRAGMA table_info(golden_sentences)").fetchall()]
                sentence_col = "sentence" if "sentence" in cols else "text" if "text" in cols else None

                if sentence_col:
                    deleted = conn.execute(f"""
                        DELETE FROM golden_sentences
                        WHERE {sentence_col} IS NULL OR LENGTH(TRIM({sentence_col})) < 5
                    """).rowcount
                    conn.commit()
                    conn.close()
                    return {"success": True, "message": f"Deleted {deleted} empty sentence(s)"}

                conn.close()
                return {"success": False, "message": "No sentence column found"}
            except Exception as e:
                return {"success": False, "message": f"Fix error: {e}"}

        return {"success": False, "message": "No auto-fix for this check"}
