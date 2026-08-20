from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys

from flickcode.config import load_config
from flickcode.agent import AgentLoop, AgentMode
from flickcode.mcp import MCPClientManager
from flickcode.mcp.adapter import MCPToolAdapter
from flickcode.mcp.client import MCPServerClient
from flickcode.mcp.errors import MCPProtocolError, MCPTimeoutError
from flickcode.mcp.jsonrpc import JsonRpcPeer, encode_message, parse_message
from flickcode.mcp.models import (
    MCPCallResult,
    MCPServerConfig,
    MCPTimeouts,
    MCPToolDefinition,
    ServerState,
)
from flickcode.mcp import manager as manager_module
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.providers.base import Message, StreamEvent
from flickcode.tools.registry import ToolRegistry


class FakeTransport:
    def __init__(self, responder=None):
        self.handler = None
        self.error_handler = None
        self.responder = responder
        self.sent = []
        self.started = 0
        self.closed = 0

    def set_message_handler(self, handler):
        self.handler = handler

    def set_error_handler(self, handler):
        self.error_handler = handler

    def start(self):
        self.started += 1

    def send(self, message):
        self.sent.append(message)
        if self.responder:
            self.responder(self, message)

    def close(self):
        self.closed += 1

    def respond(self, message):
        assert self.handler is not None
        self.handler(message)


class EchoTool(BaseTool):
    spec = ToolSpec(
        name="echo",
        description="Echo",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )

    def execute(self, params):
        return ToolResult(success=True, output=params["value"])


