"""Persistent shared task list with direct dependency checks."""

from __future__ import annotations

import json
import secrets
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Optional

from flickcode.teams.locking import locked
from flickcode.teams.models import TeamRecord, TeamTaskRecord, TeamTaskState, utc_now
from flickcode.teams.paths import TeamLayout


_TERMINAL = frozenset({TeamTaskState.COMPLETED, TeamTaskState.FAILED, TeamTaskState.CANCELLED, TeamTaskState.ROLLED_BACK})
_LEGAL = {
    TeamTaskState.PENDING: frozenset({TeamTaskState.BLOCKED, TeamTaskState.READY, TeamTaskState.CANCELLED}),
    TeamTaskState.BLOCKED: frozenset({TeamTaskState.READY, TeamTaskState.CANCELLED}),
    TeamTaskState.READY: frozenset({TeamTaskState.IN_PROGRESS, TeamTaskState.CANCELLED}),
    TeamTaskState.IN_PROGRESS: frozenset({TeamTaskState.COMPLETED, TeamTaskState.FAILED, TeamTaskState.CANCELLED, TeamTaskState.ROLLED_BACK}),
    TeamTaskState.COMPLETED: frozenset(),
    TeamTaskState.FAILED: frozenset(),
    TeamTaskState.CANCELLED: frozenset(),
    TeamTaskState.ROLLED_BACK: frozenset(),
}


