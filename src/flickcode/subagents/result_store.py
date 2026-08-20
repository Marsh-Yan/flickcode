"""Session-lifetime storage for large SubAgent results."""

from __future__ import annotations

import re
import shutil
import tempfile
import threading
from pathlib import Path

_TASK_ID = re.compile(r"^agent-[0-9a-f]{12}$")


class SubAgentResultStore:
    def __init__(
        self,
        inline_chars: int = 16_384,
        max_chars: int = 1_000_000,
        base_dir: Path | None = None,
    ) -> None:
        if inline_chars <= 0 or max_chars < inline_chars:
            raise ValueError("result limits are invalid")
        self.inline_chars = inline_chars
        self.max_chars = max_chars
        parent = Path(base_dir or (Path.cwd() / ".tmp" / "subagents")).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="session-", dir=str(parent)))
        self._closed = False
        self._lock = threading.Lock()

    def store(self, task_id: str, content: str) -> tuple[str, Path | None, bool]:
        if not _TASK_ID.fullmatch(task_id):
            raise ValueError("task id is invalid")
        with self._lock:
            if self._closed:
                raise RuntimeError("result store is closed")
            truncated = len(content) > self.max_chars
            safe = content[: self.max_chars]
            if truncated:
                safe += "\n[truncated at configured result limit]"
            if len(safe) <= self.inline_chars:
                return safe, None, truncated
            path = self.root / f"{task_id}.txt"
            path.write_text(safe, encoding="utf-8")
            return "", path, truncated

    def read(self, path: Path) -> str:
        resolved = path.resolve()
        resolved.relative_to(self.root.resolve())
        return resolved.read_text(encoding="utf-8")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        shutil.rmtree(self.root, ignore_errors=True)
