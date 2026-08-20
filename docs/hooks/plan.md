# Agent 生命周期 Hooks Plan

## 架构概览

采用“集中式 Hook 引擎 + 明确生命周期接线”的结构。

    三级 YAML 规则
            |
            v
    HookCatalog（发现、合并、校验）
            |
            v
    不可变规则快照 ---> HookEngine（匹配、调度、状态、诊断）
                              |
               +--------------+--------------+----------------+
               |              |              |                |
             Shell          Prompt          HTTP         SubAgent 占位
                              |
                              v
                    持久提示词 + 下一请求队列

    生命周期事件上下文 ---> HookEngine ---> 工具 allow / deny
    通用 Matcher ----------> HookEngine             |
         |                                          v
         +-----------------> 权限规则 ---> 原权限检查 ---> 真实工具

### 通用匹配层

新增与业务无关的匹配模块，负责：

- 从嵌套事件上下文读取字段；
- 执行 exact、not、regex、glob；
- 执行单层 all 或 any 组合；
- 在加载时预编译和校验正则。

权限规则继续保留原有 YAML 格式，由适配器把旧 pattern 转换为等价 glob 谓词。Hooks 与权限系统依赖通用匹配层，二者互不依赖。

### Hook 配置目录

独立的 Hook 配置目录负责三级文件发现、解析、命名覆盖、匿名追加、字段校验和不可变快照生成。

加载分为两个阶段：

1. 准备：读取并校验全部三级规则，不执行动作。
2. 激活：根据项目信任结果过滤项目级规则，提交完整快照。

无效单条规则进入诊断但不影响其他规则；根级 YAML 无法解析等整体错误不会替换上一份有效快照。

### Hook 引擎

每个主 Session 持有一个会话级 Hook 引擎，统一负责：

- 接收固定类型的生命周期事件；
- 匹配当前快照；
- 按稳定顺序同步执行或调度异步动作；
- 保存当前会话的 once 集合；
- 维护系统级、会话级和下一请求提示词；
- 解析工具前置动作的结构化判定；
- 收集同步及后台诊断；
- 在关闭时停止接收任务并回收后台资源。

独立 Skill 子会话本阶段不单独创建 Hook 引擎，避免在 SubAgent 对接前引入不完整的继承语义；主 Session 的共享 Skill 执行仍通过现有主 Agent Loop 触发 Hooks。

### 动作执行层

四种动作使用统一执行接口并返回标准化结果：

- Shell：真实执行，返回退出码、输出、错误和耗时。
- Prompt：不调用模型，只把展开后的文本写入对应提示词缓冲区。
- HTTP：通过标准库发送受超时约束的请求，返回状态、正文和耗时。
- SubAgent：返回“尚未支持”的诊断结果，不启动任何会话。

异步调度使用有界执行池；每个动作自身捕获异常并转换为失败结果，不向 Agent 主调用链抛出。

### 生命周期接线

Session 继续作为组合根。现有入口只做窄接线：

- CLI/TUI：绑定项目信任回调并触发系统启动、正常关闭。
- Session：发出会话开始、恢复、结束、轮次开始、轮次结束和用户消息事件。
- Agent Loop：发出模型请求前、模型完整响应和工具前后事件。
- 工具执行：先运行工具前置 Hooks；未被拒绝时再进入现有权限引擎和真实工具；最终统一发出工具结果事件。

启动动作从对象构造中分离为幂等启动阶段：

- 交互模式绑定确认回调后启动，能够询问项目级信任。
- 管道模式没有交互能力，默认不信任项目级规则并输出诊断。
- 用户级和本地级规则不受此限制。

### 提示词接入

Hook 提示词不进入 Session.messages：

- 系统级与会话级提示词作为稳定额外提示区参与请求。
- 一次性提示词在模型请求前原子取出，加入当前 transient messages，随后清空。
- 上下文压缩、会话归档和记忆更新只看到原有持久消息。

## 核心数据结构

