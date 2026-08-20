"""Fixed event schemas and isolated event-context builders."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

from flickcode.hooks.models import HookEvent, HookEventName


_AGENT_ID = {
    "agent.task_id", "agent.parent_task_id", "agent.kind", "agent.invocation_type",
    "agent.role_name", "agent.state", "agent.background", "agent.stop_reason",
    "agent.isolation", "agent.project_root", "agent.worktree_root", "agent.branch",
}
_COMMON = {"event.name", "system.cwd", "system.config_sources"} | _AGENT_ID
_SESSION = _COMMON | {"session.id", "session.state"}
_TURN = _SESSION | {"turn.number", "turn.mode", "turn.stop_reason"}
_MESSAGE = _TURN | {"message.role", "message.content", "message.stage"}
_TOOL = _TURN | {
    "tool.call_id", "tool.name", "tool.arguments", "tool.result",
}
_AGENT = _SESSION

EVENT_SCHEMAS = {
    HookEventName.SYSTEM_STARTED: _COMMON,
    HookEventName.SYSTEM_STOPPING: _COMMON,
    HookEventName.SESSION_STARTED: _SESSION,
    HookEventName.SESSION_RESUMED: _SESSION,
    HookEventName.SESSION_ENDING: _SESSION,
    HookEventName.TURN_STARTED: _TURN,
    HookEventName.TURN_ENDED: _TURN,
    HookEventName.MESSAGE_USER_ACCEPTED: _MESSAGE,
    HookEventName.MESSAGE_MODEL_REQUEST: _MESSAGE,
    HookEventName.MESSAGE_ASSISTANT_COMPLETED: _MESSAGE,
    HookEventName.TOOL_BEFORE: _TOOL,
    HookEventName.TOOL_AFTER: _TOOL,
    HookEventName.AGENT_STARTED: _AGENT,
    HookEventName.AGENT_BACKGROUNDED: _AGENT,
    HookEventName.AGENT_COMPLETED: _AGENT,
    HookEventName.AGENT_LIMITED: _AGENT,
    HookEventName.AGENT_FAILED: _AGENT,
    HookEventName.AGENT_CANCELLED: _AGENT,
}


def event_schema(name: HookEventName) -> frozenset[str]:
    if name not in EVENT_SCHEMAS:
        raise ValueError(f"unsupported Hook event: {name}")
    return frozenset(EVENT_SCHEMAS[name])


def _freeze(value: Any) -> Any:
    value = copy.deepcopy(value)
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def build_event(
    name: HookEventName,
    *,
    cwd: Path,
    config_sources: tuple[str, ...] = (),
    session_id: str = "",
    session_state: str = "",
    turn_number: int = 0,
    turn_mode: str = "",
    turn_stop_reason: str = "",
    message_role: str = "",
    message_content: Any = "",
    message_stage: str = "",
    tool_call_id: str = "",
    tool_name: str = "",
    tool_arguments: Optional[Mapping[str, Any]] = None,
    tool_result: Optional[Mapping[str, Any]] = None,
    agent_task_id: str = "",
    agent_parent_task_id: str = "",
    agent_kind: str = "parent",
    agent_invocation_type: str = "",
    agent_role_name: str = "",
    agent_state: str = "",
    agent_background: bool = False,
    agent_stop_reason: str = "",
    agent_isolation: str = "shared",
    agent_project_root: str = "",
    agent_worktree_root: str = "",
    agent_branch: str = "",
) -> HookEvent:
    context: dict[str, Any] = {
        "event": {"name": name.value},
        "system": {
            "cwd": str(cwd),
            "config_sources": config_sources,
        },
    }
    schema = event_schema(name)
    if "session.id" in schema:
        context["session"] = {"id": session_id, "state": session_state}
    if "turn.number" in schema:
        context["turn"] = {
            "number": turn_number,
            "mode": turn_mode,
            "stop_reason": turn_stop_reason,
        }
    if "message.role" in schema:
        context["message"] = {
            "role": message_role,
            "content": message_content,
            "stage": message_stage,
        }
    if "tool.call_id" in schema:
        context["tool"] = {
            "call_id": tool_call_id,
            "name": tool_name,
            "arguments": dict(tool_arguments or {}),
            "result": dict(tool_result or {}),
        }
    if "agent.task_id" in schema:
        context["agent"] = {
            "task_id": agent_task_id,
            "parent_task_id": agent_parent_task_id,
            "kind": agent_kind,
            "invocation_type": agent_invocation_type,
            "role_name": agent_role_name,
            "state": agent_state,
            "background": agent_background,
            "stop_reason": agent_stop_reason,
            "isolation": agent_isolation,
            "project_root": agent_project_root,
            "worktree_root": agent_worktree_root,
            "branch": agent_branch,
        }
    return HookEvent(name, datetime.now(timezone.utc), _freeze(context))
