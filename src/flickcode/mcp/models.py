"""Data structures shared by the MCP client layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass
class MCPServerConfig:
    """Validated and environment-expanded configuration for one server."""

    name: str
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPClientInfo:
    name: str = "FlickCode"
    version: str = "0.1.0"


@dataclass(frozen=True)
class MCPTimeouts:
    connect_seconds: float = 10.0
    request_seconds: float = 60.0
    shutdown_seconds: float = 5.0
    max_tool_pages: int = 100


@dataclass(frozen=True)
class MCPToolDefinition:
    server_name: str
    name: str
    title: str | None
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPCallResult:
    content: list[dict[str, Any]]
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
    raw_result: dict[str, Any] = field(default_factory=dict)


class ServerState(str, Enum):
    CONFIGURED = "configured"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass
class MCPServerReport:
    name: str
    transport: str
    state: ServerState
    tool_count: int = 0
    error: str | None = None


@dataclass
class MCPStartupReport:
    """Aggregate startup result; one failed server must not hide others."""

    servers: list[MCPServerReport] = field(default_factory=list)
    registered_tools: list[str] = field(default_factory=list)

    @property
    def successful_servers(self) -> list[str]:
        return [
            item.name
            for item in self.servers
            if item.state == ServerState.READY
        ]

    @property
    def failed_servers(self) -> list[MCPServerReport]:
        return [
            item for item in self.servers if item.state == ServerState.FAILED
        ]
