# FlickCode 命令注册与分发 Plan

## 架构概览

采用“注册中心 + 统一解析分发器 + 界面控制端口”的方案。命令核心不直接引用
`prompt_toolkit` 或 Rich；它只依赖 Session 能力和一个可测试的界面控制接口。
交互式 TUI 与管道模式共享同一个 `CommandDispatcher`，仅提供不同的
`CommandUI` 适配器。

```text
TUI Enter / pipe line
        │
        ▼
InputRouter.handle(raw_input)
        │
        ├── empty       → ignored
        ├── normal text → CommandUI.send_user_message(text, current_mode)
        └── slash input → CommandParser.parse()
                              │
                              ├── unknown → UI.show_error + /help hint
                              └── match   → CommandDispatcher.dispatch()
                                              │
                 ┌──────────────────────────┼──────────────────────────┐
                 ▼                          ▼                          ▼
             LOCAL                    UI_STATE                    PROMPT
         local Session APIs       CommandUI methods       send preset intent
```

注册中心在应用启动时创建并注册全部内置命令。注册过程完成规范名称与别名的规范化、
冲突检查和索引建立；如果冲突，抛出启动级异常，由 CLI 顶层转为致命错误退出。
运行时分发只访问已构建的索引，不再做注册校验。

## 核心数据结构

### `CommandType`

使用字符串枚举表达命令主路由：

- `LOCAL`：只调用本地能力；
- `UI_STATE`：只改变界面或交互状态；
- `PROMPT`：构造预设意图后交给 Agent。

类型用于分发策略、帮助中的 AI 标记和测试断言，不限制某个处理函数在一次执行中
调用多个端口能力。

### `CommandSpec`

每个命令的不可变元数据包含：

- `name: str`：规范名称，不带 `/`；
- `aliases: tuple[str, ...]`；
- `description: str`；
- `usage: str`；
- `command_type: CommandType`；
- `argument_hint: str | None`；
- `hidden: bool`；
- `handler: CommandHandler`。

创建 `CommandSpec` 时校验名称、别名和展示文本非空；名称和别名只允许单个命令词，
不允许包含 `/` 或空白。处理函数使用统一签名，避免每个命令自行解析输入：

```python
CommandHandler = Callable[[CommandContext], CommandResult]
```

### `ParsedCommand`

解析器输出以下信息：

- `raw_input: str`：去除外层空白后的原始输入；
- `name: str`：去除 `/` 后的小写命令名；
- `arguments: str`：命令后的原始参数文本，去除分隔边界空白；
- `is_command: bool`：是否以 `/` 开头；
- `error: str | None`：例如空命令名。

普通文本不创建可执行命令对象，而由 `InputRouter` 直接走 Agent 路径。以 `/` 开头的
输入始终进入命令路径，即使命令名为空或未命中，也不回退为普通文本。

### `CommandContext`

处理函数通过上下文获得本次调用所需资源：

- `spec`：当前命令的规范信息；
- `arguments`：原始参数文本；
- `session`：当前 `Session`；
- `ui`：`CommandUI` 端口；
- `registry`：用于 `/help`、帮助查询和补全；
- `mode`：当前交互模式。

上下文不持有具体 `PromptSession`、Rich `Console` 或输出缓冲区。命令处理函数返回
`CommandResult`，用于描述是否继续循环、是否已发送 Agent 请求及可选诊断；错误通过
统一结果或异常边界转为 UI 错误消息。

### `CommandResult`

至少包含：

- `handled: bool`；
- `continue_loop: bool`，默认 `True`；
- `agent_sent: bool`，默认 `False`；
- `error: str | None`；
- `mode_changed: bool`。

退出命令可以返回 `continue_loop=False`。本阶段 `/exit` 和 `/quit` 可作为兼容命令
注册，但其退出语义由分发器结果统一处理。

### `InteractionMode`

命令层新增轻量交互状态枚举：

- `DEFAULT`：普通输入调用 `AgentMode.FULL`，状态标签 `[DEFAULT]`；
- `PLAN`：普通输入调用 `AgentMode.PLAN`，状态标签 `[PLAN]`。

