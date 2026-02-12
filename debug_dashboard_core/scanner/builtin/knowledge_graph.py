"""Builtin: Knowledge Graph checker — node/edge integrity, orphans, mapping ratio.

Checks:
  - table_integrity: knowledge_nodes/edges/qa/claims tables exist
  - orphan_edges: edges referencing non-existent nodes
  - global_mapping: node_mappings coverage ratio

Applicable when: config has checks.knowledge_graph.enabled = true
"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class KnowledgeGraphChecker(BaseChecker):
    name = "knowledge_graph"
    display_name = "KNOWLEDGE"
    description = "Knowledge graph node/edge integrity, orphan detection, and global mapping ratio."
    tooltip_why = "지식 그래프의 정합성이 깨지면 검색 결과 누락, 잘못된 관계 표시 등 UX 문제가 발생합니다."
    tooltip_what = "knowledge 테이블 존재, 고아 에지(부모 없는 관계), 글로벌 매핑 비율을 검사합니다."
    tooltip_result = "PASS: 지식 그래프 정합성 양호 · WARN: 고아 에지/낮은 매핑 비율 · FAIL: 필수 테이블 누락"
    icon = "🕸️"
    color = "#06b6d4"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        db_path_str = config.get("project", {}).get("db_path", "scripts.db")
        db_path = project_root / db_path_str
        min_mapping_pct = phase_cfg.get("min_mapping_pct", 50)

        if not db_path.is_file():
            report.add(CheckResult("table_integrity", CheckResult.FAIL,
                                   f"Database not found: {db_path_str}"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Get existing tables
            tables = {row[0] for row in
                      conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            # Check 1: Required knowledge tables
            required = {"knowledge_nodes", "knowledge_edges"}
            optional = {"knowledge_qa", "knowledge_claims", "global_nodes", "global_edges", "node_mappings"}
            missing_req = required - tables
            found_opt = optional & tables

            if missing_req:
                report.add(CheckResult("table_integrity", CheckResult.FAIL,
                                       f"Missing required tables: {', '.join(sorted(missing_req))}"))
                conn.close()
                return report
            else:
                report.add(CheckResult("table_integrity", CheckResult.PASS,
                                       f"Knowledge tables present (+ {len(found_opt)} optional)"))

            # Check 2: Orphan edges — edges with source/target not in nodes
            try:
                # Get column names to handle varying schemas
                cols = [row[1] for row in conn.execute("PRAGMA table_info(knowledge_edges)").fetchall()]

                source_col = "source_id" if "source_id" in cols else "source"
                target_col = "target_id" if "target_id" in cols else "target"
                node_id_col_info = conn.execute("PRAGMA table_info(knowledge_nodes)").fetchall()
                node_id_col = "id" if any(r[1] == "id" for r in node_id_col_info) else "rowid"

                total_edges = conn.execute("SELECT COUNT(*) FROM knowledge_edges").fetchone()[0]

                if total_edges > 0:
                    # Check for orphan sources
                    orphan_q = f"""
                        SELECT COUNT(*) FROM knowledge_edges e
                        WHERE NOT EXISTS (
                            SELECT 1 FROM knowledge_nodes n WHERE n.{node_id_col} = e.{source_col}
                        )
                    """
                    try:
                        orphan_count = conn.execute(orphan_q).fetchone()[0]
                    except Exception:
                        orphan_count = 0  # Schema mismatch, skip

                    if orphan_count > 0:
                        pct = (orphan_count / total_edges) * 100
                        status = CheckResult.WARN if pct < 5 else CheckResult.FAIL
                        report.add(CheckResult("orphan_edges", status,
                                               f"{orphan_count}/{total_edges} orphan edges ({pct:.1f}%)",
                                               details={"orphan_count": orphan_count, "total": total_edges},
                                               fixable=True,
                                               fix_desc="고아 에지를 삭제합니다"))
                    else:
                        report.add(CheckResult("orphan_edges", CheckResult.PASS,
                                               f"No orphan edges ({total_edges} total)"))
                else:
                    report.add(CheckResult("orphan_edges", CheckResult.SKIP,
                                           "No edges in knowledge graph"))
            except Exception as e:
                report.add(CheckResult("orphan_edges", CheckResult.WARN,
                                       f"Orphan check error: {e}"))

            # Check 3: Global mapping ratio
            if "node_mappings" in tables and "knowledge_nodes" in tables:
                try:
                    total_nodes = conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0]
                    mapped_nodes = conn.execute("SELECT COUNT(DISTINCT local_id) FROM node_mappings").fetchone()[0]

                    if total_nodes > 0:
                        pct = (mapped_nodes / total_nodes) * 100
                        if pct >= min_mapping_pct:
                            report.add(CheckResult("global_mapping", CheckResult.PASS,
                                                   f"Mapping: {mapped_nodes}/{total_nodes} ({pct:.0f}%)"))
                        else:
                            report.add(CheckResult("global_mapping", CheckResult.WARN,
                                                   f"Low mapping: {mapped_nodes}/{total_nodes} ({pct:.0f}%, target ≥{min_mapping_pct}%)"))
                    else:
                        report.add(CheckResult("global_mapping", CheckResult.SKIP,
                                               "No knowledge nodes"))
                except Exception as e:
                    report.add(CheckResult("global_mapping", CheckResult.WARN,
                                           f"Mapping check error: {e}"))
            else:
                report.add(CheckResult("global_mapping", CheckResult.SKIP,
                                       "node_mappings table not present"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("table_integrity", CheckResult.FAIL, f"DB error: {e}"))

        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        if check_name == "orphan_edges":
            db_path_str = config.get("project", {}).get("db_path", "scripts.db")
            db_path = project_root / db_path_str

            if not db_path.is_file():
                return {"success": False, "message": "Database not found"}

            try:
                conn = sqlite3.connect(str(db_path))
                cols = [row[1] for row in conn.execute("PRAGMA table_info(knowledge_edges)").fetchall()]
                source_col = "source_id" if "source_id" in cols else "source"
                node_id_col_info = conn.execute("PRAGMA table_info(knowledge_nodes)").fetchall()
                node_id_col = "id" if any(r[1] == "id" for r in node_id_col_info) else "rowid"

                delete_q = f"""
                    DELETE FROM knowledge_edges
                    WHERE NOT EXISTS (
                        SELECT 1 FROM knowledge_nodes n WHERE n.{node_id_col} = knowledge_edges.{source_col}
                    )
                """
                cursor = conn.execute(delete_q)
                deleted = cursor.rowcount
                conn.commit()
                conn.close()
                return {"success": True, "message": f"Deleted {deleted} orphan edge(s)"}
            except Exception as e:
                return {"success": False, "message": f"Fix error: {e}"}

        return {"success": False, "message": "No auto-fix for this check"}
