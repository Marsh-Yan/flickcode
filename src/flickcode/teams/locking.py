"""Small cross-process lock-file primitive used by team storage."""

from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


class LockTimeoutError(TimeoutError):
    pass


class FileLock:
    def __init__(
        self,
        path: Path,
        *,
        retry_seconds: float = 2.0,
        stale_seconds: float = 30.0,
        poll_seconds: float = 0.02,
    ) -> None:
        if retry_seconds <= 0 or stale_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("lock timing values must be positive")
        self.path = Path(path)
        self.retry_seconds = retry_seconds
        self.stale_seconds = stale_seconds
        self.poll_seconds = poll_seconds
        self._token: Optional[str] = None

    def acquire(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.retry_seconds
        token = secrets.token_hex(12)
        while True:
            try:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                descriptor = os.open(str(self.path), flags)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump({"pid": os.getpid(), "token": token, "created_at": time.time()}, handle)
                self._token = token
                return self
            except FileExistsError:
                self._remove_if_stale()
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(f"Timed out acquiring team lock: {self.path}")
                time.sleep(min(self.poll_seconds, max(0.0, deadline - time.monotonic())))

    def _remove_if_stale(self) -> None:
        try:
            stat = self.path.stat()
            if time.time() - stat.st_mtime <= self.stale_seconds:
                return
            observed_mtime = stat.st_mtime_ns
            current = self.path.stat()
            if current.st_mtime_ns != observed_mtime:
                return
            self.path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    def release(self) -> None:
        token = self._token
        self._token = None
        if token is None:
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if value.get("token") != token:
                return
            self.path.unlink(missing_ok=True)
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            return

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


@contextmanager
def locked(path: Path, **kwargs) -> Iterator[FileLock]:
    lock = FileLock(path, **kwargs)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()

