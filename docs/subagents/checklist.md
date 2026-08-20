# FlickCode 子 Agent 委派 Checklist

> 每一项都通过运行代码、测试或观察输出验证；不以阅读实现代码作为通过依据。

## 统一工具、配置与角色目录

- [x] **单一稳定工具（AC1）**：分别在无自定义角色、增加角色、删除角色和覆盖同名角色后刷新 Session，观察主 Agent 工具列表始终只有同一个 `agent` 委派入口且 schema 完全一致。（验证：运行 `uv run python -m unittest tests.test_subagent_tool.AgentToolTests -v`）

- [ ] **两类启动分流（AC1）**：使用同一个 `agent` 工具分别提交 `type=defined` 与 `type=fork`，观察进入对应启动路径且返回统一结构。（验证：运行 `uv run python -m unittest tests.test_subagent_tool.CoordinatorTests -v`）

- [ ] **条件参数校验（AC1）**：分别提交缺 task、定义式缺 role、Fork 携带 role、查询缺 task ID 和未知 operation，观察每次都返回明确错误且不创建任务。（验证：运行 `uv run python -m unittest tests.test_subagent_tool -v`）

- [ ] **配置边界（AC1、AC13）**：加载默认配置和完整子 Agent 配置均成功；未知键、非正数限制、重复插件目录和未知 Provider 别名均在启动时被拒绝。（验证：运行 `uv run python -m unittest tests.test_subagent_integration.SubAgentConfigTests -v`）

- [x] **完整角色解析（AC2）**：加载包含所有 frontmatter 字段和非空正文的角色，观察名称、说明、工具、模型、轮次、权限和正文均按声明生效。（验证：运行 `uv run python -m unittest tests.test_subagent_roles.RoleParserTests -v`）

- [ ] **非法角色隔离（AC2）**：逐一加载缺字段、未知字段、非法 YAML、空正文、非法模型、非法权限、重复工具和不安全路径，观察对应角色不可调用且诊断包含来源与原因。（验证：运行 `uv run python -m unittest tests.test_subagent_roles.RoleParserTests -v`）

- [ ] **坏文件不阻断合法角色（AC2）**：同一来源同时放置一个合法和一个非法角色，观察合法角色仍能解析、刷新和运行。（验证：运行 `uv run python -m unittest tests.test_subagent_roles.RoleCatalogTests -v`）

- [ ] **角色正文生命周期（AC2）**：让定义式子 Agent 执行多个模型轮次，观察每轮请求使用同一固定角色 system prompt。（验证：运行 `uv run python -m unittest tests.test_subagent_integration.DefinedEndToEndTests -v`）

- [ ] **四层覆盖顺序（AC3）**：在插件、内置、用户和项目来源放置同名角色，观察项目定义生效；逐层移除后依次回退到用户、内置、插件。（验证：运行 `uv run python -m unittest tests.test_subagent_roles.RoleCatalogTests -v`）

- [ ] **覆盖不合并（AC3）**：让各来源的同名角色声明不同工具和模型，观察最终角色完全来自单一最高优先级文件，没有字段拼接。（验证：运行 `uv run python -m unittest tests.test_subagent_roles.RoleCatalogTests -v`）

- [ ] **同层冲突确定性（AC3）**：同一层放置两个同名角色并改变目录枚举顺序，观察角色被标为冲突而不是由最后遍历文件获胜。（验证：运行 `uv run python -m unittest tests.test_subagent_roles.RoleCatalogTests -v`）

- [ ] **覆盖可观测性（AC3）**：刷新角色目录后查看状态和诊断，观察生效来源、被覆盖定义和无效定义均可识别。（验证：运行 `uv run python -m unittest tests.test_subagent_roles.RoleCatalogTests tests.test_subagent_integration.SessionIntegrationTests -v`）

## 启动上下文与运行时隔离

- [x] **定义式空白历史（AC4）**：父对话包含多轮消息时启动定义式任务，观察子 Agent 首次请求不含任何父对话普通消息。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.DefinedRuntimeTests -v`）

- [ ] **定义式受控环境（AC4）**：观察定义式首请求只包含角色提示、项目根目录/平台/日期/项目类型等受控环境和本次任务，不含父临时 Hook prompt、激活 Skill 或父记忆内容。（验证：运行 `uv run python -m unittest tests.test_subagent_integration.DefinedEndToEndTests -v`）

- [ ] **角色运行设置生效（AC4）**：分别声明继承/别名模型、不同最大轮次、工具范围和权限模式，观察实际 Provider、终止轮次、可见工具及权限结果符合角色配置且不会放宽父权限。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.DefinedRuntimeTests tests.test_subagent_policy -v`）