### YAML 规则

    hooks:
      - name: block-dangerous-command
        event: tool.before
        if:
          all:
            - field: tool.name
              exact: execute_command
            - field: tool.arguments.command
              regex: "^rm\\s+-rf\\b"
        action:
          type: shell
          command: "python .flick/check_command.py"
          timeout: 5
        once: false
        async: false

规则约束：

- hooks 必须是规则列表。
- if 只能包含一个 all 或一个 any。
- 每个谓词必须包含 field，并且只能声明 exact、not、regex、glob 中的一个。
- not 表示“不等于给定值”的反向精确匹配。
- 模板变量使用 {{tool.name}}、{{session.id}} 这类点路径，不支持表达式或函数。
- 字典和列表模板值使用稳定 JSON 表示。
- 匿名规则由“来源文件 + 列表位置”生成内部身份。

### 固定事件

    class HookEventName(str, Enum):
        SYSTEM_STARTED = "system.started"
        SYSTEM_STOPPING = "system.stopping"
        SESSION_STARTED = "session.started"
        SESSION_RESUMED = "session.resumed"
        SESSION_ENDING = "session.ending"
        TURN_STARTED = "turn.started"
        TURN_ENDED = "turn.ended"
        MESSAGE_USER_ACCEPTED = "message.user_accepted"
        MESSAGE_MODEL_REQUEST = "message.model_request"
        MESSAGE_ASSISTANT_COMPLETED = "message.assistant_completed"
        TOOL_BEFORE = "tool.before"
        TOOL_AFTER = "tool.after"

reset_session 映射为旧会话 session.ending，随后为新会话触发 session.started。恢复成功只触发 session.resumed。

### 匹配模型

    class MatchOperator(str, Enum):
        EXACT = "exact"
        NOT = "not"
        REGEX = "regex"
        GLOB = "glob"

    class LogicalMode(str, Enum):
        ALL = "all"
        ANY = "any"

    @dataclass(frozen=True)
    class MatchPredicate:
        field: str
        operator: MatchOperator
        expected: object

    @dataclass(frozen=True)
    class ConditionGroup:
        mode: LogicalMode
        predicates: tuple[MatchPredicate, ...]

公开接口：

    def compile_condition(raw, allowed_fields):
        ...

    def matches(condition, context):
        ...

    def match_value(actual, operator, expected):
        ...

    def resolve_field(context, path):
        ...

匹配规则：

- exact 与 not 保留标量类型比较。
- regex 与 glob 只接受字符串期望值；实际值按稳定文本形式匹配。
- glob 使用现有权限规则等价的 fnmatch 语义。
- 权限模块通过 match_value(actual, GLOB, pattern) 保持原先首个字符串参数匹配行为。

### 规则与动作

    class HookSource(str, Enum):
        USER = "user"
        PROJECT = "project"
        LOCAL = "local"

    class ActionType(str, Enum):
        SHELL = "shell"
        PROMPT = "prompt"
        HTTP = "http"
        SUBAGENT = "subagent"

    @dataclass(frozen=True)
    class ShellAction:
        command: str
        cwd: Optional[str]
        env: Mapping[str, str]
        timeout_seconds: float

    @dataclass(frozen=True)
    class PromptAction:
        content: str

    @dataclass(frozen=True)
    class HttpAction:
        method: str
        url: str
        headers: Mapping[str, str]
        body: object
        timeout_seconds: float

    @dataclass(frozen=True)
    class SubAgentAction:
        task: str

    @dataclass(frozen=True)
    class HookRule:
        rule_id: str
        name: Optional[str]
        event: HookEventName
        condition: Optional[ConditionGroup]
        action: HookAction
        once: bool
        asynchronous: bool
        source: HookSource
        source_path: Path
        source_index: int

Shell 的 cwd 默认项目根目录；env 只增量覆盖当前进程环境。HTTP method 默认 POST，mapping/list body 自动编码为 JSON，字符串按 UTF-8 原样发送。HTTP 不自动跟随重定向。

### 事件上下文

    @dataclass(frozen=True)
    class HookEvent:
        name: HookEventName
        occurred_at: datetime
        context: Mapping[str, object]

固定点路径：

