# Agent 生命周期 Hooks Checklist

> 每一项都通过运行代码、测试或观察输出验证；不以阅读实现代码作为通过依据。

## 规则与加载

- [ ] **最小三要素规则（AC2）**：加载只含 event 与 action 的规则并触发对应事件，观察动作无条件执行；加入 if 后只有条件命中才执行。（验证：运行 tests.test_hooks_loader.SingleFileLoaderTests 与 tests.test_hooks_engine.DispatchTests）

- [ ] **必填与未知字段（AC2）**：分别加载缺少 event、缺少 action、声明多个动作及包含未知字段的规则，观察每条规则被单独跳过并显示来源与位置。（验证：运行 tests.test_hooks_loader.RuleValidationTests）

- [ ] **三级匿名合并（AC3）**：在用户、项目、本地文件各放置匿名规则，信任项目后触发同一事件，观察三条规则按 user → project → local 顺序执行。（验证：运行 tests.test_hooks_loader.MergeTests）

- [ ] **命名覆盖（AC3）**：三级文件声明同名规则，观察最终只执行最接近项目的可信定义，状态中能看到覆盖关系。（验证：运行 tests.test_hooks_loader.MergeTests）

- [ ] **未信任项目不遮蔽用户（AC3）**：项目规则未获信任且与用户规则同名时，观察用户规则仍然执行，项目规则只显示为未信任。（验证：运行 tests.test_hooks_loader.SnapshotTests）

- [ ] **会话级信任（AC3）**：首次激活项目规则时确认一次并连续触发多个事件，观察不重复询问；新进程再次启动时重新询问。（验证：运行 tests.test_hooks_integration.HookTrustUITests）

- [ ] **原子快照（AC14）**：先加载完整有效规则，再重新加载根级损坏 YAML，观察旧快照继续生效且没有新旧规则混合。（验证：运行 tests.test_hooks_loader.SnapshotTests）

- [ ] **单条错误隔离（AC14）**：同一文件同时放置有效和无效规则，观察有效规则可执行，无效规则有独立诊断。（验证：运行 tests.test_hooks_loader.SingleFileLoaderTests）

## 匹配与上下文

- [ ] **四种匹配（AC4）**：用同一事件上下文分别验证 exact、not、regex、glob 的命中与不命中结果。（验证：运行 tests.test_matching.MatchOperatorTests）

- [ ] **all 与 any（AC4）**：验证 all 需要全部谓词满足、any 只需一个满足；混用、空组及无效正则在加载阶段被拒绝。（验证：运行 tests.test_matching.ConditionTests）

- [ ] **权限规则兼容（AC4）**：使用原有 permission YAML 验证 glob、星号、首个字符串参数和 local → project → user 优先级未改变。（验证：运行 tests.test_permission_rules）

- [ ] **完整事件字段（AC5）**：在系统、会话、轮次、消息和工具事件中引用各自允许字段，观察模板得到正确工作目录、会话 ID、轮次、内容、工具参数和结果。（验证：运行 tests.test_hooks_engine.EventSnapshotTests 与 tests.test_hooks_actions.TemplateStructuredTests）

- [ ] **事件快照隔离（AC5）**：事件创建后分别修改原工具参数和事件视图，观察真实调用与 Hook 读取值互不影响。（验证：运行 tests.test_hooks_engine.EventSnapshotTests）

- [ ] **模板错误放行（AC5）**：动作引用不存在的模板路径，观察动作不调度、once 不消耗、Agent 主流程继续。（验证：运行 tests.test_hooks_actions.TemplateScalarTests 与 tests.test_hooks_engine.DispatchTests）

- [ ] **敏感上下文脱敏（AC5、AC15）**：在 headers、env、工具参数和动作输出放入测试密钥，观察诊断、状态和 stderr 均不包含原值。（验证：运行 tests.test_hooks_actions.InterceptAndRedactionTests，并搜索测试捕获输出）

## 动作

- [ ] **Shell 成功结果（AC6）**：执行受控 fixture，观察退出码、stdout、stderr 和耗时被记录，cwd 与 env 模板正确传入。（验证：运行 tests.test_hooks_actions.ShellActionTests）

- [ ] **Shell 失败隔离（AC6）**：分别触发非零退出、异常和超时，观察只产生 Hook 失败诊断且后续生命周期继续。（验证：运行 tests.test_hooks_actions.ShellActionTests）

- [ ] **会话持久 Prompt（AC7）**：在 session.started 注入提示词，连续发出两次模型请求，观察两次请求都包含该提示词。（验证：运行 tests.test_hooks_integration.ModelRequestHookTests）

- [ ] **下一请求 Prompt（AC7）**：在 tool.after 注入一次性提示词，观察只在紧接着的一次 Provider 请求出现，之后不再出现。（验证：运行 tests.test_hooks_integration.AssistantMessageHookTests）

