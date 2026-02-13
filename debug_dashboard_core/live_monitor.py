"""Live Monitor — connects Debug Dashboard to the main service for real-time agent observation.

Two data channels:
  1. MainServiceDBReader: reads scripts.db (read-only) for session history + budget
  2. SSEProxyClient: subscribes to main service SSE for live events (Phase 4)

Config-driven via defaults.yaml -> monitor section.
Zero overhead when monitor.enabled: false.
"""

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue, Full
from typing import Any, Dict, List, Optional

logger = logging.getLogger("monitor")


# ──────────────────────────────────────────────────────────────
# MainServiceDBReader — read-only access to scripts.db
# ──────────────────────────────────────────────────────────────

class MainServiceDBReader:
    """Read-only access to the main service's scripts.db.

    Uses URI mode=ro for OS-level read-only guarantee.
    Per-call connection pattern: open -> query -> close (thread-safe).

    Primary data source: budget_history (6000+ session records)
    Secondary: agent_sessions + tool_invocations (per-session details)

    LLM-only filter: Only sessions with actual LLM usage (cost > 0 OR total_tokens > 0)
    are included in listings and statistics. Non-LLM operations (e.g. document indexing)
    that happen to be logged in budget_history are excluded.
    """

    # Filter condition to include only sessions where LLM was actually used.
    # Sessions with cost=0 AND total_tokens=0 are non-LLM operations
    # (e.g. doc indexing, placeholder rows, scaffold test entries).
    _LLM_FILTER = "(cost > 0 OR total_tokens > 0)"

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self._tables_verified = False

    @property
    def is_available(self) -> bool:
        """Check if DB file exists and is readable."""
        p = Path(self.db_path)
        return p.exists() and p.is_file()

    def _get_conn(self) -> sqlite3.Connection:
        """Open a read-only connection. Caller must close it."""
        # GPT Review #1,#2: URI mode=ro — OS-level read-only, no WAL forcing
        conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=5,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _verify_tables(self) -> bool:
        """Check that required tables exist (first call only)."""
        if self._tables_verified:
            return True
        try:
            conn = self._get_conn()
            try:
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                self._tables_verified = "budget_history" in tables
                return self._tables_verified
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[monitor] DB table verification failed: {e}")
            return False

    def check_readable(self) -> bool:
        """Quick health check — can we read from DB?"""
        try:
            conn = self._get_conn()
            try:
                conn.execute("SELECT 1").fetchone()
                return True
            finally:
                conn.close()
        except Exception:
            return False

    # ── Session List (budget_history) ─────────────────────────

    def get_sessions(
        self,
        limit: int = 20,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get sessions with keyset pagination.

        Args:
            limit: max results (default 20)
            cursor: created_at value for keyset pagination (fetch older than this)
            status: filter by status (completed, exceeded, error, cancelled)
            model: filter by model_name

        Returns:
            {"sessions": [...], "next_cursor": "2026-..." or None, "total_count": N}
        """
        if not self._verify_tables():
            return {"sessions": [], "next_cursor": None, "total_count": 0}

        conn = self._get_conn()
        try:
            # Build WHERE clause — always include LLM-only filter
            conditions = [f"(bh.cost > 0 OR bh.total_tokens > 0)"]
            params: list = []

            if cursor:
                conditions.append("bh.created_at < ?")
                params.append(cursor)
            if status and status != "all":
                conditions.append("bh.status = ?")
                params.append(status)
            if model and model != "all":
                conditions.append("bh.model_name = ?")
                params.append(model)

            where = "WHERE " + " AND ".join(conditions)

            # Keyset pagination — GPT Review #4
            sql = f"""
                SELECT bh.id, bh.session_id, bh.video_id, bh.video_title,
                       bh.provider, bh.model_name, bh.tool_calls,
                       bh.tokens_input, bh.tokens_output, bh.total_tokens,
                       bh.cost, bh.duration_sec,
                       bh.max_tool_calls, bh.max_tokens, bh.max_cost, bh.max_duration_sec,
                       bh.status, bh.exceeded_type, bh.created_at
                FROM budget_history bh
                {where}
                ORDER BY bh.created_at DESC
                LIMIT ?
            """
            params.append(limit + 1)  # +1 to detect if there are more

            rows = conn.execute(sql, params).fetchall()
            sessions = [dict(r) for r in rows[:limit]]

            # Next cursor
            next_cursor = None
            if len(rows) > limit:
                next_cursor = sessions[-1]["created_at"]

            # Total count — LLM sessions only
            total = conn.execute(
                f"SELECT count(*) FROM budget_history WHERE {self._LLM_FILTER}"
            ).fetchone()[0]

            return {
                "sessions": sessions,
                "next_cursor": next_cursor,
                "total_count": total,
            }
        except Exception as e:
            logger.error(f"[monitor] get_sessions error: {e}")
            return {"sessions": [], "next_cursor": None, "total_count": 0}
        finally:
            conn.close()

    # ── Session Detail ────────────────────────────────────────

    def get_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get single session with budget info + tool invocations.

        Tool invocations loaded on click only — GPT Review #5.
        """
        if not self.is_available:
            return None

        conn = self._get_conn()
        try:
            # Budget history record
            row = conn.execute(
                "SELECT * FROM budget_history WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return None

            session = dict(row)

            # Tool invocations (click-time only — GPT Review #5)
            invocations = []
            try:
                inv_rows = conn.execute(
                    """SELECT id, tool_name, input_summary, output_summary,
                              status, started_at, completed_at, duration_ms,
                              iteration, tokens_in, tokens_out, cost
                       FROM tool_invocations
                       WHERE session_id = ?
                       ORDER BY iteration, id""",
                    (session_id,),
                ).fetchall()
                invocations = [dict(r) for r in inv_rows]
            except Exception:
                # tool_invocations table might not exist or schema differs
                pass

            session["invocations"] = invocations
            return session
        except Exception as e:
            logger.error(f"[monitor] get_session_detail error: {e}")
            return None
        finally:
            conn.close()

    # ── Statistics ─────────────────────────────────────────────

    def get_stats_today(self) -> Dict[str, Any]:
        """Today's summary: session count, cost, success rate."""
        if not self._verify_tables():
            return {"sessions_today": 0, "cost_today": 0, "avg_duration": 0, "success_rate": 0}

        conn = self._get_conn()
        try:
            row = conn.execute(f"""
                SELECT
                    count(*) as cnt,
                    coalesce(sum(cost), 0) as total_cost,
                    coalesce(avg(duration_sec), 0) as avg_dur,
                    count(CASE WHEN status='completed' THEN 1 END) as success_cnt
                FROM budget_history
                WHERE created_at >= date('now') AND {self._LLM_FILTER}
            """).fetchone()

            cnt = row["cnt"] or 0
            return {
                "sessions_today": cnt,
                "cost_today": round(row["total_cost"] or 0, 4),
                "avg_duration": round(row["avg_dur"] or 0, 1),
                "success_rate": round((row["success_cnt"] / cnt * 100) if cnt > 0 else 0, 1),
            }
        except Exception as e:
            logger.error(f"[monitor] get_stats_today error: {e}")
            return {"sessions_today": 0, "cost_today": 0, "avg_duration": 0, "success_rate": 0}
        finally:
            conn.close()

    def get_budget_stats(self) -> Dict[str, Any]:
        """Aggregate budget stats across all sessions."""
        if not self._verify_tables():
            return {}

        conn = self._get_conn()
        try:
            row = conn.execute(f"""
                SELECT
                    count(*) as total_sessions,
                    coalesce(sum(cost), 0) as total_cost,
                    coalesce(avg(cost), 0) as avg_cost,
                    coalesce(avg(duration_sec), 0) as avg_duration,
                    coalesce(sum(total_tokens), 0) as total_tokens,
                    count(CASE WHEN status='completed' THEN 1 END) as completed,
                    count(CASE WHEN status='exceeded' THEN 1 END) as exceeded,
                    count(CASE WHEN status='error' THEN 1 END) as errors,
                    count(CASE WHEN status='cancelled' THEN 1 END) as cancelled
                FROM budget_history
                WHERE {self._LLM_FILTER}
            """).fetchone()

            return {
                "total_sessions": row["total_sessions"],
                "total_cost": round(row["total_cost"], 4),
                "avg_cost": round(row["avg_cost"], 6),
                "avg_duration": round(row["avg_duration"], 1),
                "total_tokens": row["total_tokens"],
                "completed": row["completed"],
                "exceeded": row["exceeded"],
                "errors": row["errors"],
                "cancelled": row["cancelled"],
            }
        except Exception as e:
            logger.error(f"[monitor] get_budget_stats error: {e}")
            return {}
        finally:
            conn.close()

    def get_model_stats(self) -> List[Dict[str, Any]]:
        """Per-model statistics: count, avg cost, avg tokens, success rate."""
        if not self._verify_tables():
            return []

        conn = self._get_conn()
        try:
            rows = conn.execute(f"""
                SELECT
                    provider, model_name,
                    count(*) as runs,
                    coalesce(avg(cost), 0) as avg_cost,
                    coalesce(avg(total_tokens), 0) as avg_tokens,
                    coalesce(avg(duration_sec), 0) as avg_duration,
                    count(CASE WHEN status='completed' THEN 1 END) as success_cnt
                FROM budget_history
                WHERE {self._LLM_FILTER}
                GROUP BY provider, model_name
                ORDER BY runs DESC
            """).fetchall()

            result = []
            for r in rows:
                runs = r["runs"]
                result.append({
                    "provider": r["provider"],
                    "model": r["model_name"],
                    "runs": runs,
                    "avg_cost": round(r["avg_cost"], 6),
                    "avg_tokens": int(r["avg_tokens"]),
                    "avg_duration": round(r["avg_duration"], 1),
                    "success_rate": round((r["success_cnt"] / runs * 100) if runs > 0 else 0, 1),
                })
            return result
        except Exception as e:
            logger.error(f"[monitor] get_model_stats error: {e}")
            return []
        finally:
            conn.close()

    def detect_running_session(self) -> Optional[Dict[str, str]]:
        """Check if any session is currently 'running'. Returns {session_id, video_id}."""
        if not self.is_available:
            return None

        conn = self._get_conn()
        try:
            # Check agent_sessions table for running status
            try:
                row = conn.execute(
                    "SELECT session_id, video_id FROM agent_sessions "
                    "WHERE status = 'running' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if row:
                    return {"session_id": row["session_id"], "video_id": row["video_id"]}
            except Exception:
                pass  # Table might not exist

            return None
        except Exception:
            return None
        finally:
            conn.close()

    def get_distinct_models(self) -> List[str]:
        """Get list of distinct model names for filter dropdown."""
        if not self._verify_tables():
            return []

        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"SELECT DISTINCT model_name FROM budget_history WHERE {self._LLM_FILTER} ORDER BY model_name"
            ).fetchall()
            return [r["model_name"] for r in rows]
        except Exception:
            return []
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────────
# SSEProxyClient — relay main service SSE to dashboard clients
# ──────────────────────────────────────────────────────────────

class SSEProxyClient:
    """Subscribe to main service SSE and relay events to dashboard clients.

    Single connection to main service per video_id (1:N broadcast).
    Ref-count based: unsubscribes when no dashboard clients are watching.
    """

    def __init__(self, base_url: str, on_event=None):
        self.base_url = base_url.rstrip("/")
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._client_queues: List[Queue] = []
        self._lock = threading.Lock()
        self._current_video_id: Optional[str] = None
        self._connected = False
        self._on_event = on_event  # External callback for live feed relay

    @property
    def is_connected(self) -> bool:
        return self._connected and self._thread is not None and self._thread.is_alive()

    def subscribe(self, video_id: str):
        """Start listening to a specific video's SSE stream."""
        if self._current_video_id == video_id and self.is_connected:
            return  # Already subscribed

        self.unsubscribe()
        self._current_video_id = video_id
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._stream_loop,
            args=(video_id,),
            daemon=True,
            name=f"sse-proxy-{video_id[:8]}",
        )
        self._thread.start()

    def unsubscribe(self):
        """Stop listening to the current SSE stream."""
        self._stop_event.set()
        self._connected = False
        self._current_video_id = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def register_client(self) -> Queue:
        """Register a dashboard SSE client to receive relayed events."""
        q: Queue = Queue(maxsize=100)
        with self._lock:
            self._client_queues.append(q)
        return q

    def unregister_client(self, q: Queue):
        """Remove a client queue. Unsubscribe if no clients left (ref-count)."""
        with self._lock:
            if q in self._client_queues:
                self._client_queues.remove(q)
            # Ref-count: if no one is watching, disconnect
            if not self._client_queues:
                self.unsubscribe()

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._client_queues)

    def _broadcast(self, event: dict):
        """Push event to all registered dashboard clients."""
        dead_clients = []
        with self._lock:
            for q in self._client_queues:
                try:
                    q.put_nowait(event)
                except Full:
                    dead_clients.append(q)
            for q in dead_clients:
                self._client_queues.remove(q)

        # Relay to external callback (ActiveProcessingDetector)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass

    def _stream_loop(self, video_id: str):
        """Background thread: consume main service SSE, normalize, broadcast."""
        try:
            import requests
        except ImportError:
            logger.error("[monitor] requests library not installed for SSE proxy")
            return

        url = f"{self.base_url}/api/rag/generate_knowledge_stream/{video_id}"
        logger.info(f"[monitor] SSE proxy connecting to {url}")

        try:
            resp = requests.get(url, stream=True, timeout=(5, None))
            self._connected = True

            buffer = ""
            current_event_type = "message"
            current_data = ""

            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                if self._stop_event.is_set():
                    break

                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.rstrip("\r")

                    if line.startswith("event:"):
                        current_event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        current_data = line[5:].strip()
                    elif line == "":
                        # End of event
                        if current_data:
                            try:
                                data = json.loads(current_data)
                            except json.JSONDecodeError:
                                data = {"raw": current_data}

                            event = {
                                "event_type": current_event_type,
                                "data": data,
                                "timestamp": datetime.now().isoformat(),
                                "source": "main_service_sse",
                            }
                            self._broadcast(event)

                        current_event_type = "message"
                        current_data = ""

        except Exception as e:
            logger.warning(f"[monitor] SSE proxy error: {e}")
        finally:
            self._connected = False
            logger.info("[monitor] SSE proxy disconnected")