| 范围 | 字段 |
|---|---|
| 通用 | event.name、system.cwd、system.config_sources |
| 会话 | session.id、session.state |
| 轮次 | turn.number、turn.mode、turn.stop_reason |
| 消息 | message.role、message.content、message.stage |
| 工具 | tool.call_id、tool.name、tool.arguments、tool.result |

每种事件注册自己的允许字段集合。条件引用不可用字段时在加载阶段报错；动作模板也尽量静态校验，动态嵌套工具参数无法预知时退化为运行时诊断。

事件上下文使用递归只读快照，Hook 无法修改真实工具参数、结果或消息。

### 执行与拦截结果

    class InterceptDecision(str, Enum):
        ALLOW = "allow"
        DENY = "deny"

    @dataclass(frozen=True)
    class ActionResult:
        success: bool
        output: str
        error: str
        elapsed_seconds: float
        status_code: Optional[int] = None
        exit_code: Optional[int] = None

    @dataclass(frozen=True)
    class InterceptResult:
        decision: Optional[InterceptDecision]
        reason: str = ""

    @dataclass(frozen=True)
    class HookDispatchResult:
        intercepted: bool
        reason: str
        executed_rule_ids: tuple[str, ...]
        diagnostics: tuple[HookDiagnostic, ...]

拦截只检查成功动作的主输出：

- Shell 从 stdout 解析单个 JSON 对象。
- HTTP 从成功响应正文解析单个 JSON 对象。
- decision=deny 且 reason 非空才拒绝。
- allow、无判定或非法结构均不拒绝；非法结构另记诊断。
- Prompt 与 SubAgent 不能产生拦截判定。

### 规则快照与加载

    @dataclass(frozen=True)
    class HookSnapshot:
        generation: int
        rules: tuple[HookRule, ...]
        diagnostics: tuple[HookDiagnostic, ...]
        overrides: tuple[HookOverride, ...]

    @dataclass(frozen=True)
    class HookRefresh:
        previous: HookSnapshot
        candidate: Optional[HookSnapshot]
        fatal_diagnostics: tuple[HookDiagnostic, ...]

    class HookCatalog:
        def prepare_refresh(self):
            ...

        def commit(self, refresh):
            ...

prepare_refresh 不改变当前状态；只有候选快照完整形成后才能 commit。命名覆盖后的最终排序使用生效规则所在来源和文件位置。

### 项目信任

    class ProjectTrust(str, Enum):
        PENDING = "pending"
        TRUSTED = "trusted"
        UNTRUSTED = "untrusted"

    ProjectTrustCallback = Callable[
        [Path, tuple[HookRuleSummary, ...]],
        bool,
    ]

交互模式显示项目路径、规则数量及动作类型摘要。管道模式不提供回调并直接标记 UNTRUSTED。结果只保存在当前 Hook Engine 内。

### Hook Engine

    class HookEngine:
        def start(self, trust_callback=None):
            ...

        def dispatch(self, event):
            ...

        def before_tool(self, call_id, name, arguments, base_context):
            ...

        def begin_session(self, session_id, resumed):
            ...

        def end_session(self, session_id, reason):
            ...

        def persistent_prompts(self):
            ...

        def consume_request_prompts(self):
            ...

        def status_snapshot(self):
            ...

        def drain_diagnostics(self):
            ...

        def close(self):
            ...

状态规则：

- start 与 close 幂等。
- dispatch 在未启动或已关闭时返回空结果。
- once 在动作成功进入同步执行或异步队列后立即记录；模板展开失败或队列拒绝不记录。
- 异步池使用固定上限和有界待执行队列。
- close 停止接收新任务，在短暂宽限期后取消尚未开始的任务。

### 提示词 Section

新增 HookPromptSection，从 Prompt Builder context 读取系统级与会话级持久提示词，加入 stable System Prompt。

每次模型请求顺序：

1. 构建基础事件上下文。
2. 分发 message.model_request。
3. 读取持久提示词并构建 System Prompt。
4. 原子消费下一请求提示词并转换为 transient system message。
5. 执行现有上下文预检。
6. 调用 Provider。

