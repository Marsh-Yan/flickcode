"""MCP lifecycle and tool operations for one server."""

from __future__ import annotations

import logging
from typing import Any

from flickcode.mcp.errors import MCPProtocolError, MCPToolCallError
from flickcode.mcp.jsonrpc import JsonRpcPeer
from flickcode.mcp.models import (
    MCPCallResult,
    MCPClientInfo,
    MCPServerConfig,
    MCPTimeouts,
    MCPToolDefinition,
)
from flickcode.mcp.transport import (
    MCPTransport,
    StdioTransport,
    StreamableHttpTransport,
)

log = logging.getLogger("flickcode.mcp.client")
PROTOCOL_VERSION = "2025-06-18"


class MCPServerClient:
    """A stateful MCP client for one configured server."""

    def __init__(
        self,
        config: MCPServerConfig,
        timeouts: MCPTimeouts | None = None,
        transport: MCPTransport | None = None,
        client_info: MCPClientInfo | None = None,
    ) -> None:
        self.config = config
        self.timeouts = timeouts or MCPTimeouts()
        self.transport = transport or self._make_transport()
        self.peer = JsonRpcPeer(self.transport, self.timeouts)
        self.client_info = client_info or MCPClientInfo()
        self.protocol_version: str = PROTOCOL_VERSION
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}
        self._tools_cache: list[MCPToolDefinition] = []
        self._ready = False
        self._closed = False

    def _make_transport(self) -> MCPTransport:
        if self.config.transport == "stdio":
            return StdioTransport(self.config, self.timeouts)
        if self.config.transport == "streamable_http":
            return StreamableHttpTransport(self.config, self.timeouts)
        raise MCPProtocolError(
            f"Unsupported MCP transport: {self.config.transport}",
            self.config.name,
            "connect",
        )

    def connect_and_discover(self) -> list[MCPToolDefinition]:
        if self._ready:
            return list(self._tools_cache)
        self.peer.start()
        initialize_result = self.peer.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": self.client_info.name,
                    "version": self.client_info.version,
                },
            },
        )
        if not isinstance(initialize_result, dict):
            raise MCPProtocolError(
                "initialize result must be an object",
                self.config.name,
                "initialize",
            )
        self.protocol_version = initialize_result.get(
            "protocolVersion", PROTOCOL_VERSION
        )
        if self.protocol_version not in (PROTOCOL_VERSION, "2025-03-26"):
            raise MCPProtocolError(
                f"Unsupported negotiated protocol version: {self.protocol_version}",
                self.config.name,
                "initialize",
            )
        self.server_info = initialize_result.get("serverInfo") or {}
        self.server_capabilities = initialize_result.get("capabilities") or {}
        if "tools" not in self.server_capabilities:
            raise MCPProtocolError(
                "MCP server does not advertise tools capability",
                self.config.name,
                "initialize",
            )
        if isinstance(self.transport, StreamableHttpTransport):
            self.transport.set_protocol_version(self.protocol_version)
        self.peer.notify("notifications/initialized")

        tools: list[MCPToolDefinition] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(self.timeouts.max_tool_pages):
            params = {"cursor": cursor} if cursor is not None else None
            result = self.peer.request("tools/list", params)
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise MCPProtocolError(
                    "tools/list result must contain a tools list",
                    self.config.name,
                    "tools/list",
                )
            for raw_tool in result["tools"]:
                parsed = self._parse_tool(raw_tool)
                if parsed is not None:
                    tools.append(parsed)
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
                raise MCPProtocolError(
                    "tools/list returned a repeated or invalid cursor",
                    self.config.name,
                    "tools/list",
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise MCPProtocolError(
                "tools/list exceeded maximum page count",
                self.config.name,
                "tools/list",
            )

        self._tools_cache = list(tools)
        self._ready = True
        return list(tools)

    @staticmethod
    def _parse_tool(raw_tool: Any) -> MCPToolDefinition | None:
        if not isinstance(raw_tool, dict):
            return None
        name = raw_tool.get("name")
        schema = raw_tool.get("inputSchema")
        if not isinstance(name, str) or not name:
            return None
        if not isinstance(schema, dict) or schema.get("type") != "object":
            return None
        return MCPToolDefinition(
            server_name="",
            name=name,
            title=raw_tool.get("title") if isinstance(raw_tool.get("title"), str) else None,
            description=(
                raw_tool.get("description")
                if isinstance(raw_tool.get("description"), str)
                else "MCP tool"
            ),
            input_schema=dict(schema),
            output_schema=(
                dict(raw_tool["outputSchema"])
                if isinstance(raw_tool.get("outputSchema"), dict)
                else None
            ),
            annotations=(
                dict(raw_tool["annotations"])
                if isinstance(raw_tool.get("annotations"), dict)
                else {}
            ),
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        if not self._ready:
            raise MCPToolCallError(
                "MCP server is not ready", self.config.name, "tools/call"
            )
        result = self.peer.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if not isinstance(result, dict):
            raise MCPToolCallError(
                "tools/call result must be an object",
                self.config.name,
                "tools/call",
            )
        content = result.get("content", [])
        if not isinstance(content, list):
            raise MCPToolCallError(
                "tools/call content must be a list",
                self.config.name,
                "tools/call",
            )
        structured = result.get("structuredContent")
        return MCPCallResult(
            content=[item for item in content if isinstance(item, dict)],
            structured_content=structured if isinstance(structured, dict) else None,
            is_error=bool(result.get("isError", False)),
            raw_result=result,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._ready = False
        self.peer.close()
