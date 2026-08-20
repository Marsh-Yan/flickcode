"""Immutable public models for lifecycle Hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from flickcode.matching import ConditionGroup


class HookEventName(str, Enum):
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPING = "system.stopping"
    SESSION_STARTED = "session.started"
    SESSION_RESUMED = "session.resumed"
    SESSION_ENDING = "session.ending"
    TURN_STARTED = "turn.started"
    TURN_ENDED = "turn.ended"
    MESSAGE_USER_ACCEPTED = "message.user_accepted"
    MESSAGE_MODEL_REQUEST = "message.model_request"
    MESSAGE_ASSISTANT_COMPLETED = "message.assistant_completed"
    TOOL_BEFORE = "tool.before"
    TOOL_AFTER = "tool.after"
    AGENT_STARTED = "agent.started"
    AGENT_BACKGROUNDED = "agent.backgrounded"
    AGENT_COMPLETED = "agent.completed"
    AGENT_LIMITED = "agent.limited"
    AGENT_FAILED = "agent.failed"
    AGENT_CANCELLED = "agent.cancelled"


class HookSource(str, Enum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


class ActionType(str, Enum):
    SHELL = "shell"
    PROMPT = "prompt"
    HTTP = "http"
    SUBAGENT = "subagent"


class ProjectTrust(str, Enum):
    PENDING = "pending"
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class InterceptDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


def _positive_timeout(value: float) -> float:
    converted = float(value)
    if converted <= 0 or converted == float("inf"):
        raise ValueError("timeout must be a finite positive number")
    return converted


@dataclass(frozen=True)
class ShellAction:
    command: str
    cwd: Optional[str] = None
    env: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    type: ActionType = field(default=ActionType.SHELL, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.command, str) or not self.command:
            raise ValueError("shell action requires command")
        object.__setattr__(self, "timeout_seconds", _positive_timeout(self.timeout_seconds))


@dataclass(frozen=True)
class PromptAction:
    content: str
    type: ActionType = field(default=ActionType.PROMPT, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content:
            raise ValueError("prompt action requires content")


@dataclass(frozen=True)
class HttpAction:
    url: str
    method: str = "POST"
    headers: Mapping[str, str] = field(default_factory=dict)
    body: Any = None
    timeout_seconds: float = 10.0
    type: ActionType = field(default=ActionType.HTTP, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("http action requires url")
        if not isinstance(self.method, str) or not self.method:
            raise ValueError("http action requires method")
        object.__setattr__(self, "method", self.method.upper())
        object.__setattr__(self, "timeout_seconds", _positive_timeout(self.timeout_seconds))


@dataclass(frozen=True)
class SubAgentAction:
    task: str
    type: ActionType = field(default=ActionType.SUBAGENT, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task:
            raise ValueError("subagent action requires task")


HookAction = Union[ShellAction, PromptAction, HttpAction, SubAgentAction]


@dataclass(frozen=True)
class HookRule:
    rule_id: str
    name: Optional[str]
    event: HookEventName
    condition: Optional[ConditionGroup]
    action: HookAction
    once: bool
    asynchronous: bool
    source: HookSource
    source_path: Path
    source_index: int


@dataclass(frozen=True)
class HookEvent:
    name: HookEventName
    occurred_at: datetime
    context: Mapping[str, Any]


@dataclass(frozen=True)
class ActionResult:
    success: bool
    output: str = ""
    error: str = ""
    elapsed_seconds: float = 0.0
    status_code: Optional[int] = None
    exit_code: Optional[int] = None


@dataclass(frozen=True)
class InterceptResult:
    decision: Optional[InterceptDecision] = None
    reason: str = ""


@dataclass(frozen=True)
class HookDiagnostic:
    message: str
    rule_id: str = ""
    source: str = ""
    event: str = ""
    action: str = ""
    elapsed_seconds: float = 0.0
    fatal: bool = False

    def safe_text(self) -> str:
        identity = self.rule_id or "system"
        metadata = ", ".join(
            item for item in (
                self.source,
                self.event,
                self.action,
                f"{self.elapsed_seconds:.3f}s" if self.elapsed_seconds else "",
            )
            if item
        )
        suffix = f" [{metadata}]" if metadata else ""
        return f"Hook {identity}: {self.message}{suffix}"


@dataclass(frozen=True)
class HookOverride:
    name: str
    replaced_source: HookSource
    effective_source: HookSource


@dataclass(frozen=True)
class HookSnapshot:
    generation: int = 0
    rules: tuple[HookRule, ...] = ()
    diagnostics: tuple[HookDiagnostic, ...] = ()
    overrides: tuple[HookOverride, ...] = ()
    skipped_rules: int = 0


@dataclass(frozen=True)
class HookRefresh:
    previous: HookSnapshot
    candidate: Optional[HookSnapshot]
    fatal_diagnostics: tuple[HookDiagnostic, ...] = ()


@dataclass(frozen=True)
class HookDispatchResult:
    intercepted: bool = False
    reason: str = ""
    executed_rule_ids: tuple[str, ...] = ()
    diagnostics: tuple[HookDiagnostic, ...] = ()


@dataclass(frozen=True)
class HookRuleSummary:
    name: str
    action: str
    event: str


@dataclass(frozen=True)
class HookStatusSnapshot:
    started: bool = False
    active_rules: int = 0
    skipped_rules: int = 0
    project_trust: str = ProjectTrust.PENDING.value
    once_count: int = 0
    background_count: int = 0
    overrides: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
