"""Builtin: Ontology Sync checker — global/local consistency, synonym dupes.

Checks:
  - global_local_sync: global_nodes coverage of knowledge_nodes concepts
  - synonym_dupes: duplicate entries in concept_synonyms
  - concept_orphans: concepts with no edges (isolated nodes)

Applicable when: config has checks.ontology_sync.enabled = true
"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class OntologySyncChecker(BaseChecker):
    name = "ontology_sync"
    display_name = "ONTOLOGY"
    description = "Global-local ontology synchronization, synonym duplicates, and isolated concept detection."
    tooltip_why = "온톨로지 동기화 불일치는 검색 누락과 잘못된 개념 관계를 유발합니다."
    tooltip_what = "글로벌↔로컬 노드 동기화 비율, 동의어 중복, 고립된 개념(에지 없음)을 검사합니다."
    tooltip_result = "PASS: 온톨로지 정합성 양호 · WARN: 동기화율 낮음/중복 존재 · FAIL: 필수 테이블 누락"
    icon = "🔬"
    color = "#f43f5e"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        db_path_str = config.get("project", {}).get("db_path", "scripts.db")
        db_path = project_root / db_path_str

        if not db_path.is_file():
            report.add(CheckResult("global_local_sync", CheckResult.SKIP,
                                   f"Database not found: {db_path_str}"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))
            tables = {row[0] for row in
                      conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            # Check 1: Global ↔ Local sync
            if "global_nodes" in tables and "knowledge_nodes" in tables:
                try:
                    local_count = conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0]
                    global_count = conn.execute("SELECT COUNT(*) FROM global_nodes").fetchone()[0]

                    if local_count > 0 and global_count > 0:
                        ratio = global_count / local_count
                        if ratio > 0.5:
                            report.add(CheckResult("global_local_sync", CheckResult.PASS,
                                                   f"Global: {global_count} / Local: {local_count} ({ratio:.0%})"))
                        else:
                            report.add(CheckResult("global_local_sync", CheckResult.WARN,
                                                   f"Low global coverage: {global_count}/{local_count} ({ratio:.0%})"))
                    elif local_count > 0:
                        report.add(CheckResult("global_local_sync", CheckResult.WARN,
                                               f"No global nodes yet ({local_count} local nodes exist)"))
                    else:
                        report.add(CheckResult("global_local_sync", CheckResult.SKIP,
                                               "No knowledge nodes"))
                except Exception as e:
                    report.add(CheckResult("global_local_sync", CheckResult.WARN, f"Error: {e}"))
            else:
                missing = []
                if "global_nodes" not in tables:
                    missing.append("global_nodes")
                if "knowledge_nodes" not in tables:
                    missing.append("knowledge_nodes")
                report.add(CheckResult("global_local_sync", CheckResult.SKIP,
                                       f"Tables missing: {', '.join(missing)}"))

            # Check 2: Synonym duplicates
            if "concept_synonyms" in tables:
                try:
                    dupes = conn.execute("""
                        SELECT synonym, COUNT(*) as cnt
                        FROM concept_synonyms
                        GROUP BY LOWER(synonym)
                        HAVING cnt > 1
                        LIMIT 20
                    """).fetchall()

                    if dupes:
                        dupe_list = [{"synonym": r[0], "count": r[1]} for r in dupes]
                        report.add(CheckResult("synonym_dupes", CheckResult.WARN,
                                               f"{len(dupes)} duplicate synonym(s)",
                                               details=dupe_list[:10],
                                               fixable=True,
                                               fix_desc="중복 동의어를 정리합니다"))
                    else:
                        total = conn.execute("SELECT COUNT(*) FROM concept_synonyms").fetchone()[0]
                        report.add(CheckResult("synonym_dupes", CheckResult.PASS,
                                               f"No duplicate synonyms ({total} total)"))
                except Exception as e:
                    report.add(CheckResult("synonym_dupes", CheckResult.WARN, f"Error: {e}"))
            else:
                report.add(CheckResult("synonym_dupes", CheckResult.SKIP,
                                       "concept_synonyms table not present"))

            # Check 3: Isolated concepts (no edges)
            if "knowledge_nodes" in tables and "knowledge_edges" in tables:
                try:
                    cols = [row[1] for row in conn.execute("PRAGMA table_info(knowledge_edges)").fetchall()]
                    source_col = "source_id" if "source_id" in cols else "source"
                    target_col = "target_id" if "target_id" in cols else "target"
                    node_cols = [row[1] for row in conn.execute("PRAGMA table_info(knowledge_nodes)").fetchall()]
                    node_id_col = "id" if "id" in node_cols else "rowid"

                    total = conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0]
                    if total > 0:
                        isolated_q = f"""
                            SELECT COUNT(*) FROM knowledge_nodes n
                            WHERE NOT EXISTS (
                                SELECT 1 FROM knowledge_edges e
                                WHERE e.{source_col} = n.{node_id_col} OR e.{target_col} = n.{node_id_col}
                            )
                        """
                        try:
                            isolated = conn.execute(isolated_q).fetchone()[0]
                        except Exception:
                            isolated = 0

                        if isolated > 0:
                            pct = (isolated / total) * 100
                            status = CheckResult.WARN if pct < 30 else CheckResult.WARN
                            report.add(CheckResult("concept_orphans", status,
                                                   f"{isolated}/{total} isolated concepts ({pct:.0f}%)"))
                        else:
                            report.add(CheckResult("concept_orphans", CheckResult.PASS,
                                                   "All concepts have at least one edge"))
                    else:
                        report.add(CheckResult("concept_orphans", CheckResult.SKIP, "No nodes"))
                except Exception as e:
                    report.add(CheckResult("concept_orphans", CheckResult.WARN, f"Error: {e}"))
            else:
                report.add(CheckResult("concept_orphans", CheckResult.SKIP, "Required tables missing"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("global_local_sync", CheckResult.FAIL, f"DB error: {e}"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "synonym_dupes":
            db_path_str = config.get("project", {}).get("db_path", "scripts.db")
            db_path = project_root / db_path_str

            if not db_path.is_file():
                return {"success": False, "message": "Database not found"}

            try:
                conn = sqlite3.connect(str(db_path))
                # Keep lowest rowid for each synonym, delete duplicates
                deleted = conn.execute("""
                    DELETE FROM concept_synonyms
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid) FROM concept_synonyms
                        GROUP BY LOWER(synonym), concept_id
                    )
                """).rowcount
                conn.commit()
                conn.close()
                return {"success": True, "message": f"Removed {deleted} duplicate synonym(s)"}
            except Exception as e:
                return {"success": False, "message": f"Fix error: {e}"}

        return {"success": False, "message": "No auto-fix for this check"}
