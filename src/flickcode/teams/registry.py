"""Stable member-name to durable route registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

from flickcode.teams.locking import locked
from flickcode.teams.paths import TeamLayout


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


class NameRegistry:
    def __init__(self, layout: TeamLayout, *, retry_seconds: float = 2.0, stale_seconds: float = 30.0) -> None:
        self.layout = layout
        self.retry_seconds = retry_seconds
        self.stale_seconds = stale_seconds

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.layout.registry.exists():
            return {}
        with self.layout.registry.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("team registry must be a map")
        return {str(key): dict(item) for key, item in value.items() if isinstance(item, Mapping)}

    def register(
        self,
        *,
        name: str,
        member_id: str,
        mailbox_path: Path,
        context_path: Path,
        backend: str,
        state: str,
        runtime_handle: Optional[str] = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("member name must be non-empty")
        with locked(self.layout.lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            value = self._read()
            current = value.get(name)
            if current is not None and current.get("member_id") != member_id:
                raise ValueError(f"member name already registered: {name}")
            value[name] = {
                "member_id": member_id,
                "mailbox_path": str(mailbox_path),
                "context_path": str(context_path),
                "backend": backend,
                "state": state,
                "runtime_handle": runtime_handle,
            }
            _atomic_json(self.layout.registry, value)

    def resolve(self, name: str) -> dict[str, Any]:
        with locked(self.layout.lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            value = self._read()
        route = value.get(name)
        if route is None:
            raise KeyError(f"Unknown team member: {name}")
        return dict(route)

    def update_runtime(self, member_id: str, *, state: str, runtime_handle: Optional[str], backend: Optional[str] = None) -> None:
        with locked(self.layout.lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            value = self._read()
            found = None
            for route in value.values():
                if route.get("member_id") == member_id:
                    found = route
                    break
            if found is None:
                raise KeyError(f"Unknown team member id: {member_id}")
            found["state"] = state
            found["runtime_handle"] = runtime_handle
            if backend is not None:
                found["backend"] = backend
            _atomic_json(self.layout.registry, value)

    def remove(self, member_id: str) -> None:
        with locked(self.layout.lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            value = self._read()
            value = {name: route for name, route in value.items() if route.get("member_id") != member_id}
            _atomic_json(self.layout.registry, value)

    def routes(self) -> dict[str, dict[str, Any]]:
        with locked(self.layout.lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            return self._read()

