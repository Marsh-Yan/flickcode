"""Public and internal data models for SubAgent delegation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, TYPE_CHECKING

from flickcode.agent import AgentMode, StopReason
from flickcode.permissions.models import PermissionMode
from flickcode.providers.base import Message
from flickcode.worktrees.models import (
    AgentIsolationMode,
    WorkspaceRequest,
    WorkspaceStatus,
)

if TYPE_CHECKING:
    from flickcode.config import ProviderConfig
    from flickcode.tools.registry import ToolRegistryView


class AgentRoleSource(str, Enum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
    PLUGIN = "plugin"


class AgentModelAlias(str, Enum):
    INHERIT = "inherit"
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


class AgentPermissionMode(str, Enum):
    INHERIT = "inherit"
    STRICT = "strict"
    DEFAULT = "default"
    PERMISSIVE = "permissive"


class AgentToolOperation(str, Enum):
    START = "start"
    STATUS = "status"
    RESULT = "result"
    CANCEL = "cancel"


class AgentInvocationType(str, Enum):
    DEFINED = "defined"
    FORK = "fork"


class SubAgentTaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    LIMITED = "limited"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATES = frozenset({
    SubAgentTaskState.COMPLETED,
    SubAgentTaskState.LIMITED,
    SubAgentTaskState.FAILED,
    SubAgentTaskState.CANCELLED,
})

LEGAL_TASK_TRANSITIONS = MappingProxyType({
    SubAgentTaskState.QUEUED: frozenset({SubAgentTaskState.RUNNING, SubAgentTaskState.CANCELLED}),
    SubAgentTaskState.RUNNING: TERMINAL_TASK_STATES,
    SubAgentTaskState.COMPLETED: frozenset(),
    SubAgentTaskState.LIMITED: frozenset(),
    SubAgentTaskState.FAILED: frozenset(),
    SubAgentTaskState.CANCELLED: frozenset(),
})


@dataclass(frozen=True)
class AgentRoleDefinition:
    name: str
    description: str
    allowed_tools: frozenset[str]
    denied_tools: frozenset[str]
    model: AgentModelAlias
    max_turns: int
    permission_mode: AgentPermissionMode
    system_prompt: str
    source: AgentRoleSource
    source_path: Path
    fingerprint: str
    isolation: AgentIsolationMode = AgentIsolationMode.SHARED


@dataclass(frozen=True)
class AgentRoleDiagnostic:
    severity: str
    phase: str
    message: str
    path: Optional[Path] = None
    role_name: str = ""


@dataclass(frozen=True)
class AgentRoleCatalogSnapshot:
    generation: int = 0
    effective: Mapping[str, AgentRoleDefinition] = field(
        default_factory=lambda: MappingProxyType({})
    )
    shadowed: Mapping[str, tuple[AgentRoleDefinition, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    diagnostics: tuple[AgentRoleDiagnostic, ...] = ()


@dataclass(frozen=True)
class AgentRoleCatalogCandidate:
    previous: AgentRoleCatalogSnapshot
    current: AgentRoleCatalogSnapshot


@dataclass
class AgentUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    rounds: int = 0

    def copy(self) -> "AgentUsage":
        return AgentUsage(**self.__dict__)


@dataclass(frozen=True)
class ParentRequestSnapshot:
    session_id: str
    turn_number: int
    mode: AgentMode
    messages: tuple[Message, ...]
    system_prompt: Optional[str]
    tool_view: "ToolRegistryView"
    provider_config: "ProviderConfig"
    thinking: bool


@dataclass(frozen=True)
class SubAgentLaunchSpec:
    task_id: str
    parent_session_id: str
    invocation_type: AgentInvocationType
    role: Optional[AgentRoleDefinition]
    task: str
    messages: tuple[Message, ...]
    system_prompt: str
    mode: AgentMode
    provider_config: "ProviderConfig"
    tool_view: "ToolRegistryView"
    permission_mode: PermissionMode
    max_turns: int
    thinking: bool
    forced_background: bool = False
    workspace_request: WorkspaceRequest = field(
        default_factory=lambda: WorkspaceRequest(AgentIsolationMode.SHARED, "")
    )


@dataclass(frozen=True)
class AgentToolRequest:
    operation: AgentToolOperation
    invocation_type: Optional[AgentInvocationType] = None
    task: Optional[str] = None
    role: Optional[str] = None
    background: Optional[bool] = None
    task_id: Optional[str] = None


@dataclass(frozen=True)
class AgentToolResponse:
    success: bool
    task_id: Optional[str] = None
    status: Optional[str] = None
    background: bool = False
    forced_background: bool = False
    summary: str = ""
    usage: Optional[AgentUsage] = None
    error: Optional[str] = None
    result: Optional[str] = None
    result_path: Optional[str] = None
    workspace: Optional[WorkspaceStatus] = None

    def to_dict(self) -> dict[str, Any]:
        value = dict(self.__dict__)
        if self.usage is not None:
            value["usage"] = dict(self.usage.__dict__)
        if self.workspace is not None:
            value["workspace"] = self.workspace.to_dict()
        return value


@dataclass
class SubAgentTaskRecord:
    task_id: str
    parent_session_id: str
    invocation_type: AgentInvocationType
    role_name: Optional[str]
    state: SubAgentTaskState
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    usage: AgentUsage = field(default_factory=AgentUsage)
    stop_reason: Optional[StopReason] = None
    summary: str = ""
    result: str = ""
    result_path: Optional[Path] = None
    error: str = ""
    cancel_requested: bool = False
    background: bool = False
    notified: bool = False
    workspace: WorkspaceStatus = field(default_factory=WorkspaceStatus)


@dataclass(frozen=True)
class SubAgentTaskSnapshot:
    task_id: str
    parent_session_id: str
    invocation_type: AgentInvocationType
    role_name: Optional[str]
    state: SubAgentTaskState
    created_at: datetime
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    usage: AgentUsage
    stop_reason: Optional[StopReason]
    summary: str
    error: str
    cancel_requested: bool
    background: bool
    workspace: WorkspaceStatus = field(default_factory=WorkspaceStatus)


@dataclass(frozen=True)
class SubAgentResultView:
    task_id: str
    state: SubAgentTaskState
    result: str = ""
    result_path: Optional[Path] = None
    truncated: bool = False


@dataclass(frozen=True)
class SubAgentExecutionResult:
    state: SubAgentTaskState
    content: str
    summary: str
    usage: AgentUsage
    stop_reason: StopReason
    error: str = ""


@dataclass(frozen=True)
class AgentNotification:
    task_id: str
    state: SubAgentTaskState
    summary: str
    stop_reason: str
    usage: AgentUsage
    result_hint: str
    workspace: WorkspaceStatus = field(default_factory=WorkspaceStatus)


@dataclass(frozen=True)
class AgentHookMetadata:
    agent_kind: str = "parent"
    task_id: str = ""
    parent_task_id: str = ""
    invocation_type: str = ""
    role_name: str = ""
    isolation: AgentIsolationMode = AgentIsolationMode.SHARED
    project_root: str = ""
    worktree_root: str = ""
    branch: str = ""
