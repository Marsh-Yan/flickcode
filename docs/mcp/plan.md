# MCP Client Integration Plan

## 架构概览

本方案在现有 `Session -> ToolRegistry -> AgentLoop -> BaseTool` 链路旁增加 MCP 管理层。MCP 工具在启动阶段完成发现并注册，运行阶段只表现为普通 `BaseTool`，因此 Agent、Provider 和 TUI 不需要为 MCP 增加专用分支。

```text
CLI
  |
  v
Session
  |-- Config.mcp_servers
  |-- MCPClientManager.start_all()
  |       |-- MCPServerConnection (per server)
  |       |       |-- JsonRpcPeer
  |       |       |       |-- StdioTransport
  |       |       |       `-- StreamableHttpTransport
  |       |       `-- MCPToolAdapter -> ToolRegistry.register_instance()
  |
  `-- AgentLoop -> ToolRegistry -> MCPToolAdapter.execute()
                                      |
                                      `-- tools/call -> MCPServerConnection
```

职责边界如下：

- `config.py` 只负责读取、合并、校验配置和环境变量展开，不负责启动进程或访问网络。
- `transport.py` 只负责字节/HTTP 消息传输，不理解 MCP 方法语义。
- `jsonrpc.py` 负责 JSON-RPC 2.0 消息编码、请求 ID、pending 表、响应配对和协议错误。
- `client.py` 负责 MCP 生命周期、工具列表分页和工具调用，不直接处理 YAML 或 ToolRegistry。
- `adapter.py` 负责把 MCP 工具定义/调用结果映射为 FlickCode 的 `BaseTool`/`ToolResult`。
- `manager.py` 负责多个 Server 的并行启动、失败隔离、缓存和关闭。
- `session.py` 负责把 MCP Manager 接入 Session 生命周期和现有工具注册流程。

## 核心数据结构

### `MCPServerConfig`

表示已经完成类型校验和变量展开的单个 Server 配置。

```python
@dataclass
class MCPServerConfig:
    name: str
    transport: str  # "stdio" | "streamable_http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
```

`stdio` 只允许使用 `command/args/env`，`streamable_http` 只允许使用 `url/headers`。解析后的对象不保留 secret 展开前后的日志文本。

### `MCPClientInfo`

```python
@dataclass(frozen=True)
class MCPClientInfo:
    name: str
    version: str
```

初始化请求固定声明 FlickCode 客户端身份和 MCP `2025-06-18` 协议版本。客户端 capability 只声明本期真正实现的能力，不声明 sampling、roots 或其他未实现能力。

### `JsonRpcRequest` / `JsonRpcResponse` / `JsonRpcError`

内部使用轻量 dataclass 或受控 dict 表示 JSON-RPC 消息，所有边界都经过校验：

```python
@dataclass(frozen=True)
class JsonRpcRequest:
    request_id: int | str
    method: str
    params: dict[str, Any] | None = None

@dataclass(frozen=True)
class JsonRpcError:
    code: int
    message: str
    data: Any = None

@dataclass(frozen=True)
class JsonRpcResponse:
    request_id: int | str | None
    result: dict[str, Any] | None = None
    error: JsonRpcError | None = None
```

编码器统一补充 `jsonrpc: "2.0"`。响应模型保证 `result` 与 `error` 不能同时存在；通知单独走不带 ID 的编码路径。

### `MCPToolDefinition`

```python
@dataclass(frozen=True)
class MCPToolDefinition:
    server_name: str
    name: str
    title: str | None
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
```

`input_schema` 保留 MCP 返回的完整 object schema，`annotations` 只作为元数据和展示参考，不作为权限判断依据。

### `MCPCallResult`

```python
@dataclass(frozen=True)
class MCPCallResult:
    content: list[dict[str, Any]]
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
    raw_result: dict[str, Any] = field(default_factory=dict)
```

适配器使用该结构把文本、结构化内容和其他 content block 稳定序列化为 `ToolResult`。

### `ServerState`

```python
class ServerState(str, Enum):
    CONFIGURED = "configured"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"
```

每个 Server 独立保存状态、连接对象、发现到的工具、失败原因和关闭结果；管理器不使用一个全局状态代表所有 Server。

## 核心接口

### `MCPTransport`

```python
class MCPTransport(Protocol):
    def start(self) -> None: ...
    def send(self, message: dict[str, Any]) -> None: ...
    def set_message_handler(self, handler: Callable[[dict[str, Any]], None]) -> None: ...
    def close(self) -> None: ...
```

`start()` 建立底层通道并启动必要的读取任务；`send()` 只发送一条完整 JSON-RPC 消息；读取到消息后调用 handler；`close()` 必须幂等。

### `StdioTransport`

