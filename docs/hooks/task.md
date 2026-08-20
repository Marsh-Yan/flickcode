# Agent 生命周期 Hooks Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | src/flickcode/matching.py | 共享字段解析、匹配运算与条件组合 |
| 新建 | src/flickcode/hooks/__init__.py | Hooks 稳定公共导出 |
| 新建 | src/flickcode/hooks/models.py | 事件、规则、动作、结果、诊断和快照模型 |
| 新建 | src/flickcode/hooks/events.py | 事件 schema 与只读上下文快照 |
| 新建 | src/flickcode/hooks/template.py | 严格模板发现、校验和递归展开 |
| 新建 | src/flickcode/hooks/validation.py | 规则及跨字段集中校验 |
| 新建 | src/flickcode/hooks/loader.py | 三级 YAML、信任过滤、覆盖和原子快照 |
| 新建 | src/flickcode/hooks/prompt_state.py | 三类提示词及 once 会话状态 |
| 新建 | src/flickcode/hooks/actions.py | 四类动作、拦截解析和有界调度支持 |
| 新建 | src/flickcode/hooks/engine.py | 事件匹配、调度、拦截、异步和诊断 |
| 新建 | src/flickcode/hooks/prompt.py | HookPromptSection |
| 修改 | src/flickcode/prompt/__init__.py | 导出 HookPromptSection |
| 修改 | src/flickcode/permissions/rules.py | 改用共享 glob matcher |
| 修改 | src/flickcode/agent.py | 模型及工具生命周期接线、工具两阶段处理 |
| 修改 | src/flickcode/session.py | Hook 组合根、启动、会话、轮次和状态接线 |
| 修改 | src/flickcode/tui.py | 项目信任提示、启动和管道诊断 |
| 修改 | src/flickcode/commands/builtin.py | status 展示 Hook 摘要 |
| 新建 | tests/test_matching.py | 匹配核心单元测试 |
| 新建 | tests/test_permission_rules.py | 旧权限行为回归测试 |
| 新建 | tests/test_hooks_loader.py | 规则解析、校验、覆盖、信任和快照测试 |
| 新建 | tests/test_hooks_actions.py | 模板、动作、超时、脱敏和拦截测试 |
| 新建 | tests/test_hooks_engine.py | 顺序、once、async、提示词和诊断测试 |
| 新建 | tests/test_hooks_integration.py | Session、Agent、Provider 与工具集成测试 |
| 修改 | tests/test_context.py | Hook Prompt 不落历史、归档和摘要的回归 |
| 修改 | tests/test_command_integration.py | Hook 状态输出测试 |
| 新建 | tests/fixtures/hooks/valid.yaml | 完整合法规则样例 |
| 新建 | tests/fixtures/hooks/invalid.yaml | 集中校验错误样例 |
| 新建 | tests/fixtures/hooks/decide.py | 可控 Shell allow/deny/failure fixture |

## T1：建立共享匹配数据模型

**文件：** src/flickcode/matching.py、tests/test_matching.py

**依赖：** 无

**步骤：**

1. 定义 MatchOperator、LogicalMode、MatchPredicate 和 ConditionGroup。
2. 为数据模型增加空字段、未知运算符和空条件组的基础校验。
3. 建立测试类和最小合法/非法构造样例。

**验证：** 运行 uv run python -m unittest tests.test_matching -v；预期数据模型合法样例通过，非法样例产生明确 ValueError。

## T2：实现点路径字段解析

**文件：** src/flickcode/matching.py、tests/test_matching.py

**依赖：** T1

**步骤：**

1. 实现从嵌套 mapping 读取 a.b.c 点路径。
2. 区分字段不存在与字段值为 null。
3. 拒绝空段、列表索引和对象属性访问。
4. 覆盖嵌套成功、缺失、null 和非法路径测试。

**验证：** 运行 uv run python -m unittest tests.test_matching.FieldResolutionTests -v；预期点路径只读取 mapping 且错误可区分。

## T3：实现四种匹配运算

**文件：** src/flickcode/matching.py、tests/test_matching.py

**依赖：** T1

**步骤：**

