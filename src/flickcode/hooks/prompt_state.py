"""Thread-safe prompt scopes and once state."""

from __future__ import annotations

import threading


class PromptState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._system: list[tuple[str, str]] = []
        self._session: list[tuple[str, str]] = []
        self._pending: list[tuple[str, str]] = []
        self._once: set[str] = set()

    def add_system(self, rule_id: str, content: str) -> None:
        with self._lock:
            self._system.append((rule_id, content))

    def add_session(self, rule_id: str, content: str) -> None:
        with self._lock:
            self._session.append((rule_id, content))

    def add_pending(self, rule_id: str, content: str) -> None:
        with self._lock:
            self._pending.append((rule_id, content))

    def persistent(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(text for _, text in self._system + self._session)

    def consume_pending(self) -> tuple[str, ...]:
        with self._lock:
            result = tuple(text for _, text in self._pending)
            self._pending.clear()
            return result

    def begin_session(self) -> None:
        with self._lock:
            self._session.clear()
            self._pending.clear()
            self._once.clear()

    def end_session(self) -> None:
        with self._lock:
            self._session.clear()
            self._pending.clear()
            self._once.clear()

    def has_run(self, rule_id: str) -> bool:
        with self._lock:
            return rule_id in self._once

    def mark_run(self, rule_id: str) -> None:
        with self._lock:
            self._once.add(rule_id)

    @property
    def once_count(self) -> int:
        with self._lock:
            return len(self._once)
