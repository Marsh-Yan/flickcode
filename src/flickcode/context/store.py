"""Safe local storage for oversized tool results and summaries."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from flickcode.context.models import ContextConfig, StoredResult


class ContextStorageError(RuntimeError):
    """Raised when a context artifact cannot be written safely."""


class ResultStore:
    """Store context artifacts without overwriting caller-owned files."""

    _SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")

    def __init__(self, config: ContextConfig):
        self.config = config
        self.root = config.storage_dir.expanduser()

    def store_tool_result(
        self,
        *,
        session_id: str,
        message_index: int,
        tool_call_id: str,
        tool_name: str,
        content: str,
    ) -> StoredResult:
        """Persist a complete tool output and return a compact preview."""
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        filename = "-".join(
            [
                "tool",
                self._safe_component(session_id),
                str(message_index),
                self._safe_component(tool_name or "unknown"),
                self._safe_component(tool_call_id or "no-call-id"),
                digest,
            ]
        ) + ".txt"
        path = self._write_unique(filename, content)
        preview = self._tool_preview(
            path=path,
            tool_name=tool_name or "unknown",
            tool_call_id=tool_call_id or "unknown",
            original_chars=len(content),
        )
        return StoredResult(
            path=path,
            preview=preview,
            original_chars=len(content),
            content_hash=digest,
        )

    def store_summary(self, *, session_id: str, summary: str) -> Path:
        """Persist a summary copy for inspection and recovery."""
        digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16]
        filename = "-".join(
            ["summary", self._safe_component(session_id), digest]
        ) + ".md"
        return self._write_unique(filename, summary)

    def _write_unique(self, filename: str, content: str) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            root = self.root.resolve()
        except OSError as exc:
            raise ContextStorageError(
                f"Could not create context storage directory {self.root}: {exc}"
            ) from exc

        candidate = root / filename
        stem = candidate.stem
        suffix = candidate.suffix
        for counter in range(10_000):
            path = candidate if counter == 0 else root / f"{stem}-{counter}{suffix}"
            try:
                with path.open("x", encoding="utf-8", newline="") as handle:
                    handle.write(content)
                return path.resolve()
            except FileExistsError:
                continue
            except OSError as exc:
                raise ContextStorageError(
                    f"Could not store context artifact at {path}: {exc}"
                ) from exc

        raise ContextStorageError(
            f"Could not create a unique context artifact under {root}"
        )

    @classmethod
    def _safe_component(cls, value: str) -> str:
        cleaned = cls._SAFE_COMPONENT.sub("-", value).strip(".-")
        return cleaned[:80] or "unknown"

    @staticmethod
    def _tool_preview(
        *,
        path: Path,
        tool_name: str,
        tool_call_id: str,
        original_chars: int,
    ) -> str:
        return (
            "[FlickCode stored tool result]\n"
            f"Tool: {tool_name}\n"
            f"Tool call ID: {tool_call_id}\n"
            f"Original size: {original_chars} characters\n"
            f"Full result path: {path}\n"
            "Read this file again with a tool when details are needed. "
            "Do not infer unavailable details from this preview."
        )
