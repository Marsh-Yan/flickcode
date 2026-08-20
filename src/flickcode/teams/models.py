"""Data models for durable team collaboration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class TeamStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class MemberBackendKind(str, Enum):
    PANE = "pane"
    IN_PROCESS = "in_process"


class MemberState(str, Enum):
    REGISTERED = "registered"
    STARTING = "starting"
    BUSY = "busy"
    IDLE = "idle"
    STOPPED = "stopped"
    FAILED = "failed"


class TeamTaskState(str, Enum):
    PENDING = "pending"
    BLOCKED = "blocked"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class TeamRecord:
    team_id: str
    name: str
    lead_member_id: str
    root: Path
    created_at: datetime
    updated_at: datetime
    status: TeamStatus = TeamStatus.ACTIVE
    coordinator_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "lead_member_id": self.lead_member_id,
            "root": str(self.root),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status.value,
            "coordinator_enabled": self.coordinator_enabled,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamRecord":
        return cls(
            team_id=str(value["team_id"]),
            name=str(value["name"]),
            lead_member_id=str(value["lead_member_id"]),
            root=Path(str(value["root"])).expanduser().resolve(strict=False),
            created_at=_datetime(value["created_at"]),
            updated_at=_datetime(value["updated_at"]),
            status=TeamStatus(str(value.get("status", TeamStatus.ACTIVE.value))),
            coordinator_enabled=bool(value.get("coordinator_enabled", False)),
        )


@dataclass(frozen=True)
class TeamMemberRecord:
    member_id: str
    name: str
    team_id: str
    role: str
    workdir: Path
    backend: MemberBackendKind
    backend_reason: str = ""
    approval_required: bool = False
    state: MemberState = MemberState.REGISTERED
    mailbox_path: Path = Path()
    context_path: Path = Path()
    runtime_handle: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "name": self.name,
            "team_id": self.team_id,
            "role": self.role,
            "workdir": str(self.workdir),
            "backend": self.backend.value,
            "backend_reason": self.backend_reason,
            "approval_required": self.approval_required,
            "state": self.state.value,
            "mailbox_path": str(self.mailbox_path),
            "context_path": str(self.context_path),
            "runtime_handle": self.runtime_handle,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamMemberRecord":
        return cls(
            member_id=str(value["member_id"]),
            name=str(value["name"]),
            team_id=str(value["team_id"]),
            role=str(value["role"]),
            workdir=Path(str(value["workdir"])).expanduser().resolve(strict=False),
            backend=MemberBackendKind(str(value["backend"])),
            backend_reason=str(value.get("backend_reason", "")),
            approval_required=bool(value.get("approval_required", False)),
            state=MemberState(str(value.get("state", MemberState.REGISTERED.value))),
            mailbox_path=Path(str(value.get("mailbox_path", ""))).expanduser(),
            context_path=Path(str(value.get("context_path", ""))).expanduser(),
            runtime_handle=value.get("runtime_handle"),
            created_at=_datetime(value.get("created_at", utc_now().isoformat())),
            updated_at=_datetime(value.get("updated_at", utc_now().isoformat())),
            last_error=str(value.get("last_error", "")),
        )


@dataclass(frozen=True)
class TeamTaskRecord:
    task_id: str
    team_id: str
    title: str
    description: str
    assignee_id: Optional[str]
    dependency_ids: tuple[str, ...]
    state: TeamTaskState
    created_by: str
    created_at: datetime
    updated_at: datetime
    result_summary: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "team_id": self.team_id,
            "title": self.title,
            "description": self.description,
            "assignee_id": self.assignee_id,
            "dependency_ids": list(self.dependency_ids),
            "state": self.state.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "result_summary": self.result_summary,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamTaskRecord":
        deps = value.get("dependency_ids", [])
        if not isinstance(deps, (list, tuple)):
            raise ValueError("dependency_ids must be a list")
        return cls(
            task_id=str(value["task_id"]),
            team_id=str(value["team_id"]),
            title=str(value["title"]),
            description=str(value.get("description", "")),
            assignee_id=value.get("assignee_id"),
            dependency_ids=tuple(str(item) for item in deps),
            state=TeamTaskState(str(value.get("state", TeamTaskState.PENDING.value))),
            created_by=str(value.get("created_by", "")),
            created_at=_datetime(value["created_at"]),
            updated_at=_datetime(value["updated_at"]),
            result_summary=str(value.get("result_summary", "")),
            error=str(value.get("error", "")),
        )


@dataclass(frozen=True)
class TeamMessage:
    message_id: str
    team_id: str
    sender_id: str
    recipient_id: Optional[str]
    kind: str
    body: str
    summary: str
    timestamp: datetime
    read: bool = False
    protocol_version: int = 1
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "team_id": self.team_id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "kind": self.kind,
            "body": self.body,
            "summary": self.summary,
            "timestamp": self.timestamp.isoformat(),
            "read": self.read,
            "protocol_version": self.protocol_version,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamMessage":
        payload = value.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("message payload must be a map")
        return cls(
            message_id=str(value["message_id"]),
            team_id=str(value["team_id"]),
            sender_id=str(value["sender_id"]),
            recipient_id=value.get("recipient_id"),
            kind=str(value["kind"]),
            body=str(value.get("body", "")),
            summary=str(value.get("summary", "")),
            timestamp=_datetime(value["timestamp"]),
            read=bool(value.get("read", False)),
            protocol_version=int(value.get("protocol_version", 1)),
            payload=dict(payload),
        )


@dataclass(frozen=True)
class BackendSelection:
    backend: Optional[MemberBackendKind]
    reason: str
    probes: tuple[tuple[str, bool, str], ...] = ()


@dataclass(frozen=True)
class RuntimeSnapshot:
    member_id: str
    state: MemberState
    backend: MemberBackendKind
    runtime_handle: Optional[str] = None
    task_id: Optional[str] = None
    error: str = ""