构造函数接收 `MCPServerConfig` 和 `MCPTimeouts`。实现使用 `subprocess.Popen` 的参数列表模式启动子进程，stdin/stdout 使用 UTF-8 文本管道，stdout reader 按行解析 JSON，stderr reader 只写脱敏诊断日志。stdout reader 退出时向 JSON-RPC peer 广播连接关闭错误。

### `StreamableHttpTransport`

构造函数接收 URL、用户 headers、超时和 HTTP client 工厂。每个 request 通过 POST 发送单个 JSON-RPC 消息，自动追加 `Accept: application/json, text/event-stream`，初始化后的 session ID 和协商协议版本由 transport 保存并追加到后续请求。

HTTP 响应解析分两路：`application/json` 解析一个消息；`text/event-stream` 按 SSE event/data 解析其中的 JSON-RPC 消息。HTTP worker 将解析到的每条消息交给 peer handler。非 2xx、无法解析的 content type、连接超时和读取超时均通过 peer 的 pending 请求返回错误。

### `JsonRpcPeer`

```python
class JsonRpcPeer:
    def __init__(self, transport: MCPTransport, timeouts: MCPTimeouts): ...
    def start(self) -> None: ...
    def request(self, method: str, params: dict[str, Any] | None = None) -> Any: ...
    def notify(self, method: str, params: dict[str, Any] | None = None) -> None: ...
    def close(self) -> None: ...
```

实现细节：

- 用锁保护递增 request ID 和 `pending: dict[id, PendingRequest]`。
- `request()` 先注册 pending，再调用 transport.send，等待对应事件或超时。
- `_handle_message()` 根据 response ID 完成对应 pending；无 ID 的 notification 交给通知处理器；未知 ID 记录协议警告。
- 任一 transport 错误、连接关闭或 peer close 都会以同一错误完成所有 pending，随后清空表。
- 本期不接受 Server 发起的业务 request；遇到这类消息返回“未实现”错误或记录并关闭对应会话，不能伪造成功响应。

### `MCPServerClient`

```python
class MCPServerClient:
    def connect_and_discover(self) -> list[MCPToolDefinition]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult: ...
    def close(self) -> None: ...
```

`connect_and_discover()` 的固定流程为 `transport.start()` → `initialize` → 校验结果 → `notifications/initialized` → 循环 `tools/list`。工具列表用 cursor 集合和最大页数保护；重复 cursor 直接失败当前 Server。

### `MCPToolAdapter`

```python
class MCPToolAdapter(BaseTool):
    source_server: str
    remote_name: str

    def execute(self, params: dict[str, Any]) -> ToolResult: ...
```

适配器的 `spec.name` 为 `mcp__{server_name}__{remote_name}`，`spec.input_schema` 保留完整 MCP schema。`execute()` 只通过持有的 `MCPServerClient` 调用远端，并将协议错误、工具级错误和 content blocks 转成稳定 `ToolResult`。

### `MCPClientManager`

```python
class MCPClientManager:
    def __init__(
        self,
        configs: dict[str, MCPServerConfig],
        timeouts: MCPTimeouts | None = None,
    ): ...

    def start_all(self, registry: ToolRegistry) -> MCPStartupReport: ...
    def close(self) -> None: ...
```

`start_all()` 使用每个 Server 独立的工作单元并行连接/发现；每个成功的工具先检查全局名称冲突，再通过 `register_instance()` 注册。返回报告包含成功 Server、失败 Server、注册工具数量和脱敏错误摘要，供 Session/CLI 输出。

### `MCPTimeouts`

```python
@dataclass(frozen=True)
class MCPTimeouts:
    connect_seconds: float = 10.0
    request_seconds: float = 60.0
    shutdown_seconds: float = 5.0
    max_tool_pages: int = 100
```

这些默认值集中定义，后续如需暴露配置可以扩展，不在本期把所有运行参数扩展到用户配置格式。

## ToolRegistry 兼容扩展

现有 `ToolRegistry.register(tool_cls)` 继续保留，新增：

```python
def register_instance(self, tool: BaseTool) -> None: ...
def has(self, name: str) -> bool: ...
```

`register_instance()` 拒绝重复名称，不覆盖原有工具；内置工具仍走原来的按类实例化路径。

`ToolSpec` 增加可选的完整 schema 字段：

```python
input_schema: dict[str, Any] | None = None
```

Registry 的 Anthropic/OpenAI formatter 优先使用 `input_schema`；旧工具继续由 `parameters` 生成 schema。这样既维持现有工具的行为，也允许 MCP 传递任意合法 JSON object schema。

## 配置加载设计

`Config` 增加：

```python
mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
```

增加私有的原始 YAML 层合并函数，流程为：

