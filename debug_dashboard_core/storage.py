"""
Scan history storage — SQLite database for tracking scan results over time.

Tables:
  - scan_history: per-workspace scan results (existing)
  - agent_events: agent loop event log (agent mode)
  - llm_analyses: LLM deep analysis results (Tier 2)
  - agent_insights: cross-checker insights (agent reasoning)

Note: DB_PATH must be set via configure() before use.
      init_db() is NOT called at module load — call it explicitly from create_app().
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict


# Default DB path (can be overridden via configure())
DB_PATH: Path = Path(__file__).parent / "debug_dashboard.db"


def configure(db_path: Path):
    """Override the default DB path. Call before init_db()."""
    global DB_PATH
    DB_PATH = Path(db_path)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if not exist. Must be called explicitly from create_app()."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            project_name TEXT NOT NULL,
            overall_status TEXT NOT NULL,
            total_pass INTEGER DEFAULT 0,
            total_warn INTEGER DEFAULT 0,
            total_fail INTEGER DEFAULT 0,
            health_pct REAL DEFAULT 0,
            phases_json TEXT,
            duration_ms INTEGER DEFAULT 0
        )
    """)

    # ── Agent tables ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            data_json TEXT,
            workspace_id TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            checker_name TEXT NOT NULL,
            model_used TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            analysis_text TEXT,
            root_causes_json TEXT,
            fix_suggestions_json TEXT,
            evidence_json TEXT,
            workspace_id TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            insight_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            checkers_json TEXT,
            workspace_id TEXT DEFAULT ''
        )
    """)

    conn.commit()
    conn.close()


def save_scan(project_name: str, overall_status: str, total_pass: int,
              total_warn: int, total_fail: int, health_pct: float,
              phases: list, duration_ms: int):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO scan_history
        (timestamp, project_name, overall_status, total_pass, total_warn, total_fail, health_pct, phases_json, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        project_name,
        overall_status,
        total_pass, total_warn, total_fail,
        health_pct,
        json.dumps(phases, ensure_ascii=False),
        duration_ms,
    ))
    conn.commit()
    conn.close()


def get_history(limit: int = 30, project_name: str = None) -> List[dict]:
    """Get scan history, optionally filtered by project_name (workspace-scoped)."""
    conn = _get_conn()
    if project_name:
        rows = conn.execute(
            "SELECT * FROM scan_history WHERE project_name = ? ORDER BY id DESC LIMIT ?",
            (project_name, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM scan_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_latest(project_name: str = None) -> Optional[dict]:
    """Get latest scan, optionally filtered by project_name (workspace-scoped)."""
    conn = _get_conn()
    if project_name:
        row = conn.execute(
            "SELECT * FROM scan_history WHERE project_name = ? ORDER BY id DESC LIMIT 1",
            (project_name,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM scan_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
    conn.close()
    if row:
        result = dict(row)
        result["phases"] = json.loads(result.get("phases_json", "[]"))
        return result
    return None


# ── Agent event storage ──────────────────────────────────

def save_agent_event(event_type: str, source: str, data_json: str,
                     workspace_id: str = ""):
    """Save an agent event to the log."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO agent_events (timestamp, event_type, source, data_json, workspace_id)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), event_type, source, data_json, workspace_id))
    conn.commit()
    conn.close()


def get_agent_events(limit: int = 100, workspace_id: str = "",
                     since_id: int = 0) -> List[dict]:
    """Get recent agent events. Supports SSE reconnect via since_id."""
    conn = _get_conn()
    if workspace_id and since_id:
        rows = conn.execute(
            "SELECT * FROM agent_events WHERE workspace_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
            (workspace_id, since_id, limit)
        ).fetchall()
    elif workspace_id:
        rows = conn.execute(
            "SELECT * FROM agent_events WHERE workspace_id = ? ORDER BY id DESC LIMIT ?",
            (workspace_id, limit)
        ).fetchall()
    elif since_id:
        rows = conn.execute(
            "SELECT * FROM agent_events WHERE id > ? ORDER BY id DESC LIMIT ?",
            (since_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM agent_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_llm_analysis(checker_name: str, model: str, prompt_tokens: int,
                      completion_tokens: int, cost_usd: float,
                      analysis: str, root_causes: list, fix_suggestions: list,
                      evidence: dict = None, workspace_id: str = ""):
    """Save an LLM analysis result."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO llm_analyses
        (timestamp, checker_name, model_used, prompt_tokens, completion_tokens,
         cost_usd, analysis_text, root_causes_json, fix_suggestions_json,
         evidence_json, workspace_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(), checker_name, model,
        prompt_tokens, completion_tokens, cost_usd,
        analysis, json.dumps(root_causes, ensure_ascii=False),
        json.dumps(fix_suggestions, ensure_ascii=False),
        json.dumps(evidence or {}, ensure_ascii=False),
        workspace_id,
    ))
    conn.commit()
    conn.close()


def get_llm_analyses(limit: int = 20, workspace_id: str = "") -> List[dict]:
    """Get LLM analysis history."""
    conn = _get_conn()
    if workspace_id:
        rows = conn.execute(
            "SELECT * FROM llm_analyses WHERE workspace_id = ? ORDER BY id DESC LIMIT ?",
            (workspace_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM llm_analyses ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_agent_insight(insight_type: str, severity: str, message: str,
                       checkers: list, workspace_id: str = ""):
    """Save a cross-checker insight."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO agent_insights
        (timestamp, insight_type, severity, message, checkers_json, workspace_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), insight_type, severity, message,
          json.dumps(checkers, ensure_ascii=False), workspace_id))
    conn.commit()
    conn.close()


def purge_old_agent_data(event_max_rows: int = 10000, event_max_days: int = 7,
                         analysis_max_days: int = 90) -> dict:
    """GPT Risk #4: Retention policy — purge old agent data.

    Call periodically (e.g., on agent start or daily).
    Returns dict with deletion counts (GPT Review #6 UI: purge notification).
    """
    conn = _get_conn()
    total_deleted = 0
    # Purge agent_events by row count
    cur = conn.execute("""
        DELETE FROM agent_events WHERE id NOT IN (
            SELECT id FROM agent_events ORDER BY id DESC LIMIT ?
        )
    """, (event_max_rows,))
    events_by_rows = cur.rowcount
    total_deleted += events_by_rows
    # Purge agent_events by age
    cur = conn.execute("""
        DELETE FROM agent_events
        WHERE timestamp < datetime('now', '-' || ? || ' days')
    """, (event_max_days,))
    events_by_age = cur.rowcount
    total_deleted += events_by_age
    # Purge old analyses
    cur = conn.execute("""
        DELETE FROM llm_analyses
        WHERE timestamp < datetime('now', '-' || ? || ' days')
    """, (analysis_max_days,))
    analyses_deleted = cur.rowcount
    total_deleted += analyses_deleted
    # Purge old insights (same as events)
    cur = conn.execute("""
        DELETE FROM agent_insights
        WHERE timestamp < datetime('now', '-' || ? || ' days')
    """, (event_max_days,))
    insights_deleted = cur.rowcount
    total_deleted += insights_deleted
    conn.commit()
    conn.close()
    return {
        "total_deleted": total_deleted,
        "events_deleted": events_by_rows + events_by_age,
        "analyses_deleted": analyses_deleted,
        "insights_deleted": insights_deleted,
    }


# NOTE: init_db() removed from module load — must be called from create_app()
