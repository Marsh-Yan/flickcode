# MCP Client Integration Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `src/flickcode/config.py` | MCP 配置模型、双层合并、环境变量展开和校验 |
| 修改 | `src/flickcode/tools/base.py` | 为 `ToolSpec` 增加可选完整 input schema |
| 修改 | `src/flickcode/tools/registry.py` | 增加实例注册、冲突检测和 schema 优先转换 |
| 新建 | `src/flickcode/mcp/__init__.py` | MCP 公共导出 |
| 新建 | `src/flickcode/mcp/models.py` | 配置后模型、JSON-RPC/MCP 数据、状态、超时和启动报告 |
| 新建 | `src/flickcode/mcp/errors.py` | 分层异常和错误上下文 |
| 新建 | `src/flickcode/mcp/jsonrpc.py` | JSON-RPC 编解码、请求配对、通知和 pending 清理 |
| 新建 | `src/flickcode/mcp/transport.py` | stdio 与 Streamable HTTP 传输 |
| 新建 | `src/flickcode/mcp/client.py` | MCP 初始化、工具发现分页、工具调用和关闭 |
| 新建 | `src/flickcode/mcp/adapter.py` | MCP 工具到 BaseTool、结果到 ToolResult 的适配 |
| 新建 | `src/flickcode/mcp/manager.py` | 多 Server 并行启动、缓存、注册和关闭 |
| 修改 | `src/flickcode/session.py` | 创建 MCP Manager、启动发现、接入 Registry、关闭生命周期 |
| 修改 | `src/flickcode/cli.py` | 启动摘要与退出清理 |
| 修改 | `src/flickcode/tui.py` | 展示启动报告并在退出时关闭 Session |
| 新建 | `tests/test_mcp_config.py` | 配置解析和合并测试 |
| 新建 | `tests/test_mcp_jsonrpc.py` | JSON-RPC 编解码和乱序配对测试 |
| 新建 | `tests/test_mcp_stdio_transport.py` | stdio 传输测试 |
| 新建 | `tests/test_mcp_http_transport.py` | Streamable HTTP JSON/SSE 测试 |
| 新建 | `tests/test_mcp_client.py` | 初始化、分页发现、调用和关闭测试 |
| 新建 | `tests/test_mcp_adapter.py` | schema、命名和结果转换测试 |
| 新建 | `tests/test_mcp_manager.py` | 多 Server 隔离、缓存、冲突和关闭测试 |
| 新建 | `tests/test_mcp_integration.py` | Session + Registry + Agent 调用集成测试 |

## T1：扩展 MCP 配置数据模型与单层解析

**文件：** `src/flickcode/config.py`、`src/flickcode/mcp/models.py`、`src/flickcode/mcp/errors.py`

**依赖：** 无

**步骤：**

1. 定义 `MCPServerConfig`、`MCPTimeouts`、`ServerState` 和配置诊断结构。
2. 在 `Config` 增加 `mcp_servers`，保持已有 provider 字段和构造方式兼容。
3. 实现单个 raw Server map 到 `MCPServerConfig` 的校验：transport、stdio 字段、HTTP 字段和未知值。
4. 实现 `${VAR}` 展开；未定义变量抛出带变量名和 Server 名称的配置错误，错误文本不得包含 secret 值。
5. 为每种无效字段写测试输入和预期诊断。

**验证：** `uv run pytest tests/test_mcp_config.py -q`；预期合法配置解析成功，非法配置只产生对应 Server 级错误。

## T2：实现用户级与项目级配置合并

**文件：** `src/flickcode/config.py`、`tests/test_mcp_config.py`

**依赖：** T1

**步骤：**

1. 将用户默认配置、显式 `--config` 配置和当前目录 `.flickcode/config.yaml` 建模为 base/project 两层。
2. 对 `mcp_servers` 按 key 合并；同名 Server 使用项目级完整覆盖，不同名 Server 全部保留。
3. 当任一文件不存在时按空层处理，不改变既有 provider 缺失和默认模板行为。
4. 验证显式 `--config` 的 provider 语义保持不变，同时项目 MCP 仍能合并。
5. 覆盖空文件、同名覆盖、不同名追加、无 MCP 配置和 provider-only 配置场景。