`AgentMode.EXECUTE` 仍只用于 `/do` 的一次 Agent 调用，不作为持续交互模式。该设计
避免把当前 Agent Loop 的一次执行模式与用户后续输入的交互模式混为一谈。

## 核心接口

### `CommandRegistry`

职责：登记、校验、查找、生成帮助和补全候选。

```python
class CommandRegistry:
    def register(self, spec: CommandSpec) -> None: ...
    def resolve(self, name: str) -> CommandSpec | None: ...
    def all(self, *, include_hidden: bool = False) -> tuple[CommandSpec, ...]: ...
    def completions(self, prefix: str) -> tuple[str, ...]: ...
    def help_for(self, name: str | None = None) -> str: ...
    def validate(self) -> None: ...
```

实现使用一个规范化名称到 `CommandSpec` 的字典索引，以及一份按注册顺序保存的
规范命令元数据。别名解析直接指向同一 `CommandSpec`，不复制处理函数或命令元数据。
`register()` 立即检测冲突，`validate()` 作为启动装配末尾的显式安全检查保留；两者
都必须报告冲突词和涉及的命令。

帮助只从规范命令列表生成，默认过滤 `hidden=True`；指定名称时允许通过别名查询。
补全只返回规范名称和别名中符合前缀的可见候选，去重后排序并保留规范命令优先的
稳定顺序。实现层可以选择只补全规范名称，但必须保证别名能被解析；更完整的设计
是候选同时支持别名并在直接补全时使用用户当前输入的命名形式。

### `CommandParser`

```python
class CommandParser:
    def parse(self, raw_input: str) -> ParsedCommand | None: ...
```

返回 `None` 表示空输入或非命令普通文本；返回 `ParsedCommand` 表示任何斜杠输入。
解析只做边界空白、首个空白切分和命令名小写化，不调用 Session 或 UI。

### `CommandUI`

这是命令层的界面/交互端口，TUI 和 pipe 分别实现：

```python
class CommandUI(Protocol):
    def show_message(self, text: str) -> None: ...
    def show_progress(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def send_user_message(self, text: str, mode: AgentMode) -> None: ...
    def get_mode(self) -> InteractionMode: ...
    def set_mode(self, mode: InteractionMode) -> None: ...
    def token_status(self) -> TokenStatus: ...
    def refresh_status(self) -> None: ...
    def clear_display(self) -> None: ...
```

`send_user_message()` 内部负责调用 `Session.agent_chat()`、消费现有 AgentEvent 并
渲染或输出事件；命令核心不重复实现事件循环。`token_status()` 返回面向展示的
不可变快照，至少包含最近 Token 使用量和 `ContextManager.state.last_diagnostic`。

### `CommandDispatcher`

```python
class CommandDispatcher:
    def dispatch(
        self,
        parsed: ParsedCommand,
        *,
        session: Session,
        ui: CommandUI,
    ) -> CommandResult: ...
```

分发器解析命令后执行以下边界：

1. 通过 registry 解析规范名称或别名；
2. 未命中时 `ui.show_error("Unknown command ... Use /help ...")` 并返回已处理结果；
3. 构造 `CommandContext`；
4. 调用 handler；
5. 捕获普通命令异常，转为错误消息并保持循环；
6. 根据 `CommandResult` 刷新状态栏，必要时让入口结束循环。

启动级 `CommandRegistrationError` 不在这里吞掉，以便 CLI 初始化阶段退出。

### `InputRouter`

```python
class InputRouter:
    def handle(
        self,
        raw_input: str,
        *,
        session: Session,
        ui: CommandUI,
    ) -> CommandResult: ...
```

统一处理 TUI 回车与 pipe 行输入：空输入返回默认结果；普通文本调用
`ui.send_user_message()`，模式由 `ui.get_mode()` 映射到 `AgentMode.PLAN` 或
`AgentMode.FULL`；斜杠输入交给 parser 和 dispatcher。`/` 开头但解析失败仍返回错误，
不调用 Agent。