1. 读取用户默认配置；若用户配置不存在，沿用现有默认模板创建逻辑。
2. 读取当前目录 `.flickcode/config.yaml`；不存在视为空层。
3. 当未传 `--config` 时，用户层作为 base；传入 `--config` 时，该文件替代用户层作为 base，以保留现有自定义配置语义。
4. 对 `mcp_servers` 单独按 key 合并：项目层同名 key 完整覆盖 base 层，同名不做字段级深合并。
5. 先展开 `${VAR}`，再校验 transport 和对应字段；不定义变量只使对应 Server 无效。
6. provider 仍按现有列表校验和解析，MCP 配置错误通过独立的 per-server diagnostics 返回，不改变现有 provider 必须存在的语义。

项目级 MCP 配置在显式 `--config` 下仍会合并，但项目文件只贡献 `mcp_servers`，不会覆盖自定义配置文件中的 providers；这样同时保留 `--config` 的 provider 语义和项目级 MCP 的自动接入。

## 模块设计

### 配置模块：`src/flickcode/config.py`

**职责：** 定义 `MCPServerConfig`、解析 MCP map、加载双层配置、展开环境变量、返回脱敏诊断。

**依赖：** YAML、`os.environ`、`Path`；不依赖 transport、subprocess、ToolRegistry。

**对外影响：** `Config` 新增 `mcp_servers`，原有 `ProviderConfig` 和 `load_config()` 调用方式保持兼容。

### MCP 协议模块：`src/flickcode/mcp/jsonrpc.py`

**职责：** JSON-RPC 2.0 编解码、request ID、pending 配对、通知、超时和连接关闭错误传播。

**依赖：** 标准库 `json`、`threading`、`queue` 或 `concurrent.futures`。

**不负责：** MCP 方法名含义、工具 schema 或 HTTP headers。

### MCP 传输模块：`src/flickcode/mcp/transport.py`

**职责：** 提供 `MCPTransport`、`StdioTransport`、`StreamableHttpTransport` 和 transport 异常类型。

**依赖：** stdio 使用 `subprocess`；HTTP 使用标准库 HTTP 客户端或项目批准的轻量同步 HTTP 依赖。若引入第三方依赖，只在该模块使用，并提供 fake transport 测试注入点。

### MCP 客户端模块：`src/flickcode/mcp/client.py`

**职责：** 组装 transport 和 peer，执行 initialize、initialized、tools/list 分页、tools/call 和 close。

**依赖：** `jsonrpc.py`、`transport.py`、MCP 数据结构。

### 工具适配模块：`src/flickcode/mcp/adapter.py`

**职责：** MCP tool definition 到 `ToolSpec`/`BaseTool`、MCP call result 到 `ToolResult` 的转换，处理命名、schema 保留和 content 序列化。

**依赖：** `mcp/client.py`、`flickcode.tools.base`。

### 生命周期模块：`src/flickcode/mcp/manager.py`

**职责：** 多 Server 并行启动、状态缓存、冲突检测、报告生成、失败隔离和统一关闭。

**依赖：** `config.py`、`client.py`、`adapter.py`、`ToolRegistry`。

### Session 接入：`src/flickcode/session.py`

**职责：** 在默认或传入 Registry 准备好之后启动 MCP Manager，把成功发现的适配器注册进去，并提供 `close()`/上下文退出路径。

**交互规则：** MCP Manager 初始化失败不抛出会阻断主程序的总异常；Session 保留 manager 引用，在关闭时调用 manager.close()。显式传入的自定义 Registry 仍允许测试或调用方控制内置工具集合，MCP 工具注册到该 Registry。

### CLI/TUI 接入：`src/flickcode/cli.py`、`src/flickcode/tui.py`

**职责：** 启动后展示 MCP startup report 摘要，退出时确保 Session close。TUI 不处理协议细节，运行中的 MCP 工具继续使用现有 AgentEvent/tool_result 渲染。

### 工具系统：`src/flickcode/tools/base.py`、`src/flickcode/tools/registry.py`

**职责：** 增加完整 input schema 和实例注册的向后兼容扩展。

## 模块交互

### 启动流程

```text
Session.__init__
  -> load_config()
  -> create_default_registry()
  -> MCPClientManager(config.mcp_servers)
  -> manager.start_all(registry)
       -> per-server connect
       -> initialize / initialized
       -> tools/list(cursor...)
       -> create MCPToolAdapter
       -> registry.register_instance(adapter)
  -> AgentLoop sees one combined registry
```

一个 Server 的失败路径只结束该 Server 的工作单元；`start_all()` 汇总报告后返回，不因单项异常中断其他工作单元。

### Agent 调用流程

```text
AgentLoop._execute_single_tool
  -> registry.get("mcp__server__tool")
  -> MCPToolAdapter.execute(arguments)
  -> MCPServerClient.call_tool(remote_name, arguments)
  -> JsonRpcPeer.request("tools/call", params)
  -> transport.send()
  -> response matched by request id
  -> MCPCallResult -> ToolResult
  -> existing AgentEvent("tool_result") path
```

