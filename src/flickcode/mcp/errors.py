"""MCP-specific exceptions with server and operation context."""

from __future__ import annotations


class MCPError(Exception):
    """Base class for errors that can be attributed to an MCP server."""

    def __init__(
        self,
        message: str,
        server_name: str | None = None,
        operation: str | None = None,
    ) -> None:
        self.server_name = server_name
        self.operation = operation
        self.message = message
        prefix = []
        if server_name:
            prefix.append(f"server={server_name}")
        if operation:
            prefix.append(f"operation={operation}")
        context = f" ({', '.join(prefix)})" if prefix else ""
        super().__init__(f"{message}{context}")


class MCPConfigError(MCPError):
    pass


class MCPTransportError(MCPError):
    pass


class MCPProtocolError(MCPError):
    pass


class MCPTimeoutError(MCPTransportError):
    pass


class MCPToolCallError(MCPError):
    pass
