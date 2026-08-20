"""Per-agent file content cache keyed by absolute paths and file versions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Dict, Optional


@dataclass(frozen=True)
class FileVersion:
    mtime_ns: int
    size: int
    inode: int = 0
    ctime_ns: int = 0


@dataclass(frozen=True)
class _Entry:
    version: FileVersion
    content: str


class FileContentCache:
    def __init__(self) -> None:
        self._entries: Dict[Path, _Entry] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _version(path: Path) -> FileVersion:
        stat = path.stat()
        return FileVersion(
            getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
            stat.st_size,
            getattr(stat, "st_ino", 0),
            getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000)),
        )

    def read_text(self, path: Path, encoding: str = "utf-8") -> str:
        key = path.expanduser().resolve()
        version = self._version(key)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.version == version:
                return entry.content
            content = key.read_text(encoding=encoding)
            self._entries[key] = _Entry(version, content)
            return content

    def invalidate(self, path: Path) -> None:
        with self._lock:
            self._entries.pop(path.expanduser().resolve(), None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def keys(self) -> tuple[Path, ...]:
        with self._lock:
            return tuple(self._entries)


__all__ = ["FileContentCache", "FileVersion"]