**验证：** `uv run pytest tests/test_mcp_config.py -q`；预期每个合并场景的 Server map 和 provider 结果与 spec 一致。

## T3：扩展 ToolSpec 与 ToolRegistry

**文件：** `src/flickcode/tools/base.py`、`src/flickcode/tools/registry.py`、相关现有工具测试或新增 `tests/test_mcp_adapter.py`

**依赖：** 无

**步骤：**

1. 给 `ToolSpec` 增加可选 `input_schema`，不改变旧工具的 `parameters` 初始化。
2. 增加 `ToolRegistry.register_instance(tool)` 和 `has(name)`。
3. 注册实例时拒绝重复名称，不覆盖已注册工具。
4. 修改 Anthropic/OpenAI formatter：存在完整 `input_schema` 时优先使用，否则按旧 parameters 生成。
5. 验证六个内置工具的 API schema 和名称不发生变化。

**验证：** `uv run pytest -q`；预期既有工具测试通过，实例注册和完整 object schema 测试通过。

## T4：定义 JSON-RPC 模型、错误和编解码

**文件：** `src/flickcode/mcp/jsonrpc.py`、`src/flickcode/mcp/models.py`、`src/flickcode/mcp/errors.py`、`tests/test_mcp_jsonrpc.py`

**依赖：** T1

**步骤：**

1. 定义 request、response、error、notification 的内部表示或校验函数。
2. 实现 JSON-RPC 2.0 单行 JSON 编码，禁止 batch 和嵌入换行的 stdio 消息。
3. 校验 `jsonrpc`、request id、method、result/error 互斥和 notification 无 id。
4. 为无效 JSON、缺字段、result/error 同时存在和未知消息类型返回分层协议错误。
5. 使用固定 fixture 验证合法消息的编码和解析结果。

**验证：** `uv run pytest tests/test_mcp_jsonrpc.py -q`；预期合法 fixture round-trip，非法 fixture 均被拒绝并带可读错误。

## T5：实现 JsonRpcPeer 请求配对与关闭传播

**文件：** `src/flickcode/mcp/jsonrpc.py`、`tests/test_mcp_jsonrpc.py`

**依赖：** T4

**步骤：**

1. 实现线程安全递增 request ID 和 pending map。
2. 实现 `request()`：先登记 pending，再发送消息，等待对应 response 或 request timeout。
3. 实现按 ID 完成 pending 的 message handler，支持响应乱序到达。
4. 实现 notification 处理、未知 response ID 警告和重复 response 防护。
5. 实现 transport error/close 时完成所有 pending 并清空状态，`close()` 幂等。
6. 使用 fake transport 同时发起多个请求，注入乱序、未知 id、超时和 close 场景。

**验证：** `uv run pytest tests/test_mcp_jsonrpc.py -q`；预期所有请求收到正确响应或正确错误，测试结束 pending 数为 0。

## T6：实现 stdio Transport

**文件：** `src/flickcode/mcp/transport.py`、`tests/test_mcp_stdio_transport.py`

**依赖：** T4、T5

**步骤：**

1. 使用 `Popen` 参数列表启动 command/args，注入展开后的 env，不经过 shell。
2. 实现 stdin 单行 UTF-8 JSON 发送。
3. 实现 stdout 按行读取和 JSON 解析，将消息投递给 handler。
4. 实现 stderr 独立读取并脱敏记录，不把 stderr 当响应。
5. 处理进程退出、stdout 非 JSON、管道异常和 close；close 后确保进程退出或被终止并回收。
6. 使用测试子进程 fixture 模拟回显、乱序响应、stderr、异常退出和非法 stdout。

**验证：** `uv run pytest tests/test_mcp_stdio_transport.py -q`；预期消息可双向传输，异常可观察，测试结束不存在子进程。

## T7：实现 Streamable HTTP Transport

**文件：** `src/flickcode/mcp/transport.py`、`tests/test_mcp_http_transport.py`

**依赖：** T4、T5

**步骤：**