- [ ] **父临时状态不泄漏（AC4、AC6）**：父 Agent 预先记录临时权限、Token 用量和文件读取状态后启动定义式任务，观察子运行时对应状态为空且父状态保持不变。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.DefinedRuntimeTests -v`）

- [x] **Fork 历史前缀（AC5）**：完成多轮父请求后启动 Fork，观察子 Agent 首次请求的 system prompt 与已完成消息前缀保持内容和顺序一致，子任务只追加在末尾。（验证：运行 `uv run python -m unittest tests.test_subagent_snapshots tests.test_subagent_runtime.ForkRuntimeTests -v`）

- [ ] **Fork 排除半成品（AC5）**：在父模型返回 Agent 工具调用时创建 Fork，观察当前未完成 assistant 响应、本次工具结果和 transient whisper 不在子历史中。（验证：运行 `uv run python -m unittest tests.test_subagent_snapshots -v`）

- [ ] **Fork 继承与收紧（AC5）**：观察 Fork 继承父 Provider、thinking、AgentMode 和父工具视图，同时移除委派工具并应用后台白名单。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.ForkRuntimeTests -v`）

- [ ] **Fork 缓存用量（AC5）**：fake Provider 返回缓存创建和缓存读取 Token，观察任务状态和最终通知准确记录对应值；不返回时显示零且任务仍成功。（验证：运行 `uv run python -m unittest tests.test_subagent_provider_pool.ProviderUsageTests tests.test_subagent_integration.ForkAndBackgroundEndToEndTests -v`）

- [ ] **无快照 Fork 拒绝（AC5）**：在尚未发生父 Provider 请求时启动 Fork，观察返回明确错误且没有任务进入队列。（验证：运行 `uv run python -m unittest tests.test_subagent_tool.CoordinatorTests -v`）

- [ ] **并发消息隔离（AC6）**：同时运行两个子 Agent，使其生成不同消息和轮次，观察各自历史、最终文本和轮次统计互不混合。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime -v`）

- [ ] **读取缓存隔离（AC6）**：两个任务读取同一文件，观察缓存对象与命中计数独立；修改文件后各任务都能检测失效并读取新内容。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.TaskScopedToolTests -v`）

- [ ] **权限与取消隔离（AC6）**：让一个任务被权限拒绝并取消，观察另一个任务和父 Agent 的临时权限、取消状态及执行不受影响。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime tests.test_subagent_tasks -v`）

- [ ] **基础设施共享（AC6）**：并发任务使用同一连接配置和文件系统，观察底层 Provider client 只创建一次、共享文件变化可见，同时任务用量与 Hook scope 独立。（验证：运行 `uv run python -m unittest tests.test_subagent_provider_pool.ProviderPoolTests tests.test_subagent_runtime -v`）

## 执行、权限与工具安全

- [ ] **模型停止即完成（AC7）**：fake 模型返回文本且不调用工具，观察任务进入 completed，结果、摘要和停止原因正确。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime -v`）

- [ ] **轮次上限（AC7）**：fake 模型持续调用工具超过角色上限，观察任务进入 limited，停止原因为 max iterations，已累计用量保留。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.AgentLoopExtensionTests -v`）

- [ ] **非交互权限拒绝（AC7）**：在 default undecided 和 strict deny 下请求工具，观察没有 TUI 确认、没有 HITL callback，模型收到“操作不可用”并可继续选择替代方案。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.AgentLoopExtensionTests -v`）

- [ ] **Provider 与工具失败终态（AC7）**：分别让 Provider 抛错、工具返回失败和 Runner 抛出内部异常，观察结果能区分工具反馈与任务失败，父会话继续工作。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime tests.test_subagent_integration.SecurityAndFailureEndToEndTests -v`）

- [ ] **取消响应（AC7）**：对 queued 和 running 任务请求取消，观察查询立即显示 cancel requested，任务随后进入 cancelled 且用量不被清零。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks -v`）

- [ ] **安全交集（AC8）**：组合父工具集、角色 allow/deny、固定禁止、配置追加禁止、后台 allow 和计划模式，观察最终工具恰好为各层安全交集。（验证：运行 `uv run python -m unittest tests.test_subagent_policy -v`）