1. 实现保留类型的 exact 与 not。
2. 实现字符串 regex，并在编译阶段拒绝无效表达式。
3. 使用 fnmatch 等价语义实现 glob。
4. 为 mapping/list 定义排序稳定的 JSON 文本形式。
5. 覆盖字符串、数字、布尔、复杂值和非法类型。

**验证：** 运行 uv run python -m unittest tests.test_matching.MatchOperatorTests -v；预期四种运算及类型边界全部通过。

## T4：实现条件编译和 all/any 求值

**文件：** src/flickcode/matching.py、tests/test_matching.py

**依赖：** T2、T3

**步骤：**

1. 把 YAML 风格原始条件编译为 ConditionGroup。
2. 校验只能存在一个 all 或 any。
3. 校验每个谓词只有一个匹配运算符。
4. 根据 allowed_fields 拒绝未知字段。
5. 实现无条件、all 短路和 any 短路求值。

**验证：** 运行 uv run python -m unittest tests.test_matching.ConditionTests -v；预期合法组合正确求值，混用与未知字段被拒绝。

## T5：迁移权限 glob 到共享 matcher

**文件：** src/flickcode/permissions/rules.py、tests/test_permission_rules.py

**依赖：** T3

**步骤：**

1. 建立用户、项目、本地三级临时权限文件 fixture。
2. 记录现有通配符、首个字符串参数、无匹配和来源优先级期望。
3. 将 Rule.matches 的 fnmatch 调用替换为共享 GLOB 匹配。
4. 保持星号无条件命中和反向遍历不变。

**验证：** 运行 uv run python -m unittest tests.test_permission_rules -v；预期旧 YAML 无需修改且所有原语义通过。

## T6：定义 Hooks 核心枚举与动作模型

**文件：** src/flickcode/hooks/models.py、src/flickcode/hooks/__init__.py、tests/test_hooks_loader.py

**依赖：** T1

**步骤：**

1. 定义 HookEventName、HookSource、ActionType、ProjectTrust 和 InterceptDecision。
2. 定义 ShellAction、PromptAction、HttpAction、SubAgentAction。
3. 校验动作必填字段、有限正数超时和 HTTP method 规范化。
4. 从 hooks/__init__.py 导出稳定公共类型。

**验证：** 运行 uv run python -m unittest tests.test_hooks_loader.ActionModelTests -v；预期四类合法动作可构造，非法超时与空字段被拒绝。

## T7：定义规则、结果、诊断和快照模型

**文件：** src/flickcode/hooks/models.py、src/flickcode/hooks/__init__.py、tests/test_hooks_loader.py

**依赖：** T6

**步骤：**

1. 定义 HookRule、HookEvent、ActionResult、InterceptResult 和 HookDispatchResult。
2. 定义 HookDiagnostic、HookOverride、HookSnapshot、HookRefresh 和 HookStatusSnapshot。
3. 为匿名规则身份、来源位置和 generation 建立稳定字段。
4. 验证公开状态可以转换为不含动作秘密的安全摘要。

**验证：** 运行 uv run python -m unittest tests.test_hooks_loader.CoreModelTests -v；预期不可变模型、默认值和安全摘要通过。

## T8：建立固定事件 schema

**文件：** src/flickcode/hooks/events.py、tests/test_hooks_engine.py

**依赖：** T7

**步骤：**

1. 为十二个固定事件登记允许字段。
2. 定义通用、会话、轮次、消息和工具字段集合。
3. 实现 event_schema 查询并拒绝未知事件。
4. 测试每个事件只开放 plan 中声明的字段。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.EventSchemaTests -v；预期十二个事件 schema 稳定且未知事件失败。

## T9：实现事件上下文递归冻结

**文件：** src/flickcode/hooks/events.py、tests/test_hooks_engine.py

**依赖：** T8

**步骤：**

1. 实现 JSON 兼容 mapping/list 的深复制和递归只读转换。
2. 实现带 UTC 时间的系统、会话、轮次、消息和工具事件构造器。
3. 确保修改原参数不会改变事件，修改事件也不会改变原参数。
4. 覆盖工具结果、null、嵌套列表和稳定序列化。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.EventSnapshotTests -v；预期事件与原对象双向隔离并使用 UTC 时间。

## T10：实现模板引用发现与标量展开