class MCPTests(unittest.TestCase):
    def test_registry_instance_and_schema(self):
        registry = ToolRegistry()
        tool = EchoTool()
        registry.register_instance(tool)
        self.assertTrue(registry.has("echo"))
        self.assertEqual(
            registry.to_api_tools("anthropic")[0]["input_schema"]["required"],
            ["value"],
        )
        with self.assertRaises(ValueError):
            registry.register_instance(EchoTool())

    def test_config_merge_and_env_expansion(self):
        test_tmp_root = Path(__file__).parent / "_tmp"
        test_tmp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_tmp_root) as directory:
            root = Path(directory)
            user_config = root / "user.yaml"
            user_config.write_text(
                """
providers:
  - name: test
    protocol: openai
    model: test
    base_url: https://example.invalid
    api_key: key
mcp_servers:
  shared:
    transport: stdio
    command: python
    args: [one]
  user_only:
    transport: streamable_http
    url: https://user.invalid/mcp
""",
                encoding="utf-8",
            )
            project_dir = root / ".flickcode"
            project_dir.mkdir()
            (project_dir / "config.yaml").write_text(
                """
mcp_servers:
  shared:
    transport: stdio
    command: ${MCP_COMMAND}
    env:
      TOKEN: ${MCP_TOKEN}
  project_only:
    transport: streamable_http
    url: https://project.invalid/mcp
""",
                encoding="utf-8",
            )
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                with mock.patch.dict(
                    os.environ, {"MCP_COMMAND": "python", "MCP_TOKEN": "secret"}
                ):
                    config = load_config(str(user_config))
            finally:
                os.chdir(old_cwd)
            self.assertEqual(set(config.mcp_servers), {"shared", "user_only", "project_only"})
            self.assertEqual(config.mcp_servers["shared"].env["TOKEN"], "secret")

    def test_real_stdio_transport(self):
        from flickcode.mcp.transport import StdioTransport

        config = MCPServerConfig(
            name="stdio_fixture",
            transport="stdio",
            command=sys.executable,
            args=[str(Path(__file__).parent / "fixtures" / "mcp_echo_server.py")],
        )
        client = MCPServerClient(config, MCPTimeouts(request_seconds=2.0))
        tools = client.connect_and_discover()
        self.assertEqual([item.name for item in tools], ["echo"])
        result = client.call_tool("echo", {"text": "hello"})
        self.assertTrue(result.content)
        self.assertEqual(result.content[0]["text"], "hello")
        process = client.transport.process
        client.close()
        self.assertIsNotNone(process)
        self.assertIsNotNone(process.poll())

    def test_streamable_http_json_and_session_headers(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                message = json.loads(self.rfile.read(length).decode("utf-8"))
                received.append((message, dict(self.headers)))
                request_id = message.get("id")
                method = message.get("method")
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "http-fixture", "version": "1"},
                    }
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Mcp-Session-Id", "session-1")
                    self.end_headers()
                    self.wfile.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode())
                    return
                if method == "tools/list":
                    result = {"tools": [{"name": "http_echo", "inputSchema": {"type": "object"}}]}
                elif method == "tools/call":
                    result = {"content": [{"type": "text", "text": "http-ok"}]}
                else:
                    self.send_response(202)
                    self.end_headers()
                    return
                payload = {"jsonrpc": "2.0", "id": request_id, "result": result}
                self.send_response(200)
                if method == "tools/call":
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
                else:
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(payload).encode())

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = MCPServerConfig(
                name="http_fixture",
                transport="streamable_http",
                url=f"http://127.0.0.1:{server.server_port}/mcp",
                headers={"X-Test": "yes"},
            )
            client = MCPServerClient(config, MCPTimeouts(request_seconds=2.0))
            tools = client.connect_and_discover()
            self.assertEqual(tools[0].name, "http_echo")
            result = client.call_tool("http_echo", {})
            self.assertEqual(result.content[0]["text"], "http-ok")
            client.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertGreaterEqual(len(received), 3)
        def header(headers, name):
            return next((value for key, value in headers.items() if key.lower() == name.lower()), None)

        self.assertEqual(header(received[0][1], "X-test"), "yes")
        self.assertEqual(header(received[1][1], "Mcp-session-id"), "session-1")

    def test_jsonrpc_乱序配对和超时清理(self):
        transport = FakeTransport()
        peer = JsonRpcPeer(transport, MCPTimeouts(request_seconds=0.2))
        peer.start()
        results = {}

        def call(method):
            results[method] = peer.request(method)

        first = threading.Thread(target=call, args=("first",))
        second = threading.Thread(target=call, args=("second",))
        first.start()
        second.start()
        deadline = time.time() + 1
        while len(transport.sent) < 2 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(transport.sent), 2)
        for message in reversed(transport.sent):
            transport.respond({"jsonrpc": "2.0", "id": message["id"], "result": message["method"]})
        first.join()
        second.join()
        self.assertEqual(results, {"first": "first", "second": "second"})
        with self.assertRaises(MCPTimeoutError):
            peer.request("timeout", timeout=0.01)
        self.assertEqual(peer.pending_count, 0)

    def test_jsonrpc_invalid_response(self):
        with self.assertRaises(MCPProtocolError):
            parse_message({"jsonrpc": "2.0", "id": 1, "result": {}, "error": {}})
        encoded = encode_message({"jsonrpc": "2.0", "method": "initialized"}, True)
        self.assertNotIn("\n", encoded)

    def test_client_lifecycle_pagination_and_call(self):
        def respond(transport, message):
            method = message.get("method")
            request_id = message.get("id")
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "1"},
                }
            elif method == "tools/list":
                if message.get("params", {}).get("cursor") == "next":
                    result = {"tools": [{"name": "second", "inputSchema": {"type": "object"}}]}
                else:
                    result = {
                        "tools": [{
                            "name": "first",
                            "description": "First",
                            "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
                        }],
                        "nextCursor": "next",
                    }
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": "called"}]}
            else:
                if "id" not in message:
                    return
                result = {}
            if request_id is not None:
                transport.respond({"jsonrpc": "2.0", "id": request_id, "result": result})

        transport = FakeTransport(respond)
        client = MCPServerClient(
            MCPServerConfig(name="fake", transport="stdio", command="ignored"),
            transport=transport,
        )
        tools = client.connect_and_discover()
        self.assertEqual([tool.name for tool in tools], ["first", "second"])
        result = client.call_tool("first", {"x": "ok"})
        self.assertEqual(result.content[0]["text"], "called")
        self.assertEqual(transport.started, 1)
        client.close()
        self.assertEqual(transport.closed, 1)

    def test_adapter_result_conversion(self):
        class FakeClient:
            def call_tool(self, name, arguments):
                return MCPCallResult(
                    content=[
                        {"type": "text", "text": "hello"},
                        {"type": "resource_link", "uri": "file:///tmp/a"},
                    ],
                    structured_content={"ok": True},
                )

        definition = MCPToolDefinition(
            server_name="remote",
            name="search",
            title=None,
            description="Search",
            input_schema={"type": "object"},
        )
        adapter = MCPToolAdapter(definition, FakeClient())
        self.assertEqual(adapter.spec.name, "mcp__remote__search")
        result = adapter.execute({"q": "x"})
        self.assertTrue(result.success)
        self.assertIn("hello", result.output)
        self.assertIn("resource_link", result.output)

    def test_manager_isolates_failed_server(self):
        original = manager_module.MCPServerClient

        class FakeClient:
            def __init__(self, config, timeouts):
                self.config = config
                self.closed = False

            def connect_and_discover(self):
                if self.config.name == "bad":
                    raise RuntimeError("unavailable")
                return [MCPToolDefinition(
                    server_name=self.config.name,
                    name="echo",
                    title=None,
                    description="Echo",
                    input_schema={"type": "object"},
                )]

            def close(self):
                self.closed = True

            def call_tool(self, name, arguments):
                return MCPCallResult(content=[{"type": "text", "text": "ok"}])

        manager_module.MCPServerClient = FakeClient
        try:
            configs = {
                name: MCPServerConfig(name=name, transport="stdio", command="x")
                for name in ("good", "bad")
            }
            manager = MCPClientManager(configs)
            registry = ToolRegistry()
            report = manager.start_all(registry)
            self.assertEqual(report.successful_servers, ["good"])
            self.assertEqual(len(report.failed_servers), 1)
            self.assertIsNotNone(registry.get("mcp__good__echo"))
            manager.close()
        finally:
            manager_module.MCPServerClient = original

    def test_agent_loop_calls_mcp_adapter_through_registry(self):
        class FakeProvider:
            class Config:
                protocol = "openai"

            config = Config()

            def __init__(self):
                self.calls = 0

            def stream_chat(self, messages, thinking=False, tools=None, system=None):
                self.calls += 1
                if self.calls == 1:
                    yield StreamEvent(
                        "tool_call",
                        json.dumps({
                            "id": "call-1",
                            "name": "mcp__fake__echo",
                            "arguments": {"text": "from-agent"},
                        }),
                    )
                    yield StreamEvent("done", json.dumps({"usage": {}}))
                else:
                    self.assert_tool_result(messages)
                    yield StreamEvent("text", "done")
                    yield StreamEvent("done", json.dumps({"usage": {}}))

            @staticmethod
            def assert_tool_result(messages):
                tool_messages = [message for message in messages if message.role == "tool"]
                assert tool_messages and tool_messages[-1].content == "from-agent"

        class FakeClient:
            def call_tool(self, name, arguments):
                self.last_call = (name, arguments)
                return MCPCallResult(content=[{"type": "text", "text": arguments["text"]}])

        definition = MCPToolDefinition(
            server_name="fake",
            name="echo",
            title=None,
            description="Echo",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        )
        registry = ToolRegistry()
        registry.register_instance(MCPToolAdapter(definition, FakeClient()))
        provider = FakeProvider()
        messages = [Message(role="user", content="echo this")]
        events = list(AgentLoop(provider, registry, AgentMode.FULL).run(messages))
        self.assertEqual(provider.calls, 2)
        self.assertEqual([event.type for event in events].count("tool_result"), 1)
        self.assertEqual(messages[-1].role, "assistant")
        self.assertEqual(messages[-1].content, "done")


if __name__ == "__main__":
    unittest.main()
