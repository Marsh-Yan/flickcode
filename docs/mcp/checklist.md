# MCP Client Integration Checklist

> 每一项都必须通过命令、测试输出或可观察运行行为验证；不能只通过阅读代码判断完成。

## 实现完整性

- [ ] [配置模型] `MCPServerConfig`、`MCPTimeouts`、`ServerState` 和配置诊断可被导入并实例化（验证：`uv run python -c "from flickcode.config import Config; from flickcode.mcp.models import MCPServerConfig, MCPTimeouts, ServerState; print('models ok')"`）。
- [ ] [stdio 配置] 合法 stdio map 能解析 command、args、env（验证：运行 `tests/test_mcp_config.py` 的合法配置用例，断言字段值）。
- [ ] [HTTP 配置] 合法 `streamable_http` map 能解析 url、headers（验证：运行 `tests/test_mcp_config.py` 的 HTTP 配置用例，断言字段值）。
- [ ] [配置校验] 缺 transport、缺 command/url、transport 未知或字段类型错误时，只有对应 Server 被标记失败（验证：`uv run pytest tests/test_mcp_config.py -q`，观察 per-server diagnostics）。
- [ ] [配置合并] 用户级与项目级 MCP map 同名覆盖、不同名保留（验证：`uv run pytest tests/test_mcp_config.py -q`，断言最终 Server map）。
- [ ] [环境变量] `${VAR}` 能展开，未定义变量会失败且日志不含变量值或 secret（验证：`uv run pytest tests/test_mcp_config.py -q`，检查异常与 caplog）。
- [ ] [Registry 实例注册] `register_instance()` 能注册 MCP adapter，重复名称不会覆盖原工具（验证：`uv run pytest tests/test_mcp_adapter.py -q`，断言原实例仍在）。
- [ ] [完整 schema] 带 `input_schema` 的 ToolSpec 经 Anthropic/OpenAI formatter 后仍保留 properties、required 和描述；旧内置工具格式不变（验证：`uv run pytest -q`）。

## JSON-RPC 与传输

- [ ] [JSON-RPC 编码] 合法 request、response、error、notification 可编码/解析；stdio 消息为单行 UTF-8 JSON（验证：`uv run pytest tests/test_mcp_jsonrpc.py -q`）。
- [ ] [JSON-RPC 拒绝非法消息] 无效 JSON、缺少 jsonrpc/id/method、result 与 error 同时存在、notification 带 id 会被拒绝（验证：`uv run pytest tests/test_mcp_jsonrpc.py -q`，观察具体异常类型/信息）。
- [ ] [请求 ID 唯一] 同一 Server 会话内并发请求生成不重复的 ID（验证：`uv run pytest tests/test_mcp_jsonrpc.py -q`，断言发送 fixture 的 IDs 唯一）。
- [ ] [乱序配对] 多个并发请求以乱序 response 返回时，每个调用方收到自己的 result（验证：`uv run pytest tests/test_mcp_jsonrpc.py -q`，运行 fake transport 乱序用例）。
- [ ] [异常清理] 未知 response ID、响应超时、transport close 会完成/清理所有 pending 请求（验证：`uv run pytest tests/test_mcp_jsonrpc.py -q`，断言 pending 数为 0）。
- [ ] [stdio 双向通信] 测试子进程能收到一行 JSON-RPC 并返回响应（验证：`uv run pytest tests/test_mcp_stdio_transport.py -q`）。
- [ ] [stdio stderr 隔离] 子进程 stderr 被记录为诊断但不会被当作 JSON-RPC 响应（验证：`uv run pytest tests/test_mcp_stdio_transport.py -q`，检查响应配对和日志）。
- [ ] [stdio 退出回收] 子进程异常退出、stdout 非 JSON 或 close 后，进程和管道被回收（验证：`uv run pytest tests/test_mcp_stdio_transport.py -q`，断言 process.poll() 非空）。
- [ ] [HTTP JSON] Streamable HTTP 返回 `application/json` 时，客户端能完成请求配对（验证：`uv run pytest tests/test_mcp_http_transport.py -q`）。
- [ ] [HTTP SSE] Streamable HTTP 返回 `text/event-stream` 时，客户端能解析 data 中的 JSON-RPC 消息（验证：`uv run pytest tests/test_mcp_http_transport.py -q`）。
- [ ] [HTTP headers/session] 客户 headers、Accept、MCP 协议版本和初始化返回的 session id 在后续请求中正确出现（验证：`uv run pytest tests/test_mcp_http_transport.py -q`，检查 fake client 捕获的 headers）。
- [ ] [HTTP 错误] HTTP 非 2xx、无效 content type、连接超时和读取超时转换为明确 transport error（验证：`uv run pytest tests/test_mcp_http_transport.py -q`）。

## MCP 生命周期与工具发现