**文件：** src/flickcode/hooks/template.py、tests/test_hooks_actions.py

**依赖：** T2、T8

**步骤：**

1. 解析 {{path.to.value}} 引用并拒绝表达式、函数和空路径。
2. 使用共享字段解析器展开字符串模板。
3. 对复杂值使用排序稳定的紧凑 JSON。
4. 未知变量返回专用模板错误，不静默替换。

**验证：** 运行 uv run python -m unittest tests.test_hooks_actions.TemplateScalarTests -v；预期标量、复杂值、多变量和未知变量行为通过。

## T11：实现结构化模板递归展开

**文件：** src/flickcode/hooks/template.py、tests/test_hooks_actions.py

**依赖：** T10

**步骤：**

1. 对 mapping、list、tuple 和字符串递归展开。
2. 保持非字符串标量原类型。
3. 提供模板引用静态扫描，供 validation 使用。
4. 覆盖 HTTP body、headers 和 Shell env 的嵌套模板。

**验证：** 运行 uv run python -m unittest tests.test_hooks_actions.TemplateStructuredTests -v；预期结构和类型保持稳定。

## T12：实现单条规则集中校验

**文件：** src/flickcode/hooks/validation.py、tests/test_hooks_loader.py

**依赖：** T4、T6、T8、T11

**步骤：**

1. 校验 event、action 必填和顶层未知字段。
2. 调用条件编译器校验 all/any、运算符和事件字段。
3. 校验动作模板引用与该事件 schema 的兼容性。
4. 禁止 async tool.before 和 Prompt/SubAgent 拦截声明。
5. 将错误转换为包含来源和规则位置的 HookDiagnostic。

**验证：** 运行 uv run python -m unittest tests.test_hooks_loader.RuleValidationTests -v；预期每种无效组合被单独定位，合法规则无诊断。

## T13：解析单个 Hook YAML 文件

**文件：** src/flickcode/hooks/loader.py、tests/test_hooks_loader.py、tests/fixtures/hooks/valid.yaml、tests/fixtures/hooks/invalid.yaml

**依赖：** T12

**步骤：**

1. 读取 hooks 根列表并保留 source_path 与 source_index。
2. 把四类 action mapping 转换为对应动作模型。
3. 为命名规则和匿名规则生成稳定 rule_id。
4. 单条错误跳过该规则，根结构错误标记为快照级错误。
5. 建立覆盖全部字段的合法及非法 fixture。

**验证：** 运行 uv run python -m unittest tests.test_hooks_loader.SingleFileLoaderTests -v；预期合法规则完整解析，单条与根级错误正确分类。

## T14：实现三级发现与稳定合并

**文件：** src/flickcode/hooks/loader.py、tests/test_hooks_loader.py

**依赖：** T13

**步骤：**

1. 接受显式用户目录和项目根，构造三个固定文件位置。
2. 按 user、project、local 和文件内位置形成稳定候选序列。
3. 匿名规则全部追加。
4. 命名规则移除低层旧定义，并在最终来源位置加入完整新定义。
5. 记录 HookOverride 关系。

**验证：** 运行 uv run python -m unittest tests.test_hooks_loader.MergeTests -v；预期同名覆盖、匿名追加和重复加载顺序稳定。

## T15：实现信任过滤与原子快照

**文件：** src/flickcode/hooks/loader.py、tests/test_hooks_loader.py

**依赖：** T14

**步骤：**

1. 在命名覆盖前按 ProjectTrust 过滤项目规则。
2. 验证 UNTRUSTED 项目同名规则不会遮蔽用户规则。
3. 实现 prepare_refresh 不变更当前 snapshot。
4. candidate 完整时 commit generation；根级致命错误时保留旧 snapshot。
5. 覆盖 TRUSTED、UNTRUSTED、无项目规则和重新加载失败。

**验证：** 运行 uv run python -m unittest tests.test_hooks_loader.SnapshotTests -v；预期信任过滤、覆盖和失败回退均原子。

## T16：实现 PromptState 的三种作用域

**文件：** src/flickcode/hooks/prompt_state.py、tests/test_hooks_engine.py

**依赖：** T7

**步骤：**