class TaskStore:
    def __init__(self, team: TeamRecord, *, retry_seconds: float = 2.0, stale_seconds: float = 30.0) -> None:
        self.team = team
        self.layout = TeamLayout(team.root)
        self.retry_seconds = retry_seconds
        self.stale_seconds = stale_seconds

    def _read(self) -> dict[str, TeamTaskRecord]:
        if not self.layout.tasks.exists():
            return {}
        with self.layout.tasks.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("tasks file must be a map")
        return {key: TeamTaskRecord.from_dict(item) for key, item in value.items()}

    def _write(self, tasks: dict[str, TeamTaskRecord]) -> None:
        self.layout.root.mkdir(parents=True, exist_ok=True)
        temporary = self.layout.tasks.with_name(self.layout.tasks.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump({key: value.to_dict() for key, value in tasks.items()}, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(self.layout.tasks)

    def list_tasks(self, *, state: Optional[TeamTaskState] = None) -> tuple[TeamTaskRecord, ...]:
        with locked(self.layout.tasks_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            tasks = self._read()
        values = tuple(sorted(tasks.values(), key=lambda item: item.created_at))
        return tuple(item for item in values if state is None or item.state is state)

    def get_task(self, task_id: str) -> TeamTaskRecord:
        with locked(self.layout.tasks_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            task = self._read().get(task_id)
        if task is None:
            raise KeyError(f"Unknown team task: {task_id}")
        return task

    def create_task(
        self,
        title: str,
        description: str = "",
        *,
        assignee_id: Optional[str] = None,
        dependency_ids: Iterable[str] = (),
        created_by: str = "",
    ) -> TeamTaskRecord:
        if not title.strip():
            raise ValueError("task title must be non-empty")
        deps = tuple(dict.fromkeys(str(item) for item in dependency_ids))
        task_id = "task-" + secrets.token_hex(6)
        now = utc_now()
        with locked(self.layout.tasks_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            tasks = self._read()
            if any(task_id in task.dependency_ids for task in tasks.values()):
                raise RuntimeError("generated duplicate task id")
            missing = [dep for dep in deps if dep not in tasks]
            if missing:
                raise ValueError("unknown task dependency: " + ", ".join(missing))
            if task_id in deps or self._would_cycle(tasks, task_id, deps):
                raise ValueError("task dependencies contain a cycle")
            state = TeamTaskState.READY if not deps else TeamTaskState.BLOCKED
            task = TeamTaskRecord(task_id, self.team.team_id, title.strip(), description, assignee_id, deps, state, created_by, now, now)
            tasks[task_id] = task
            self._write(tasks)
            return task

    @staticmethod
    def _would_cycle(tasks: dict[str, TeamTaskRecord], task_id: str, deps: tuple[str, ...]) -> bool:
        edges = {key: set(value.dependency_ids) for key, value in tasks.items()}
        edges[task_id] = set(deps)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for dependency in edges.get(node, ()):
                if visit(dependency):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in edges)

    def update_task(self, task_id: str, **changes) -> TeamTaskRecord:
        allowed = {"title", "description", "assignee_id", "dependency_ids", "result_summary", "error"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("unsupported task field(s): " + ", ".join(sorted(unknown)))
        with locked(self.layout.tasks_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            tasks = self._read()
            current = tasks.get(task_id)
            if current is None:
                raise KeyError(f"Unknown team task: {task_id}")
            deps = tuple(dict.fromkeys(str(item) for item in changes.get("dependency_ids", current.dependency_ids)))
            missing = [dep for dep in deps if dep not in tasks]
            if missing:
                raise ValueError("unknown task dependency: " + ", ".join(missing))
            if self._would_cycle(tasks, task_id, deps):
                raise ValueError("task dependencies contain a cycle")
            updated = replace(current, **{key: value for key, value in changes.items() if key != "dependency_ids"}, dependency_ids=deps, updated_at=utc_now())
            if updated.state in {TeamTaskState.PENDING, TeamTaskState.BLOCKED, TeamTaskState.READY}:
                updated = replace(updated, state=self._readiness(updated, tasks))
            tasks[task_id] = updated
            self._write(tasks)
            return updated

    def start_task(self, task_id: str) -> TeamTaskRecord:
        return self._transition(task_id, TeamTaskState.IN_PROGRESS)

    def complete_task(self, task_id: str, summary: str = "") -> TeamTaskRecord:
        return self._transition(task_id, TeamTaskState.COMPLETED, result_summary=summary)

    def fail_task(self, task_id: str, error: str) -> TeamTaskRecord:
        return self._transition(task_id, TeamTaskState.FAILED, error=error)

    def cancel_task(self, task_id: str) -> TeamTaskRecord:
        return self._transition(task_id, TeamTaskState.CANCELLED)

    def _transition(self, task_id: str, state: TeamTaskState, **changes) -> TeamTaskRecord:
        with locked(self.layout.tasks_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            tasks = self._read()
            current = tasks.get(task_id)
            if current is None:
                raise KeyError(f"Unknown team task: {task_id}")
            if current.state is state:
                return current
            if state not in _LEGAL[current.state]:
                raise ValueError(f"illegal task transition: {current.state.value} -> {state.value}")
            if state is TeamTaskState.IN_PROGRESS and self._readiness(current, tasks) is not TeamTaskState.READY:
                raise ValueError("task dependencies are not complete")
            updated = replace(current, state=state, updated_at=utc_now(), **changes)
            tasks[task_id] = updated
            self._write(tasks)
            return updated

    @staticmethod
    def _readiness(task: TeamTaskRecord, tasks: dict[str, TeamTaskRecord]) -> TeamTaskState:
        if not task.dependency_ids:
            return TeamTaskState.READY
        return TeamTaskState.READY if all(tasks[dep].state is TeamTaskState.COMPLETED for dep in task.dependency_ids) else TeamTaskState.BLOCKED

    def ready_tasks(self) -> tuple[TeamTaskRecord, ...]:
        with locked(self.layout.tasks_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            tasks = self._read()
            changed = False
            for key, task in list(tasks.items()):
                if task.state in {TeamTaskState.PENDING, TeamTaskState.BLOCKED}:
                    state = self._readiness(task, tasks)
                    if state is not task.state:
                        tasks[key] = replace(task, state=state, updated_at=utc_now())
                        changed = True
            if changed:
                self._write(tasks)
            return tuple(task for task in tasks.values() if task.state is TeamTaskState.READY)

