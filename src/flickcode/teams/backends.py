"""Member backend selection and runtime handles."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from flickcode.teams.models import BackendSelection, MemberBackendKind, TeamMemberRecord
from flickcode.teams.pane import PaneAdapter, PaneHandle, default_pane_adapters


@dataclass(frozen=True)
class MemberLaunch:
    command: tuple[str, ...] = ()
    cwd: Optional[Path] = None


@dataclass(frozen=True)
class BackendHandle:
    backend: MemberBackendKind
    token: str
    raw: object = None


class BackendUnavailable(RuntimeError):
    pass


class InProcessMemberBackend:
    kind = MemberBackendKind.IN_PROCESS

    def __init__(self) -> None:
        self._handles: dict[str, BackendHandle] = {}

    def probe(self) -> tuple[bool, str]:
        return True, "in-process scheduler available"

    def start(self, member: TeamMemberRecord, launch: MemberLaunch) -> BackendHandle:
        token = "inproc-" + secrets.token_hex(8)
        handle = BackendHandle(self.kind, token)
        self._handles[token] = handle
        return handle

    def wake(self, handle: BackendHandle, reason: str = "mailbox") -> bool:
        return handle.token in self._handles

    def stop(self, handle: BackendHandle) -> None:
        self._handles.pop(handle.token, None)


class PaneMemberBackend:
    kind = MemberBackendKind.PANE

    def __init__(self, adapters: Mapping[str, PaneAdapter]) -> None:
        self.adapters = dict(adapters)
        self._handles: dict[str, tuple[PaneAdapter, PaneHandle]] = {}

    def probe(self) -> tuple[bool, str]:
        reasons = []
        for adapter in self.adapters.values():
            ok, reason = adapter.probe()
            if ok:
                return True, f"{adapter.name}: {reason}"
            reasons.append(f"{adapter.name}: {reason}")
        return False, "; ".join(reasons) or "no pane adapters configured"

    def start(self, member: TeamMemberRecord, launch: MemberLaunch) -> BackendHandle:
        command = launch.command
        if not command:
            raise BackendUnavailable("pane backend requires a launch command")
        for adapter in self.adapters.values():
            ok, _ = adapter.probe()
            if not ok:
                continue
            pane = adapter.start(command, cwd=launch.cwd or member.workdir)
            token = "pane-" + secrets.token_hex(8)
            handle = BackendHandle(self.kind, token, pane)
            self._handles[token] = (adapter, pane)
            return handle
        raise BackendUnavailable("no configured terminal pane adapter is available")

    def wake(self, handle: BackendHandle, reason: str = "mailbox") -> bool:
        item = self._handles.get(handle.token)
        if item is None:
            return False
        adapter, pane = item
        return adapter.wake(pane, reason)

    def stop(self, handle: BackendHandle) -> None:
        item = self._handles.pop(handle.token, None)
        if item is not None:
            item[0].stop(item[1])


class BackendSelector:
    def __init__(self, *, pane_adapters: Mapping[str, PaneAdapter] | None = None) -> None:
        adapters = pane_adapters if pane_adapters is not None else default_pane_adapters(("tmux", "windows_terminal"))
        self._backends = {
            MemberBackendKind.PANE: PaneMemberBackend(adapters),
            MemberBackendKind.IN_PROCESS: InProcessMemberBackend(),
        }

    def choose(self, preference: Sequence[MemberBackendKind | str]) -> BackendSelection:
        probes = []
        for item in preference:
            kind = MemberBackendKind(item)
            backend = self._backends[kind]
            ok, reason = backend.probe()
            probes.append((kind.value, ok, reason))
            if ok:
                return BackendSelection(kind, f"selected {kind.value}: {reason}", tuple(probes))
        return BackendSelection(None, "no preferred member backend is available", tuple(probes))

    def backend(self, kind: MemberBackendKind):
        return self._backends[kind]
