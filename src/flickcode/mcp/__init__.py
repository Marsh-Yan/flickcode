"""MCP client support for FlickCode.

Imports are lazy so the configuration layer can import ``mcp.models`` without
eagerly constructing the transport/client dependency graph.
"""

__all__ = [
    "MCPCallResult",
    "MCPClientManager",
    "MCPServerClient",
    "MCPServerConfig",
    "MCPStartupReport",
    "MCPTimeouts",
    "MCPToolDefinition",
    "ServerState",
]


def __getattr__(name: str):
    if name == "MCPClientManager":
        from flickcode.mcp.manager import MCPClientManager

        return MCPClientManager
    if name == "MCPServerClient":
        from flickcode.mcp.client import MCPServerClient

        return MCPServerClient
    from flickcode.mcp.models import (
        MCPCallResult,
        MCPServerConfig,
        MCPStartupReport,
        MCPTimeouts,
        MCPToolDefinition,
        ServerState,
    )

    values = {
        "MCPCallResult": MCPCallResult,
        "MCPServerConfig": MCPServerConfig,
        "MCPStartupReport": MCPStartupReport,
        "MCPTimeouts": MCPTimeouts,
        "MCPToolDefinition": MCPToolDefinition,
        "ServerState": ServerState,
    }
    if name in values:
        return values[name]
    raise AttributeError(name)