- [ ] **Prompt 不持久化（AC7）**：观察 Provider 能看到 Hook Prompt，但 Session 消息、会话归档、上下文摘要和记忆更新输入均看不到。（验证：运行 tests.test_context 与 tests.test_hooks_integration.PromptPersistenceTests）

- [ ] **HTTP 请求构造（AC8）**：用 fake endpoint 验证模板化 method、URL、headers、JSON body、字符串 body 和 timeout。（验证：运行 tests.test_hooks_actions.HttpActionTests）

- [ ] **HTTP 安全边界（AC8）**：让 endpoint 返回重定向、非 2xx、非法 body、网络错误和超时，观察不跟随重定向、记录脱敏失败且 Agent 继续。（验证：运行 tests.test_hooks_actions.HttpActionTests）

- [ ] **SubAgent 占位（AC9）**：触发合法 SubAgent 动作，观察“尚未支持”诊断，同时没有新子会话、Provider 调用或后台 Agent。（验证：运行 tests.test_hooks_actions.PromptAndSubAgentTests）

## 执行控制与拦截

- [ ] **once 当前会话（AC10）**：同一会话重复触发 once 规则，观察只成功调度一次；reset 或成功 resume 后可再次调度。（验证：运行 tests.test_hooks_engine.OnceStateTests、SessionResetTests 和 SessionResumeTests）

- [ ] **异步不阻塞（AC10）**：提交一个受控未完成动作，观察事件分发立即返回且后台状态可查询。（验证：运行 tests.test_hooks_engine.BoundedExecutorTests）

- [ ] **异步资源上限（AC10、AC15）**：填满 worker 和 32 个排队位置，观察额外动作被拒绝并记录诊断，不继续增长任务数量。（验证：运行 tests.test_hooks_engine.BoundedExecutorTests）

- [ ] **拦截事件禁止异步（AC10）**：加载 async tool.before 规则，观察加载阶段直接跳过该规则。（验证：运行 tests.test_hooks_loader.RuleValidationTests）

- [ ] **Shell 显式拒绝（AC11）**：前置 Shell 返回合法 deny 与 reason，观察真实工具及该工具剩余前置规则不执行，失败 ToolResult 包含理由。（验证：运行 tests.test_hooks_engine.ToolInterceptTests 与 tests.test_hooks_integration.ToolHookTests）

- [ ] **HTTP 显式拒绝（AC11）**：前置 HTTP 返回合法 deny 与 reason，观察与 Shell 拒绝相同的模型反馈和 tool.after 行为。（验证：运行 tests.test_hooks_actions.InterceptAndRedactionTests 与 tests.test_hooks_integration.ToolHookTests）

- [ ] **显式 allow（AC11）**：动作返回 allow，观察继续执行后续 Hook、原 PermissionEngine 和真实工具。（验证：运行 tests.test_hooks_engine.ToolInterceptTests）

- [ ] **故障默认放行（AC12）**：前置动作分别非零退出、超时、网络失败、非 2xx、空响应及非法 JSON，观察全部进入原权限与工具流程且不误拦截。（验证：运行 tests.test_hooks_actions.InterceptAndRedactionTests）

- [ ] **五类工具结果事件（AC11、AC12）**：成功、执行错误、Hook 拒绝、权限拒绝和未知工具均恰好触发一次 tool.after，结果按模型调用顺序出现。（验证：运行 tests.test_hooks_integration.ToolHookTests）

## 生命周期与集成

- [ ] **完整事件序列（AC1）**：运行包含两个模型迭代和一次工具调用的轮次，观察 system、session、turn、完整 message、tool before/after 事件顺序与 spec 一致。（验证：运行 tests.test_hooks_integration.TurnLifecycleTests 和 EndToEndHookTests）

- [ ] **不触发流式片段（AC1）**：Provider 返回多个 text 与 thinking delta，观察每个完整响应只产生一次 message.assistant_completed。（验证：运行 tests.test_hooks_integration.AssistantMessageHookTests）

- [ ] **启动幂等**：重复调用 Session 启动，观察信任询问、system.started 和 session.started 均只发生一次。（验证：运行 tests.test_hooks_integration.SessionStartupTests）

- [ ] **Reset 边界**：执行 reset，观察旧 session.ending 在状态清理前发生，新 session.started 在新 ID 生效后发生，原有消息、计划、Skill 和 Context 行为不回归。（验证：运行 tests.test_hooks_integration.SessionResetTests）

- [ ] **Resume 原子性**：恢复失败时不发生 Hook 会话切换；恢复成功时依次结束当前会话并触发 session.resumed。（验证：运行 tests.test_hooks_integration.SessionResumeTests）