## 模块设计

### flickcode.matching

职责：

- 提供业务无关的值匹配和条件组求值。
- 校验字段、运算符、类型和正则。
- 为 Hooks 与权限规则提供同一匹配入口。

依赖：仅标准库，不导入 Hooks、权限、Session 或 Agent。

### flickcode.hooks.models

职责：集中定义事件、来源、动作、规则、快照、执行结果、拦截判定、信任状态和诊断等不可变数据模型。

约束：不读取文件、不执行动作、不引用 Session 或 Agent Loop；对外状态可稳定序列化。

### flickcode.hooks.events

职责：

- 维护固定事件目录及允许字段。
- 从系统、Session、轮次、消息与工具数据生成只读上下文。
- 递归冻结参数和结果。
- 提供稳定 JSON 文本转换。

### flickcode.hooks.template

职责：

- 发现并校验模板点路径。
- 递归展开字符串、请求头、环境变量和结构化 body。
- 对复杂值使用稳定 JSON。
- 将未知变量转换为受控模板错误。

不支持表达式、默认值、函数或代码执行。

### flickcode.hooks.loader

职责：

- 读取三级 YAML 并保留来源位置。
- 解析规则与动作。
- 调用 matcher、template 和 validator。
- 根据会话信任过滤项目规则。
- 合并匿名规则与命名覆盖。
- 生成候选不可变快照。

### flickcode.hooks.validation

职责：

- 校验三要素及未知字段。
- 校验一个谓词只有一个运算符。
- 校验事件字段和模板。
- 校验动作必填字段与正数超时。
- 禁止异步 tool.before。
- 阻止 Prompt/SubAgent 声明拦截。
- 形成规则级或快照级诊断。

### flickcode.hooks.actions

职责：

- 展开动作模板。
- 分派 Shell、Prompt、HTTP 与 SubAgent 占位执行器。
- 截断并脱敏可记录输出。
- 返回统一 ActionResult。
- 对工具前事件解析显式拦截判定。

Shell 使用系统默认 shell、明确 cwd、环境增量和超时。HTTP 使用标准库客户端、禁用自动重定向并设置超时。

### flickcode.hooks.prompt_state

职责：

- 维护系统级持久提示词。
- 维护会话级持久提示词。
- 维护下一请求提示词。
- 维护当前会话 once 集合。

切换会话时保留系统提示词，清除会话提示词、pending 与 once。

### flickcode.hooks.engine

职责：

- 持有 Catalog 快照、信任状态、动作分派器、提示词状态及有界后台执行器。
- 匹配事件并稳定调度规则。
- 在首个合法 deny 后停止当前工具的前置分发。
- 将所有异常转换为线程安全诊断。
- 提供状态快照、会话切换和关闭能力。

### flickcode.hooks.prompt

职责：提供 HookPromptSection，将系统级与会话级持久提示词接入现有 SystemPromptBuilder。

### flickcode.permissions.rules

改动：保留读取、三级合并、反向遍历和 Rule 结构，只将 fnmatch 调用改为共享 glob matcher。

不得改变权限 YAML、首个字符串参数语义、通配符行为、来源优先级和 allow/deny 结果。

### flickcode.session

职责：

- 创建 Hook Catalog、Engine 和 Prompt Section。
- 提供幂等 start。
- 发出系统、会话、轮次和用户消息事件。
- 把 Engine 与基础上下文提供器传给 Agent Loop。
- 在 reset/resume 成功边界切换 Hook 会话状态。
- close 时结束会话、停止系统并关闭后台执行器。
- 把 Hook 状态与诊断接入现有 Session 能力。

agent_chat 尚未显式启动时执行安全的惰性启动；由于没有信任回调，项目规则默认不受信任。

### flickcode.agent

职责：

- 每次 Provider 请求前发出 message.model_request。
- 组合持久与下一请求 Hook 提示词。
- 完整 Provider 响应后发出 message.assistant_completed。
- 在权限检查前调用工具前置 Hook。
- 为所有工具结果调用 tool.after。