- [ ] **黑名单优先（AC8）**：同一工具同时进入角色 allow 与 deny，观察工具不对模型可见也不可执行。（验证：运行 `uv run python -m unittest tests.test_subagent_policy -v`）

- [ ] **禁止直接和间接嵌套（AC8）**：父视图显式包含 `agent` 与 `load_skill`，观察所有子 Agent 视图都移除两者，角色配置不能恢复。（验证：运行 `uv run python -m unittest tests.test_subagent_policy tests.test_subagent_runtime.TaskScopedToolTests -v`）

- [ ] **伪造调用执行前拒绝（AC8）**：绕过模型可见 schema 直接提交被过滤工具名，观察真实工具实现从未被调用并返回安全拒绝。（验证：运行 `uv run python -m unittest tests.test_subagent_runtime.TaskScopedToolTests tests.test_subagent_integration.SecurityAndFailureEndToEndTests -v`）

## 前后台与任务管理

- [ ] **显式后台（AC9）**：定义式任务声明 background，观察调用立即返回 task ID，任务继续运行且父 Agent 可继续下一轮。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks tests.test_subagent_integration.ForkAndBackgroundEndToEndTests -v`）

- [ ] **超时自动后台（AC9）**：让前台任务超过配置阈值，观察同一任务自动脱离并返回 task ID，没有第二次 Runner 启动。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks -v`）

- [ ] **Ctrl+B 手动后台（AC9）**：前台任务运行时发送 fake `Ctrl+B`，观察等待立即结束、TUI 恢复输入，任务仍使用原 ID/Future 继续。（验证：运行 `uv run python -m unittest tests.test_subagent_tui.ForegroundControlTests tests.test_subagent_integration.ForkAndBackgroundEndToEndTests -v`）

- [ ] **转后台状态连续（AC9）**：在 detach 前后查询同一任务，观察消息、轮次、用量和已完成工具调用连续且没有重复执行。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks tests.test_subagent_integration.ForkAndBackgroundEndToEndTests -v`）

- [ ] **Fork 强制后台（AC9）**：提交 `type=fork, background=false`，观察立即返回原任务 ID、`forced_background=true` 和明确说明。（验证：运行 `uv run python -m unittest tests.test_subagent_tool.CoordinatorTests -v`）

- [ ] **全状态查询（AC10）**：对 queued、running、completed、limited、failed 和 cancelled 任务查询，观察父子关系、类型、角色、时间、停止原因、轮次和全部用量准确。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks -v`）

- [ ] **完整结果查询（AC10）**：查询内联和外置结果，观察获得完整可用内容或明确截断标记；查询行为不增加父对话消息。（验证：运行 `uv run python -m unittest tests.test_subagent_notifications tests.test_subagent_tui.AgentCommandTests -v`）

- [ ] **用户本地任务命令（AC10）**：执行 `/agent status`、`/agent result` 和 `/agent cancel`，观察命令直接操作任务管理器、不调用主模型且错误帮助稳定。（验证：运行 `uv run python -m unittest tests.test_subagent_tui.AgentCommandTests -v`）

- [ ] **未知与非法操作（AC10）**：对未知 ID 查询/取消、对终态任务重复取消，观察返回明确结果，不创建记录、不改变既有终态。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks tests.test_subagent_tool -v`）

- [ ] **结果存储安全（AC10、AC13）**：提交超出 inline 和最大上限的结果及恶意 task ID，观察外置、截断和路径拒绝符合配置，Session 关闭后临时目录清理。（验证：运行 `uv run python -m unittest tests.test_subagent_notifications -v`）

## 通知、Hook 与可观测性

- [ ] **单次结构化通知（AC11）**：后台任务完成并重复触发完成回调，观察父会话只收到一次 `<agent-notification>`。（验证：运行 `uv run python -m unittest tests.test_subagent_notifications tests.test_subagent_integration.SessionIntegrationTests -v`）

- [ ] **通知字段完整（AC11）**：观察通知包含 task ID、终态、摘要、停止原因、输入/输出/思考/缓存用量、轮次和结果查询提示。（验证：运行 `uv run python -m unittest tests.test_subagent_notifications -v`）

- [ ] **通知不携带完整结果（AC11）**：让任务产生明显超长输出，观察 TUI 通知和父消息历史只含有界摘要，完整输出仅通过 result 查询出现。（验证：运行 `uv run python -m unittest tests.test_subagent_integration.SessionIntegrationTests -v`）

- [ ] **关闭父会话不补发（AC11）**：父 Session 关闭时完成后台任务，观察结果被安全终结或取消，没有向新 Session 或已关闭 UI 投递通知。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks tests.test_subagent_integration.SessionIntegrationTests -v`）

