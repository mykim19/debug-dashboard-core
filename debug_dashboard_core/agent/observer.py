"""FileObserver — watchdog-based file system monitoring with debounce.

GPT Risk #3 addressed: 2-stage mapping (extension + path heuristic).
Debounce prevents event flooding. IGNORE_DIRS filters noise.
"""
import queue
import time
import threading
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .events import AgentEvent, EventType, FileChangeEvent

logger = logging.getLogger("agent.observer")

# ── Stage 1: Extension → Checker mapping ──
EXTENSION_CHECKER_MAP: Dict[str, List[str]] = {
    ".py": ["code_quality", "security", "performance", "api_health", "dependency"],
    ".sql": ["database", "schema_migration"],
    ".db": ["database", "schema_migration"],
    ".sqlite": ["database", "schema_migration"],
    ".yaml": ["config_drift", "environment"],
    ".yml": ["config_drift"],
    ".env": ["environment", "security"],
    ".txt": ["dependency"],           # requirements.txt
    ".toml": ["dependency"],          # pyproject.toml
    ".cfg": ["dependency"],           # setup.cfg
    ".md": ["skill_template"],
    ".json": ["config_drift"],
    ".html": ["code_quality"],
    ".js": ["code_quality"],
    ".css": ["code_quality"],
}

# ── Stage 2: Path keyword → Checker refinement ──
PATH_KEYWORD_MAP: Dict[str, List[str]] = {
    "test": ["test_coverage"],
    "tests": ["test_coverage"],
    "migration": ["schema_migration"],
    "migrations": ["schema_migration"],
    "alembic": ["schema_migration"],
    "skills": ["skill_template"],
    "rag": ["rag_pipeline"],
    "agent": ["agent_budget"],
    "whisper": ["whisper_health"],
    "ytdlp": ["ytdlp_pipeline"],
    "yt_dlp": ["ytdlp_pipeline"],
    "ontology": ["ontology_sync"],
    "knowledge": ["knowledge_graph"],
    "golden": ["golden_quality"],
    "citation": ["citation_integrity"],
    "search": ["search_index"],
    "url": ["url_pattern"],
}

# Directories to always ignore
IGNORE_DIRS: Set[str] = {
    ".git", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".debugger", "debug_dashboard",
    ".tox", "dist", "build", ".eggs",
    ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "chroma_db", ".ipynb_checkpoints",
    # GPT Review #3B: prevent self-trigger loop from agent/dashboard output
    "debug_dashboard_core", ".debug_dashboard",
}

# Files to always ignore
IGNORE_FILES: Set[str] = {
    ".DS_Store", "Thumbs.db", ".gitkeep",
}

# GPT Review #3B: extensions that cause self-trigger loops
# Agent writes .db (storage), .lock (singleton), .log files — must never re-trigger
SELF_TRIGGER_EXTENSIONS: Set[str] = {
    ".db", ".sqlite", ".sqlite3",   # storage writes
    ".lock", ".pid",                 # singleton lock
    ".log",                          # log files
    ".pyc", ".pyo",                  # compiled python
    ".swp", ".swo",                  # vim swap files
}