1. 实现 POST 单消息发送、用户 headers、Accept header 和 request timeout。
2. 解析 `application/json` 单对象响应并投递 handler。
3. 解析 `text/event-stream` 的 SSE data JSON-RPC 消息并投递 handler。
4. 在初始化响应中捕获 session id，并在后续请求追加 session id 和协议版本 header。
5. 处理非 2xx、无效 content type、连接/读取超时和网络异常。
6. 提供可注入 fake HTTP client 或本地测试 server，不依赖真实网络。

**验证：** `uv run pytest tests/test_mcp_http_transport.py -q`；预期 JSON/SSE/错误响应均有明确结果，敏感 header 值不进入日志。

## T8：实现 MCP Server Client 生命周期与工具发现

**文件：** `src/flickcode/mcp/client.py`、`src/flickcode/mcp/models.py`、`tests/test_mcp_client.py`

**依赖：** T5、T6、T7

**步骤：**

1. 根据配置创建 stdio 或 HTTP transport 和 JsonRpcPeer。
2. 实现 `initialize` 请求，声明 `2025-06-18`、客户端信息和实际 capability。
3. 校验协议版本、serverInfo、tools capability，发送 `notifications/initialized`。
4. 实现 `tools/list` cursor 分页，保存 cursor 集合并限制最大页数。
5. 将合法 tool definition 转为 `MCPToolDefinition`，单个非法工具只跳过该项。
6. 实现 `tools/call`，解析协议 error、`isError`、content、structuredContent 和 raw result。
7. 实现幂等 close，关闭 peer 和 transport，记录关闭失败。

**验证：** `uv run pytest tests/test_mcp_client.py -q`；预期 fixture 能完成握手、分页发现、调用和关闭，顺序符合 spec。

## T9：实现 MCPToolAdapter 与结果/schema 转换

**文件：** `src/flickcode/mcp/adapter.py`、`tests/test_mcp_adapter.py`

**依赖：** T3、T8

**步骤：**

1. 根据 Server 名称和远端 tool name 生成 `mcp__server__tool`，保留 source server/remote name。
2. 将完整 `inputSchema` 放入 `ToolSpec.input_schema`，描述为空时使用稳定回退文本。
3. 实现 `execute(params)` 调用 Server Client 的 `call_tool`。
4. 将文本 content 按顺序拼接，将非文本 content、structuredContent 和 raw metadata 稳定 JSON 序列化。
5. 将 MCP `isError`、JSON-RPC error、transport error 转换为 `ToolResult(success=False)`。
6. 验证 adapter 不依赖 Agent/TUI 专用分支，直接满足现有 `BaseTool`。

**验证：** `uv run pytest tests/test_mcp_adapter.py -q`；预期名称、schema、成功/失败/复杂结果转换全部稳定。

## T10：实现 MCP Manager 的并行启动、缓存与冲突隔离

**文件：** `src/flickcode/mcp/manager.py`、`src/flickcode/mcp/models.py`、`tests/test_mcp_manager.py`

**依赖：** T8、T9

**步骤：**

1. 为每个 Server 创建独立 `MCPServerClient` 和状态记录。
2. 使用线程池并行执行连接/初始化/发现；单个 future 异常转换为该 Server 失败报告。
3. 对每个 adapter 做全局名称冲突检查，拒绝重复项并保留双方诊断。
4. 成功后将 adapter 用 `register_instance()` 注册，并缓存 client/definitions/adapters。
5. 对重复 `start_all()` 做幂等处理，不重复连接或注册。
6. 实现独立关闭所有 clients，即使某个 close 失败也继续其他 close。

**验证：** `uv run pytest tests/test_mcp_manager.py -q`；预期一个 Server 失败不影响其他 Server，重复启动无重复注册，关闭无泄漏。

## T11：接入 Session 生命周期

**文件：** `src/flickcode/session.py`、`tests/test_mcp_integration.py`

**依赖：** T3、T10

**步骤：**

