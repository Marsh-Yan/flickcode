# MCP Client Integration Spec

## 背景

FlickCode 当前已经具备统一的工具抽象和注册中心：内置工具通过 `BaseTool` 提供名称、描述、参数定义和执行入口，`ToolRegistry` 负责注册、查找以及向 Agent 使用的模型 API 格式转换。现有 Agent Loop 只认识已经注册到该中心的工具。

外部 MCP Server 提供了标准化的工具发现和调用协议，但 FlickCode 目前没有 MCP 客户端能力。用户无法仅通过配置复用文件系统、数据库、浏览器或其他领域的 MCP 工具，也无法让这些工具自然地参与现有 Agent 的工具调用流程。

本功能为 FlickCode 增加一个启动阶段的 MCP 客户端层：读取配置中声明的 Server，建立对应传输连接，完成 MCP 初始化和工具发现，再把发现到的工具适配为现有工具接口。后续 Agent 不需要区分内置工具和 MCP 工具，仍通过现有 `ToolRegistry` 查找并执行。

## 目标

- FlickCode 启动时自动读取并合并用户级、项目级 MCP Server 配置。
- 支持本地 stdio 子进程和远程 Streamable HTTP 两种 MCP 传输方式。
- 按 JSON-RPC 2.0 处理请求、响应和错误，并支持并发请求按 `id` 正确配对。
- 为每个配置的 Server 完成初始化握手和工具列表发现。
- 将远端工具映射为 FlickCode 已有的工具接口，注册后由 Agent 透明调用。
- 缓存多个 Server 的连接和发现结果，并在 Session 生命周期结束时释放资源。
- 单个 Server 连接、初始化或发现失败时隔离错误，不阻断其他 Server 和 FlickCode 主流程。
- 为外部工具建立稳定、无冲突的命名规则，并保留来源 Server 信息以便诊断。

本阶段推荐采用“协议核心 + 传输适配器 + 工具适配器 + 生命周期管理器”的分层方案。这样既能让 stdio 与 HTTP 共享 JSON-RPC 和 MCP 会话逻辑，也能把现有 `ToolRegistry` 的改动限制在注册外部工具所必需的范围内。

## 功能需求

### F1：配置文件声明 MCP Server

FlickCode 必须支持在 YAML 配置中使用 map 声明 MCP Server，map 的 key 是用户定义的 Server 名称。每个 Server 必须声明且只能选择一种传输配置：

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env:
      API_KEY: "${MCP_API_KEY}"

  remote_search:
    transport: streamable_http
    url: "https://example.com/mcp"
    headers:
      Authorization: "Bearer ${SEARCH_TOKEN}"