# ──────────────────────────────────────────────────────────────
# ActiveProcessingDetector — detect new videos + auto-subscribe SSE
# ──────────────────────────────────────────────────────────────

class ActiveProcessingDetector:
    """Detect newly added videos via DB polling and auto-subscribe to SSE.

    Polls the `videos` table every 2 seconds for rows with recent `created_at`.
    When a new video_id appears, subscribes an SSEProxyClient to the main
    service's generate_knowledge_stream endpoint, relaying events to
    dashboard clients via /api/monitor/live.
    """

    def __init__(self, db_reader: Optional[MainServiceDBReader],
                 sse_proxy: 'SSEProxyClient', base_url: str):
        self._db_reader = db_reader
        self._sse_proxy = sse_proxy
        self._base_url = base_url.rstrip("/")
        self._seen_videos: set = set()
        self._active_video: Optional[str] = None
        self._active_title: str = ""
        self._client_queues: List[Queue] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._sse_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sse_stop = threading.Event()

    # ── Properties ────────────────────────────────────────────

    @property
    def active_video(self) -> Optional[str]:
        return self._active_video

    @property
    def active_title(self) -> str:
        return self._active_title

    # ── Client management (same pattern as SSEProxyClient) ────

    def register_client(self) -> Queue:
        """Register a dashboard live feed SSE client."""
        q: Queue = Queue(maxsize=200)
        with self._lock:
            self._client_queues.append(q)
        return q

    def unregister_client(self, q: Queue):
        """Remove a live feed client queue."""
        with self._lock:
            if q in self._client_queues:
                self._client_queues.remove(q)

    def _broadcast(self, event: dict):
        """Push event to all live feed clients."""
        dead = []
        with self._lock:
            for q in self._client_queues:
                try:
                    q.put_nowait(event)
                except Full:
                    dead.append(q)
            for q in dead:
                self._client_queues.remove(q)

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self):
        """Start the 2-second DB polling loop."""
        if not self._db_reader:
            logger.info("[live] No DB reader — live detector disabled")
            return
        self._init_seen_videos()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="live-detector"
        )
        self._thread.start()
        logger.info("[live] ActiveProcessingDetector started")

    def stop(self):
        """Stop polling and SSE subscription."""
        self._stop_event.set()
        self._sse_stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=3)

    # ── Initialization ────────────────────────────────────────

    def _init_seen_videos(self):
        """Load recent video_ids into _seen_videos to avoid false triggers."""
        if not self._db_reader or not self._db_reader.is_available:
            return
        try:
            conn = self._db_reader._get_conn()
            try:
                rows = conn.execute(
                    "SELECT video_id FROM videos ORDER BY rowid DESC LIMIT 200"
                ).fetchall()
                self._seen_videos = {r["video_id"] for r in rows}
                logger.info(f"[live] Initialized with {len(self._seen_videos)} known videos")
            finally:
                conn.close()
        except Exception as e:
            logger.debug(f"[live] init_seen_videos error: {e}")

    # ── Polling Loop ──────────────────────────────────────────

    def _poll_loop(self):
        """Poll every 2 seconds for newly created videos."""
        while not self._stop_event.is_set():
            try:
                self._check_new_videos()
            except Exception as e:
                logger.debug(f"[live] poll error: {e}")
            self._stop_event.wait(2)

    def _check_new_videos(self):
        """Check videos table for entries created in the last 60 seconds."""
        if not self._db_reader or not self._db_reader.is_available:
            return

        try:
            conn = self._db_reader._get_conn()
            try:
                rows = conn.execute(
                    """SELECT video_id, title, created_at FROM videos
                       WHERE created_at > datetime('now', '-60 seconds')
                       ORDER BY created_at DESC LIMIT 5"""
                ).fetchall()
            finally:
                conn.close()
        except Exception as e:
            logger.debug(f"[live] DB query error: {e}")
            return

        for row in rows:
            vid = row["video_id"]
            if vid not in self._seen_videos:
                self._seen_videos.add(vid)
                title = row["title"] or vid
                logger.info(f"[live] New video detected: {vid} ({title})")

                self._active_video = vid
                self._active_title = title

                # Broadcast detection event
                self._broadcast({
                    "type": "processing_detected",
                    "video_id": vid,
                    "title": title,
                    "timestamp": datetime.now().isoformat(),
                })

                # Start tracking knowledge generation via DB polling
                self._start_knowledge_tracker(vid, title)
                break  # Handle one at a time

    # ── Knowledge Generation Tracker (DB polling) ─────────────

    def _start_knowledge_tracker(self, video_id: str, title: str):
        """Track knowledge generation progress via DB polling.

        Instead of subscribing to the SSE endpoint (which would trigger a
        duplicate generation), we poll the videos table for changes to
        script_stepaz_path — when it transitions from NULL to a path,
        the generation is complete.

        Also polls budget_history for the agent session associated with
        this video, relaying progress events to dashboard clients.
        """
        self._sse_stop.set()
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=2)

        self._sse_stop = threading.Event()
        self._sse_thread = threading.Thread(
            target=self._knowledge_track_loop,
            args=(video_id, title),
            daemon=True,
            name=f"live-track-{video_id[:8]}",
        )
        self._sse_thread.start()

    def _knowledge_track_loop(self, video_id: str, title: str):
        """Poll DB every 2 seconds to track knowledge generation status."""
        logger.info(f"[live] Tracking knowledge generation for {video_id}")

        step = 0
        total_steps = 5
        last_stepaz = None
        last_knowledge_count = 0
        poll_count = 0
        max_polls = 90  # 3 minutes max (2s * 90)

        while not self._sse_stop.is_set() and not self._stop_event.is_set():
            poll_count += 1
            if poll_count > max_polls:
                logger.info(f"[live] Tracking timeout for {video_id}")
                self._broadcast({
                    "type": "live_complete",
                    "video_id": video_id,
                    "title": title,
                    "success": False,
                    "message": "Tracking timeout",
                    "timestamp": datetime.now().isoformat(),
                })
                self._active_video = None
                return

            try:
                conn = self._db_reader._get_conn()
                try:
                    # Check video's stepaz path
                    row = conn.execute(
                        "SELECT script_stepaz_path, status FROM videos WHERE video_id = ?",
                        (video_id,),
                    ).fetchone()

                    if not row:
                        self._sse_stop.wait(2)
                        continue

                    stepaz_path = row["script_stepaz_path"]
                    video_status = row["status"]

                    # Check knowledge_nodes count for progress
                    try:
                        kn_count = conn.execute(
                            "SELECT count(*) FROM knowledge_nodes WHERE video_id = ?",
                            (video_id,),
                        ).fetchone()[0]
                    except Exception:
                        kn_count = 0

                    # Check budget_history for session info
                    try:
                        bh_row = conn.execute(
                            """SELECT session_id, tool_calls, total_tokens, cost,
                                      duration_sec, status
                               FROM budget_history
                               WHERE video_id = ?
                               ORDER BY created_at DESC LIMIT 1""",
                            (video_id,),
                        ).fetchone()
                    except Exception:
                        bh_row = None

                finally:
                    conn.close()

                # Determine progress step based on what we see
                new_step = step
                message = ""

                if kn_count > last_knowledge_count:
                    last_knowledge_count = kn_count
                    new_step = max(step, 3)
                    message = f"Knowledge nodes: {kn_count}"

                if stepaz_path and stepaz_path != last_stepaz:
                    last_stepaz = stepaz_path
                    new_step = max(step, 4)
                    message = "STEPAZ knowledge file generated"

                if bh_row:
                    # Agent session detected
                    if bh_row["status"] == "completed":
                        new_step = total_steps
                        message = "Agent session completed"
                    elif bh_row["tool_calls"] and bh_row["tool_calls"] > 0:
                        new_step = max(step, 2)
                        message = f"Agent: {bh_row['tool_calls']} tool calls, {bh_row['total_tokens'] or 0} tokens"

                if new_step > step:
                    step = new_step
                    progress_evt = {
                        "type": "live_progress",
                        "video_id": video_id,
                        "title": title,
                        "step": step,
                        "total": total_steps,
                        "message": message,
                        "sections_done": step,
                        "sections_total": total_steps,
                        "timestamp": datetime.now().isoformat(),
                    }
                    self._broadcast(progress_evt)
                    logger.info(f"[live] Progress {step}/{total_steps}: {message}")

                # Check for completion
                if step >= total_steps or (bh_row and bh_row["status"] == "completed"):
                    success = bh_row["status"] == "completed" if bh_row else bool(stepaz_path)
                    self._broadcast({
                        "type": "live_complete",
                        "video_id": video_id,
                        "title": title,
                        "success": success,
                        "timestamp": datetime.now().isoformat(),
                    })
                    logger.info(f"[live] Complete for {video_id} (success={success})")
                    self._active_video = None
                    return

                # Also complete if stepaz appeared
                if stepaz_path and poll_count > 5:
                    self._broadcast({
                        "type": "live_complete",
                        "video_id": video_id,
                        "title": title,
                        "success": True,
                        "timestamp": datetime.now().isoformat(),
                    })
                    logger.info(f"[live] Complete via stepaz for {video_id}")
                    self._active_video = None
                    return

            except Exception as e:
                logger.debug(f"[live] Track error: {e}")

            self._sse_stop.wait(2)


