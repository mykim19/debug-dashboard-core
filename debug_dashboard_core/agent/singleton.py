"""Agent singleton lock — ensures only one AgentLoop runs per workspace.

GPT Risk #1: gunicorn multi-worker / reload / debug mode can spawn multiple
AgentLoop instances. This file-based lock prevents duplicate execution.

Usage:
    lock = AgentSingletonLock(workspace_id, lock_dir)
    if lock.acquire():
        try:
            agent.start()
            ...
        finally:
            lock.release()
"""
import os
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent.singleton")


class AgentSingletonLock:
    """File-based singleton lock for agent per workspace.

    Creates a lock file containing PID + timestamp.
    On acquire, checks if existing lock's PID is still alive (stale lock detection).

    Lock Priority Logic (GPT Review #5-1):
      Case 1: PID is dead           → always reclaim (crash/kill -9)
      Case 2: PID alive + age > TTL → reclaim (PID recycled by OS)
      Case 3: PID alive + age < TTL → genuine lock, reject acquire

    Priority: Case 1 > Case 2 > Case 3
    A dead PID always wins regardless of TTL. TTL only matters when the PID
    *appears* alive but has likely been recycled by the OS to an unrelated process.

    GPT Review hardening:
      - TTL-based stale detection: if lock age > max_age_seconds AND PID is same
        process but different (recycled PID), the lock is reclaimed.
      - Covers kill -9 / crash scenarios where PID may be reassigned to unrelated process.
    """

    # Default max lock age before considering stale even if PID appears alive
    # (guards against PID recycling on long-running systems)
    # GPT Review #4-1: now configurable via agent.singleton_max_age_seconds
    DEFAULT_MAX_AGE_SECONDS = 86400  # 24 hours

    def __init__(
        self,
        workspace_id: str,
        lock_dir: Optional[Path] = None,
        max_age_seconds: Optional[int] = None,
    ):
        self._workspace_id = workspace_id
        self._max_age_seconds = max_age_seconds or self.DEFAULT_MAX_AGE_SECONDS
        if lock_dir is None:
            lock_dir = Path.home() / ".debug_dashboard" / "locks"
        self._lock_dir = lock_dir
        self._lock_file = self._lock_dir / f"agent_{workspace_id}.lock"
        self._acquired = False

    @property
    def is_acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        self._lock_dir.mkdir(parents=True, exist_ok=True)

        if self._lock_file.exists():
            # Check if existing lock is stale
            try:
                content = self._lock_file.read_text().strip()
                parts = content.split(":")
                if len(parts) >= 2:
                    pid = int(parts[0])
                    lock_ts = float(parts[1]) if len(parts) >= 2 else 0
                    lock_age = time.time() - lock_ts if lock_ts else float("inf")

                    # Case 1: PID is dead → stale lock (crash/kill -9)
                    if not self._pid_alive(pid):
                        logger.info(
                            f"Stale lock detected (PID {pid} dead). Reclaiming."
                        )
                        self._lock_file.unlink(missing_ok=True)

                    # Case 2: PID alive but lock is extremely old
                    # → PID was recycled by OS to a different process
                    elif lock_age > self._max_age_seconds:
                        logger.warning(
                            f"Lock aged out ({lock_age:.0f}s > {self._max_age_seconds}s, "
                            f"PID {pid} likely recycled). Reclaiming."
                        )
                        self._lock_file.unlink(missing_ok=True)

                    # Case 3: PID alive and lock is fresh → genuine lock
                    else:
                        logger.warning(
                            f"Agent already running for workspace {self._workspace_id} "
                            f"(PID {pid}, age {lock_age:.0f}s). Skipping."
                        )
                        return False
                else:
                    # Malformed lock content
                    logger.warning("Malformed lock file, removing")
                    self._lock_file.unlink(missing_ok=True)
            except (ValueError, OSError) as e:
                logger.warning(f"Corrupt lock file, removing: {e}")
                self._lock_file.unlink(missing_ok=True)

        # Write our lock
        try:
            self._lock_file.write_text(
                f"{os.getpid()}:{time.time():.0f}:{self._workspace_id}"
            )
            self._acquired = True
            logger.info(
                f"Agent lock acquired for workspace {self._workspace_id} "
                f"(PID {os.getpid()})"
            )
            return True
        except OSError as e:
            logger.error(f"Failed to create lock file: {e}")
            return False

    def release(self):
        """Release the lock."""
        if self._acquired and self._lock_file.exists():
            try:
                # Only remove if we own it
                content = self._lock_file.read_text().strip()
                if content.startswith(f"{os.getpid()}:"):
                    self._lock_file.unlink(missing_ok=True)
                    logger.info(
                        f"Agent lock released for workspace {self._workspace_id}"
                    )
            except OSError:
                pass
        self._acquired = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a PID is still running."""
        try:
            os.kill(pid, 0)  # Signal 0 = check existence only
            return True
        except (OSError, ProcessLookupError):
            return False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(
                f"Could not acquire agent lock for workspace {self._workspace_id}"
            )
        return self

    def __exit__(self, *args):
        self.release()

    def __del__(self):
        self.release()