## 内置命令设计

内置命令在 `builtin.py` 中通过工厂函数创建，工厂只依赖上下文接口；注册装配保持
显式、可读并且顺序稳定。建议规范名称和兼容别名如下：

| 规范名称 | 别名 | 类型 | 处理设计 |
|---|---|---|---|
| `help` | `?` | `LOCAL` | 无参数列出可见命令；有参数按 registry 查询详情。 |
| `compact` | — | `LOCAL` | 调用 `Session.compact_context()`，根据 `ContextPreparation.diagnostic` 展示实际结果和路径；不调用 `send_user_message()`。 |
| `clear` | — | `UI_STATE` | 调用 `ui.clear_display()`，保留 Session 数据。 |
| `plan` | — | `PROMPT` | 无参数 `set_mode(PLAN)`；有参数先 `set_mode(PLAN)`，再 `send_user_message(arguments, AgentMode.PLAN)`。 |
| `do` | `execute` | `PROMPT` | 先检查 `session.plan_context`；无计划报错不改模式；有计划 `set_mode(DEFAULT)`，发送固定意图 `Execute the plan.`，使用 `AgentMode.EXECUTE`。 |
| `session` | `sessions` | `LOCAL` | 调用 `Session.list_sessions()`，展示当前 ID、历史摘要、可恢复性和诊断。 |
| `memory` | — | `LOCAL` | 读取 `Session.instruction_bundle`、`project_memory.read_index()`、`user_memory.read_index()`，展示受限摘要及诊断。 |
| `permission` | `permissions` | `LOCAL` | 展示 `session.permission_mode`、`permission_engine.mode` 和规则来源/数量；不修改规则。 |
| `status` | — | `LOCAL` | 展示 Provider 名称/模型、模式、计划上下文存在性、Token 快照、上下文诊断、MCP 注册/失败统计和待处理诊断。 |
| `review` | `audit` | `PROMPT` | 固定提示词为审查当前项目/变更；arguments 作为关注点追加，固定使用 `AgentMode.FULL`；不修改持续交互模式。 |
| `resume` | — | `LOCAL` | 保留现有 `/resume <session-id>` 参数校验和 `Session.resume_session()` 语义。 |
| `exit` | `quit` | `UI_STATE` | 返回 `continue_loop=False`；真正的确认行为由交互入口保留或适配。 |

### 关于 `/review` 的 mode 决策

`/review` 是提示词命令，但 spec 只要求其预设审查意图，不要求它改变模式。固定使用
`AgentMode.FULL`，因为审查可能需要读取项目并提出修改建议，而用户当前是否处于
`[PLAN]` 只影响普通输入。该选择在实现中固化为常量和测试断言。

## 命令执行流

### 普通输入

```text
raw text
  ├─ strip empty? yes → return
  ├─ startswith('/')? no
  └─ ui.send_user_message(text, PLAN if mode=PLAN else FULL)
```

### 本地命令

```text
/status
  → parse name=status, args=""
  → registry.resolve("status")
  → status.handler(context)
  → ui.show_message(...)
  → ui.refresh_status()
  → no Session.agent_chat()
```

### 提示词命令

```text
/plan fix parser
  → parse
  → handler sets mode PLAN
  → ui.send_user_message("fix parser", AgentMode.PLAN)
  → Session.agent_chat() → existing event consumer
  → refresh status
```

### `/do` 状态变更时序

为避免无计划时错误地切换模式，`/do` 处理顺序固定为：

1. 检查 `session.plan_context`；
2. 不存在则显示错误并返回，模式不变；
3. 存在则设置 `InteractionMode.DEFAULT` 并刷新状态栏；
4. 使用 `AgentMode.EXECUTE` 发送固定意图；
5. Agent 失败时保留计划上下文和已切换的默认模式，允许再次 `/do` 或普通输入。

## TUI 与 pipe 适配

### `TUICommandUI`

放在 `tui.py` 或独立 `tui_commands.py`，复用现有 `Renderer` 和 `_consume_agent_events()`：