1. 分别保存系统级、会话级和 pending 提示词及规则身份。
2. 实现 persistent_prompts 的稳定组合。
3. 实现 pending 的原子读取并清空。
4. 会话切换时保留系统提示词并清空会话与 pending。
5. 覆盖重复消费、空消费和会话切换。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.PromptStateTests -v；预期三个作用域互不污染。

## T17：实现 once 会话状态

**文件：** src/flickcode/hooks/prompt_state.py、tests/test_hooks_engine.py

**依赖：** T11、T16

**步骤：**

1. 增加线程安全的 once 查询和标记。
2. 只在成功进入同步执行或异步队列后标记。
3. 会话开始、恢复或 reset 时清空 once。
4. 系统提示词状态不得被 once 清理误删。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.OnceStateTests -v；预期同会话最多一次，切换会话后可再次运行。

## T18：实现 Shell 动作执行器

**文件：** src/flickcode/hooks/actions.py、tests/test_hooks_actions.py、tests/fixtures/hooks/decide.py

**依赖：** T7、T11

**步骤：**

1. 使用可注入 runner 执行模板展开后的命令。
2. 默认项目根 cwd，合并环境增量并使用系统默认 shell。
3. 捕获 stdout、stderr、exit code、耗时和 timeout。
4. 将异常、非零退出和超时转换为 ActionResult，不向外抛出。
5. 创建输出 allow、deny、非法 JSON、非零和超时的受控脚本。

**验证：** 运行 uv run python -m unittest tests.test_hooks_actions.ShellActionTests -v；预期成功、失败、超时、cwd 和 env 行为可控。

## T19：实现 HTTP 动作执行器

**文件：** src/flickcode/hooks/actions.py、tests/test_hooks_actions.py

**依赖：** T7、T11

**步骤：**

1. 使用可注入 opener 构造 method、URL、headers 和 body。
2. mapping/list body 编码为 JSON，字符串按 UTF-8 原样发送。
3. 禁止自动重定向并传递显式 timeout。
4. 捕获 2xx、非 2xx、网络错误和超时为 ActionResult。
5. 测试中使用 fake opener，不访问真实网络。

**验证：** 运行 uv run python -m unittest tests.test_hooks_actions.HttpActionTests -v；预期请求编码、重定向拒绝、状态和错误转换通过。

## T20：实现 Prompt 与 SubAgent 占位动作

**文件：** src/flickcode/hooks/actions.py、src/flickcode/hooks/prompt_state.py、tests/test_hooks_actions.py

**依赖：** T16

**步骤：**

1. Prompt 执行器根据事件层级写入正确提示词作用域。
2. SubAgent 执行器返回稳定的 unsupported 诊断，不创建会话。
3. 两种动作均返回统一 ActionResult。
4. 验证 Prompt 模板失败时不写入状态。

**验证：** 运行 uv run python -m unittest tests.test_hooks_actions.PromptAndSubAgentTests -v；预期作用域正确且 SubAgent 无副作用。

## T21：实现输出截断、脱敏与拦截解析

**文件：** src/flickcode/hooks/actions.py、tests/test_hooks_actions.py

**依赖：** T18、T19、T20

**步骤：**

1. 对 stdout、stderr 和 HTTP 正文应用 16 KiB 诊断上限。
2. 对 Authorization、token、api_key、secret 等字段和值做统一脱敏。
3. 仅从成功 Shell stdout 或成功 HTTP body 解析单个 JSON 对象。
4. 只接受 allow 或带非空 reason 的 deny。
5. 非零、超时、非 2xx 和非法结构始终放行并形成诊断。

**验证：** 运行 uv run python -m unittest tests.test_hooks_actions.InterceptAndRedactionTests -v；预期只有合法 deny 拦截，敏感数据不出现在诊断。

## T22：实现有界异步提交器

**文件：** src/flickcode/hooks/actions.py、tests/test_hooks_engine.py

**依赖：** T7

**步骤：**

1. 用 ThreadPoolExecutor 和 BoundedSemaphore 限制 worker 与排队总量。
2. 提交成功、队列已满、任务异常和完成回调均产生确定状态。
3. 关闭时停止新提交，等待宽限期并取消未开始任务。
4. 支持注入 executor 和时钟以避免测试 sleep。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.BoundedExecutorTests -v；预期队列不越界、异常可观察且关闭幂等。

