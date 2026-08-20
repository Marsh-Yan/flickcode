"""Terminal pane adapters for isolated team members."""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


@dataclass(frozen=True)
class PaneHandle:
    adapter: str
    handle: str
    process_id: Optional[int] = None


class PaneAdapter:
    name = "pane"

    def probe(self) -> tuple[bool, str]:
        raise NotImplementedError

    def start(self, command: Sequence[str], *, cwd: Path) -> PaneHandle:
        raise NotImplementedError

    def wake(self, handle: PaneHandle, reason: str = "mailbox") -> bool:
        raise NotImplementedError

    def stop(self, handle: PaneHandle) -> None:
        raise NotImplementedError


class CommandPaneAdapter(PaneAdapter):
    """Minimal adapter around a terminal command, without shell parsing."""

    def __init__(self, name: str, executable: str, prefix: Sequence[str] = ()) -> None:
        self.name = name
        self.executable = executable
        self.prefix = tuple(prefix)
        self._processes: dict[str, subprocess.Popen] = {}

    def probe(self) -> tuple[bool, str]:
        path = shutil.which(self.executable)
        if path is None:
            return False, f"executable not found: {self.executable}"
        return True, path

    def start(self, command: Sequence[str], *, cwd: Path) -> PaneHandle:
        available, reason = self.probe()
        if not available:
            raise RuntimeError(reason)
        if not command:
            raise ValueError("pane launch command must be non-empty")
        token = "pane-" + secrets.token_hex(8)
        process = subprocess.Popen(
            [self.executable, *self.prefix, *tuple(str(item) for item in command)],
            cwd=str(Path(cwd).expanduser().resolve()),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._processes[token] = process
        return PaneHandle(self.name, token, process.pid)

    def wake(self, handle: PaneHandle, reason: str = "mailbox") -> bool:
        process = self._processes.get(handle.handle)
        if process is None:
            return False
        return process.poll() is None

    def stop(self, handle: PaneHandle) -> None:
        process = self._processes.pop(handle.handle, None)
        if process is None:
            return
        if process.poll() is None:
            process.terminate()


class TmuxPaneAdapter(CommandPaneAdapter):
    def __init__(self) -> None:
        super().__init__("tmux", "tmux", ("new-window", "-d"))


class WindowsTerminalPaneAdapter(CommandPaneAdapter):
    def __init__(self) -> None:
        super().__init__("windows_terminal", "wt", ("-w", "0", "split-pane", "--"))


def default_pane_adapters(names: Sequence[str]) -> dict[str, PaneAdapter]:
    available = {
        "tmux": TmuxPaneAdapter(),
        "windows_terminal": WindowsTerminalPaneAdapter(),
    }
    unknown = sorted(set(names) - set(available))
    if unknown:
        raise ValueError("unknown pane adapter(s): " + ", ".join(unknown))
    return {name: available[name] for name in names}

