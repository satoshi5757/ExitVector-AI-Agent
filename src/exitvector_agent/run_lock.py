"""Non-blocking OS process lock, with readable local watch/run metadata.

The inode/file is retained on release: unlinking lock files creates ownership races.
Process death releases the kernel lock; a timeout never steals a live owner's lock.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    def __init__(self, database_path: Path, timeout_minutes: float = 60) -> None:
        resolved = database_path.resolve()
        self.path = resolved.with_suffix(resolved.suffix + ".agent.lock")
        self.timeout_minutes = timeout_minutes
        self.handle = None
        self.metadata: dict[str, Any] = {}
        self.recovered = False

    def acquire(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0"); handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise AlreadyRunning("Another ExitVector orchestrator owns this database lock") from exc
        self.handle = handle
        try:
            old = self.read_metadata()
            self.recovered = bool(old.get("active"))
            self.update(active=True, pid=os.getpid(), next_run_at=None)
        except BaseException:
            handle.close()  # Closing releases the OS lock even if metadata writing failed.
            self.handle = None
            raise
        return self

    def read_metadata(self) -> dict[str, Any]:
        try:
            with self.path.open("rb") as reader:
                reader.seek(1)  # The locked byte stays readable only by its owner on Windows.
                payload = json.loads(reader.read(65536))
                return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def update(self, **metadata) -> None:
        if self.handle is None:
            raise RuntimeError("Lock is not owned")
        self.metadata.update(metadata)
        self.handle.seek(1)
        self.handle.truncate()
        self.handle.write(json.dumps(self.metadata).encode("utf-8"))
        self.handle.flush()

    def release(self) -> None:
        if self.handle is None:
            return
        handle = self.handle
        try:
            self.update(active=False, next_run_at=None, run_id=None)
        finally:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
                self.handle = None

    def state(self) -> dict[str, Any]:
        """Probe an existing lock without creating it or changing metadata."""
        if not self.path.exists():
            return {"active": False, "path": str(self.path)}
        metadata = self.read_metadata()
        try:
            with self.path.open("r+b") as handle:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            active = False
        except OSError:
            active = True
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(metadata['started_at'])).total_seconds() / 60
        except (KeyError, ValueError, TypeError):
            age = 0
        return {**metadata, "active": active, "stale": bool(metadata.get("active")) and not active,
                "long_running": active and age > self.timeout_minutes,
                "path": str(self.path)}

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()
