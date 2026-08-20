"""Model-facing tools exposed only in Lead or member team contexts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache


def _result(value: Any) -> ToolResult:
    return ToolResult(True, output=json.dumps(value, ensure_ascii=False, default=str))


class TeamLeadTool(BaseTool):
    spec = ToolSpec(
        name="team_lead",
        description="Manage a durable team: create members, assign/terminate work, inspect status, send messages, and merge branches.",
        input_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["create_member", "assign", "terminate", "status", "send", "broadcast", "merge", "coordinator"]},
                "name": {"type": "string"}, "role": {"type": "string"}, "workdir": {"type": "string"},
                "title": {"type": "string"}, "description": {"type": "string"}, "assignee": {"type": "string"},
                "dependencies": {"type": "array", "items": {"type": "string"}}, "member_id": {"type": "string"},
                "recipient": {"type": "string"}, "kind": {"type": "string"}, "payload": {"type": "object"},
                "body": {"type": "string"}, "summary": {"type": "string"}, "branches": {"type": "array", "items": {"type": "string"}},
                "approval_required": {"type": "boolean"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )

    def __init__(self, coordinator, actor_id: Optional[str] = None) -> None:
        self.coordinator = coordinator
        self.actor_id = actor_id

    def execute(self, params: dict[str, Any], *, cwd: Optional[Path] = None, file_cache: Optional[FileContentCache] = None) -> ToolResult:
        try:
            operation = params.get("operation")
            if operation == "create_member":
                member = self.coordinator.create_member(name=params["name"], role=params.get("role", "worker"), workdir=Path(params["workdir"]) if params.get("workdir") else cwd, approval_required=bool(params.get("approval_required", False)))
                return _result(member.to_dict())
            if operation == "assign":
                task = self.coordinator.assign(title=params["title"], description=params.get("description", ""), assignee=params.get("assignee"), dependencies=params.get("dependencies", ()))
                return _result(task.to_dict())
            if operation == "terminate":
                return _result(self.coordinator.terminate(params["member_id"]))
            if operation == "status":
                return _result(self.coordinator.status())
            if operation == "send":
                return _result(self.coordinator.send_message(recipient=params["recipient"], kind=params.get("kind", "member.wakeup"), payload=params.get("payload"), body=params.get("body", ""), summary=params.get("summary", "")))
            if operation == "broadcast":
                return _result(self.coordinator.broadcast(kind=params.get("kind", "member.wakeup"), payload=params.get("payload"), body=params.get("body", ""), summary=params.get("summary", "")))
            if operation == "merge":
                return _result(self.coordinator.merge_branches(params.get("branches", ())))
            if operation == "coordinator":
                return _result(self.coordinator.coordinator_state())
            raise ValueError("unsupported team_lead operation")
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            return ToolResult(False, error=str(exc))


class TeamTaskTool(BaseTool):
    spec = ToolSpec(
        name="team_tasks",
        description="Create, inspect, update, and complete shared team tasks.",
        input_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["create", "list", "get", "update", "start", "complete", "cancel"]},
                "task_id": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"},
                "assignee_id": {"type": "string"}, "dependencies": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"}, "error": {"type": "string"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    def execute(self, params: dict[str, Any], *, cwd: Optional[Path] = None, file_cache: Optional[FileContentCache] = None) -> ToolResult:
        try:
            _, tasks, _, _ = self.coordinator._require()
            operation = params.get("operation")
            if operation == "create":
                return _result(tasks.create_task(params["title"], params.get("description", ""), assignee_id=params.get("assignee_id"), dependency_ids=params.get("dependencies", ()), created_by=self.actor_id or self.coordinator.team.lead_member_id).to_dict())
            if operation == "list":
                return _result([item.to_dict() for item in tasks.list_tasks()])
            if operation == "get":
                return _result(tasks.get_task(params["task_id"]).to_dict())
            if operation == "update":
                values = {key: params[key] for key in ("title", "description", "assignee_id") if key in params}
                if "dependencies" in params:
                    values["dependency_ids"] = params["dependencies"]
                return _result(tasks.update_task(params["task_id"], **values).to_dict())
            if operation == "start":
                return _result(tasks.start_task(params["task_id"]).to_dict())
            if operation == "complete":
                return _result(tasks.complete_task(params["task_id"], params.get("summary", "")).to_dict())
            if operation == "cancel":
                return _result(tasks.cancel_task(params["task_id"]).to_dict())
            raise ValueError("unsupported team_tasks operation")
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            return ToolResult(False, error=str(exc))


class TeamMessageTool(BaseTool):
    spec = ToolSpec(
        name="team_message",
        description="Send direct or broadcast team messages and inspect a member mailbox.",
        input_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["send", "broadcast", "inbox", "read"]},
                "recipient": {"type": "string"}, "member_id": {"type": "string"}, "kind": {"type": "string"},
                "payload": {"type": "object"}, "body": {"type": "string"}, "summary": {"type": "string"},
                "message_ids": {"type": "array", "items": {"type": "string"}}, "unread_only": {"type": "boolean"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )

    def __init__(self, coordinator, actor_id: Optional[str] = None) -> None:
        self.coordinator = coordinator
        self.actor_id = actor_id

    def execute(self, params: dict[str, Any], *, cwd: Optional[Path] = None, file_cache: Optional[FileContentCache] = None) -> ToolResult:
        try:
            team, _, mailbox, _ = self.coordinator._require()
            operation = params.get("operation")
            if operation == "send":
                return _result(self.coordinator.send_message(recipient=params["recipient"], kind=params.get("kind", "member.wakeup"), payload=params.get("payload"), body=params.get("body", ""), summary=params.get("summary", ""), sender_id=self.actor_id))
            if operation == "broadcast":
                return _result(self.coordinator.broadcast(kind=params.get("kind", "member.wakeup"), payload=params.get("payload"), body=params.get("body", ""), summary=params.get("summary", ""), sender_id=self.actor_id))
            member_id = params.get("member_id") or self.actor_id or team.lead_member_id
            if operation == "inbox":
                return _result([item.to_dict() for item in mailbox.list_messages(member_id, unread_only=bool(params.get("unread_only", False)))])
            if operation == "read":
                return _result({"marked": mailbox.mark_read(member_id, params.get("message_ids", ()))})
            raise ValueError("unsupported team_message operation")
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            return ToolResult(False, error=str(exc))