工具拒绝转换为现有 ToolResult。并行读工具采用顺序预检、并行执行、顺序收尾。

### flickcode.tui 与 flickcode.cli

职责：

- 交互模式展示项目路径、规则数量及动作类型并收集一次信任决定。
- 回调绑定后调用 session.start。
- 管道模式无回调启动，项目规则默认不信任。
- 重复关闭只触发一次生命周期结束。

### flickcode.commands.builtin

扩展 status，展示 Hook 启动状态、生效与跳过数量、项目信任、once 数量、后台数量和最近诊断；不得显示命令正文、凭据或完整事件。

## 模块交互

### 启动

    CLI/TUI 构造 Session
      -> HookCatalog 读取并校验三级规则（不执行）
      -> UI 绑定 trust_callback
      -> Session.start
      -> HookEngine.start
      -> 项目信任确认
      -> 提交过滤后的完整快照
      -> system.started
      -> begin_session
      -> session.started

用户级与本地级规则无需确认。项目规则存在且可能生效时才确认。Hooks 初始化失败时 Session 在禁用 Hooks 的状态继续。

### 用户轮次

    Session
      -> turn.started
      -> message.user_accepted
      -> 用户消息写入历史
      -> AgentLoop.run

    每次模型迭代
      -> message.model_request
      -> 合并持久及下一请求提示词
      -> 上下文预检
      -> Provider
      -> 收集完整响应
      -> message.assistant_completed
      -> 可选工具执行

    AgentLoop done
      -> turn.ended

关键顺序：

- turn.started 先于 message.user_accepted。
- 用户消息 Hook 完成后才写入历史，Hook 失败不能阻止写入。
- message.model_request 在 Hook 提示词合并和上下文预检前触发。
- 事件中的 message.content 是持久消息快照，不含本次新注入提示词。
- Hook 提示词加入后才计算上下文预算。
- message.assistant_completed 每个完整 Provider 响应触发一次。
- 最终没有下一请求时，pending 提示词保留到下一个用户轮次。
- 任意停止原因最多触发一次 turn.ended。

### 工具调用

    模型工具调用
      -> 确认工具存在与参数已解析
      -> 按模型顺序执行 tool.before
      -> allow 时进入原权限检查
      -> deny 时生成 Hook 拒绝 ToolResult
      -> 获准读工具并行、写工具串行
      -> 按模型顺序重排结果
      -> 按模型顺序执行 tool.after
      -> 写入历史并反馈模型

不存在的工具不触发 tool.before，但生成未知工具结果并触发 tool.after。所有已知工具先顺序完成 Hook 与权限预检，再执行获准工具。并行完成顺序不影响结果或 Hook 顺序。

### 拦截判定

    动作失败
      -> 记录失败并放行

    动作成功
      -> 非法 JSON：记录非法判定并放行
      -> decision=allow：继续后续规则
      -> decision=deny 且 reason 非空：立即拒绝
      -> 其他：记录非法判定并放行

Shell 只解析 stdout，HTTP 只解析 2xx 正文。首个合法拒绝停止该工具的剩余前置 Hook，但不影响同批其他工具。

### 提示词流转

    system.started Prompt -> 系统级持久提示词 -> 每次请求读取
    session.started/resumed Prompt -> 会话级持久提示词 -> 每次请求读取
    turn/message/tool Prompt -> pending -> 下一请求原子消费

同一事件按规则顺序追加，不同事件按实际发生顺序追加。pending 合并为一条带 Hook 标记的 transient system message。

### Reset

1. 旧会话触发 session.ending(reason=reset)。
2. 完成原有归档边界。
3. 清空消息、计划、Skill 与上下文。
4. 清空会话提示词、pending 与 once。
5. 切换新会话标识。
6. 触发 session.started。

### Resume

1. 在临时状态中完成恢复、Skill 解析和上下文检查。
2. 失败时不触发生命周期切换，不修改 Hook 状态。
3. 成功后结束当前会话，reason=resume_switch。
4. 原子提交恢复状态。
5. 清空原会话 Hook 状态。
6. 触发 session.resumed。

