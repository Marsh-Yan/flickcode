"""JSON-RPC 2.0 peer used by both MCP transports."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from flickcode.mcp.errors import (
    MCPError,
    MCPProtocolError,
    MCPTimeoutError,
    MCPTransportError,
)
from flickcode.mcp.models import MCPTimeouts

log = logging.getLogger("flickcode.mcp.jsonrpc")


def encode_request(
    request_id: int | str,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not method or not isinstance(method, str):
        raise MCPProtocolError("JSON-RPC method must be a non-empty string")
    message: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        message["params"] = params
    return message


def encode_notification(
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not method or not isinstance(method, str):
        raise MCPProtocolError("JSON-RPC method must be a non-empty string")
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    return message


def encode_message(message: dict[str, Any], single_line: bool = False) -> str:
    """Serialize one JSON-RPC message as UTF-8-safe JSON text."""
    parsed = parse_message(message)
    text = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    if single_line and ("\n" in text or "\r" in text):
        raise MCPProtocolError("JSON-RPC stdio message must be single-line")
    return text


def parse_message(message: Any) -> dict[str, Any]:
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except json.JSONDecodeError as exc:
            raise MCPProtocolError(f"Invalid JSON-RPC JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise MCPProtocolError("JSON-RPC message must be an object")
    if message.get("jsonrpc") != "2.0":
        raise MCPProtocolError("JSON-RPC message must contain jsonrpc=2.0")

    has_id = "id" in message
    has_method = "method" in message
    has_result = "result" in message
    has_error = "error" in message
    if has_result and has_error:
        raise MCPProtocolError("JSON-RPC response cannot contain result and error")

    if has_method:
        if not isinstance(message["method"], str) or not message["method"]:
            raise MCPProtocolError("JSON-RPC method must be a non-empty string")
        if has_id and message["id"] is None:
            raise MCPProtocolError("JSON-RPC request id must not be null")
        if has_id and (has_result or has_error):
            raise MCPProtocolError("JSON-RPC request cannot contain result/error")
        if not has_id and (has_result or has_error):
            raise MCPProtocolError("JSON-RPC notification cannot contain result/error")
        return message

    if not has_id or not (has_result or has_error):
        raise MCPProtocolError("JSON-RPC message is neither request nor response")
    if has_error:
        error = message["error"]
        if not isinstance(error, dict):
            raise MCPProtocolError("JSON-RPC error must be an object")
        if not isinstance(error.get("code"), int) or not isinstance(
            error.get("message"), str
        ):
            raise MCPProtocolError("JSON-RPC error requires integer code and message")
    return message


def encode_response(
    request_id: int | str,
    result: Any = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if error is not None and result is not None:
        raise MCPProtocolError("JSON-RPC response cannot contain result and error")
    if error is None:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


class _Pending:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: Exception | None = None


class JsonRpcPeer:
    """Thread-safe request/response correlation over an MCP transport."""

    def __init__(self, transport: Any, timeouts: MCPTimeouts | None = None):
        self.transport = transport
        self.timeouts = timeouts or MCPTimeouts()
        self._lock = threading.RLock()
        self._next_id = 1
        self._pending: dict[int | str, _Pending] = {}
        self._notification_handler: Callable[[dict[str, Any]], None] | None = None
        self._closed = False

        self.transport.set_message_handler(self._handle_message)
        if hasattr(self.transport, "set_error_handler"):
            self.transport.set_error_handler(self._handle_transport_error)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def set_notification_handler(
        self, handler: Callable[[dict[str, Any]], None] | None
    ) -> None:
        self._notification_handler = handler

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise MCPTransportError("Cannot start a closed JSON-RPC peer")
        self.transport.start()

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        with self._lock:
            if self._closed:
                raise MCPTransportError("JSON-RPC peer is closed")
            request_id = self._next_id
            self._next_id += 1
            pending = _Pending()
            self._pending[request_id] = pending

        message = encode_request(request_id, method, params)
        try:
            self.transport.send(message)
        except Exception as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            if isinstance(exc, MCPError):
                raise
            raise MCPTransportError(str(exc), operation=method) from exc

        wait_seconds = timeout if timeout is not None else self.timeouts.request_seconds
        if not pending.event.wait(wait_seconds):
            with self._lock:
                self._pending.pop(request_id, None)
            raise MCPTimeoutError(
                f"JSON-RPC request timed out after {wait_seconds:.1f}s",
                operation=method,
            )
        if pending.error is not None:
            raise pending.error
        return pending.result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self._closed:
                raise MCPTransportError("JSON-RPC peer is closed")
        try:
            self.transport.send(encode_notification(method, params))
        except Exception as exc:
            if isinstance(exc, MCPError):
                raise
            raise MCPTransportError(str(exc), operation=method) from exc

    def _handle_message(self, raw_message: dict[str, Any]) -> None:
        try:
            message = parse_message(raw_message)
        except Exception as exc:
            self._handle_transport_error(
                exc if isinstance(exc, Exception) else Exception(str(exc))
            )
            return

        if "method" in message:
            if "id" in message:
                log.warning("Unsupported server request: %s", message["method"])
            elif self._notification_handler is not None:
                self._notification_handler(message)
            return

        request_id = message["id"]
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            log.warning("Received response for unknown JSON-RPC id %r", request_id)
            return

        if "error" in message:
            error = message["error"]
            pending.error = MCPProtocolError(
                f"JSON-RPC error {error['code']}: {error['message']}"
            )
        else:
            pending.result = message.get("result")
        pending.event.set()

    def _handle_transport_error(self, error: Exception) -> None:
        if not isinstance(error, Exception):
            error = Exception(str(error))
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.error = (
                error
                if isinstance(error, MCPError)
                else MCPTransportError(str(error))
            )
            item.event.set()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._handle_transport_error(MCPTransportError("JSON-RPC peer closed"))
        try:
            self.transport.close()
        except Exception as exc:
            log.warning("Error closing MCP transport: %s", exc)