- `show_message/progress/error` 映射到 Renderer；
- `send_user_message` 调用 `session.agent_chat(text, mode=...)` 并消费事件；
- `clear_display` 使用 prompt_toolkit 输出对象或 ANSI 清屏能力，不能清理 Session；
- `refresh_status` 更新提示符或独立状态栏文本，至少确保下一次输入前显示当前标签；
- `token_status` 读取 `session.context_manager.state`、`last_diagnostic` 和 provider 配置。

### `PipeCommandUI`

放在 `tui.py` 的适配层或 `commands/adapters.py`，使用现有 `_safe_print`、
`_safe_write` 输出：

- 普通消息和进度写 stdout；
- 错误和诊断写 stderr；
- `send_user_message` 复用现有 pipe AgentEvent 消费逻辑，不能调用交互式 prompt；
- `clear_display` 在无 TTY 下输出可观察的清屏控制序列或简短提示，不能假设终端；
- 模式状态在每次模式变化时输出 `[PLAN]` 或 `[DEFAULT]`，以便管道测试观测。

两个适配器共享 `InputRouter` 和 `CommandDispatcher`，只允许输出和交互细节不同。

## Tab 补全设计

在创建 `PromptSession` 时为输入绑定 `prompt_toolkit.completion.Completer` 适配器。
适配器从当前 buffer 文本和 cursor position 判断：

1. 只接受当前输入首个非空字符为 `/` 的单命令候选；
2. 找到第一个空白前的 token，去掉 `/` 作为 prefix；
3. cursor 位于参数区域时返回空候选；
4. 调用 `registry.completions(prefix)`；
5. 单候选返回一个 `Completion`，多候选返回全部候选，让 prompt_toolkit 展示菜单；
6. 隐藏命令在 registry 层已被过滤。

补全文本应只替换命令 token，不把参数覆盖掉；大小写匹配使用 registry 规范化，
展示候选使用规范名称（带 `/`）。

## 现有代码迁移策略

### `tui.py`

- 删除交互循环中的 `/compact`、`/sessions`、`/resume`、`/do`、`/plan` 逐项分支，
  改为创建 `CommandDispatcher`、`TUICommandUI` 和 `InputRouter` 后统一处理；
- 保留高风险确认和 HITL 回调装配，因为它们属于 Session/工具交互，不属于命令解析；
- 保留 `_consume_agent_events`，由 TUI UI 适配器调用；
- 将欢迎文本和提示符更新为包含 `/help`、`[DEFAULT]` 的信息；
- 为 prompt session 加入命令补全。

### `Session`

- 新增或暴露只读的状态快照方法，避免命令层直接拼装过多内部字段；
- 保留 `agent_chat()`、`compact_context()`、`list_sessions()`、`resume_session()` 和
  `plan_context` 语义；
- 交互模式状态属于命令/UI 会话层，不写入 Provider 历史，不修改 `AgentMode` 枚举；
- 如需要记忆摘要，优先复用现有 `MemoryRepository.read_index()` 和
  `InstructionBundle.diagnostics`，不新增写入行为。

### `renderer.py`

- 只补充命令需要的清屏、状态栏或消息辅助能力；
- 不把命令注册逻辑放进 Renderer；
- 状态栏的 `[PLAN]` / `[DEFAULT]` 文本由 UI 适配器控制，Renderer 只负责展示。

### `agent.py`

- 不修改 `AgentMode` 现有语义；
- `/do` 继续使用 `AgentMode.EXECUTE`；
- `/plan <task>` 继续通过 `AgentMode.PLAN` 生成 `PlanContext`；
- `/review` 固定使用 `AgentMode.FULL`，不新增 Agent 模式。

## 模块与文件组织