# ──────────────────────────────────────────────────────────────
# MainServiceConnector — orchestrates DB reader, SSE proxy, health
# ──────────────────────────────────────────────────────────────

class MainServiceConnector:
    """Top-level connector managing DB reader, SSE proxy, and health checks.

    Tracks 3 independent statuses (GPT Review #10):
      - service_online: HTTP health check to main service
      - db_readable: scripts.db accessible
      - sse_available: SSE proxy can connect
    """

    def __init__(self, config: dict):
        self.config = config
        monitor_cfg = config.get("monitor", {})

        self.enabled = monitor_cfg.get("enabled", False)
        self.base_url = monitor_cfg.get("main_service_url", "http://127.0.0.1:5000")
        self.poll_interval = monitor_cfg.get("poll_interval_sec", 3)
        self.health_interval = monitor_cfg.get("health_check_interval_sec", 10)

        # Resolve DB path
        db_path = monitor_cfg.get("main_service_db", "")
        if not db_path:
            # Auto-detect from project root
            project_root = config.get("project", {}).get("root", ".")
            candidate = Path(project_root) / "scripts.db"
            if candidate.exists():
                db_path = str(candidate)
            else:
                # Try common relative paths
                for rel in ["../project0914/scripts.db", "../../project0914/scripts.db"]:
                    candidate = Path(project_root) / rel
                    if candidate.exists():
                        db_path = str(candidate.resolve())
                        break

        # Sub-components
        self._db_reader: Optional[MainServiceDBReader] = None
        if db_path and Path(db_path).exists():
            self._db_reader = MainServiceDBReader(db_path)
            logger.info(f"[monitor] DB reader: {db_path}")
        else:
            logger.warning(f"[monitor] scripts.db not found at: {db_path or '(auto-detect failed)'}")

        self._sse_proxy = SSEProxyClient(self.base_url)

        # Live processing detector
        self._live_detector = ActiveProcessingDetector(
            db_reader=self._db_reader,
            sse_proxy=self._sse_proxy,
            base_url=self.base_url,
        )

        # 3-state health tracking (GPT Review #10)
        self._service_online = False
        self._db_readable = self._db_reader.check_readable() if self._db_reader else False
        self._sse_available = False
        self._last_health_check: Optional[str] = None

        # Health check thread
        self._health_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── Properties ────────────────────────────────────────────

    @property
    def service_online(self) -> bool:
        return self._service_online

    @property
    def db_readable(self) -> bool:
        return self._db_readable

    @property
    def sse_available(self) -> bool:
        return self._sse_proxy.is_connected

    @property
    def db_reader(self) -> Optional[MainServiceDBReader]:
        return self._db_reader

    @property
    def sse_proxy(self) -> SSEProxyClient:
        return self._sse_proxy

    @property
    def live_detector(self) -> ActiveProcessingDetector:
        return self._live_detector

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self):
        """Start health check thread and live detector."""
        if not self.enabled:
            return

        self._stop_event.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            daemon=True,
            name="monitor-health",
        )
        self._health_thread.start()

        # Start live processing detector
        self._live_detector.start()

    def stop(self):
        """Graceful shutdown."""
        self._live_detector.stop()
        self._stop_event.set()
        self._sse_proxy.unsubscribe()
        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=3)

    # ── Health Check ──────────────────────────────────────────

    def _check_service_health(self) -> bool:
        """HTTP GET to main service root with 2s timeout."""
        try:
            import requests
            resp = requests.get(self.base_url, timeout=2)
            return resp.status_code < 500
        except Exception:
            return False

    def _health_loop(self):
        """Background thread: periodic health checks."""
        while not self._stop_event.is_set():
            try:
                self._service_online = self._check_service_health()
                self._db_readable = (
                    self._db_reader.check_readable() if self._db_reader else False
                )
                self._last_health_check = datetime.now().isoformat()
            except Exception as e:
                logger.debug(f"[monitor] Health check error: {e}")

            self._stop_event.wait(self.health_interval)

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Full status for /api/monitor/status endpoint."""
        return {
            "enabled": self.enabled,
            "service_online": self._service_online,
            "db_readable": self._db_readable,
            "sse_available": self.sse_available,
            "sse_clients": self._sse_proxy.client_count,
            "main_service_url": self.base_url,
            "db_path": self._db_reader.db_path if self._db_reader else None,
            "last_health_check": self._last_health_check,
        }