## T23：实现 HookEngine 基础分发

**文件：** src/flickcode/hooks/engine.py、src/flickcode/hooks/__init__.py、tests/test_hooks_engine.py

**依赖：** T15、T17、T21、T22

**步骤：**

1. 创建 Engine 状态锁、Catalog snapshot、PromptState、动作分派器和诊断缓冲。
2. 实现幂等 start 和未启动/已关闭空分发。
3. 按事件筛选规则、求值条件并保持 snapshot 顺序。
4. 分派同步或异步动作，并正确标记 once。
5. 将所有异常转换为 HookDiagnostic。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.DispatchTests -v；预期匹配、顺序、once、async 和故障隔离通过。

## T24：实现工具前置拦截

**文件：** src/flickcode/hooks/engine.py、tests/test_hooks_engine.py

**依赖：** T23

**步骤：**

1. 实现 before_tool 事件构造与同步规则分发。
2. 忽略 allow 并继续后续规则。
3. 首个合法 deny 返回 HookDispatchResult 并停止剩余前置规则。
4. 动作失败或非法判定记录后继续。
5. 验证一个工具拒绝不改变另一个工具的分发。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.ToolInterceptTests -v；预期首个 deny、失败放行和工具隔离通过。

## T25：实现 Engine 会话切换、提示词和关闭

**文件：** src/flickcode/hooks/engine.py、tests/test_hooks_engine.py

**依赖：** T23、T24

**步骤：**

1. 实现 begin_session 和 end_session 的事件及状态顺序。
2. 实现 persistent_prompts 和 consume_request_prompts。
3. 实现最近 100 条诊断与可 drain 的新增诊断双视图。
4. 实现 HookStatusSnapshot。
5. 实现 session.ending、system.stopping、异步关闭和重复 close 幂等。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.LifecycleTests -v；预期会话状态、提示词、诊断和关闭行为通过。

## T26：接入 HookPromptSection

**文件：** src/flickcode/hooks/prompt.py、src/flickcode/prompt/__init__.py、tests/test_hooks_engine.py

**依赖：** T25

**步骤：**

1. 定义名称稳定、system channel 的 HookPromptSection。
2. 从 builder context 读取系统级与会话级 Hook 提示词。
3. 为空时不产生 section，非空时按规则顺序组合并带明确标题。
4. 从 prompt 包导出 Section。

**验证：** 运行 uv run python -m unittest tests.test_hooks_engine.HookPromptSectionTests -v；预期空、有值和顺序测试通过。

## T27：在 Session 创建并启动 Hook 组合根

**文件：** src/flickcode/session.py、tests/test_hooks_integration.py

**依赖：** T15、T25、T26

**步骤：**

1. Session 构造时创建 Catalog 与 Engine，但不执行 Hook。
2. 把 HookPromptSection 注册进现有 SystemPromptBuilder。
3. 新增带可选 trust callback 的幂等 start。
4. start 依次触发 system.started 与当前 session.started。
5. Hook 初始化失败时记录诊断并保持 Session 可用。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.SessionStartupTests -v；预期构造无动作、start 顺序正确、失败时禁用不崩溃。

## T28：接入 Session reset 生命周期

**文件：** src/flickcode/session.py、tests/test_hooks_integration.py

**依赖：** T27

**步骤：**

1. reset 成功路径先为旧会话触发 session.ending(reason=reset)。
2. 保留现有归档、消息、计划、Skill 和 ContextManager 重置顺序。
3. 切换会话标识后调用 begin_session(resumed=False)。
4. 验证系统提示词保留，会话提示词、pending 和 once 清空。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.SessionResetTests -v；预期旧结束、新开始及原有 reset 行为通过。

## T29：接入 Session resume 生命周期

**文件：** src/flickcode/session.py、tests/test_hooks_integration.py

**依赖：** T27

**步骤：**

1. 保持恢复、Skill 解析和上下文检查在临时状态完成。
2. 恢复失败时不发结束/恢复事件且不修改 Hook 状态。
3. 恢复成功后结束当前会话并原子提交恢复状态。
4. 调用 begin_session(resumed=True) 触发 session.resumed。
5. 验证 once 和会话提示词重新开始。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.SessionResumeTests -v；预期成功与失败边界均无半切换。

