"""AgentLoop — autonomous Observe → Reason → Act cycle.

This is the heart of the agent system. It runs in a background daemon thread,
processing events from a queue and cycling through the ORA loop.

GPT Risk #1 addressed: singleton lock prevents duplicate agent instances.
GPT Risk #2 addressed: workspace_id flows through all events.
GPT Risk #4 addressed: retention purge on startup.
"""
import threading
import time
import queue
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import AgentState
from .events import AgentEvent, EventType
from .observer import FileObserver
from .reasoner import Reasoner
from .executor import Executor
from .memory import AgentMemory
from .singleton import AgentSingletonLock
from .. import storage

logger = logging.getLogger("agent.loop")


class AgentLoop:
    """Main agent loop. Runs in a background daemon thread.

    Lifecycle:
        agent = AgentLoop(config, checkers_dict, project_root, ...)
        agent.start()               # begins background thread
        agent.request_scan()         # manual trigger
        agent.request_analysis(name) # manual LLM trigger
        agent.stop()                 # graceful shutdown

    Events are pushed by the Observer (file watcher) or by user actions.
    The Reasoner decides which checkers to run.
    The Executor runs them with dependency ordering.
    """

    def __init__(
        self,
        config: dict,
        checkers_dict: Dict[str, "BaseChecker"],
        project_root: Path,
        workspace_id: str,
        memory: AgentMemory,
        reasoner: Reasoner,
        executor: Executor,
        observer: FileObserver,
        on_event: Callable[[AgentEvent], None] = None,
    ):
        self.config = config
        self.checkers_dict = checkers_dict
        self.project_root = project_root
        self.workspace_id = workspace_id
        self.memory = memory
        self.reasoner = reasoner
        self.executor = executor
        self.observer = observer
        self.on_event = on_event or (lambda e: None)

        self._state = AgentState.IDLE
        self._event_queue: queue.Queue[AgentEvent] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # GPT Review #4-1: pass configurable TTL to singleton lock
        singleton_ttl = config.get("agent", {}).get("singleton_max_age_seconds", 86400)
        self._singleton_lock = AgentSingletonLock(workspace_id, max_age_seconds=singleton_ttl)

        # GPT Review #3E: runtime purge tracking
        self._last_purge_time: float = 0
        self._purge_interval_seconds: float = config.get(
            "agent", {}
        ).get("purge_interval_seconds", 3600)  # default: 1 hour

        # Wire observer's output into our event queue
        self.observer.set_event_sink(self._event_queue)

        # SSE client queues — for real-time browser updates
        self._sse_clients: List[queue.Queue] = []
        self._sse_lock = threading.Lock()

    @property
    def state(self) -> AgentState:
        return self._state

    def _set_state(self, new_state: AgentState):
        old = self._state
        self._state = new_state
        if old != new_state:
            self._emit(AgentEvent(
                type=EventType.AGENT_STATE_CHANGED,
                data={"old": old.value, "new": new_state.value},
                source="loop",
                workspace_id=self.workspace_id,
            ))

    def _emit(self, event: AgentEvent):
        """Emit event to memory + external listeners (SSE clients)."""
        self.memory.record_event(event)
        self.on_event(event)
        # Push to all SSE clients
        with self._sse_lock:
            dead: List[queue.Queue] = []
            for client_q in self._sse_clients:
                try:
                    client_q.put_nowait(event)
                except queue.Full:
                    dead.append(client_q)
            for d in dead:
                self._sse_clients.remove(d)

    def register_sse_client(self) -> queue.Queue:
        """Register a new SSE client and return its event queue."""
        client_q: queue.Queue = queue.Queue(maxsize=200)
        with self._sse_lock:
            self._sse_clients.append(client_q)
        return client_q

    def unregister_sse_client(self, client_q: queue.Queue):
        """Unregister an SSE client."""
        with self._sse_lock:
            if client_q in self._sse_clients:
                self._sse_clients.remove(client_q)

    def start(self) -> bool:
        """Start the agent loop. Returns False if already running or lock fails."""
        if self._thread and self._thread.is_alive():
            logger.info("Agent loop already running")
            return True

        # GPT Risk #1: singleton lock
        if not self._singleton_lock.acquire():
            logger.warning("Another agent instance is running for this workspace")
            return False

        # GPT Risk #4: purge old data on startup
        try:
            retention = self.config.get("agent", {}).get("retention", {})
            storage.purge_old_agent_data(
                event_max_rows=retention.get("event_max_rows", 10000),
                event_max_days=retention.get("event_max_days", 7),
                analysis_max_days=retention.get("analysis_max_days", 90),
            )
        except Exception as e:
            logger.warning(f"Retention purge failed: {e}")

        self._stop_event.clear()
        self.observer.start()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"agent-{self.workspace_id[:6]}"
        )
        self._thread.start()
        logger.info(f"Agent loop started (workspace={self.workspace_id})")
        return True

    def stop(self):
        """Graceful shutdown."""
        self._stop_event.set()
        self.observer.stop()
        if self._thread:
            self._thread.join(timeout=5)
        self._singleton_lock.release()
        self._set_state(AgentState.IDLE)
        logger.info("Agent loop stopped")

    def request_scan(self, checker_names: List[str] = None):
        """Manual scan request from user."""
        self._event_queue.put(AgentEvent(
            type=EventType.SCAN_REQUESTED,
            data={"checkers": checker_names},
            source="user",
            workspace_id=self.workspace_id,
        ))

    def request_analysis(self, checker_name: str):
        """Manual LLM deep analysis request."""
        self._event_queue.put(AgentEvent(
            type=EventType.LLM_ANALYSIS_REQUESTED,
            data={"checker": checker_name},
            source="user",
            workspace_id=self.workspace_id,
        ))

    def _maybe_runtime_purge(self):
        """GPT Review #3E: periodic purge during long-running sessions.
        GPT Review #6 UI: emits purge event if data was actually deleted.
        """
        now = time.time()
        if now - self._last_purge_time < self._purge_interval_seconds:
            return
        self._last_purge_time = now
        try:
            retention = self.config.get("agent", {}).get("retention", {})
            result = storage.purge_old_agent_data(
                event_max_rows=retention.get("event_max_rows", 10000),
                event_max_days=retention.get("event_max_days", 7),
                analysis_max_days=retention.get("analysis_max_days", 90),
            )
            if result.get("total_deleted", 0) > 0:
                logger.info(f"Runtime purge: {result}")
                self._emit(AgentEvent(
                    type=EventType.INSIGHT_GENERATED,
                    data={"purge": True, **result},
                    source="loop",
                    workspace_id=self.workspace_id,
                ))
            else:
                logger.debug("Runtime purge: nothing to clean")
        except Exception as e:
            logger.warning(f"Runtime purge failed: {e}")

    def _run(self):
        """Main loop: wait for events, reason, execute."""
        self._set_state(AgentState.OBSERVING)
        self._last_purge_time = time.time()  # Reset on start
        while not self._stop_event.is_set():
            try:
                event = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                # GPT Review #3E: check for periodic purge during idle
                self._maybe_runtime_purge()
                continue

            try:
                # OBSERVE: event received
                self._set_state(AgentState.OBSERVING)
                self._emit(event)

                # REASON: decide what to do
                self._set_state(AgentState.REASONING)
                actions = self.reasoner.evaluate(event, self.memory)

                # ACT: execute actions
                if actions:
                    self._set_state(AgentState.EXECUTING)
                    for action in actions:
                        if action.action_type == "llm_analyze":
                            self._set_state(AgentState.WAITING_LLM)

                        result_event = self.executor.execute(action)
                        self._emit(result_event)

                        # Record scan reports for memory (regression detection)
                        if (result_event.type == EventType.SCAN_COMPLETED
                                and not result_event.data.get("skipped")
                                and result_event.data.get("reports")):
                            self.memory.record_scan_reports(
                                result_event.data["reports"]
                            )

                            # Save to storage.py for persistence
                            try:
                                data = result_event.data
                                storage.save_scan(
                                    project_name=f"{self.config.get('project', {}).get('name', 'Unknown')} [{self.workspace_id}]",
                                    overall_status=data.get("overall", "UNKNOWN"),
                                    total_pass=data.get("total_pass", 0),
                                    total_warn=data.get("total_warn", 0),
                                    total_fail=data.get("total_fail", 0),
                                    health_pct=data.get("health_pct", 0),
                                    phases=[],  # agent doesn't use phases_json
                                    duration_ms=data.get("duration_ms", 0),
                                )
                            except Exception as e:
                                logger.warning(f"Failed to save scan: {e}")

                        # Save LLM analysis to storage
                        if (result_event.type == EventType.LLM_ANALYSIS_COMPLETED
                                and not result_event.data.get("error")):
                            try:
                                d = result_event.data
                                storage.save_llm_analysis(
                                    checker_name=d.get("checker", ""),
                                    model=d.get("model", ""),
                                    prompt_tokens=d.get("tokens", {}).get("prompt", 0),
                                    completion_tokens=d.get("tokens", {}).get("completion", 0),
                                    cost_usd=d.get("cost_usd", 0),
                                    analysis=d.get("analysis", ""),
                                    root_causes=d.get("root_causes", []),
                                    fix_suggestions=d.get("fix_suggestions", []),
                                    evidence=d.get("evidence", {}),
                                    workspace_id=self.workspace_id,
                                )
                            except Exception as e:
                                logger.warning(f"Failed to save analysis: {e}")

                        # Save insights
                        if result_event.type == EventType.INSIGHT_GENERATED:
                            for insight in result_event.data.get("insights", []):
                                try:
                                    storage.save_agent_insight(
                                        insight_type=insight.get("type", ""),
                                        severity=insight.get("severity", "info"),
                                        message=insight.get("message", ""),
                                        checkers=insight.get("checkers", [insight.get("checker", "")]),
                                        workspace_id=self.workspace_id,
                                    )
                                except Exception:
                                    pass

                self._set_state(AgentState.OBSERVING)

            except Exception as e:
                logger.exception(f"Agent loop error: {e}")
                self._set_state(AgentState.ERROR)
                self._emit(AgentEvent(
                    type=EventType.AGENT_STATE_CHANGED,
                    data={"error": str(e)},
                    source="loop",
                    workspace_id=self.workspace_id,
                ))
                # Recover after brief pause
                time.sleep(2)
                self._set_state(AgentState.OBSERVING)

    def get_status(self) -> dict:
        """Get current agent status for API."""
        return {
            "state": self._state.value,
            "workspace_id": self.workspace_id,
            "observer_running": self.observer.is_running,
            "executor_busy": self.executor.is_executing,
            "llm_available": self.executor._llm is not None if hasattr(self.executor, '_llm') else False,
            "event_queue_size": self._event_queue.qsize(),
            "sse_clients": len(self._sse_clients),
        }
