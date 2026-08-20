"""The single stable Agent delegation tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from flickcode.subagents.models import AgentInvocationType, AgentToolOperation, AgentToolRequest
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache


class AgentTool(BaseTool):
    spec = ToolSpec(
        name="agent",
        description=(
            "Start a defined or forked SubAgent, or query/cancel an existing SubAgent task. "
            "Fork tasks always run in the background."
        ),
        parameters=[],
        input_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["start", "status", "result", "cancel"]},
                "type": {"type": "string", "enum": ["defined", "fork"]},
                "task": {"type": "string"},
                "role": {"type": "string"},
                "background": {"type": "boolean"},
                "task_id": {"type": "string"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )

    def __init__(self) -> None:
        self._coordinator = None
        self._refresh_callback = None

    def bind(self, coordinator, refresh_callback=None) -> None:
        self._coordinator = coordinator
        self._refresh_callback = refresh_callback

    def execute(
        self,
        params: dict,
        *,
        cwd: Optional[Path] = None,
        file_cache: Optional[FileContentCache] = None,
    ) -> ToolResult:
        if self._coordinator is None:
            return ToolResult(False, error="Agent tool is not bound.")
        try:
            operation = AgentToolOperation(params.get("operation"))
            if operation is AgentToolOperation.START and self._refresh_callback is not None:
                self._refresh_callback()
            invocation = params.get("type")
            request = AgentToolRequest(
                operation=operation,
                invocation_type=AgentInvocationType(invocation) if invocation is not None else None,
                task=params.get("task"),
                role=params.get("role"),
                background=params.get("background"),
                task_id=params.get("task_id"),
            )
            response = self._coordinator.handle(request)
            payload = json.dumps(response.to_dict(), ensure_ascii=False, default=str)
            return ToolResult(response.success, output=payload if response.success else "", error=response.error or "")
        except (TypeError, ValueError) as exc:
            return ToolResult(False, error=f"Invalid Agent request: {exc}")