## T30：接入 Session 轮次与用户消息事件

**文件：** src/flickcode/session.py、tests/test_hooks_integration.py

**依赖：** T27

**步骤：**

1. agent_chat 未启动时执行无信任回调的安全惰性 start。
2. 为每次 agent_chat 分配会话内递增 turn.number。
3. 先发 turn.started，再发 message.user_accepted，再写用户历史。
4. 在所有结束路径最多发一次 turn.ended，并携带 stop_reason。
5. Hook 失败不得阻止消息写入或 Agent Loop。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.TurnLifecycleTests -v；预期正常、Provider 错误和取消路径事件顺序稳定。

## T31：接入模型请求与 Hook Prompt

**文件：** src/flickcode/agent.py、src/flickcode/session.py、tests/test_hooks_integration.py

**依赖：** T26、T30

**步骤：**

1. 向 AgentLoop 注入 HookEngine 与基础上下文 provider。
2. 在每次迭代构建消息快照并发 message.model_request。
3. 在事件之后读取持久提示词并构建 System Prompt。
4. 原子消费 pending，合并为一条 Hook transient system message。
5. 再执行 ContextManager 预检并调用 Provider。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.ModelRequestHookTests -v；预期当前请求收到注入、预算计算包含注入且持久历史不含 transient。

## T32：接入完整助手消息事件

**文件：** src/flickcode/agent.py、tests/test_hooks_integration.py

**依赖：** T31

**步骤：**

1. Provider 流完成后、历史变更前构造完整响应事件。
2. 每个模型迭代只发一次 message.assistant_completed。
3. 文本 delta 与 thinking delta 不触发 Hook。
4. 工具调用响应产生的 pending Prompt 留给下一模型请求。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.AssistantMessageHookTests -v；预期多 delta 单事件、多轮请求各一次且 pending 作用域正确。

## T33：重构工具批次为顺序预检和稳定收尾

**文件：** src/flickcode/agent.py、tests/test_hooks_integration.py

**依赖：** T30

**步骤：**

1. 从真实执行中分离工具存在性和 PermissionEngine 预检。
2. 按模型调用顺序预检全部已知工具。
3. 保持获准读工具并行、写工具串行。
4. 把并行结果恢复为原模型调用顺序。
5. 为未知、权限拒绝、读写混合和并发完成乱序增加回归测试。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.ToolBatchTests -v；预期现有权限与并行策略保留，结果顺序稳定。

## T34：接入工具前后 Hook

**文件：** src/flickcode/agent.py、tests/test_hooks_integration.py

**依赖：** T24、T32、T33

**步骤：**

1. 已知工具在 PermissionEngine 前调用 before_tool。
2. deny 转换为带固定 Hook 前缀和理由的失败 ToolResult。
3. allow 或 Hook 失败继续原权限路径。
4. 成功、执行错误、Hook 拒绝、权限拒绝和未知工具都按原调用顺序触发 tool.after。
5. tool.after 失败不得改变 ToolResult。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.ToolHookTests -v；预期五类结果及模型反馈全部通过。

## T35：接入交互式项目规则信任

**文件：** src/flickcode/tui.py、tests/test_hooks_integration.py

**依赖：** T27

**步骤：**

1. 新增信任提示回调，展示规范化项目路径和四类动作数量。
2. 不显示命令正文、URL 凭据或 Prompt 内容。
3. 绑定高风险、权限与 Hook 信任回调后再调用 session.start。
4. 确认和拒绝均只询问一次。
5. 启动摘要显示生效、跳过及未信任规则数量。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.HookTrustUITests -v；预期确认内容脱敏、状态只在当前会话有效。

## T36：接入管道模式、状态和关闭

**文件：** src/flickcode/tui.py、src/flickcode/session.py、src/flickcode/commands/builtin.py、tests/test_command_integration.py、tests/test_hooks_integration.py

**依赖：** T25、T27、T35

**步骤：**

1. 管道模式使用无信任回调 start，并把未信任诊断写入 stderr。
2. 扩展 SessionStatusSnapshot，加入安全 Hook 状态字段。
3. 扩展 status 输出启动、规则、信任、once、后台及最近诊断摘要。
4. Session.close 依次结束会话、停止系统、关闭 Hook、MCP 和 Memory。
5. 验证 TUI 与 CLI 重复 close 只发一次结束事件。

