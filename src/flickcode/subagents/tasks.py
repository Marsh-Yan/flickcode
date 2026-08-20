"""Bounded in-memory SubAgent task manager."""

from __future__ import annotations

import secrets
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

from flickcode.agent import StopReason
from flickcode.subagents.foreground import CancellationToken, ForegroundControl
from flickcode.subagents.models import (
    AgentNotification,
    AgentUsage,
    LEGAL_TASK_TRANSITIONS,
    SubAgentExecutionResult,
    SubAgentLaunchSpec,
    SubAgentResultView,
    SubAgentTaskRecord,
    SubAgentTaskSnapshot,
    SubAgentTaskState,
    TERMINAL_TASK_STATES,
)
from flickcode.subagents.notifications import NotificationInbox
from flickcode.subagents.result_store import SubAgentResultStore
from flickcode.worktrees.models import WorktreeDisposition, WorkspaceStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SubAgentTaskManager:
    def __init__(
        self,
        runner: Callable[[SubAgentLaunchSpec, CancellationToken], SubAgentExecutionResult],
        notifications: NotificationInbox,
        result_store: SubAgentResultStore,
        foreground: ForegroundControl,
        *,
        max_workers: int = 4,
        max_pending: int = 16,
        foreground_timeout: float = 30.0,
        poll_interval: float = 0.05,
        event_callback: Optional[Callable[[str, SubAgentTaskSnapshot], None]] = None,
    ) -> None:
        self.runner = runner
        self.notifications = notifications
        self.result_store = result_store
        self.foreground = foreground
        self.foreground_timeout = foreground_timeout
        self.poll_interval = poll_interval
        self.event_callback = event_callback
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="flick-agent")
        self._slots = threading.BoundedSemaphore(max_workers + max_pending)
        self._lock = threading.RLock()
        self._records: dict[str, SubAgentTaskRecord] = {}
        self._futures: dict[str, Future] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._closed = False

    @staticmethod
    def new_task_id() -> str:
        return "agent-" + secrets.token_hex(6)

    def submit(self, spec: SubAgentLaunchSpec, background: bool) -> SubAgentTaskSnapshot:
        with self._lock:
            if self._closed:
                raise RuntimeError("SubAgent task manager is closed")
            if not self._slots.acquire(blocking=False):
                raise RuntimeError("SubAgent capacity is full")
            record = SubAgentTaskRecord(
                task_id=spec.task_id,
                parent_session_id=spec.parent_session_id,
                invocation_type=spec.invocation_type,
                role_name=spec.role.name if spec.role else None,
                state=SubAgentTaskState.QUEUED,
                created_at=utc_now(),
                background=background,
                workspace=WorkspaceStatus(),
            )
            token = CancellationToken()
            self._records[spec.task_id] = record
            self._tokens[spec.task_id] = token
            try:
                future = self._pool.submit(self._run, spec, token)
            except Exception:
                self._records.pop(spec.task_id, None)
                self._tokens.pop(spec.task_id, None)
                self._slots.release()
                raise
            self._futures[spec.task_id] = future
            return self._snapshot(record)

    def _run(self, spec: SubAgentLaunchSpec, token: CancellationToken) -> None:
        try:
            with self._lock:
                record = self._records[spec.task_id]
                if record.state is SubAgentTaskState.CANCELLED:
                    return
                self._transition(record, SubAgentTaskState.RUNNING)
                record.started_at = utc_now()
                started = self._snapshot(record)
            self._emit("started", started)
            try:
                result = self.runner(spec, token)
            except Exception as exc:
                result = SubAgentExecutionResult(
                    SubAgentTaskState.FAILED,
                    "",
                    "SubAgent failed.",
                    AgentUsage(),
                    StopReason.ERROR,
                    str(exc)[:2048],
                )
            self._finish(spec.task_id, result)
        finally:
            self._slots.release()

    def _finish(self, task_id: str, result: SubAgentExecutionResult) -> None:
        notification = None
        with self._lock:
            record = self._records[task_id]
            if record.state in TERMINAL_TASK_STATES:
                return
            self._transition(record, result.state)
            record.ended_at = utc_now()
            record.usage = result.usage.copy()
            record.stop_reason = result.stop_reason
            record.summary = result.summary
            record.error = result.error
            inline, path, _ = self.result_store.store(task_id, result.content or result.error)
            record.result = inline
            record.result_path = path
            if record.background:
                notification = AgentNotification(
                    task_id=task_id,
                    state=record.state,
                    summary=record.summary,
                    stop_reason=result.stop_reason.value,
                    usage=record.usage.copy(),
                    result_hint=f'use agent(operation="result", task_id="{task_id}")',
                    workspace=record.workspace,
                )
                record.notified = True
        if notification is not None:
            self.notifications.publish(notification)
        self._emit(result.state.value, self.status(task_id))

    def _emit(self, event: str, snapshot: SubAgentTaskSnapshot) -> None:
        if self.event_callback is None:
            return
        try:
            self.event_callback(event, snapshot)
        except Exception:
            pass

    @staticmethod
    def _transition(record: SubAgentTaskRecord, state: SubAgentTaskState) -> None:
        if state not in LEGAL_TASK_TRANSITIONS[record.state]:
            raise RuntimeError(f"Illegal task transition: {record.state.value} -> {state.value}")
        record.state = state

    @staticmethod
    def _snapshot(record: SubAgentTaskRecord) -> SubAgentTaskSnapshot:
        return SubAgentTaskSnapshot(
            task_id=record.task_id,
            parent_session_id=record.parent_session_id,
            invocation_type=record.invocation_type,
            role_name=record.role_name,
            state=record.state,
            created_at=record.created_at,
            started_at=record.started_at,
            ended_at=record.ended_at,
            usage=record.usage.copy(),
            stop_reason=record.stop_reason,
            summary=record.summary,
            error=record.error,
            cancel_requested=record.cancel_requested,
            background=record.background,
            workspace=record.workspace,
        )

    def record_workspace(self, task_id: str, workspace: WorkspaceStatus) -> None:
        """Record entered/terminal workspace state without changing task state."""
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return
            current = record.workspace
            if (
                current.disposition is not WorktreeDisposition.NOT_USED
                and workspace.disposition is WorktreeDisposition.NOT_USED
            ):
                return
            record.workspace = workspace

    def status(self, task_id: str) -> SubAgentTaskSnapshot:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(f"Unknown SubAgent task: {task_id}")
            return self._snapshot(record)

    def result(self, task_id: str) -> SubAgentResultView:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(f"Unknown SubAgent task: {task_id}")
            content = record.result
            path = record.result_path
            state = record.state
        if path is not None:
            content = self.result_store.read(path)
        return SubAgentResultView(task_id, state, content, path, "[truncated" in content)

    def cancel(self, task_id: str) -> SubAgentTaskSnapshot:
        notification = None
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(f"Unknown SubAgent task: {task_id}")
            if record.state in TERMINAL_TASK_STATES:
                return self._snapshot(record)
            record.cancel_requested = True
            self._tokens[task_id].request_cancel()
            if record.state is SubAgentTaskState.QUEUED:
                self._transition(record, SubAgentTaskState.CANCELLED)
                record.ended_at = utc_now()
                record.stop_reason = StopReason.USER_CANCELLED
                record.summary = "SubAgent cancelled before it started."
                if record.background and not record.notified:
                    notification = AgentNotification(
                        task_id=task_id,
                        state=record.state,
                        summary=record.summary,
                        stop_reason=StopReason.USER_CANCELLED.value,
                        usage=record.usage.copy(),
                        result_hint=f'use agent(operation="result", task_id="{task_id}")',
                        workspace=record.workspace,
                    )
                    record.notified = True
            snapshot = self._snapshot(record)
        if notification is not None:
            self.notifications.publish(notification)
        if snapshot.state is SubAgentTaskState.CANCELLED:
            self._emit("cancelled", snapshot)
        return snapshot

    def wait_or_detach(self, task_id: str) -> SubAgentTaskSnapshot:
        self.foreground.begin(task_id)
        deadline = time.monotonic() + self.foreground_timeout
        try:
            while True:
                snapshot = self.status(task_id)
                if snapshot.state in TERMINAL_TASK_STATES:
                    return snapshot
                if self.foreground.should_detach(task_id) or time.monotonic() >= deadline:
                    notification = None
                    with self._lock:
                        record = self._records[task_id]
                        record.background = True
                        if record.state in TERMINAL_TASK_STATES and not record.notified:
                            notification = AgentNotification(
                                task_id=task_id,
                                state=record.state,
                                summary=record.summary,
                                stop_reason=(record.stop_reason or StopReason.ERROR).value,
                                usage=record.usage.copy(),
                                result_hint=f'use agent(operation="result", task_id="{task_id}")',
                                workspace=record.workspace,
                            )
                            record.notified = True
                    if notification is not None:
                        self.notifications.publish(notification)
                    snapshot = self.status(task_id)
                    self._emit("backgrounded", snapshot)
                    return snapshot
                time.sleep(self.poll_interval)
        finally:
            self.foreground.end(task_id)

    def counts(self) -> dict[str, int]:
        with self._lock:
            result: dict[str, int] = {}
            for record in self._records.values():
                result[record.state.value] = result.get(record.state.value, 0) + 1
            return result

    def close(self, timeout: float = 5.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            task_ids = list(self._records)
        for task_id in task_ids:
            try:
                self.cancel(task_id)
            except Exception:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if all(r.state in TERMINAL_TASK_STATES for r in self._records.values()):
                    break
            time.sleep(self.poll_interval)
        try:
            self._pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # compatibility with small test/fallback executors
            self._pool.shutdown(wait=False)
        self.foreground.close()
