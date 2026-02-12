"""Builtin: Search Index checker — FTS5 integrity, retrieval cache, index freshness.

Checks:
  - fts_integrity: FTS5 virtual table integrity check
  - cache_size: retrieval_cache / analysis_cache bloat detection
  - index_freshness: check if index is stale relative to documents

Applicable when: config has checks.search_index.enabled = true
"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class SearchIndexChecker(BaseChecker):
    name = "search_index"
    display_name = "SEARCH IDX"
    description = "FTS5 index integrity, retrieval cache size, and index freshness."
    tooltip_why = "검색 인덱스 손상이나 캐시 비대화는 검색 속도 저하와 결과 부정확을 유발합니다."
    tooltip_what = "FTS5 integrity_check, 캐시 테이블 크기, 인덱스 갱신 시점을 검사합니다."
    tooltip_result = "PASS: 인덱스 정상 · WARN: 캐시 비대/인덱스 오래됨 · FAIL: FTS 인덱스 손상"
    icon = "🔎"
    color = "#14b8a6"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
        db_path = project_root / db_path_str
        cache_warn_rows = phase_cfg.get("cache_warn_rows", 10000)
        fts_table = phase_cfg.get("fts_table", "unified_search_fts")

        if not db_path.is_file():
            report.add(CheckResult("fts_integrity", CheckResult.SKIP,
                                   f"Database not found: {db_path_str}"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))
            tables = {row[0] for row in
                      conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            # Check 1: FTS5 integrity
            if fts_table in tables:
                try:
                    result = conn.execute(
                        f"INSERT INTO {fts_table}({fts_table}) VALUES('integrity-check')"
                    )
                    report.add(CheckResult("fts_integrity", CheckResult.PASS,
                                           f"{fts_table} integrity check passed"))
                except Exception as e:
                    err = str(e)
                    if "integrity-check" in err.lower() or "no such" in err.lower():
                        # Not an FTS5 table or different interface
                        report.add(CheckResult("fts_integrity", CheckResult.SKIP,
                                               f"Cannot run integrity check: {err[:80]}"))
                    else:
                        report.add(CheckResult("fts_integrity", CheckResult.FAIL,
                                               f"FTS integrity error: {err[:100]}",
                                               fixable=True,
                                               fix_desc="FTS 인덱스를 재구축합니다"))
            else:
                # Look for any FTS table
                fts_tables = [t for t in tables if "fts" in t.lower() or "search" in t.lower()]
                if fts_tables:
                    report.add(CheckResult("fts_integrity", CheckResult.PASS,
                                           f"Search tables found: {', '.join(fts_tables[:5])}"))
                else:
                    report.add(CheckResult("fts_integrity", CheckResult.SKIP,
                                           "No FTS tables found"))

            # Check 2: Cache sizes
            cache_tables = [t for t in tables if "cache" in t.lower()]
            if cache_tables:
                cache_info = []
                total_rows = 0
                for ct in cache_tables:
                    try:
                        cnt = conn.execute(f"SELECT COUNT(*) FROM [{ct}]").fetchone()[0]
                        cache_info.append({"table": ct, "rows": cnt})
                        total_rows += cnt
                    except Exception:
                        continue

                if total_rows > cache_warn_rows:
                    report.add(CheckResult("cache_size", CheckResult.WARN,
                                           f"Cache tables: {total_rows} total rows (threshold: {cache_warn_rows})",
                                           details=cache_info,
                                           fixable=True,
                                           fix_desc="오래된 캐시 레코드를 정리합니다"))
                else:
                    report.add(CheckResult("cache_size", CheckResult.PASS,
                                           f"Cache: {total_rows} rows across {len(cache_tables)} table(s)"))
            else:
                report.add(CheckResult("cache_size", CheckResult.SKIP,
                                       "No cache tables found"))

            # Check 3: Index freshness (if rag_index_status or similar exists)
            status_tables = [t for t in tables if "index_status" in t.lower()]
            if status_tables:
                st = status_tables[0]
                try:
                    cols = [row[1] for row in conn.execute(f"PRAGMA table_info([{st}])").fetchall()]
                    status_col = None
                    for candidate in ["status", "state", "indexed"]:
                        if candidate in cols:
                            status_col = candidate
                            break

                    if status_col:
                        total = conn.execute(f"SELECT COUNT(*) FROM [{st}]").fetchone()[0]
                        pending = conn.execute(
                            f"SELECT COUNT(*) FROM [{st}] WHERE {status_col} = 'pending' OR {status_col} = 0"
                        ).fetchone()[0]

                        if total > 0 and pending > 0:
                            pct = (pending / total) * 100
                            if pct > 20:
                                report.add(CheckResult("index_freshness", CheckResult.WARN,
                                                       f"{pending}/{total} items pending indexing ({pct:.0f}%)"))
                            else:
                                report.add(CheckResult("index_freshness", CheckResult.PASS,
                                                       f"Index mostly fresh ({pending} pending / {total} total)"))
                        elif total > 0:
                            report.add(CheckResult("index_freshness", CheckResult.PASS,
                                                   f"All {total} items indexed"))
                        else:
                            report.add(CheckResult("index_freshness", CheckResult.SKIP,
                                                   "Index status table empty"))
                    else:
                        report.add(CheckResult("index_freshness", CheckResult.SKIP,
                                               f"No status column in {st}"))
                except Exception as e:
                    report.add(CheckResult("index_freshness", CheckResult.WARN, f"Error: {e}"))
            else:
                report.add(CheckResult("index_freshness", CheckResult.SKIP,
                                       "No index status table"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("fts_integrity", CheckResult.FAIL, f"DB error: {e}"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "fts_integrity":
            db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
            db_path = project_root / db_path_str
            phase_cfg = config.get("checks", {}).get(self.name, {})
            fts_table = phase_cfg.get("fts_table", "unified_search_fts")

            if not db_path.is_file():
                return {"success": False, "message": "Database not found"}

            try:
                conn = sqlite3.connect(str(db_path))
                conn.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES('rebuild')")
                conn.commit()
                conn.close()
                return {"success": True, "message": f"FTS index '{fts_table}' rebuilt"}
            except Exception as e:
                return {"success": False, "message": f"Rebuild error: {e}"}

        if check_name == "cache_size":
            db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
            db_path = project_root / db_path_str

            if not db_path.is_file():
                return {"success": False, "message": "Database not found"}

            try:
                conn = sqlite3.connect(str(db_path))
                tables = {row[0] for row in
                          conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                cache_tables = [t for t in tables if "cache" in t.lower()]

                total_deleted = 0
                for ct in cache_tables:
                    try:
                        cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{ct}])").fetchall()]
                        if "created_at" in cols:
                            deleted = conn.execute(f"""
                                DELETE FROM [{ct}]
                                WHERE created_at < datetime('now', '-7 day')
                            """).rowcount
                        else:
                            # Keep latest 1000 rows
                            deleted = conn.execute(f"""
                                DELETE FROM [{ct}]
                                WHERE rowid NOT IN (
                                    SELECT rowid FROM [{ct}] ORDER BY rowid DESC LIMIT 1000
                                )
                            """).rowcount
                        total_deleted += deleted
                    except Exception:
                        continue

                conn.commit()
                conn.close()
                return {"success": True, "message": f"Cleaned {total_deleted} old cache row(s)"}
            except Exception as e:
                return {"success": False, "message": f"Fix error: {e}"}

        return {"success": False, "message": "No auto-fix for this check"}
