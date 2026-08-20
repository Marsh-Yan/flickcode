"""Bounded, deduplicated SubAgent completion notifications."""

from __future__ import annotations

import threading
from collections import deque

from flickcode.subagents.models import AgentNotification


class NotificationInbox:
    def __init__(self, max_items: int = 256) -> None:
        self._lock = threading.Lock()
        self._items: deque[AgentNotification] = deque()
        self._seen: set[str] = set()
        self._max_items = max_items
        self._closed = False

    def publish(self, item: AgentNotification) -> bool:
        with self._lock:
            if self._closed or item.task_id in self._seen or len(self._items) >= self._max_items:
                return False
            self._seen.add(item.task_id)
            self._items.append(item)
            return True

    def drain(self) -> tuple[AgentNotification, ...]:
        with self._lock:
            result = tuple(self._items)
            self._items.clear()
            return result

    def close(self) -> None:
        with self._lock:
            self._closed = True


def serialize_notification(item: AgentNotification, max_summary: int = 2048) -> str:
    summary = item.summary[:max_summary]
    usage = item.usage
    return (
        "<agent-notification>\n"
        f"task_id: {item.task_id}\n"
        f"status: {item.state.value}\n"
        f"summary: {summary}\n"
        f"stop_reason: {item.stop_reason}\n"
        "usage: "
        f"input={usage.input_tokens} output={usage.output_tokens} "
        f"thinking={usage.thinking_tokens} cache_create={usage.cache_creation_input_tokens} "
        f"cache_read={usage.cache_read_input_tokens} rounds={usage.rounds}\n"
        f"workspace: path={str(item.workspace.path) if item.workspace.path else ''} "
        f"worktree_root={str(item.workspace.worktree_root) if item.workspace.worktree_root else ''} "
        f"branch={item.workspace.branch} disposition={item.workspace.disposition.value} "
        f"isolation={item.workspace.isolation.value} "
        f"reason={item.workspace.reason}\n"
        f"result: {item.result_hint}\n"
        "</agent-notification>"
    )