```text
src/flickcode/
├── commands/
│   ├── __init__.py          # 公共导出与默认 registry 工厂
│   ├── models.py            # CommandType, CommandSpec, ParsedCommand, Result, Context
│   ├── registry.py          # 注册、冲突检查、resolve、help、completion
│   ├── parser.py            # 斜杠输入解析
│   ├── dispatcher.py        # CommandDispatcher + InputRouter
│   ├── builtin.py           # 十个内置命令及兼容命令 handler
│   └── adapters.py          # CommandUI Protocol、TUI/Pipe 适配共用类型或辅助函数
├── tui.py                   # 入口装配、TUICommandUI、补全器接入
├── renderer.py              # 清屏/状态显示辅助（如确有必要）
└── session.py               # 只读状态快照（如确有必要）

tests/
├── test_commands.py         # 模型、注册、解析、帮助、补全、分发
└── test_command_integration.py # TUI/pipe 路由、Session fake、模式与兼容命令
```

文件名和具体拆分在 task 阶段可以根据实现粒度微调，但不得把核心命令逻辑重新放回
`tui.py` 的输入分支，也不得让 TUI 和 pipe 各自维护一份命令表。

## 模块设计

### `commands/models.py`

**职责**：定义命令层所有稳定数据结构和类型别名，不依赖 TUI、Rich 或 Provider。

**对外接口**：`CommandType`、`InteractionMode`、`CommandSpec`、`ParsedCommand`、
`CommandResult`、`CommandContext`、`TokenStatus`、`CommandHandler`。

**依赖**：标准库类型、`AgentMode`（仅在 `CommandUI.send_user_message` 的类型签名处，
如需避免循环依赖可使用 TYPE_CHECKING）。

### `commands/registry.py`

**职责**：唯一命令元数据来源；构建规范化索引、冲突检测、帮助和补全。

**对外接口**：`CommandRegistry`、`CommandRegistrationError`。

**依赖**：`models.py`。

### `commands/parser.py`

**职责**：纯函数式解析斜杠输入，不访问外部状态。

**对外接口**：`CommandParser.parse()`。

**依赖**：`ParsedCommand`。

### `commands/dispatcher.py`

**职责**：统一处理命令解析结果和普通文本路由，捕获运行时命令异常，处理循环继续/退出。

**对外接口**：`CommandDispatcher.dispatch()`、`InputRouter.handle()`。

**依赖**：registry、parser、models、Session 协议、CommandUI 协议。

### `commands/builtin.py`

**职责**：提供内置命令 handler 和 `build_default_registry()`。

**对外接口**：`build_default_registry()`。

**依赖**：commands models/registry、Session 公开能力、权限规则读取函数、现有会话和
上下文模型。不得依赖 Renderer。

### `commands/adapters.py`

**职责**：定义 `CommandUI` Protocol、状态快照格式，以及对 Session 状态的安全读取
辅助；为 TUI/pipe 适配器提供共享的非渲染逻辑。

**依赖**：`AgentMode`、上下文模型、标准库 Protocol。

### 入口层

`tui.py` 负责构建真实 UI、注册 Session 回调、创建默认 registry 和路由器。它只负责
输入采集和适配器，不能再包含按命令名硬编码的分发判断。管道和交互式 TUI 都在各自
循环中调用同一个 `router.handle()`。

## 模块交互

### 启动装配

```text
cli.main
  → create Session
  → build_default_registry()
  → registry.validate()
  → if conflict: fatal exit
  → run_interactive_loop(session, registry)
```

如果注册中心在 `tui.run_interactive_loop()` 内创建，仍须在进入第一个输入循环之前
完成；更推荐由 CLI/TUI 入口创建后显式传入，使启动错误不隐藏在第一次读取输入之后。

### 一次普通输入

```text
InputRouter.handle(text)
  → parser.parse(text)
  → no ParsedCommand
  → ui.get_mode()
  → ui.send_user_message(text, AgentMode.PLAN/FULL)
```

### 一次斜杠输入

```text
InputRouter.handle(text)
  → parser.parse(text)
  → dispatcher.dispatch(parsed)
  → registry.resolve(name)
  → handler(CommandContext)
  → UI/session operations
  → result + refresh_status
```

### 依赖关系

```text
models  ← parser
   ↑       ↑
registry ← dispatcher ← builtin
               ↑
           adapters/entrypoints
```