### 关闭

    Session.close
      -> session.ending(reason=close)
      -> system.stopping
      -> 停止接收新异步任务
      -> 等待有限宽限期
      -> 取消未开始任务
      -> 关闭 Hook 执行器
      -> 关闭 MCP
      -> 关闭 Memory Scheduler

close 使用状态锁保证幂等。关闭动作或清理失败只进入诊断，后续资源继续关闭。

## 文件组织

    src/flickcode/
    ├── matching.py
    ├── hooks/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── events.py
    │   ├── template.py
    │   ├── validation.py
    │   ├── loader.py
    │   ├── prompt_state.py
    │   ├── actions.py
    │   ├── engine.py
    │   └── prompt.py
    ├── permissions/rules.py
    ├── agent.py
    ├── session.py
    ├── tui.py
    └── commands/builtin.py

    tests/
    ├── test_matching.py
    ├── test_permission_rules.py
    ├── test_hooks_loader.py
    ├── test_hooks_actions.py
    ├── test_hooks_engine.py
    ├── test_hooks_integration.py
    ├── test_context.py
    ├── test_command_integration.py
    └── fixtures/hooks/

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Hook 文件位置 | 用户 ~/.flickcode/hooks.yaml；项目 .flick/hooks.yaml；本地 .flick/hooks.local.yaml | 与权限三级模型一致且隔离团队与私有规则 |
| 覆盖顺序 | 先信任过滤，再命名覆盖 | 未信任项目规则不能遮蔽用户规则 |
| 条件语言 | 点路径 + 四运算符 + 单层 all/any | 满足需求且不引入任意表达式 |
| Hook 动作授权 | 用户/本地可信，项目会话级整体确认 | 避免逐动作打断，同时阻止未信任项目自动执行 |
| 运行时依赖 | PyYAML + 标准库 | 不增加第三方依赖 |
| Shell | 系统默认 shell、明确 cwd/env/timeout | 符合 Shell 动作语义并保持跨平台 |
| HTTP | urllib、禁用重定向、显式超时 | 控制目标和依赖范围 |
| 模板 | 严格 {{path}}，失败不静默替换 | 防止错误动作和隐藏配置问题 |
| 事件数据 | 递归只读快照、UTC 时间 | 防止 Hook 修改主流程数据 |
| Prompt | 持久 System Prompt + transient system message | 不污染历史且计入上下文预算 |
| 工具批次 | 顺序预检、原策略执行、顺序收尾 | 同时满足拦截、并行和确定性 |
| 诊断 | 最近历史 + Session 即时投递 | status 与实时反馈兼得 |
| 测试 | Runner、opener、时钟、executor、trust callback 可注入 | 无需真实网络或模型 |

固定默认资源：

| 项目 | 默认值 |
|---|---|
| Shell 超时 | 30 秒 |
| HTTP 超时 | 10 秒 |
| 异步 worker | 4 |
| 异步排队上限 | 32 |
| 关闭宽限期 | 2 秒 |
| 单输出诊断上限 | 16 KiB |
| 最近诊断 | 100 条 |

异步提交使用 BoundedSemaphore 限制线程池运行与排队总量。队列满时动作失败并记录诊断，不阻塞 Agent。

## Spec 覆盖矩阵

| Spec | 设计归属 |
|---|---|
| F1 生命周期目录 | hooks.events、Session、Agent Loop |
| F2 规则结构 | hooks.models、loader、validation |
| F3 三级来源与信任 | loader、engine、TUI |
| F4 共享匹配 | matching.py、permissions adapter |
| F5 事件上下文 | events、template |
| F6 Shell | actions |
| F7 Prompt | prompt_state、prompt、Agent Loop |
| F8 HTTP | actions |
| F9 SubAgent 占位 | models、actions |
| F10 once/async/timeout | engine、prompt_state、actions |
| F11 工具拦截 | engine、Agent Loop |
| F12 稳定顺序 | loader、engine、工具两阶段处理 |
| F13 集中校验与快照 | validation、loader |
| F14 故障隔离与诊断 | actions、engine、Session status |
