"""Safe Git integration for member branches."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class MergeResult:
    success: bool
    rolled_back: bool
    target: Path
    merged: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    error: str = ""


class TeamGitIntegrator:
    def __init__(self, executable: str = "git", timeout: float = 60.0) -> None:
        self.executable = executable
        self.timeout = timeout

    def _run(self, args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
        root = Path(cwd).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Git cwd is not a directory: {root}")
        result = subprocess.run(
            [self.executable, *args],
            cwd=str(root),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[:2048]
            raise RuntimeError(f"git {' '.join(args[:4])} failed: {detail}")
        return result

    def preview(self, target: Path, branches: Iterable[str]) -> tuple[str, ...]:
        values = tuple(str(branch) for branch in branches)
        for branch in values:
            self._run(["check-ref-format", "--branch", branch], target)
        return values

    def merge_all(self, target: Path, branches: Iterable[str]) -> MergeResult:
        target = Path(target).expanduser().resolve()
        values = self.preview(target, branches)
        head = self._run(["rev-parse", "HEAD"], target).stdout.strip()
        merged: list[str] = []
        try:
            for branch in values:
                self._run(["merge", "--no-edit", "--no-ff", branch], target)
                merged.append(branch)
            return MergeResult(True, False, target, tuple(merged))
        except Exception as exc:
            self._run(["merge", "--abort"], target, check=False)
            self._run(["reset", "--merge", head], target, check=False)
            conflicts = tuple(
                line.strip()
                for line in self._run(["diff", "--name-only", "--diff-filter=U"], target, check=False).stdout.splitlines()
                if line.strip()
            )
            return MergeResult(False, True, target, tuple(merged), conflicts, str(exc))