- [ ] **稳定同步顺序（AC13）**：相同三级配置重复运行，观察同步动作、Prompt 组合和首个 deny 顺序完全相同。（验证：运行 tests.test_hooks_loader.MergeTests 与 tests.test_hooks_engine.DispatchTests）

- [ ] **并行工具确定性（AC13）**：让多个读工具按相反顺序完成，观察 tool.after、ToolResult 和诊断仍按模型调用顺序。（验证：运行 tests.test_hooks_integration.ToolBatchTests）

- [ ] **异步调度顺序（AC13）**：重复提交同一组异步规则，观察提交顺序稳定，同时允许完成顺序不同。（验证：运行 tests.test_hooks_engine.BoundedExecutorTests）

- [ ] **关闭幂等与清理（AC15）**：重复 close，观察 session.ending 与 system.stopping 只发生一次，超出宽限期的未开始任务被取消，MCP 与 Memory 仍继续关闭。（验证：运行 tests.test_hooks_integration.PipeStatusAndCloseTests）

- [ ] **同步与后台故障隔离（AC15）**：让四种动作分别同步失败或后台抛错，观察 Agent 继续，诊断包含规则、来源、事件、类型、耗时和脱敏原因。（验证：运行 tests.test_hooks_engine.DispatchTests 与 LifecycleTests）

- [ ] **状态可观察性（AC15）**：运行 status，观察启动状态、生效/跳过数量、信任、once、后台数、覆盖关系和最近诊断可见，且不显示动作秘密。（验证：运行 tests.test_command_integration）

- [ ] **交互与管道一致性**：交互模式确认项目规则后正常执行；管道模式不弹提示、项目规则默认未信任并把诊断写入 stderr。（验证：运行 tests.test_hooks_integration.HookTrustUITests 与 PipeStatusAndCloseTests）

## 编译与回归

- [ ] **无配置兼容（AC16）**：在三个 Hook 文件都不存在时运行普通对话和工具轮次，观察没有额外进程、HTTP 请求或行为变化。（验证：运行 tests.test_hooks_integration 的 no-hooks 场景）

- [ ] **Provider 兼容（AC16）**：分别使用 Anthropic 与 OpenAI 格式的 fake Provider，观察 Prompt、工具拒绝和 ToolResult 语义等价。（验证：运行 tests.test_hooks_integration 中两个协议参数化场景）

- [ ] **Python 3.8 可解析**：使用项目支持的最低 Python 版本编译新增源码和测试。（验证：在 Python 3.8 环境运行 python -m compileall -q src tests，预期退出码 0）

- [ ] **源码编译**：当前环境编译全部源码和测试，无语法或导入错误。（验证：运行 uv run python -m compileall -q src tests，预期退出码 0）

- [ ] **Hooks 专项测试**：匹配、权限兼容、loader、actions、engine、integration 全部通过。（验证：运行 uv run python -m unittest tests.test_matching tests.test_permission_rules tests.test_hooks_loader tests.test_hooks_actions tests.test_hooks_engine tests.test_hooks_integration -v）

- [ ] **项目全量回归**：现有 Context、Commands、Skills、MCP、Memory 及新增 Hooks 测试全部通过，没有线程、进程或连接泄漏警告。（验证：运行 uv run python -m unittest discover -s tests -v）

## 端到端场景

- [ ] **安全策略闭环（AC17）**：首次进入带项目 Hook 的仓库时确认信任；安全命令继续经过 PermissionEngine 并执行，危险命令被参数正则规则拒绝，模型收到理由后选择安全替代方案并完成轮次。（验证：运行 tests.test_hooks_integration.EndToEndHookTests）

- [ ] **自动化闭环**：会话开始注入长期约束，工具完成后异步发送通知并向下一请求注入一次性上下文；观察通知故障不影响模型，Prompt 作用域正确，最终轮次完成且历史未被污染。（验证：运行 tests.test_hooks_integration 的完整 Prompt/HTTP 生命周期场景）

## 2026-08-19 实施验收记录

- Python 3.8.6 执行 `python -m compileall -q src tests`：通过。
- Hooks 专项测试覆盖 matcher、权限兼容、加载与校验、四类动作、拦截、异步边界、Prompt 作用域及 Session/Agent 生命周期集成：通过。
- 项目全量回归 `python -m unittest discover -s tests -v`：138 项通过，1 项跳过；跳过项是既有 Memory 符号链接用例，原因是当前 Windows 环境不可创建符号链接，与 Hooks 无关。
- 项目 Hook 信任流程由回调集成测试覆盖；本轮未进行真实交互终端的人工按键验收。
- SubAgent 动作按本阶段范围仅返回占位诊断；`once` 为会话内状态，未做跨进程持久化；未引入显式优先级。
