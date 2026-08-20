"""File-backed, scope-separated long-term notes and bounded indexes."""

from __future__ import annotations

import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

from flickcode.memory.models import (
    MemoryCategory,
    MemoryChange,
    MemoryDiagnostic,
    MemoryNote,
)


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


class MemoryRepository:
    """Manage one user or project note scope below a fixed root directory."""

    def __init__(
        self,
        root: Path,
        scope: str,
        *,
        index_max_lines: int = 200,
        index_max_bytes: int = 25 * 1024,
    ) -> None:
        if scope not in ("user", "project"):
            raise ValueError("scope must be 'user' or 'project'")
        if not 0 < index_max_lines <= 200 or not 0 < index_max_bytes <= 25 * 1024:
            raise ValueError("memory index limits exceed the supported bounds")
        self.root = root.expanduser().resolve()
        self.scope = scope
        self.index_max_lines = index_max_lines
        self.index_max_bytes = index_max_bytes

    @property
    def index_path(self) -> Path:
        return self.root / "index.md"

    def read_index(self) -> tuple[str, list[MemoryDiagnostic]]:
        if not self.index_path.exists():
            return "", []
        try:
            return self.index_path.read_text(encoding="utf-8"), []
        except (OSError, UnicodeError) as exc:
            return "", [MemoryDiagnostic(self.index_path, f"Cannot read memory index: {exc}")]

    def read_notes_for_update(self) -> tuple[list[MemoryNote], list[MemoryDiagnostic]]:
        if not self.root.exists():
            return [], []
        notes: list[MemoryNote] = []
        diagnostics: list[MemoryDiagnostic] = []
        try:
            paths = sorted(self.root.glob("*.md"))
        except OSError as exc:
            return [], [MemoryDiagnostic(self.root, f"Cannot list memory notes: {exc}")]
        for path in paths:
            if path.name == "index.md" or not path.is_file():
                continue
            try:
                notes.append(self._read_note(path))
            except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
                diagnostics.append(MemoryDiagnostic(path, f"Cannot read memory note: {exc}"))
        return notes, diagnostics

    def apply(self, changes: list[MemoryChange]) -> list[MemoryDiagnostic]:
        """Apply validated scope changes, then regenerate the bounded index."""
        diagnostics: list[MemoryDiagnostic] = []
        if not changes:
            return diagnostics
        with self._lock():
            notes, read_errors = self.read_notes_for_update()
            diagnostics.extend(read_errors)
            by_id = {note.note_id: note for note in notes}
            changed = False
            for change in changes:
                error = self._validate_change(change, by_id)
                if error:
                    diagnostics.append(MemoryDiagnostic(None, error))
                    continue
                if change.action == "discard":
                    continue
                note = by_id.get(change.note_id or "")
                now = _utc_now()
                if note is None:
                    note = MemoryNote(
                        note_id=change.note_id or self._new_note_id(),
                        category=change.category,  # validated above
                        content=change.content.strip(),
                        created_at=now,
                        updated_at=now,
                    )
                    by_id[note.note_id] = note
                else:
                    note.category = change.category  # type: ignore[misc]
                    note.content = change.content.strip()
                    note.updated_at = now
                try:
                    self._write_note(note)
                    changed = True
                except OSError as exc:
                    diagnostics.append(MemoryDiagnostic(self._note_path(note.note_id), f"Cannot write memory note: {exc}"))
            if changed:
                try:
                    self._write_index(list(by_id.values()))
                except OSError as exc:
                    diagnostics.append(MemoryDiagnostic(self.index_path, f"Cannot write memory index: {exc}"))
        return diagnostics

    def _validate_change(self, change: MemoryChange, existing: dict[str, MemoryNote]) -> str | None:
        if change.scope != self.scope:
            return f"Memory change has wrong scope: {change.scope}"
        if change.action not in ("upsert", "discard"):
            return f"Unsupported memory action: {change.action}"
        if change.action == "discard":
            return None
        if not isinstance(change.category, MemoryCategory):
            return "Memory upsert needs an allowed category"
        if not isinstance(change.content, str) or not change.content.strip():
            return "Memory upsert needs non-empty content"
        if len(change.content.encode("utf-8")) > 16 * 1024:
            return "Memory note content exceeds 16 KB"
        if change.note_id is not None and not self._safe_note_id(change.note_id):
            return "Memory note id is invalid"
        if change.note_id and change.note_id not in existing:
            return "Memory update refers to an unknown note id"
        return None

    def _read_note(self, path: Path) -> MemoryNote:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError("note has no frontmatter")
        try:
            _, frontmatter, content = text.split("---\n", 2)
        except ValueError as exc:
            raise ValueError("note frontmatter is incomplete") from exc
        raw = yaml.safe_load(frontmatter)
        if not isinstance(raw, dict):
            raise ValueError("note frontmatter must be a map")
        note_id = raw.get("id")
        if not isinstance(note_id, str) or not self._safe_note_id(note_id):
            raise ValueError("note id is invalid")
        try:
            category = MemoryCategory(raw.get("category"))
        except (TypeError, ValueError) as exc:
            raise ValueError("note category is invalid") from exc
        body = content.strip()
        if not body:
            raise ValueError("note content is empty")
        return MemoryNote(
            note_id=note_id,
            category=category,
            content=body,
            created_at=_parse_timestamp(raw.get("created_at")),
            updated_at=_parse_timestamp(raw.get("updated_at")),
        )

    def _write_note(self, note: MemoryNote) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        frontmatter = {
            "id": note.note_id,
            "category": note.category.value,
            "created_at": _to_timestamp(note.created_at),
            "updated_at": _to_timestamp(note.updated_at),
        }
        content = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + note.content.strip() + "\n"
        self._atomic_write(self._note_path(note.note_id), content)

    def _write_index(self, notes: list[MemoryNote]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        ordered = sorted(notes, key=lambda item: (item.updated_at, item.note_id), reverse=True)
        header = f"# FlickCode {self.scope.title()} Memory Index\n"
        result = header if self._within_index_limits(header) else ""
        for note in ordered:
            summary = " ".join(note.content.split())[:400]
            item = (
                f"- [{note.category.value}] {note.note_id} "
                f"({_to_timestamp(note.updated_at)}): {summary}\n"
            )
            candidate = result + item
            if not self._within_index_limits(candidate):
                break
            result = candidate
        self._atomic_write(self.index_path, result)

    def _within_index_limits(self, value: str) -> bool:
        return (
            len(value.splitlines()) <= self.index_max_lines
            and len(value.encode("utf-8")) <= self.index_max_bytes
        )

    def _note_path(self, note_id: str) -> Path:
        return self.root / f"{note_id}.md"

    @staticmethod
    def _safe_note_id(note_id: str) -> bool:
        return bool(note_id) and all(ch.isalnum() or ch in "-_" for ch in note_id)

    @staticmethod
    def _new_note_id() -> str:
        return _utc_now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)

    def _lock(self) -> threading.Lock:
        with _LOCKS_GUARD:
            return _LOCKS.setdefault(self.root, threading.Lock())

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