### 关闭流程

```text
CLI/TUI finally
  -> Session.close()
  -> MCPClientManager.close()
  -> close each peer/transport independently
  -> terminate stdio process / close HTTP client
  -> complete and clear pending requests
```

## 错误与日志设计

错误类型按层划分：`MCPConfigError`、`MCPTransportError`、`MCPProtocolError`、`MCPTimeoutError`、`MCPToolCallError`。每个错误携带 `server_name` 和 operation；对外文本由 manager/adapter 生成，避免把底层 secret 或完整 headers 直接插入异常。

日志使用 `logging.getLogger("flickcode.mcp")` 的子 logger，启动日志包含 Server 名称、transport、状态和工具数量；调用日志包含远端工具名、耗时和结果状态，不包含参数值。header 日志只列出 header 名称，Authorization 等敏感 header 不输出值。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| MCP 工具接入方式 | 新增 `register_instance()` + `MCPToolAdapter` | 现有 Registry 按类注册，但 MCP 工具是运行时发现的实例；保留旧 API 可向后兼容 |
| Schema 表达 | `ToolSpec.input_schema` 优先，旧 `parameters` 回退 | MCP inputSchema 是任意 JSON object schema，不能安全压缩成简单参数列表 |
| 工具命名 | `mcp__{server}__{tool}` | 解决聚合多个 Server 时的同名冲突；外部原名仍保存在 adapter 中 |
| 配置覆盖 | 项目级同名 Server 完整覆盖 base | 避免嵌套字段残留造成用户无法预测的混合配置 |
| `--config` 语义 | 自定义文件替代 provider base，但项目文件仍只合并 MCP | 保持旧 provider 配置入口，同时满足项目级 MCP 自动发现 |
| 协议基线 | MCP `2025-06-18` | 与已批准 spec 的初始化/会话设计一致；不隐式混入未来协议变更 |
| JSON-RPC 并发模型 | 同步调用 API + 每连接 pending map；stdio reader/HTTP worker 后台投递 | 兼容现有同步 Agent Loop，同时支持乱序响应和多个未完成请求 |
| stdio 执行 | `Popen` 参数列表，不经过 shell | 避免 command/args/env 被 shell 二次解释，降低注入风险 |
| HTTP 实现 | 独立 Streamable HTTP transport，JSON/SSE 双解析 | 保持协议语义与传输解耦，便于 fake transport 测试 |
| Server 失败策略 | manager per-server 隔离并返回报告 | 单个外部服务不可用不应阻断 FlickCode 或其他 Server |
| 重连/健康检查 | 本期不实现 | 与已批准 spec 的范围保持一致，避免生命周期复杂度膨胀 |
| 依赖策略 | 优先标准库；如 HTTP 流解析需要第三方则集中到 transport | 限制依赖面，保证协议核心可独立测试 |

## 文件组织

```text
docs/mcp/
├── spec.md
├── plan.md
├── task.md
└── checklist.md

src/flickcode/
├── config.py                    # MCPServerConfig + 双层 MCP 配置解析
├── session.py                   # 启动/关闭 MCP Manager
├── cli.py                       # 启动摘要与退出清理
├── tools/
│   ├── base.py                  # ToolSpec.input_schema
│   └── registry.py              # register_instance()/has()
└── mcp/
    ├── __init__.py              # MCP 公共导出
    ├── models.py                # MCP 数据结构、状态、超时、报告
    ├── errors.py                # 分层异常
    ├── jsonrpc.py               # JSON-RPC peer 与 pending 配对
    ├── transport.py             # MCPTransport、stdio、Streamable HTTP
    ├── client.py                # initialize、tools/list、tools/call
    ├── adapter.py               # MCPToolAdapter 与结果/schema 转换
    └── manager.py               # 多 Server 生命周期和注册

tests/
├── test_mcp_config.py
├── test_mcp_jsonrpc.py
├── test_mcp_stdio_transport.py
├── test_mcp_http_transport.py
├── test_mcp_client.py
├── test_mcp_adapter.py
├── test_mcp_manager.py
└── test_mcp_integration.py
```

## Spec 覆盖关系

| Spec 需求 | 主要设计归属 |
|-----------|--------------|
| F1–F3 | `config.py`、`MCPServerConfig`、双层 merge/expand |
| F4–F5 | `transport.py` |
| F6 | `jsonrpc.py`、`MCPTransport` |
| F7–F8 | `client.py` |
| F9–F10 | `adapter.py`、`ToolRegistry` |
| F11–F12 | `manager.py`、`Session.close()` |
| N1、N3、N7 | 兼容扩展、权限链路、日志脱敏 |
| N2、N4、N5、N9 | manager 状态隔离、timeouts、并发和启动报告 |
| N6、N8、N10、N11 | fake transport、协议 fixture、schema 保留和依赖布局 |