**验证：** 运行 uv run python -m unittest tests.test_command_integration tests.test_hooks_integration.PipeStatusAndCloseTests -v；预期状态脱敏、管道不提示且关闭幂等。

## T37：验证 Prompt 不进入持久化链路

**文件：** tests/test_context.py、tests/test_hooks_integration.py

**依赖：** T31、T32

**步骤：**

1. 驱动会话级和 pending Prompt 进入 Provider 请求。
2. 检查 Session.messages 不含 Hook transient message。
3. 检查 ContextCompactor 摘要输入不含 Hook 注入。
4. 检查 SessionJournal 与 Memory Scheduler 输入不含 Hook 注入。
5. 验证重构后现有 mode whisper 行为不回归。

**验证：** 运行 uv run python -m unittest tests.test_context tests.test_hooks_integration.PromptPersistenceTests -v；预期 Provider 可见注入，四条持久化路径均不可见。

## T38：实现端到端安全场景

**文件：** tests/test_hooks_integration.py、tests/fixtures/hooks/valid.yaml、tests/fixtures/hooks/decide.py

**依赖：** T28、T29、T30、T34、T35、T36、T37

**步骤：**

1. 在临时项目配置一条仅对特定 execute_command 参数命中的项目级前置规则。
2. 用 fake Provider 先请求安全命令，再请求危险命令，最后生成替代方案。
3. 验证未信任时项目规则不执行且用户规则仍有效。
4. 确认信任后，安全命令进入 PermissionEngine，危险命令被 Hook 拒绝。
5. 验证拒绝理由作为工具结果回到模型，tool.after 仍触发，轮次正常完成。

**验证：** 运行 uv run python -m unittest tests.test_hooks_integration.EndToEndHookTests -v；预期 AC17 完整场景通过且不访问真实模型或网络。

## T39：执行兼容性与全量回归

**文件：** 全部本功能文件与现有 tests

**依赖：** T5、T15、T21、T25、T34、T36、T37、T38

**步骤：**

1. 在无 Hook 文件环境运行新增测试，确认不创建进程或网络请求。
2. 运行 Python 3.8 可解析性检查，修正不兼容语法或标准库用法。
3. 运行 Hooks、权限、上下文、命令、Skill、MCP 和 Memory 全部测试。
4. 运行项目全量测试并记录测试数量与结果。
5. 检查新增诊断和状态输出不包含 fixture 密钥。

**验证：** 运行 uv run python -m unittest discover -s tests -v；预期全部测试通过且无资源泄漏警告。

## 执行顺序

    T1 ─┬─> T2 ─┐
        └─> T3 ─┴─> T4 ─> T5

    T1 ─> T6 ─> T7 ─> T8 ─> T9
                    └──────> T16 ─> T17

    T2 + T8 ─> T10 ─> T11
    T4 + T6 + T8 + T11 ─> T12 ─> T13 ─> T14 ─> T15

    T7 + T11 ─┬─> T18 ─┐
              ├─> T19 ─┼─> T21
              └─> T20 ─┘
    T7 ─> T22

    T15 + T17 + T21 + T22
              └─> T23 ─> T24 ─> T25 ─> T26

    T15 + T25 + T26
              └─> T27 ─┬─> T28
                        ├─> T29
                        └─> T30 ─┬─> T31 ─> T32
                                 └─> T33

    T24 + T32 + T33 ─> T34
    T27 ─> T35 ─> T36
    T31 + T32 ─> T37

    T28 + T29 + T30 + T34 + T35 + T36 + T37
              └─> T38 ─> T39

可并行组：

- T2 与 T3。
- T8/T9、T10/T11 和 T16/T17 在各自依赖满足后可由不同执行者推进。
- T18、T19、T20。
- T28、T29。
- T32 与 T33 在 T31/T30 对应依赖满足后。
- T35 与 Agent 接线任务可并行。

实现阶段必须按依赖执行。每个任务只有在自身验证命令通过后才标记完成；不得用后续全量测试代替任务级验证。
