"""Adapters from MCP tools to FlickCode's existing Tool interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Optional

from flickcode.mcp.client import MCPServerClient
from flickcode.mcp.errors import MCPError
from flickcode.mcp.models import MCPCallResult, MCPToolDefinition
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache


def _tool_name(server_name: str, remote_name: str) -> str:
    return f"mcp__{server_name}__{remote_name}"


def _serialize_content(result: MCPCallResult) -> str:
    text_parts: list[str] = []
    other_parts: list[dict[str, Any]] = []
    for item in result.content:
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            text_parts.append(item["text"])
        else:
            other_parts.append(item)
    output = "\n".join(text_parts)
    extras: dict[str, Any] = {}
    if other_parts:
        extras["content"] = other_parts
    if result.structured_content is not None:
        extras["structuredContent"] = result.structured_content
    if extras:
        encoded = json.dumps(extras, ensure_ascii=False, sort_keys=True)
        output = f"{output}\n{encoded}" if output else encoded
    return output


class MCPToolAdapter(BaseTool):
    """A discovered MCP tool exposed as a normal FlickCode BaseTool."""

    def __init__(
        self,
        definition: MCPToolDefinition,
        client: MCPServerClient,
    ) -> None:
        self.source_server = definition.server_name
        self.remote_name = definition.name
        self.client = client
        self.spec = ToolSpec(
            name=_tool_name(definition.server_name, definition.name),
            description=definition.description,
            input_schema=dict(definition.input_schema),
        )

    def execute(
        self,
        params: dict[str, Any],
        *,
        cwd: Optional[Path] = None,
        file_cache: Optional[FileContentCache] = None,
    ) -> ToolResult:
        try:
            result = self.client.call_tool(self.remote_name, params)
        except MCPError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, error=f"MCP tool call failed: {exc}")
        output = _serialize_content(result)
        if result.is_error:
            return ToolResult(success=False, output=output, error=output or "MCP tool error")
        return ToolResult(success=True, output=output)