```

stdio Server 的配置字段为 `transport: stdio`、`command`、可选的 `args` 和可选的 `env`；HTTP Server 的配置字段为 `transport: streamable_http`、`url` 和可选的 `headers`。未知传输类型、缺少必填字段或字段类型错误必须只使该 Server 配置失效，并记录包含 Server 名称和字段路径的错误。

### F2：用户级与项目级配置合并

配置加载必须同时读取：

- 用户级：`~/.flickcode/config.yaml`
- 项目级：当前工作目录下 `.flickcode/config.yaml`

加载顺序为用户级在前、项目级在后。两个文件中的 `mcp_servers` map 按 Server 名称合并：同名 Server 使用项目级的完整配置覆盖用户级配置；不同名 Server 全部保留。除 MCP 配置外，现有 provider 配置行为必须保持不变。

项目配置不存在时按空配置处理；用户配置不存在时也不得因为 MCP 功能单独导致启动失败。显式传入的 `--config` 仍作为主配置文件入口，项目级 MCP 配置的合并规则必须在不破坏现有 CLI 语义的前提下保持明确且可测试。

### F3：环境变量展开

stdio 的 `env` 值和 HTTP 的 `headers` 值必须支持 `${VAR}` 形式的环境变量展开。展开发生在 Server 启动或连接之前，支持一个值中包含多个占位符；未定义的变量不得静默替换为空字符串，必须使该 Server 进入失败状态并记录变量名，但日志不得输出完整的密钥值。

环境变量展开只作用于配置声明的字符串值，不改变 Server 名称、工具名称或 JSON-RPC 消息中的运行时参数。

### F4：stdio 传输

对 `transport: stdio` 的 Server，客户端必须：

1. 使用配置中的 `command` 和 `args` 启动一个子进程，并将展开后的 `env` 注入该进程环境。
2. 通过子进程 stdin 发送 UTF-8 编码、单行分隔的 JSON-RPC 消息。
3. 通过子进程 stdout 读取 JSON-RPC 消息；stdout 中的非 JSON-RPC 内容必须视为协议错误，不能被当作普通日志吞掉。
4. 将 stderr 作为诊断日志流处理，stderr 内容不能被误判为 MCP 响应。
5. 在连接关闭、进程退出或协议失败时，清理子进程及其管道，避免遗留进程。

### F5：Streamable HTTP 传输

对 `transport: streamable_http` 的 Server，客户端必须：

1. 使用配置的 `url` 向 MCP endpoint 发送 HTTP POST JSON-RPC 请求。
2. 在请求中携带用户配置的 headers，并设置 MCP 要求的 JSON 与事件流 Accept 类型。
3. 接受 `application/json` 的单个 JSON-RPC 响应和 `text/event-stream` 中承载的 JSON-RPC 消息；两者都必须能够完成对应请求的响应配对。
4. 在初始化成功后保存服务端返回的会话标识（如果存在），并在后续请求中携带；结束生命周期时尝试发送会话关闭请求，但服务器不支持时不得阻断本地清理。
5. 对 HTTP 状态码、响应格式、连接超时和读取超时生成可定位的 Server 级错误；单个请求失败必须返回工具错误，不得使其他 Server 下线。

本期不要求实现旧版 HTTP+SSE 兼容回退、OAuth 授权流程、断线续传或服务端主动请求处理。

### F6：JSON-RPC 2.0 请求与响应配对

客户端必须为每个请求生成唯一的请求 `id`，发送包含 `jsonrpc: "2.0"`、`id`、`method` 和可选 `params` 的消息，并维护未完成请求表。响应到达时必须按 `id` 找到原请求并唤醒对应调用方；响应中的 `result` 和 `error` 必须互斥处理。

客户端必须能够处理消息到达顺序与请求发送顺序不同的情况。未知响应 `id`、无效 JSON、缺少 JSON-RPC 字段或响应超时都必须转换为明确错误，并清理对应的未完成请求。通知消息不带 `id`，不得被当作普通请求响应。

### F7：MCP 初始化握手

每个 Server 首次建立连接后，客户端必须按以下顺序完成会话初始化：

1. 发送 `initialize` 请求，声明客户端支持的 MCP 协议版本、客户端信息和本期实际支持的能力。
2. 校验响应的协议版本、服务端信息和能力结构；版本不兼容或响应错误时，该 Server 发现失败。
3. 发送 `notifications/initialized` 通知，之后才进入工具发现和调用阶段。

本功能以用户要求的初始化握手流程为协议基线，固定实现 MCP `2025-06-18` 生命周期语义；未来协议版本若移除该握手流程，需作为兼容性升级单独设计，不能在本期隐式改变行为。

### F8：工具列表发现与分页

初始化完成后，客户端必须调用 `tools/list` 获取 Server 提供的工具。若响应包含 `nextCursor`，客户端必须继续请求直到没有下一页，并合并同一 Server 的全部工具。

每个 MCP 工具至少需要保留原始工具名、描述和 `inputSchema`。缺少合法对象类型 `inputSchema` 的工具不得注册，但不能阻断同一 Server 中其他合法工具的注册。Server 未声明 tools capability 或工具列表请求返回协议错误时，该 Server 不提供可用工具并记录原因。

### F9：远端工具适配与注册

发现到的工具必须包装为现有 `BaseTool` 兼容实例，注册到现有 `ToolRegistry`，并遵循以下命名规则：

```text
mcp__<server-name>__<tool-name>
```

适配器向 Agent 暴露的参数 schema 必须等价于 MCP 工具的 `inputSchema`，不能丢失 properties、required 或参数描述。若现有 `ToolParameter` 无法表达完整 JSON Schema，适配层必须保留原始 schema，并通过 Registry 的 API 转换路径生成 object schema，而不是把复杂参数降级为无约束字符串。

同一 Server 内工具名重复、生成后的注册名与已有内置工具或其他 MCP 工具冲突时，必须拒绝冲突项并记录冲突双方；不得静默覆盖已有工具。

### F10：Agent 透明调用与结果转换

Agent 调用 `mcp__<server-name>__<tool-name>` 时，适配器必须将调用转换为对应 Server 的 `tools/call` 请求：

```json
{
  "name": "<tool-name>",
  "arguments": {}
}
```

调用结果必须转换为现有 `ToolResult`：

- MCP `result.isError: true` 或 JSON-RPC error 转换为 `success: false`，并保留可读错误信息。
- MCP 文本 content 按顺序拼接为 `output`。
- 非文本 content、`structuredContent` 和原始响应元数据必须以稳定、可序列化的文本形式保留，不能因遇到图片、资源链接或结构化结果而使 Agent Loop 崩溃。
- 成功返回但 content 为空时，仍返回 `success: true` 和空输出。

工具调用必须复用现有 Agent 的工具事件、权限确认和错误展示链路；Agent 无需知道该工具来自 MCP。

### F11：多 Server 隔离与连接缓存

客户端必须为每个配置 Server 维护独立的连接状态、请求表、初始化结果、工具发现结果和错误状态。启动时可并行处理不同 Server，但一个 Server 的超时、进程退出或协议错误不得取消或阻断其他 Server。

同一个 Server 在同一 Session 生命周期内必须复用已经初始化的连接和发现结果，不得每次 Agent 调用都重新启动子进程或重新初始化 HTTP 会话。重复加载同一配置时应避免重复注册同名工具。

### F12：生命周期关闭

Session 结束、应用退出或显式关闭 MCP 管理器时，客户端必须关闭所有 Server：发送可用的协议关闭信号，关闭 HTTP 会话，终止 stdio 子进程并回收资源。关闭一个 Server 失败只能记录错误，不能阻止其他 Server 继续清理。

本期不实现健康检查、后台自动重连、工具列表变更通知后的自动刷新；已建立连接失效后，相关工具调用应返回明确错误。

## 非功能需求

### N1：向后兼容

没有配置 `mcp_servers` 时，FlickCode 的启动、内置工具注册、纯文本对话和现有 Agent Loop 行为必须与改造前一致。MCP 客户端的可选依赖、初始化失败或单个 Server 故障不得阻断内置工具和当前 LLM Provider 的使用。

### N2：故障隔离

所有 MCP 错误必须绑定到具体 Server 或具体工具调用。启动阶段不得因为一个 Server 失败而回滚其他 Server 的成功注册；运行阶段不得因为一个远端调用失败而使 Agent Loop 或其他工具不可用。错误信息至少包含 Server 名称、传输类型、操作阶段和可读原因，必要时附带底层异常类型。

### N3：安全性

配置中的 API token、Authorization header、环境变量值和子进程完整环境不得写入普通日志。日志和错误消息只允许显示变量名、header 名称或脱敏后的摘要。stdio 的 command、args 和 env 必须按结构化参数传给子进程，不能通过 shell 拼接执行，以避免配置内容被解释为额外命令。

HTTP URL、headers 和 stdio command 都属于用户授予的外部执行配置；FlickCode 必须在日志中清晰标识外部工具来源，并沿用现有工具调用确认与权限链路，不因工具来自 MCP 而绕过权限策略。

### N4：超时与资源上限

连接、初始化、工具列表发现和工具调用都必须有可配置或有明确默认值的超时，避免无限等待。stdio 子进程、HTTP 响应、SSE 读取、未完成请求和连接关闭都必须有资源回收路径。工具列表分页必须防止无界循环；重复 cursor 或超过合理页数时必须报错并停止该 Server 的发现。

### N5：并发与顺序

不同 Server 的启动连接可以并行；同一 Server 的请求配对必须线程安全。请求 ID 在一个 Server 会话内必须唯一，响应处理不得依赖网络或进程返回顺序。对同一 Server 的关闭操作必须与未完成请求协调，不能产生后台线程、读写任务或子进程泄漏。

### N6：可测试性

协议核心、stdio 传输、HTTP 传输、配置合并、工具适配和生命周期管理必须能够在不调用真实外部服务的情况下测试。测试可以注入假的传输层、固定的 JSON-RPC 响应和可控的时钟/超时，不要求依赖网络、API key 或用户机器上的特定 MCP Server。

### N7：可观测性

启动阶段至少记录每个 Server 的配置解析结果、连接结果、初始化结果、发现工具数量和失败原因；运行阶段至少记录工具调用开始、结束、耗时和成功/失败状态。默认日志不得泄露敏感值，也不得把外部工具的完整大输出重复写入日志。

### N8：协议兼容边界

本期客户端以 MCP `2025-06-18` 为实现基线，严格使用 JSON-RPC 2.0 和该版本的工具、生命周期、stdio、Streamable HTTP 消息格式。协议版本不兼容时必须失败并给出原因，而不是猜测字段或静默降级到非标准行为。

### N9：启动体验

MCP Server 的连接与发现不应让一个失效的远端服务无限阻塞 FlickCode 启动。启动完成后用户应能看到成功注册的 MCP 工具数量以及被跳过 Server 的摘要；没有 MCP 配置或没有成功发现工具时，主程序仍应正常进入交互界面。

### N10：数据完整性

MCP 工具的 JSON Schema、工具调用参数和工具结果必须在适配过程中保持可逆或可解释。适配层不得因不认识某个 schema 字段就删除核心约束；无法映射的附加字段应保留在原始结构或稳定序列化结果中。

### N11：实现语言与依赖约束

设计必须适配现有 Python 3.8+ 项目和当前依赖管理方式。新增依赖应有明确用途、许可证可接受、能够通过项目现有安装流程获得，并不得要求用户预先安装某个特定 MCP SDK 才能使用基础 stdio 或 Streamable HTTP 能力。

## 不做的事情

- 不实现 MCP resources、prompts、sampling、elicitation、roots、logging、completions 或其他非工具能力。
- 不实现旧版 HTTP+SSE 传输的兼容回退。
- 不实现 OAuth、动态客户端注册、令牌刷新或其他 MCP HTTP 授权流程；headers 只按配置原样发送并做变量展开。
- 不实现健康检查、后台自动重连、断线续传、请求重试或工具列表变更后的自动刷新。
- 不实现 MCP Server 的安装、下载、升级、版本管理或进程守护配置。
- 不修改 MCP Server 本身，不为外部 Server 增加非标准协议扩展。
- 不改变内置工具的名称、参数契约和既有权限策略。
- 不要求 Agent、Provider 或 TUI 为 MCP 增加专用调用分支；MCP 工具必须通过现有工具中心和 Agent 工具事件链路工作。
- 不承诺对所有任意 JSON Schema 生成专用参数控件；本期只保证 schema 可传递给模型并能接收 JSON object 参数。

## 验收标准

| 编号 | 可观察结果 | 对应需求 |
|------|------------|----------|
| AC1 | 使用合法 YAML 配置启动 FlickCode，能识别 stdio 和 `streamable_http` 两类 Server；缺少必填字段或类型错误时仅该 Server 被跳过，并输出带 Server 名称和字段路径的错误 | F1 |
| AC2 | 同时存在用户级和项目级配置时，同名 Server 使用项目级完整配置，不同名 Server 全部保留；不存在任一层配置时，现有配置加载和启动行为不被破坏 | F2 |
| AC3 | 配置 `${VAR}` 能在 stdio env 和 HTTP headers 中展开；未定义变量导致对应 Server 失败且日志不包含 secret 值 | F3 |
| AC4 | 使用测试 MCP stdio Server 启动、完成握手和工具发现；stdout 协议消息可读、stderr 不被当作响应，关闭 Session 后子进程退出且管道被回收 | F4 |
| AC5 | 使用测试 HTTP MCP Server，客户端能发送符合要求的 POST headers，处理 JSON 和 SSE 响应，并在有 session id 时复用它；HTTP 错误只影响对应 Server | F5 |
| AC6 | 构造乱序响应、未知 id、无效 JSON、缺失字段和超时场景，客户端能按 id 唤醒正确请求，并对异常请求清理 pending 状态 | F6 |
| AC7 | 记录并验证 `initialize` → 响应 → `notifications/initialized` → 后续请求的顺序；版本不兼容时 Server 不注册工具 | F7 |
| AC8 | 测试 Server 分多页返回工具时，客户端持续请求直到 `nextCursor` 消失；合法工具全部发现，非法 schema 工具被单独跳过 | F8 |
| AC9 | 发现名为 `search` 的 MCP 工具后，Registry 中出现 `mcp__<server>__search`；模型侧 schema 保留 properties、required 和描述；发生冲突时不覆盖既有工具 | F9 |
| AC10 | Agent 调用注册的 MCP 工具时，测试 Server 收到正确的 `tools/call` 参数；文本、结构化结果、非文本内容、`isError` 和 JSON-RPC error 都能转换为稳定的 `ToolResult` | F10 |
| AC11 | 配置两个 Server，其中一个连接失败、一个成功；成功 Server 的工具仍可注册和调用；同一 Session 内重复调用不会重复启动或初始化 Server | F11 |
| AC12 | Session 正常结束、异常结束和单个 Server 关闭失败时，所有 Server 都尝试清理；不存在遗留 stdio 进程、HTTP 会话或 pending 请求 | F12 |
| AC13 | 不配置 MCP Server 运行现有纯文本对话、内置工具 Agent Loop、provider 选择和 TUI；行为与改造前兼容 | N1 |
| AC14 | 检查启动、调用和错误日志，能看到 Server/阶段/耗时/结果状态，但看不到 API token、Authorization 值、完整 env 或完整大输出 | N2, N3, N7 |
| AC15 | 让测试 Server 永不响应或返回无限分页 cursor，客户端在超时或分页保护触发后返回可读错误并继续运行，不无限阻塞 | N4, N9 |
| AC16 | 并发发起多个 Server 连接和同一 Server 的多个请求，所有响应与请求正确配对，测试结束后无泄漏线程、任务或子进程 | N5 |
| AC17 | 协议核心、配置合并和工具适配测试可使用 fake transport 完成，不访问真实网络、不需要真实 API key 或用户本机 MCP Server | N6 |
| AC18 | 使用 MCP `2025-06-18` 的标准消息 fixture 完成初始化、分页发现和调用；收到不兼容版本时明确失败，不静默采用未知协议行为 | N8 |
| AC19 | 工具 schema 中存在适配器不认识的附加字段时，核心 object schema 和原始附加信息仍可追踪；调用参数保持 JSON object 形状 | N10 |
| AC20 | 在项目现有 Python 3.8+ 安装流程下完成依赖安装、导入和测试；未安装额外 MCP Server 时基础功能仍可运行 | N11 |
