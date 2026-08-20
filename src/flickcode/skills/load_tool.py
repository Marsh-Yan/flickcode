"""System-level tool that loads and invokes Skill definitions."""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING
from pathlib import Path

from flickcode.agent import AgentMode
from flickcode.skills.models import SkillInvocationOrigin
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache

if TYPE_CHECKING:
    from flickcode.skills.executor import SkillExecutor


class LoadSkillTool(BaseTool):
    """Always-visible loader; it is intentionally outside Skill whitelists."""

    spec = ToolSpec(
        name="load_skill",
        description="Load a reusable Skill by name and run it with optional input.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact Skill name"},
                "input": {"type": "string", "description": "Raw input substituted into {{input}}"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    )

    def __init__(self, executor: Optional["SkillExecutor"] = None) -> None:
        self._executor = executor

    def bind(self, executor: "SkillExecutor") -> None:
        self._executor = executor

    def execute(
        self,
        params: dict[str, Any],
        *,
        cwd: Optional[Path] = None,
        file_cache: Optional[FileContentCache] = None,
    ) -> ToolResult:
        name = params.get("name")
        user_input = params.get("input", "")
        if not isinstance(name, str) or not name:
            return ToolResult(success=False, error="load_skill requires a non-empty string name")
        if not isinstance(user_input, str):
            return ToolResult(success=False, error="load_skill input must be a string")
        if self._executor is None:
            return ToolResult(success=False, error="load_skill is not connected to a Skill executor")
        try:
            try:
                result = self._executor.invoke(
                    name,
                    user_input,
                    origin=SkillInvocationOrigin.TOOL,
                    parent_mode=AgentMode.FULL,
                    cwd=cwd,
                )
            except TypeError as exc:
                if "cwd" not in str(exc):
                    raise
                result = self._executor.invoke(
                    name,
                    user_input,
                    origin=SkillInvocationOrigin.TOOL,
                    parent_mode=AgentMode.FULL,
                )
        except Exception as exc:
            return ToolResult(success=False, error=f"Skill load failed: {exc}")
        if result.success:
            suffix = f"\nchild_session_id: {result.child_session_id}" if result.child_session_id else ""
            return ToolResult(success=True, output=result.summary + suffix)
        diagnostic = "; ".join(item.message for item in result.diagnostics)
        return ToolResult(success=False, output=result.summary, error=diagnostic or "Skill execution failed")