- [ ] [初始化顺序] 每个 Server 都按 `initialize` → response → `notifications/initialized` → `tools/list` 顺序发送消息（验证：`uv run pytest tests/test_mcp_client.py -q`，断言 fake Server 收到的 method 序列）。
- [ ] [协议版本] initialize 使用 MCP `2025-06-18`，收到不兼容版本时 Server 进入失败且不注册工具（验证：`uv run pytest tests/test_mcp_client.py -q`）。
- [ ] [能力校验] Server 未声明 tools capability 或返回初始化协议错误时，该 Server 不产生可用 adapter（验证：`uv run pytest tests/test_mcp_client.py -q`）。
- [ ] [tools/list 分页] 存在 nextCursor 时继续请求，直到没有 nextCursor；重复 cursor 或超过 max pages 时停止并失败该 Server（验证：`uv run pytest tests/test_mcp_client.py -q`）。
- [ ] [工具定义保留] 合法工具的 name、title、description、inputSchema、outputSchema 和 annotations 可被读取（验证：`uv run pytest tests/test_mcp_client.py -q`）。
- [ ] [局部非法工具] 同一页中一个工具 schema 非法时，该工具被跳过，其他合法工具仍被发现（验证：`uv run pytest tests/test_mcp_client.py -q`）。
- [ ] [tools/call 请求] 适配器调用时，Server 收到正确的远端名称和 arguments object（验证：`uv run pytest tests/test_mcp_client.py tests/test_mcp_adapter.py -q`）。
- [ ] [MCP close] 正常 close、重复 close 和单个 close 失败都不会阻止其他连接清理（验证：`uv run pytest tests/test_mcp_client.py tests/test_mcp_manager.py -q`）。

## 工具适配与 Agent 集成

- [ ] [命名空间] 远端 `search` 注册为 `mcp__<server>__search`，源 Server 和远端名称仍可追踪（验证：`uv run pytest tests/test_mcp_adapter.py -q`）。
- [ ] [冲突保护] MCP 工具与内置工具或另一个 Server 生成同名时，不发生静默覆盖，冲突双方进入报告（验证：`uv run pytest tests/test_mcp_manager.py -q`）。
- [ ] [文本结果] 多个 text content 按顺序转换为 ToolResult.output（验证：`uv run pytest tests/test_mcp_adapter.py -q`）。
- [ ] [复杂结果] image、audio、resource_link、embedded resource、structuredContent 等非文本/结构化内容能稳定序列化，不使 Agent 崩溃（验证：`uv run pytest tests/test_mcp_adapter.py -q`）。
- [ ] [工具级错误] `isError: true` 转换为 `success=False`，并保留可读错误内容（验证：`uv run pytest tests/test_mcp_adapter.py -q`）。
- [ ] [协议级错误] JSON-RPC error、transport error 和 timeout 转换为 `ToolResult(success=False)`（验证：`uv run pytest tests/test_mcp_adapter.py -q`）。
- [ ] [Agent 透明调用] AgentLoop 通过现有 registry lookup 和 `_execute_single_tool()` 执行 MCP adapter，不增加 MCP 专用分支（验证：`uv run pytest tests/test_mcp_integration.py -q`，观察 fake Server 收到调用）。
- [ ] [权限链路] MCP 工具调用仍经过现有 PermissionEngine，未因外部来源绕过权限（验证：`uv run pytest tests/test_mcp_integration.py -q`，使用拒绝权限 fixture）。
- [ ] [事件链路] MCP tool_call/tool_result 沿用现有 AgentEvent 和 TUI renderer（验证：运行集成测试或手工启动后观察工具调用/结果显示）。

## 多 Server 与生命周期

- [ ] [并行启动] 多个 Server 可并行连接/发现，启动结果汇总包含每个 Server 状态（验证：`uv run pytest tests/test_mcp_manager.py -q`，使用带延迟 fake clients）。
- [ ] [失败隔离] 一个 Server 连接/初始化/发现失败时，另一个 Server 仍成功注册并可调用（验证：`uv run pytest tests/test_mcp_manager.py tests/test_mcp_integration.py -q`）。
- [ ] [连接缓存] 同一 Session 内重复启动或多次调用不会重复创建、初始化同一 Server（验证：`uv run pytest tests/test_mcp_manager.py -q`，断言 fake client counters）。
- [ ] [重复注册保护] 重复 `start_all()` 不会产生重复工具或覆盖内置工具（验证：`uv run pytest tests/test_mcp_manager.py -q`）。
- [ ] [Session 关闭] Session.close() 会关闭 manager，且 close 幂等（验证：`uv run pytest tests/test_mcp_integration.py -q`）。
- [ ] [退出清理] 正常退出、Ctrl+C 和异常退出路径都执行 Session.close()（验证：运行 TUI/CLI 退出场景，或使用 monkeypatch 断言 close 被调用）。
- [ ] [启动摘要] 交互界面能显示成功注册工具数量和失败 Server 摘要（验证：运行 CLI/TUI 测试或手工启动观察输出）。

## 安全、可观测性与兼容性

