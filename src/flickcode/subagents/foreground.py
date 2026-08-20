"""Cancellation and foreground detach controls."""

from __future__ import annotations

import threading
from typing import Callable, Optional


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def request_cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class ForegroundControl:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: str | None = None
        self._detach = False
        self._closed = False
        self._poll_callback: Optional[Callable[[], bool]] = None

    def set_poll_callback(self, callback: Optional[Callable[[], bool]]) -> None:
        """Install the interactive key poller; tests may inject a fake."""
        with self._lock:
            self._poll_callback = callback

    @property
    def active_task_id(self) -> str | None:
        with self._lock:
            return self._active

    def begin(self, task_id: str) -> None:
        with self._lock:
            if self._closed or self._active is not None:
                raise RuntimeError("foreground control is unavailable")
            self._active = task_id
            self._detach = False

    def request_detach(self, task_id: str) -> bool:
        with self._lock:
            if self._closed or self._active != task_id:
                return False
            self._detach = True
            return True

    def should_detach(self, task_id: str) -> bool:
        callback = None
        with self._lock:
            if self._active != task_id:
                return False
            callback = self._poll_callback
            requested = self._detach
        if not requested and callback is not None:
            try:
                requested = bool(callback())
            except Exception:
                requested = False
        if not requested:
            return False
        with self._lock:
            if self._active != task_id:
                return False
            self._detach = False
            return True

    def end(self, task_id: str) -> None:
        with self._lock:
            if self._active == task_id:
                self._active = None
                self._detach = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._active = None
            self._detach = False
            self._poll_callback = None