- [ ] **TUI 与消息安全边界（AC11）**：后台 worker 完成时观察 UI 通过安全调度显示；父消息只在下一 Provider 请求前排空 inbox，不发生并发列表修改。（验证：运行 `uv run python -m unittest tests.test_subagent_tui tests.test_subagent_integration.SessionIntegrationTests -v`）

- [ ] **Agent 生命周期事件（AC12）**：运行完成、后台切换、失败和取消任务，观察 started、backgrounded 及对应唯一终态事件，并可用 task ID 关联。（验证：运行 `uv run python -m unittest tests.test_subagent_hooks -v`）

- [ ] **父子 Hook scope 隔离（AC12）**：父 Agent 和两个子 Agent 使用不同 session/turn/prompt state，观察 Hook 能区分 kind、parent ID、type 和 role，状态互不覆盖。（验证：运行 `uv run python -m unittest tests.test_subagent_hooks -v`）

- [ ] **权限与错误诊断（AC12）**：触发权限拒绝、Provider 错误、后台切换和完成，观察每类都产生包含任务身份的可读诊断。（验证：运行 `uv run python -m unittest tests.test_subagent_hooks tests.test_subagent_integration.SecurityAndFailureEndToEndTests -v`）

- [ ] **全通道脱敏（AC12）**：在 Provider 配置、工具参数、错误、结果和 Hook context 注入 fake API Key 与 Authorization，观察日志、状态、通知、摘要、结果诊断和 stderr 都不含原值。（验证：运行 `uv run python -m unittest tests.test_subagent_provider_pool tests.test_subagent_notifications tests.test_subagent_hooks tests.test_subagent_integration.SecurityAndFailureEndToEndTests -v`）

## 容量、可靠性与兼容性

- [ ] **容量内调度（AC13）**：将 worker 和 pending 设为小值，在容量内提交任务，观察任务按 queued/running 顺序执行且槽位在终态释放。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks -v`）

- [ ] **超量立即拒绝（AC13）**：填满 worker 与 pending 后继续提交，观察立即返回容量错误，没有悬空 TaskRecord、Future 或持续增长线程。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks -v`）

- [ ] **有界关闭（AC13）**：关闭含排队、运行和无响应任务的 Session，观察停止接收新任务、请求取消并在配置期限内返回。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks tests.test_subagent_integration.SessionIntegrationTests -v`）

- [ ] **关闭幂等与资源清理（AC13）**：重复关闭 Session，观察 Provider client、Hook runtime、MCP、结果目录和记忆调度器各自最多关闭一次，单个失败不阻止其余清理。（验证：运行 `uv run python -m unittest tests.test_subagent_provider_pool tests.test_subagent_tasks tests.test_subagent_integration.SessionIntegrationTests -v`）

- [ ] **单任务崩溃隔离（AC14）**：同时运行父 Agent、成功子任务和崩溃子任务，观察只有崩溃任务失败，其余流程继续。（验证：运行 `uv run python -m unittest tests.test_subagent_integration.SecurityAndFailureEndToEndTests -v`）

- [ ] **终态不可回退（AC14）**：对 completed、limited、failed 和 cancelled 任务模拟迟到/重复回调，观察首次终态、时间、结果和用量不被改写。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks -v`）

- [ ] **通知失败不改终态（AC14）**：让通知 inbox 或 UI callback 抛错，观察任务仍保留正确终态和完整结果，父 Session 可继续使用。（验证：运行 `uv run python -m unittest tests.test_subagent_tasks tests.test_subagent_integration.SecurityAndFailureEndToEndTests -v`）

- [ ] **现有 Agent 行为回归（AC15）**：不调用 `agent` 工具时运行普通对话、工具轮次、计划模式和上下文压缩，观察原有结果和事件语义不变。（验证：运行 `uv run python -m unittest tests.test_context tests.test_command_integration -v`）

