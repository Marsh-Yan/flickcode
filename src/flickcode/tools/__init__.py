"""Tool system package."""

from __future__ import annotations

from flickcode.tools.edit_file import EditFileTool
from flickcode.tools.execute_command import ExecuteCommandTool
from flickcode.tools.glob_tool import GlobTool
from flickcode.tools.grep_tool import GrepTool
from flickcode.tools.read_file import ReadFileTool
from flickcode.tools.registry import ToolRegistry, ToolRegistryView
from flickcode.tools.write_file import WriteFileTool

__all__ = [
    "create_default_registry",
    "EditFileTool",
    "ExecuteCommandTool",
    "GlobTool",
    "GrepTool",
    "ReadFileTool",
    "ToolRegistry",
    "ToolRegistryView",
    "WriteFileTool",
]


def create_default_registry() -> ToolRegistry:
    """Create a ToolRegistry pre-loaded with all six core tools."""
    registry = ToolRegistry()
    registry.register_all([
        ReadFileTool,
        WriteFileTool,
        EditFileTool,
        ExecuteCommandTool,
        GlobTool,
        GrepTool,
    ])
    return registry