`builtin` 可以使用 `dispatcher` 提供的 context，但不反向调用入口。TUI 依赖 commands，
commands 不依赖 TUI；Session 只向 commands 暴露能力，不依赖 commands，避免循环依赖。

## 关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 命令元数据来源 | 单一 `CommandRegistry` | 帮助、补全、解析和冲突校验共享同一数据，避免漂移。 |
| 冲突时机 | 注册/启动阶段失败 | 满足“别名冲突直接 panic 退出”的确定性要求。Python 中使用未捕获的启动异常由 CLI 转致命退出。 |
| 参数解析 | 首个空白切分，保留原始参数 | 满足现有任务描述，避免在本阶段引入 shell 语法和复杂转义。 |
| 普通/命令分流 | 统一 `InputRouter` | TUI 与 pipe 结果一致，且未知斜杠不误进 Agent。 |
| UI 解耦 | `CommandUI` Protocol | 核心命令可用内存 fake 测试，TUI 只做适配。 |
| 交互模式 | 新增 `InteractionMode` | 区分持续用户模式与一次性 `AgentMode.EXECUTE`，不破坏 Agent API。 |
| `/plan` 无参 | 只切换模式，不调用 AI | 与已批准 spec 一致，并保留 `/plan <task>` 的立即规划兼容行为。 |
| `/do` 无计划 | 报错且不切换模式 | 防止错误操作破坏当前交互状态。 |
| `/review` | 固定 `AgentMode.FULL` | 审查需要完整工具能力，且不让当前 `[PLAN]` 状态产生隐式语义变化。 |
| 命令历史 | 不把本地命令文本追加到 Session | 本地命令省 Token 且不污染主对话；提示词命令只通过统一发送入口追加。 |
| 状态栏位置 | UI 适配器/Renderer | 状态显示是渲染责任，命令核心只改变 `InteractionMode`。 |
| 记忆/权限展示 | 只读复用现有仓库和规则加载 | `/memory`、`/permission` 不新增写入或命令级 ACL。 |
| 补全实现 | registry + prompt_toolkit adapter | 候选单一来源，参数区域可准确停止补全。 |
| 兼容迁移 | `/sessions` 别名到 `/session`，保留 `/resume`/退出 | 不破坏 README 和已有用户脚本。 |

## Spec 覆盖检查

| Spec 需求 | 设计落点 |
|---|---|
| F1 注册中心/冲突 | `CommandRegistry`, `CommandRegistrationError`, 启动装配 |
| F2 解析/未知命令 | `CommandParser`, `InputRouter`, 未知命令错误边界 |
| F3 三类路径 | `CommandType`, dispatcher + builtin handlers |
| F4 UI 抽象 | `CommandUI` Protocol, TUI/Pipe adapters |
| F5 模式/状态栏 | `InteractionMode`, `/plan`, `/do`, `refresh_status` |
| F6 Tab 补全 | registry completions + prompt_toolkit adapter |
| F7 帮助 | registry help + `/help` handler |
| F8 十个命令/兼容 | `builtin.py` 注册表 |
| F9 回车统一分流 | TUI/pipe 都调用 `InputRouter.handle` |
| F10 错误边界 | 注册异常上抛；运行时 handler 错误转 UI 错误 |
| N1 低开销 | 本地 dict 索引，无额外 LLM |
| N2 可测试 | 纯 parser/registry + Memory UI fake |
| N3 兼容 | 迁移策略与 compatibility handlers |
| N4 解耦 | commands → Session 协议/UI Protocol，不依赖 Renderer |
| N5 安全 | 未知命令不进 Agent；已有权限路径不绕过 |

## 设计自检

- 接口没有遗留占位项；`/review` mode 已固定为 `FULL`。
- 注册中心、解析器、分发器、UI 端口和内置命令的职责互不重叠。
- TUI 与 pipe 只共享路由核心，不共享具体输出实现，依赖方向无环。
- 现有 `Session` 能力均以公开方法或只读快照方式复用，不要求重写 Agent/Context/Memory。
- 每条 spec 功能需求均有明确模块落点，具体文件级步骤留给 `task.md`。