- [ ] **Skill 与权限回归（AC15）**：运行共享/隔离 Skill 和现有权限规则，观察原语义、工具范围和 HITL 行为不变。（验证：运行 `uv run python -m unittest tests.test_skills_executor tests.test_skills_integration tests.test_permission_rules -v`）

- [ ] **Hook 占位兼容（AC15）**：加载并触发现有合法 `subagent` Hook action，观察仍只产生“不可执行”诊断，不创建 Agent 任务。（验证：运行 `uv run python -m unittest tests.test_hooks_actions tests.test_subagent_hooks -v`）

- [ ] **MCP 与会话日志回归（AC15）**：运行 MCP 注册/调用/关闭和会话恢复测试，观察外部工具及既有日志行为不变。（验证：运行 `uv run python -m unittest tests.test_mcp_unittest tests.test_memory -v`）

- [ ] **替代基础设施边界（AC16）**：分别注入 fake 结果存储或 fake 文件隔离适配器，观察 AgentTool 调用格式、定义式/Fork 式启动和任务查询调用方无需修改。（验证：运行 `uv run python -m unittest tests.test_subagent_integration.ExtensionBoundaryTests -v`）

## 编译、打包与测试

- [x] **Python 源码编译**：当前环境编译全部源码和测试，无语法或导入错误。（验证：运行 `uv run python -m compileall -q src tests`，预期退出码 0）

- [x] **子 Agent 专项测试**：角色、策略、快照、Provider、通知、任务、运行时、工具、Hook、TUI 和集成测试全部通过。（验证：运行 `uv run python -m unittest discover -s tests -p 'test_subagent_*.py' -v`）

- [x] **全项目回归**：现有 Commands、Context、Hooks、MCP、Memory、Permissions 和 Skills 测试全部通过，无线程、临时目录或连接泄漏警告。（验证：运行 `uv run python -m unittest discover -s tests -v`）

- [x] **内置角色打包**：构建 wheel 后观察 `general-purpose.md` 与 `explore.md` 均包含在包内，安装后的 RoleCatalog 可加载它们。（验证：运行 `uv build`，检查 wheel 内容并运行 `tests.test_subagent_roles.BuiltinRoleTests`）

- [x] **无真实外部依赖**：所有专项和端到端测试在无网络、无真实 API Key 条件下通过。（验证：使用 fake Provider/client 运行全部 `test_subagent_*`，确认没有外部连接）

## 端到端场景

- [ ] **场景 1：定义式只读调查（AC2、AC4、AC6、AC7）**：父对话包含敏感临时上下文 → 主 Agent 用内置 `explore` 启动定义式任务 → 子 Agent 只看到角色、受控环境和任务 → 使用只读工具完成 → 父对话收到有界结果且可按 ID 查询完整输出。（验证：运行 `tests.test_subagent_integration.DefinedEndToEndTests`）

- [ ] **场景 2：Fork 缓存与后台完成（AC5、AC9、AC11）**：父 Agent 完成多轮请求 → 启动 Fork 并声明前台 → 系统明确强制后台 → 首请求复用稳定前缀并记录缓存读取量 → 完成后只投递一次摘要通知。（验证：运行 `tests.test_subagent_integration.ForkAndBackgroundEndToEndTests`）

- [ ] **场景 3：前台手动切后台（AC9、AC10）**：定义式任务前台运行 → UI 显示 task ID → 用户按 `Ctrl+B` → 主对话立即恢复 → 任务继续并完成 → `/agent status` 与 `/agent result` 返回连续状态和完整结果。（验证：运行 `tests.test_subagent_tui` 与 `ForkAndBackgroundEndToEndTests`）

- [ ] **场景 4：权限与嵌套防护（AC7、AC8、AC12）**：角色尝试放宽父权限并调用禁止工具 → 最终权限被收紧 → `agent/load_skill` 不可见且伪造调用被拒绝 → 无人工询问 → Hook 和诊断记录脱敏拒绝原因。（验证：运行 `tests.test_subagent_integration.SecurityAndFailureEndToEndTests`）

- [ ] **场景 5：容量、故障与关闭（AC13、AC14、AC15）**：提交成功、崩溃、取消和超量任务 → 各任务进入正确终态且相互隔离 → 关闭 Session 在期限内回收任务与共享设施 → 重新运行普通 Agent、Skill、Hook 和 MCP 流程无回归。（验证：运行安全故障集成测试后执行全量 unittest）