- [ ] [日志脱敏] 启动、连接、调用、错误日志不包含 API token、Authorization 值、完整 env 或完整大输出（验证：`uv run pytest tests/test_mcp_config.py tests/test_mcp_http_transport.py tests/test_mcp_manager.py -q`，检查 caplog）。
- [ ] [外部执行安全] stdio command/args 使用参数列表启动，不经过 shell 拼接（验证：`uv run pytest tests/test_mcp_stdio_transport.py -q`，检查 Popen 参数）。
- [ ] [超时保护] Server 不响应时，连接/请求在默认或配置 timeout 后结束，不无限阻塞（验证：`uv run pytest tests/test_mcp_jsonrpc.py tests/test_mcp_http_transport.py -q`）。
- [ ] [资源上限] 无限 tools/list cursor、重复 cursor 和大于 max pages 的发现被终止（验证：`uv run pytest tests/test_mcp_client.py -q`）。
- [ ] [无 MCP 向后兼容] 不配置 MCP 时，内置工具、纯文本对话、provider 选择和 Agent Loop 测试全部通过（验证：`uv run pytest -q`，并运行 `uv run flick --help`）。
- [ ] [无真实外部依赖] 协议核心、配置、适配和集成测试可用 fake transport/server 完成，无网络访问和真实 API key（验证：在无网络环境运行 `uv run pytest -q`）。
- [ ] [Python/安装兼容] 项目现有 Python 3.8+ 安装流程可完成依赖安装和 MCP 模块导入（验证：`uv sync`、`uv run python -c "from flickcode.mcp import MCPClientManager"`）。

## 编译、测试与质量

- [ ] [全量单元测试] 所有单元测试通过（验证：`uv run pytest -q`）。
- [ ] [分层测试] 配置、JSON-RPC、两种 transport、client、adapter、manager 测试均可单独运行（验证：分别运行 `tests/test_mcp_*.py`）。
- [ ] [导入检查] MCP 公共接口和 Session/Registry 兼容导入通过（验证：`uv run python -c "from flickcode.mcp import MCPClientManager, MCPServerClient; from flickcode.session import Session; from flickcode.tools.registry import ToolRegistry; print('imports ok')"`）。
- [ ] [CLI 检查] CLI 帮助、无 MCP 配置启动和退出路径可用（验证：`uv run flick --help`，并运行无 MCP fixture 的 CLI 测试）。
- [ ] [文档样例] README 中 MCP 配置样例、默认路径、命名规则和失败行为与实现一致（验证：人工对照 `README.md`、`docs/mcp/spec.md`、配置测试）。

## 端到端场景

- [ ] [场景 1：stdio 工具接入] 配置一个 stdio fake MCP Server → 启动 FlickCode → 完成初始化和多页工具发现 → Registry 出现 `mcp__local__<tool>` → Agent 调用工具 → Server 返回文本结果 → TUI 显示 tool call/result → 退出后子进程被回收（验证：`uv run pytest tests/test_mcp_integration.py -q`，并记录 fake Server method 序列和 process 状态）。
- [ ] [场景 2：HTTP 与失败隔离] 配置一个成功 HTTP Server 和一个不可用 Server → 启动时成功 Server 工具注册、失败 Server 出现摘要 → Agent 调用成功工具 → 返回 JSON/SSE 结果可见 → 退出时两个 Server 都执行清理（验证：`uv run pytest tests/test_mcp_integration.py -q`，记录 startup report、调用结果和 close counters）。
- [ ] [场景 3：双层配置与冲突] 用户级配置声明 `search` 和 `shared`，项目级覆盖 `shared` 并声明另一 Server 的同名工具 → 启动后项目配置生效、不同 Server 工具保留、命名冲突被报告且不覆盖内置工具（验证：`uv run pytest tests/test_mcp_config.py tests/test_mcp_manager.py -q`）。

## 验收记录模板

完成实现后，逐项填写实际命令、结果和证据；不要只将所有项目批量标为通过。

```text
项目：AC/Checklist 编号
命令：
实际结果：
证据：
状态：通过 / 未通过
```

## 本次实现验收记录

- [x] [核心单元测试] 运行 `.venv\Scripts\python.exe -m unittest discover -v`，10 个 MCP 测试全部通过；覆盖配置合并/变量展开、Registry schema、JSON-RPC 乱序配对与超时、MCP 生命周期分页、工具适配、多 Server 隔离、真实 stdio、本地 HTTP JSON/SSE，以及 AgentLoop 端到端调用。
- [x] [编译检查] 运行 `.venv\Scripts\python.exe -m compileall -q src tests`，退出码 0。
- [x] [CLI 检查] 运行 `.venv\Scripts\flick.exe --help`，正常输出参数帮助。
- [x] [MCP 导入] 运行 `.venv\Scripts\python.exe -c "from flickcode.mcp import MCPClientManager, MCPServerClient; print('mcp import ok')"`，输出 `mcp import ok`。
- [x] [无 MCP 兼容] 使用 `tests/fixtures/minimal_config.yaml` 启动 piped CLI 并输入 `/exit`，主程序退出码 0，未连接外部 Server。
- [x] [传输清理] stdio fixture 退出后 `process.poll()` 非空；HTTP fixture 的本地 server 在测试结束后 shutdown，session header 和 DELETE close 路径可执行。
- [ ] [pytest 全量测试] 当前 `.venv` 未安装 pytest，运行 pytest 得到 `No module named pytest`；已使用标准库 unittest 完成等价的 MCP 回归验证，未伪报 pytest 通过。