class _DebouncedHandler(FileSystemEventHandler):
    """Collects file events and debounces them before emitting."""

    def __init__(self, debounce_seconds: float = 2.0, extra_config: Optional[dict] = None):
        super().__init__()
        self._pending: Dict[str, FileChangeEvent] = {}
        self._lock = threading.Lock()
        self._debounce = debounce_seconds
        self._sink: Optional[queue.Queue] = None
        self._timer: Optional[threading.Timer] = None
        self._project_root: Path = Path(".")

        # GPT Review #4-2: merge user config ignore patterns with builtins
        # GPT Review #5-2: merge policy is ADD-ONLY. Config patterns are unioned
        # with builtin sets. Removing a builtin pattern is intentionally not supported
        # to prevent accidental self-trigger loops (.db, .lock, __pycache__, etc).
        cfg = extra_config or {}
        self._ignore_dirs: Set[str] = set(IGNORE_DIRS)
        self._ignore_extensions: Set[str] = set(SELF_TRIGGER_EXTENSIONS)
        # Merge from config: ignore_patterns can contain dir names or glob-like patterns
        for pat in cfg.get("ignore_patterns", []):
            clean = pat.strip().strip("*").strip(".")
            if clean:
                self._ignore_dirs.add(clean)
        # Merge from config: explicit additional extensions
        for ext in cfg.get("ignore_extensions", []):
            if ext.startswith("."):
                self._ignore_extensions.add(ext)
            else:
                self._ignore_extensions.add(f".{ext}")

    def configure(self, project_root: Path, sink: queue.Queue):
        self._project_root = project_root
        self._sink = sink

    def _should_ignore(self, path: str) -> bool:
        p = Path(path)
        # Ignore specific files
        if p.name in IGNORE_FILES:
            return True
        # Ignore hidden files (except .env, .gitignore)
        if p.name.startswith(".") and p.name not in (".env", ".gitignore", ".flake8"):
            return True
        # Ignore certain directories (builtins + user config)
        for part in p.parts:
            if part in self._ignore_dirs:
                return True
        # GPT Review #3B: ignore self-trigger extensions (builtins + user config)
        if p.suffix in self._ignore_extensions:
            return True
        # Ignore non-mapped extensions (unless no extension = possibly relevant)
        if p.suffix and p.suffix not in EXTENSION_CHECKER_MAP:
            return True
        return False

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = event.src_path
        if self._should_ignore(path):
            return

        change_type_map = {
            "created": "created",
            "modified": "modified",
            "deleted": "deleted",
            "moved": "modified",
        }
        change_type = change_type_map.get(event.event_type, "modified")

        try:
            rel = str(Path(path).relative_to(self._project_root))
        except ValueError:
            rel = path

        fce = FileChangeEvent(
            path=path,
            change_type=change_type,
            extension=Path(path).suffix,
            relative_to_root=rel,
        )

        with self._lock:
            self._pending[path] = fce

        # Reset debounce timer
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _flush(self):
        with self._lock:
            if not self._pending or not self._sink:
                return
            batch = list(self._pending.values())
            self._pending.clear()

        # ── 2-stage mapping (GPT Risk #3) ──

        # Stage 1: Extension-based
        affected_checkers: Set[str] = set()
        for fce in batch:
            checkers = EXTENSION_CHECKER_MAP.get(fce.extension, [])
            affected_checkers.update(checkers)

        # Stage 2: Path-keyword refinement
        for fce in batch:
            path_lower = fce.relative_to_root.lower()
            for keyword, checkers in PATH_KEYWORD_MAP.items():
                if keyword in path_lower:
                    affected_checkers.update(checkers)

        # Emit a single batched event
        self._sink.put(AgentEvent(
            type=EventType.FILE_CHANGED,
            data={
                "files": [
                    {"path": f.relative_to_root, "change": f.change_type, "ext": f.extension}
                    for f in batch
                ],
                "affected_checkers": sorted(affected_checkers),
                "file_count": len(batch),
            },
            source="watcher",
        ))
        logger.info(
            f"File change batch: {len(batch)} files → "
            f"checkers: {sorted(affected_checkers)}"
        )


class FileObserver:
    """Wraps watchdog Observer with debounced event emission."""

    def __init__(self, project_root: Path, config: dict):
        self._project_root = project_root
        self._config = config
        agent_cfg = config.get("agent", {})
        self._handler = _DebouncedHandler(
            debounce_seconds=agent_cfg.get("debounce_seconds", 2.0),
            extra_config=agent_cfg,  # GPT Review #4-2: pass config for ignore pattern merging
        )
        self._observer: Optional[Observer] = None
        self._running = False

    def set_event_sink(self, sink: queue.Queue):
        self._handler.configure(self._project_root, sink)

    def start(self):
        if self._running:
            return
        self._observer = Observer()
        watch_dirs = self._config.get("agent", {}).get("watch_dirs", ["."])
        scheduled = 0
        for d in watch_dirs:
            target = self._project_root / d
            if target.is_dir():
                self._observer.schedule(self._handler, str(target), recursive=True)
                scheduled += 1
                logger.info(f"Watching: {target}")
        if scheduled == 0:
            logger.warning("No valid watch directories found")
            return
        self._observer.daemon = True
        self._observer.start()
        self._running = True
        logger.info(f"FileObserver started ({scheduled} directories)")

    def stop(self):
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._running = False
            logger.info("FileObserver stopped")

    @property
    def is_running(self) -> bool:
        return self._running
