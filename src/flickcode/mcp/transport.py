"""MCP stdio and Streamable HTTP transports."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from http.client import HTTPResponse
from typing import Any, Callable, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flickcode.mcp.errors import MCPTransportError
from flickcode.mcp.models import MCPServerConfig, MCPTimeouts
from flickcode.mcp.jsonrpc import parse_message

log = logging.getLogger("flickcode.mcp.transport")


MessageHandler = Callable[[Dict[str, Any]], None]
ErrorHandler = Callable[[Exception], None]


class MCPTransport:
    """Small transport protocol implemented as a concrete base class."""

    def __init__(self) -> None:
        self._message_handler: MessageHandler | None = None
        self._error_handler: ErrorHandler | None = None

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._message_handler = handler

    def set_error_handler(self, handler: ErrorHandler) -> None:
        self._error_handler = handler

    def _emit_message(self, message: dict[str, Any]) -> None:
        if self._message_handler is not None:
            self._message_handler(message)

    def _emit_error(self, error: Exception) -> None:
        if self._error_handler is not None:
            self._error_handler(error)
        else:
            log.warning("MCP transport error: %s", error)

    def start(self) -> None:
        raise NotImplementedError

    def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class StdioTransport(MCPTransport):
    """Line-delimited JSON-RPC transport backed by one child process."""

    def __init__(
        self,
        config: MCPServerConfig,
        timeouts: MCPTimeouts | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.timeouts = timeouts or MCPTimeouts()
        self.process: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._closed = False
        self._reader_threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.process is not None:
            return
        if not self.config.command:
            raise MCPTransportError(
                "stdio transport requires command",
                self.config.name,
                "connect",
            )
        environment = os.environ.copy()
        environment.update(self.config.env)
        try:
            self.process = subprocess.Popen(
                [self.config.command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="strict",
                shell=False,
                env=environment,
                bufsize=1,
            )
        except OSError as exc:
            raise MCPTransportError(
                f"failed to start stdio process: {exc}",
                self.config.name,
                "connect",
            ) from exc

        assert self.process.stdout is not None
        assert self.process.stderr is not None
        stdout_thread = threading.Thread(
            target=self._read_stdout,
            name=f"mcp-stdio-{self.config.name}-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stderr,
            name=f"mcp-stdio-{self.config.name}-stderr",
            daemon=True,
        )
        self._reader_threads = [stdout_thread, stderr_thread]
        stdout_thread.start()
        stderr_thread.start()

    def send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            raise MCPTransportError(
                "stdio process is not running",
                self.config.name,
                "send",
            )
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if "\n" in payload or "\r" in payload:
            raise MCPTransportError(
                "stdio JSON-RPC message must be single-line",
                self.config.name,
                "send",
            )
        try:
            with self._write_lock:
                process.stdin.write(payload + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            error = MCPTransportError(
                f"stdio send failed: {exc}", self.config.name, "send"
            )
            self._emit_error(error)
            raise error from exc

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for line in self.process.stdout:
                if self._closed:
                    return
                line = line.rstrip("\r\n")
                if not line:
                    continue
                try:
                    message = parse_message(line)
                except Exception as exc:
                    self._emit_error(
                        MCPTransportError(
                            f"invalid JSON-RPC on stdout: {exc}",
                            self.config.name,
                            "read",
                        )
                    )
                    continue
                self._emit_message(message)
        except Exception as exc:
            if not self._closed:
                self._emit_error(
                    MCPTransportError(
                        f"stdio stdout reader failed: {exc}",
                        self.config.name,
                        "read",
                    )
                )
        finally:
            if not self._closed:
                self._emit_error(
                    MCPTransportError(
                        "stdio process stdout closed",
                        self.config.name,
                        "read",
                    )
                )

    def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        try:
            for line in self.process.stderr:
                if not self._closed:
                    log.debug("[%s stderr] %s", self.config.name, line.rstrip())
        except Exception as exc:
            if not self._closed:
                log.debug("[%s stderr reader failed] %s", self.config.name, exc)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self.process
        if process is None:
            return
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=self.timeouts.shutdown_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self.timeouts.shutdown_seconds)
            except OSError:
                pass


class StreamableHttpTransport(MCPTransport):
    """POST-based MCP transport supporting JSON and Server-Sent Events."""

    def __init__(
        self,
        config: MCPServerConfig,
        timeouts: MCPTimeouts | None = None,
        opener: Callable[..., HTTPResponse] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.timeouts = timeouts or MCPTimeouts()
        self._opener = opener or urlopen
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._closed = False
        self._send_lock = threading.Lock()
        self._workers: set[threading.Thread] = set()

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def set_protocol_version(self, version: str) -> None:
        self._protocol_version = version

    def start(self) -> None:
        if not self.config.url:
            raise MCPTransportError(
                "Streamable HTTP transport requires url",
                self.config.name,
                "connect",
            )
        self._closed = False

    def send(self, message: dict[str, Any]) -> None:
        if self._closed:
            raise MCPTransportError(
                "HTTP transport is closed", self.config.name, "send"
            )
        worker = threading.Thread(
            target=self._post_message,
            args=(message,),
            name=f"mcp-http-{self.config.name}",
            daemon=True,
        )
        with self._send_lock:
            self._workers.add(worker)
        worker.start()

    def _post_message(self, message: dict[str, Any]) -> None:
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            headers.update(self.config.headers)
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id
            if self._protocol_version:
                headers["MCP-Protocol-Version"] = self._protocol_version
            body = json.dumps(message, ensure_ascii=False).encode("utf-8")
            request = Request(
                self.config.url or "",
                data=body,
                headers=headers,
                method="POST",
            )
            with self._opener(request, timeout=self.timeouts.request_seconds) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id
                content_type = response.headers.get("Content-Type", "")
                if response.status < 200 or response.status >= 300:
                    raise MCPTransportError(
                        f"HTTP status {response.status}",
                        self.config.name,
                        "send",
                    )
                if response.status == 202:
                    return
                if "text/event-stream" in content_type:
                    self._read_sse(response)
                elif "application/json" in content_type or not content_type:
                    payload = response.read().decode("utf-8")
                    if payload.strip():
                        self._emit_message(parse_message(payload))
                else:
                    raise MCPTransportError(
                        f"unsupported HTTP content type: {content_type}",
                        self.config.name,
                        "read",
                    )
        except HTTPError as exc:
            error = MCPTransportError(
                f"HTTP status {exc.code}", self.config.name, "send"
            )
            self._emit_error(error)
        except (URLError, TimeoutError, OSError) as exc:
            self._emit_error(
                MCPTransportError(str(exc), self.config.name, "send")
            )
        except Exception as exc:
            self._emit_error(
                exc
                if isinstance(exc, MCPTransportError)
                else MCPTransportError(str(exc), self.config.name, "read")
            )
        finally:
            current = threading.current_thread()
            with self._send_lock:
                self._workers.discard(current)

    def _read_sse(self, response: HTTPResponse) -> None:
        event_data: list[str] = []
        while not self._closed:
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                if event_data:
                    payload = "\n".join(event_data)
                    self._emit_message(parse_message(payload))
                    event_data = []
                continue
            if line.startswith("data:"):
                event_data.append(line[5:].lstrip())

        if event_data:
            self._emit_message(parse_message("\n".join(event_data)))

    def close(self) -> None:
        self._closed = True
        with self._send_lock:
            workers = list(self._workers)
        for worker in workers:
            worker.join(timeout=self.timeouts.shutdown_seconds)
        if self._session_id and self.config.url:
            try:
                headers = dict(self.config.headers)
                headers["Mcp-Session-Id"] = self._session_id
                request = Request(
                    self.config.url,
                    headers=headers,
                    method="DELETE",
                )
                with self._opener(request, timeout=self.timeouts.shutdown_seconds):
                    pass
            except Exception as exc:
                # Some servers intentionally return 405 for session DELETE.
                log.debug(
                    "MCP HTTP session close failed name=%s error=%s",
                    self.config.name,
                    exc,
                )
