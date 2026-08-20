"""Path validation, repository probing and Worktree metadata storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flickcode.worktrees.models import (
    RepositoryIdentity,
    WorktreeMetadata,
    WorktreeRecoveryError,
)


_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


class WorktreeNameError(ValueError):
    """Raised when a logical Worktree name is unsafe."""


@dataclass(frozen=True)
class WorktreeName:
    value: str
    segments: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str) -> "WorktreeName":
        if not isinstance(raw, str):
            raise WorktreeNameError("Worktree name must be a string")
        if not raw or len(raw) > 200:
            raise WorktreeNameError("Worktree name length must be 1..200")
        if "\\" in raw or ":" in raw:
            raise WorktreeNameError("Worktree name contains a forbidden separator")
        if raw.startswith("/") or raw.endswith("/") or "//" in raw:
            raise WorktreeNameError("Worktree name contains an empty path segment")
        segments = tuple(raw.split("/"))
        if len(segments) > 8:
            raise WorktreeNameError("Worktree name has too many path segments")
        for segment in segments:
            if segment in {".", ".."}:
                raise WorktreeNameError("dot path segments are forbidden")
            if not _SEGMENT_RE.fullmatch(segment):
                raise WorktreeNameError(
                    "each Worktree segment must start with a lowercase letter/digit "
                    "and contain only lowercase letters, digits, '.', '_' or '-'"
                )
        return cls(raw, segments)

    def target(self, managed_root: Path) -> Path:
        root = managed_root.expanduser().resolve()
        candidate = root.joinpath(*self.segments).resolve(strict=False)
        _assert_within(candidate, root, "Worktree target")
        return candidate

    def casefold_key(self) -> str:
        return self.value.casefold()


def _assert_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorktreeNameError(f"{label} escapes managed root") from exc


@dataclass(frozen=True)
class RepositoryProbe:
    identity: RepositoryIdentity
    git_dir: Path


class RepositoryLocator:
    """Find a repository using filesystem reads only."""

    @classmethod
    def probe_filesystem(cls, project_root: Path) -> RepositoryProbe:
        start = project_root.expanduser().resolve()
        for candidate in (start,) + tuple(start.parents):
            marker = candidate / ".git"
            if not marker.exists() and not marker.is_file():
                continue
            git_dir = cls._resolve_git_dir(marker)
            common_dir = cls._resolve_common_dir(git_dir)
            if not common_dir.is_dir():
                raise WorktreeRecoveryError(
                    f"Git common directory does not exist: {common_dir}"
                )
            identity = RepositoryIdentity.create(candidate, start, common_dir)
            return RepositoryProbe(identity=identity, git_dir=git_dir)
        raise WorktreeRecoveryError(f"No Git repository found above {start}")

    @staticmethod
    def _resolve_git_dir(marker: Path) -> Path:
        if marker.is_dir():
            return marker.resolve()
        try:
            first = marker.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, UnicodeError, IndexError) as exc:
            raise WorktreeRecoveryError(f"Cannot read Git marker: {marker}") from exc
        prefix = "gitdir:"
        if not first.lower().startswith(prefix):
            raise WorktreeRecoveryError(f"Invalid linked Git marker: {marker}")
        raw = first[len(prefix) :].strip()
        if not raw:
            raise WorktreeRecoveryError(f"Empty linked Git directory: {marker}")
        path = Path(raw)
        if not path.is_absolute():
            path = marker.parent / path
        return path.resolve()

    @staticmethod
    def _resolve_common_dir(git_dir: Path) -> Path:
        commondir = git_dir / "commondir"
        if not commondir.exists():
            return git_dir
        try:
            raw = commondir.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise WorktreeRecoveryError(f"Cannot read Git commondir: {commondir}") from exc
        path = Path(raw)
        if not path.is_absolute():
            path = git_dir / path
        return path.resolve()


@dataclass(frozen=True)
class WorktreeLayout:
    repository_root: Path
    managed_root: Path
    state_root: Path

    @classmethod
    def from_identity(cls, identity: RepositoryIdentity) -> "WorktreeLayout":
        managed = (identity.repository_root / ".flickcode" / "worktrees").resolve()
        state = (managed / ".state").resolve()
        _assert_within(managed, identity.repository_root, "Managed root")
        _assert_within(state, managed, "Worktree state root")
        return cls(identity.repository_root, managed, state)

    def target(self, name: WorktreeName) -> Path:
        return name.target(self.managed_root)

    def state_path(self, name: WorktreeName) -> Path:
        digest = hashlib.sha256(name.value.encode("utf-8")).hexdigest()
        path = (self.state_root / f"{digest}.json").resolve(strict=False)
        _assert_within(path, self.state_root, "Worktree state path")
        return path

    def branch_name(self, name: WorktreeName, task_id: str) -> str:
        if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
            raise WorktreeNameError("task id is not safe for a Worktree branch")
        digest = hashlib.sha256(name.value.encode("utf-8")).hexdigest()[:8]
        return f"flick/agents/{task_id}-{digest}"

    def ensure_dirs(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)


class WorktreeMetadataStore:
    """Atomic sidecar storage kept outside linked Worktrees."""

    def __init__(self, layout: WorktreeLayout) -> None:
        self.layout = layout

    def load(self, name: WorktreeName) -> Optional[WorktreeMetadata]:
        path = self.layout.state_path(name)
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise WorktreeRecoveryError("Worktree metadata is not a regular file")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorktreeRecoveryError(f"Cannot read Worktree metadata: {path}") from exc
        if not isinstance(raw, dict):
            raise WorktreeRecoveryError("Worktree metadata root must be a map")
        return WorktreeMetadata.from_mapping(raw)

    def save(self, name: WorktreeName, metadata: WorktreeMetadata) -> Path:
        self.layout.ensure_dirs()
        path = self.layout.state_path(name)
        payload = json.dumps(
            metadata.to_dict(), ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"
        temporary = None
        try:
            fd, raw_path = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=str(self.layout.state_root)
            )
            temporary = Path(raw_path)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary), str(path))
            temporary = None
            return path
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def delete(self, name: WorktreeName) -> None:
        path = self.layout.state_path(name)
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise WorktreeRecoveryError("Refusing to delete non-file metadata")
            path.unlink()
