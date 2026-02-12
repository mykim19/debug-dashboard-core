"""Project-specific: Database videos checker — content hash, status, orphan files, ontology"""

import hashlib
import sqlite3
from pathlib import Path

from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport


class DatabaseVideosChecker(BaseChecker):
    name = "database_videos"
    display_name = "DB·VIDEOS"
    description = "Content hash coverage, video status distribution, orphan file detection, and ontology graph statistics."
    tooltip_why = "영상 메타데이터와 지식 그래프가 데이터베이스에 저장됩니다. 해시 누락이나 고아 파일은 중복 탐지와 분석을 방해합니다."
    tooltip_what = "중복 탐지용 해시 누락, 영상 상태 분포(pending/failed/completed), 고아 파일(DB에 없는 다운로드), 온톨로지 규모를 점검합니다."
    tooltip_result = "통과 시 영상 데이터의 완전성이 보장됩니다. 경고 시 일부 영상 파이프라인에 문제가 있을 수 있습니다."
    icon = "🎬"
    color = "#a855f7"

    def _get_db(self, project_root, config):
        db_rel = config.get("project", {}).get("db_path", "scripts.db")
        return project_root / db_rel

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        db_path = self._get_db(project_root, config)
        if not db_path.exists():
            return {"success": False, "message": f"DB not found: {db_path}"}

        if check_name == "content_hash":
            conn = sqlite3.connect(str(db_path))
            try:
                rows = conn.execute(
                    "SELECT video_id, video_url FROM videos WHERE content_hash IS NULL OR content_hash = ''"
                ).fetchall()
                if not rows:
                    return {"success": True, "message": "No missing hashes found"}
                fixed = 0
                for vid, url in rows:
                    if url:
                        h = hashlib.sha256(url.strip().encode()).hexdigest()[:16]
                        conn.execute("UPDATE videos SET content_hash = ? WHERE video_id = ?", (h, vid))
                        fixed += 1
                conn.commit()
                return {"success": True, "message": f"Filled {fixed} content hashes from URLs"}
            except Exception as e:
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        if check_name == "status_dist":
            conn = sqlite3.connect(str(db_path))
            try:
                failed = conn.execute("SELECT COUNT(*) FROM videos WHERE status = 'failed'").fetchone()[0]
                if failed == 0:
                    return {"success": True, "message": "No failed videos to reset"}
                conn.execute("UPDATE videos SET status = 'pending' WHERE status = 'failed'")
                conn.commit()
                return {"success": True, "message": f"Reset {failed} failed videos to 'pending' for retry"}
            except Exception as e:
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        if check_name == "orphan_files":
            conn = sqlite3.connect(str(db_path))
            try:
                rows = conn.execute(
                    "SELECT video_id, script_txt_path FROM videos WHERE script_txt_path IS NOT NULL AND script_txt_path != ''"
                ).fetchall()
                downloads_dir = project_root / "downloads"
                cleared = 0
                for vid, path_str in rows:
                    p = Path(path_str)
                    if not p.is_absolute():
                        p = downloads_dir / path_str
                    if not p.exists():
                        conn.execute("UPDATE videos SET script_txt_path = NULL WHERE video_id = ?", (vid,))
                        cleared += 1
                conn.commit()
                return {"success": True, "message": f"Cleared {cleared} broken file references"}
            except Exception as e:
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        return {"success": False, "message": "No auto-fix for this check"}

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)

        db_path = self._get_db(project_root, config)
        if not db_path.exists():
            report.add(CheckResult("db_exists", CheckResult.SKIP, "DB not found — skipping video checks"))
            return report

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

            if "videos" not in tables:
                report.add(CheckResult("videos_table", CheckResult.SKIP, "No 'videos' table"))
                return report

            total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            null_hash = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE content_hash IS NULL OR content_hash = ''"
            ).fetchone()[0]
            if null_hash == 0:
                report.add(CheckResult("content_hash", CheckResult.PASS, f"All {total} have hash"))
            else:
                s = CheckResult.WARN if null_hash < total * 0.1 else CheckResult.FAIL
                report.add(CheckResult("content_hash", s, f"{null_hash}/{total} missing hash", fixable=True,
                                       fix_desc="video_url 기반 SHA256 해시를 자동 생성하여 중복 탐지를 활성화합니다"))

            status_dist = dict(conn.execute(
                "SELECT status, COUNT(*) FROM videos GROUP BY status"
            ).fetchall())
            failed = status_dist.get("failed", 0)
            s = CheckResult.WARN if failed > 0 else CheckResult.PASS
            report.add(CheckResult("status_dist", s, f"Distribution: {status_dist}",
                                   details=status_dist,
                                   fixable=True if failed > 0 else False,
                                   fix_desc=f"실패한 {failed}개 영상을 'pending' 상태로 리셋하여 재처리합니다" if failed > 0 else ""))

            downloads_dir = project_root / "downloads"
            rows = conn.execute(
                "SELECT video_id, script_txt_path FROM videos WHERE script_txt_path IS NOT NULL AND script_txt_path != '' LIMIT 200"
            ).fetchall()
            orphan = 0
            for row in rows:
                p = Path(row[1])
                if not p.is_absolute():
                    p = downloads_dir / row[1]
                if not p.exists():
                    orphan += 1
            pct = (orphan / len(rows) * 100) if rows else 0
            if orphan == 0:
                report.add(CheckResult("orphan_files", CheckResult.PASS, f"Sampled {len(rows)}: all valid"))
            else:
                report.add(CheckResult("orphan_files", CheckResult.WARN,
                                       f"{orphan}/{len(rows)} sampled ({pct:.0f}%) missing",
                                       fixable=True,
                                       fix_desc="존재하지 않는 파일 경로 참조를 NULL로 정리합니다"))

            if "global_nodes" in tables:
                gn = conn.execute("SELECT COUNT(*) FROM global_nodes").fetchone()[0]
                ge = conn.execute("SELECT COUNT(*) FROM global_edges").fetchone()[0] if "global_edges" in tables else 0
                report.add(CheckResult("ontology_stats", CheckResult.PASS, f"{gn} nodes, {ge} edges"))

        finally:
            conn.close()

        return report
