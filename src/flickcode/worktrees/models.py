"""Data models for Git Worktree isolation.

The models in this module intentionally do not import the SubAgent package.
The dependency direction is ``subagents -> worktrees`` so that the lifecycle
service can also be used by future non-agent callers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional


class WorktreeError(RuntimeError):
    """Base error for Worktree operations."""


class WorktreeConfigError(ValueError):
    """Raised for invalid project Worktree configuration."""


class WorktreeGitError(WorktreeError):
    """Raised when a Git operation fails or cannot be verified safely."""


class WorktreeRecoveryError(WorktreeError):
    """Raised when an existing directory cannot be safely recovered."""


class AgentIsolationMode(str, Enum):
    SHARED = "shared"
    WORKTREE = "worktree"


class WorktreeDisposition(str, Enum):
    NOT_USED = "not_used"
    REMOVED = "removed"
    RETAINED_CHANGES = "retained_changes"
    RETAINED_UNPUSHED = "retained_unpushed"
    RETAINED_CHECK_FAILED = "retained_check_failed"


@dataclass(frozen=True)
class WorktreeBootstrapConfig:
    copy: tuple[str, ...] = ()
    symlink: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorktreeConfig:
    expiry_days: int = 7
    bootstrap: WorktreeBootstrapConfig = field(
        default_factory=WorktreeBootstrapConfig
    )

    def __post_init__(self) -> None:
        if isinstance(self.expiry_days, bool) or not isinstance(self.expiry_days, int):
            raise WorktreeConfigError("expiry_days must be an integer")
        if self.expiry_days <= 0:
            raise WorktreeConfigError("expiry_days must be positive")
        if not isinstance(self.bootstrap, WorktreeBootstrapConfig):
            raise WorktreeConfigError("bootstrap must be a WorktreeBootstrapConfig")


@dataclass(frozen=True)
class WorktreeDiagnostic:
    severity: str
    phase: str
    message: str
    path: Optional[Path] = None


@dataclass(frozen=True)
class RepositoryIdentity:
    repository_root: Path
    main_project_root: Path
    project_relative_path: Path
    common_git_dir: Path
    fingerprint: str

    @classmethod
    def create(
        cls,
        repository_root: Path,
        main_project_root: Path,
        common_git_dir: Path,
    ) -> "RepositoryIdentity":
        repo = repository_root.expanduser().resolve()
        project = main_project_root.expanduser().resolve()
        common = common_git_dir.expanduser().resolve()
        try:
            relative = project.relative_to(repo)
        except ValueError as exc:
            raise WorktreeError(
                "Project root must be inside the repository root"
            ) from exc
        seed = "\n".join((str(repo), str(common))).encode("utf-8")
        fingerprint = hashlib.sha256(seed).hexdigest()
        return cls(repo, project, relative, common, fingerprint)


def _as_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise WorktreeRecoveryError(f"metadata {field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorktreeRecoveryError(
            f"metadata {field_name} is not a valid timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise WorktreeRecoveryError(f"metadata {field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class WorktreeMetadata:
    schema_version: int
    repository_fingerprint: str
    logical_name: str
    worktree_root: Path
    project_root: Path
    branch: str
    base_commit: str
    created_at: datetime
    last_used_at: datetime
    initialization_state: str

    SCHEMA_VERSION = 1

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != self.SCHEMA_VERSION:
            raise WorktreeRecoveryError("unsupported Worktree metadata version")
        for name, value in (
            ("repository_fingerprint", self.repository_fingerprint),
            ("logical_name", self.logical_name),
            ("branch", self.branch),
            ("base_commit", self.base_commit),
            ("initialization_state", self.initialization_state),
        ):
            if not isinstance(value, str):
                raise WorktreeRecoveryError(f"metadata {name} must be a string")
        for name, value in (
            ("worktree_root", self.worktree_root),
            ("project_root", self.project_root),
        ):
            if not isinstance(value, Path) or not value.is_absolute():
                raise WorktreeRecoveryError(f"metadata {name} must be absolute")
        if not self.logical_name or not self.repository_fingerprint:
            raise WorktreeRecoveryError("metadata identity fields must be non-empty")
        if not self.branch or not self.base_commit:
            raise WorktreeRecoveryError("metadata branch/base_commit must be non-empty")
        if self.initialization_state not in {"creating", "ready", "failed"}:
            raise WorktreeRecoveryError("metadata initialization_state is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repository_fingerprint": self.repository_fingerprint,
            "logical_name": self.logical_name,
            "worktree_root": str(self.worktree_root),
            "project_root": str(self.project_root),
            "branch": self.branch,
            "base_commit": self.base_commit,
            "created_at": _timestamp(self.created_at),
            "last_used_at": _timestamp(self.last_used_at),
            "initialization_state": self.initialization_state,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "WorktreeMetadata":
        required = {
            "schema_version",
            "repository_fingerprint",
            "logical_name",
            "worktree_root",
            "project_root",
            "branch",
            "base_commit",
            "created_at",
            "last_used_at",
            "initialization_state",
        }
        if set(raw) != required:
            missing = sorted(required - set(raw))
            unknown = sorted(set(raw) - required)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise WorktreeRecoveryError("invalid metadata fields: " + "; ".join(details))
        if not isinstance(raw["schema_version"], int) or isinstance(
            raw["schema_version"], bool
        ):
            raise WorktreeRecoveryError("metadata schema_version must be an integer")
        for key in (
            "repository_fingerprint",
            "logical_name",
            "branch",
            "base_commit",
            "initialization_state",
        ):
            if not isinstance(raw[key], str):
                raise WorktreeRecoveryError(f"metadata {key} must be a string")
        paths = {}
        for key in ("worktree_root", "project_root"):
            if not isinstance(raw[key], str):
                raise WorktreeRecoveryError(f"metadata {key} must be a string")
            path = Path(raw[key]).expanduser()
            if not path.is_absolute():
                raise WorktreeRecoveryError(f"metadata {key} must be absolute")
            paths[key] = path.resolve()
        return cls(
            schema_version=raw["schema_version"],
            repository_fingerprint=str(raw["repository_fingerprint"]),
            logical_name=str(raw["logical_name"]),
            worktree_root=paths["worktree_root"],
            project_root=paths["project_root"],
            branch=str(raw["branch"]),
            base_commit=str(raw["base_commit"]),
            created_at=_as_datetime(raw["created_at"], "created_at"),
            last_used_at=_as_datetime(raw["last_used_at"], "last_used_at"),
            initialization_state=str(raw["initialization_state"]),
        )


@dataclass(frozen=True)
class WorkspaceContext:
    isolation: AgentIsolationMode
    project_root: Path
    repository_root: Path
    main_project_root: Path
    task_id: str
    logical_name: str = ""
    branch: str = ""

    def __post_init__(self) -> None:
        project = self.project_root.expanduser().resolve()
        repository = self.repository_root.expanduser().resolve()
        main = self.main_project_root.expanduser().resolve()
        if not project.is_absolute() or not repository.is_absolute() or not main.is_absolute():
            raise WorktreeError("workspace paths must be absolute")
        try:
            project.relative_to(repository)
        except ValueError as exc:
            raise WorktreeError("workspace paths must stay inside repository root") from exc
        object.__setattr__(self, "project_root", project)
        object.__setattr__(self, "repository_root", repository)
        object.__setattr__(self, "main_project_root", main)


@dataclass(frozen=True)
class WorkspaceRequest:
    isolation: AgentIsolationMode
    task_id: str
    logical_name: str = ""


@dataclass(frozen=True)
class WorktreeHandle:
    metadata: WorktreeMetadata
    workspace: WorkspaceContext
    recovered: bool = False


@dataclass
class WorktreeLease:
    handle: WorktreeHandle
    released: bool = False
    outcome: Optional[WorktreeOutcome] = None


@dataclass(frozen=True)
class WorktreeSafetyReport:
    clean: bool
    changed_paths: tuple[str, ...] = ()
    unique_commits: tuple[str, ...] = ()
    unpushed_commits: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorktreeOutcome:
    disposition: WorktreeDisposition
    path: Optional[Path]
    branch: str = ""
    reason: str = ""


@dataclass(frozen=True)
class WorkspaceStatus:
    path: Optional[Path] = None
    branch: str = ""
    recovered: bool = False
    disposition: WorktreeDisposition = WorktreeDisposition.NOT_USED
    reason: str = ""
    worktree_root: Optional[Path] = None
    main_project_root: Optional[Path] = None
    isolation: AgentIsolationMode = AgentIsolationMode.SHARED

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path) if self.path else None,
            "branch": self.branch,
            "recovered": self.recovered,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "worktree_root": str(self.worktree_root) if self.worktree_root else None,
            "main_project_root": str(self.main_project_root) if self.main_project_root else None,
            "isolation": self.isolation.value,
        }


def metadata_json(metadata: WorktreeMetadata) -> str:
    """Return stable JSON for diagnostics and atomic persistence."""
    return json.dumps(metadata.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