1. 在现有 Config 和默认/custom Registry 准备完成后创建 `MCPClientManager`。
2. 启动发现并将成功 MCP tools 注入 Session 使用的 Registry。
3. 保存 startup report 和 manager 引用，MCP 启动错误不阻断 provider/内置工具。
4. 为 Session 增加幂等 `close()`，关闭 MCP manager；兼容无 MCP manager 的旧测试构造。
5. 验证 AgentLoop 通过已有 `_execute_single_tool()` 找到并执行 MCP adapter，不增加 MCP 专用分支。

**验证：** `uv run pytest tests/test_mcp_integration.py -q`；预期 Session 创建后 Registry 包含成功 MCP 工具，并可通过 fake provider 完成 Agent 调用。

## T12：接入 CLI/TUI 启动摘要和退出清理

**文件：** `src/flickcode/cli.py`、`src/flickcode/tui.py`、必要时 `src/flickcode/renderer.py`

**依赖：** T11

**步骤：**

1. 在交互界面启动后显示成功注册工具数量和跳过 Server 摘要。
2. 将 Session 生命周期放入 `try/finally`，确保正常退出、Ctrl+C 和异常退出都调用 `session.close()`。
3. 不把协议细节放入 TUI 工具事件处理；MCP tool_call/tool_result 沿用现有渲染。
4. 保持 `/exit`、`/quit`、piped mode 和 `--config` 的现有行为。

**验证：** `uv run pytest -q`；并运行 `uv run flick --help`，预期 CLI 可启动、退出时调用 close，未配置 MCP 时无额外错误。

## T13：补充协议 fixture、fake Server 和端到端测试

**文件：** `tests/fixtures/mcp/`、`tests/test_mcp_integration.py`、相关测试文件

**依赖：** T6、T7、T8、T9、T10、T11

**步骤：**

1. 准备 MCP `2025-06-18` initialize、initialized、tools/list 分页、tools/call 成功/失败 fixture。
2. 准备 fake stdio Server：读取 JSON-RPC，返回工具列表和调用结果，可控地延迟/乱序/退出。
3. 准备 fake HTTP handler：返回 JSON、SSE、session id、HTTP error 和 timeout 场景。
4. 写完整流程测试：配置 → Session → Manager → Registry → AgentLoop → MCP Server → ToolResult。
5. 写双 Server 隔离测试和无 MCP 向后兼容测试。

**验证：** `uv run pytest tests/test_mcp_integration.py -q`；预期至少一个真实完整流程和一个失败隔离流程通过。

## T14：执行全量验证与文档样例校准

**文件：** `docs/mcp/spec.md`、`docs/mcp/plan.md`、`README.md`、测试文件

**依赖：** T1–T13

**步骤：**

1. 运行项目全量测试、导入检查和安装检查。
2. 对照 `checklist.md` 逐项记录真实证据，不用“代码看起来正确”替代命令输出。
3. 校准 README 的 MCP 配置样例、默认路径、工具命名和失败行为。
4. 检查日志脱敏、子进程回收、pending 清理、HTTP session header 和 schema 保留。
5. 只修复验证中暴露的问题，再重复相关测试和全量测试。

**验证：** `uv run pytest -q`、`uv run python -c "from flickcode.mcp import MCPClientManager"`、`uv run flick --help`；预期全部退出码为 0，且 checklist 中每条均有证据。

## 执行顺序

```text
T1 ──┬──> T2
     ├──> T4 ──> T5 ──┬──> T6 ──┐
     └──> T3           └──> T7 ──┼──> T8 ──> T9 ──> T10 ──> T11 ──> T12
                                  └──────────────────────────────> T13 ──> T14
```

- T2 和 T3 可在 T1 后并行。
- T6 与 T7 可在 T5 后并行。
- T8 必须等待两种 transport 都能提供统一 transport 行为。
- T9 可在 T8 完成后进行，T10 依赖 adapter 和 client。
- T11/T12 是运行时接入，T13 是完整 fixture/端到端覆盖，T14 最后执行。

## 任务粒度自检

- 每个任务只聚焦一个组件或一个紧密的集成边界。
- 每个任务都列出具体文件、依赖、操作步骤和可运行验证命令。
- 文件清单覆盖 plan 中所有模块和测试层。
- 任务顺序没有循环依赖，且并行任务边界明确。
