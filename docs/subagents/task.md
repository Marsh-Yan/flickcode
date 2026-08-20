# FlickCode 子 Agent 委派 Tasks

## 文件清单

### 新建源码

| 文件 | 职责 |
|---|---|
| `src/flickcode/subagents/__init__.py` | 导出子 Agent 公共模型与服务 |
| `src/flickcode/subagents/models.py` | 角色、请求、快照、任务、用量和通知模型 |
| `src/flickcode/subagents/roles.py` | 角色解析、发现、覆盖、刷新与校验 |
| `src/flickcode/subagents/policy.py` | 工具、权限和模型解析策略 |
| `src/flickcode/subagents/snapshots.py` | 父请求不可变快照与最近快照存储 |
| `src/flickcode/subagents/provider_pool.py` | 共享底层 Provider 客户端池 |
| `src/flickcode/subagents/notifications.py` | 完成通知收件箱与摘要序列化 |
| `src/flickcode/subagents/result_store.py` | 会话期临时完整结果存储 |
| `src/flickcode/subagents/foreground.py` | 前台等待、detach 信号和输入监视端口 |
| `src/flickcode/subagents/runtime.py` | 任务级工具视图、运行时工厂与 Runner |
| `src/flickcode/subagents/tasks.py` | 有界工作池、状态机、查询、取消和关闭 |
| `src/flickcode/subagents/coordinator.py` | Agent 工具操作编排与两类启动规格构造 |
| `src/flickcode/subagents/tool.py` | 稳定的 `agent` 工具 schema 与执行入口 |
| `src/flickcode/subagents/builtins/general-purpose.md` | 通用内置角色 |
| `src/flickcode/subagents/builtins/explore.md` | 只读探索内置角色 |
| `src/flickcode/hooks/scope.py` | 共享 Hook runtime 的隔离作用域 |

### 修改源码

| 文件 | 改动 |
|---|---|
| `src/flickcode/config.py` | 加载并校验 `SubAgentConfig` |
| `src/flickcode/agent.py` | 请求快照、取消、非交互权限、缓存用量和 Agent 元数据 |
| `src/flickcode/session.py` | 组装子系统、注册工具、刷新、通知、状态和关闭 |
| `src/flickcode/tui.py` | `Ctrl+B`、后台通知和本地任务命令适配 |
| `src/flickcode/renderer.py` | 子任务运行与完成提示 |
| `src/flickcode/tools/__init__.py` | 保持核心工具工厂兼容并导出 AgentTool 接入点 |
| `src/flickcode/providers/base.py` | 标准化缓存 Token 用量字段 |
| `src/flickcode/providers/anthropic.py` | 注入共享 client，透传缓存用量 |
| `src/flickcode/providers/openai.py` | 注入共享 client，透传可用缓存用量 |
| `src/flickcode/providers/__init__.py` | 支持由共享 client 创建 Provider wrapper |
| `src/flickcode/hooks/models.py` | Agent 元数据和生命周期事件模型 |
| `src/flickcode/hooks/events.py` | Agent event schema 和公共上下文 |
| `src/flickcode/hooks/engine.py` | 共享 runtime 与隔离 scope 工厂 |
| `src/flickcode/commands/builtin.py` | `/agent status|result|cancel` |
| `pyproject.toml` | 打包内置角色 Markdown |
| `README.md` | 配置、角色、工具和命令文档 |

### 新建测试与 fixture

| 文件 | 覆盖范围 |
|---|---|
| `tests/test_subagent_roles.py` | 角色解析、来源覆盖、刷新和内置角色 |
| `tests/test_subagent_policy.py` | 工具交集、禁止嵌套、权限和模型解析 |
| `tests/test_subagent_snapshots.py` | 请求快照、深复制和 Fork 前缀 |
| `tests/test_subagent_provider_pool.py` | 客户端共享、模型隔离、用量和关闭 |
| `tests/test_subagent_notifications.py` | 通知去重、序列化、结果存储和脱敏 |
| `tests/test_subagent_tasks.py` | 状态机、容量、等待、取消和关闭 |
| `tests/test_subagent_runtime.py` | 定义式、Fork 式、隔离缓存和 Runner |
| `tests/test_subagent_tool.py` | 固定 schema、参数校验和操作分流 |
| `tests/test_subagent_hooks.py` | Hook scope、Agent 元数据和生命周期 |
| `tests/test_subagent_tui.py` | `Ctrl+B`、命令和异步显示适配 |
| `tests/test_subagent_integration.py` | Session 集成和端到端场景 |
| `tests/fixtures/subagents/**` | 合法、非法及四层同名角色 fixture |

## T1：建立子 Agent 公共枚举

**文件：** `src/flickcode/subagents/__init__.py`、`src/flickcode/subagents/models.py`

**依赖：** 无

**步骤：**
1. 定义 `AgentRoleSource`、`AgentModelAlias`、`AgentPermissionMode`、`AgentToolOperation` 和 `AgentInvocationType`。
2. 固定枚举序列化值，与 plan 中的 YAML 和工具参数一致。
3. 在包入口导出这些枚举，不导入 Session 或 TUI。

**验证：** 运行 `uv run python -c "from flickcode.subagents import AgentInvocationType, AgentRoleSource; print(AgentInvocationType.FORK.value, AgentRoleSource.PROJECT.value)"`；预期输出 `fork project`。

## T2：定义角色、请求、任务和通知模型

**文件：** `src/flickcode/subagents/models.py`

**依赖：** T1

**步骤：**
1. 定义角色、目录快照、诊断、工具请求/响应、父请求快照和启动规格 dataclass。
2. 定义 `AgentUsage`、任务状态、任务记录、冻结快照、结果视图和通知模型。
3. 定义合法状态迁移表和终态集合；拒绝终态回退。
4. 确保公开快照不暴露 Future、锁、取消令牌或 Provider 凭据。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/models.py`；预期编译通过，并用短脚本确认 `COMPLETED → RUNNING` 不在合法迁移表中。

## T3：实现 SubAgentConfig 解析

**文件：** `src/flickcode/config.py`

**依赖：** T1

**步骤：**
1. 增加 `SubAgentConfig`，包含工作池、等待、结果、后台工具、追加禁止项、插件目录和模型别名字段。
2. 实现 `subagents` YAML 的严格未知键、类型、正数和路径去重校验。
3. 校验模型别名只使用 `haiku/sonnet/opus`，目标必须引用已有 Provider 名称。
4. 把配置加入 `Config`，保持未配置时现有启动行为不变。

**验证：** 运行 `uv run python -m unittest tests.test_context tests.test_memory tests.test_mcp_unittest -v`；预期现有配置调用路径全部通过。

## T4：补充子 Agent 配置测试

**文件：** `tests/test_subagent_integration.py`

**依赖：** T3

**步骤：**
1. 覆盖默认值和完整合法配置。
2. 覆盖未知键、零/负边界、重复插件目录、未知 Provider 别名和非法工具列表。
3. 断言异常只包含字段名，不包含 API Key。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_integration.SubAgentConfigTests -v`；预期所有配置用例通过。

## T5：实现角色 Markdown 解析器

**文件：** `src/flickcode/subagents/roles.py`

**依赖：** T1、T2

**步骤：**
1. 严格拆分 YAML frontmatter 与非空正文。
2. 校验名称、单行说明、`tools.allow/deny`、模型、最大轮次和权限模式。
3. 拒绝符号链接、不安全路径、未知字段、重复工具和非法枚举值。
4. 计算原始文件指纹并构造冻结角色定义。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/roles.py`；预期编译通过。

## T6：建立角色解析 fixture 和单元测试

**文件：** `tests/fixtures/subagents/valid/**`、`tests/fixtures/subagents/invalid/**`、`tests/test_subagent_roles.py`

**依赖：** T5

**步骤：**
1. 创建完整合法角色和每类 frontmatter 错误 fixture。
2. 测试正文、来源、路径、指纹和工具集合解析正确。
3. 测试一个无效文件不影响另一个合法文件的独立解析。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_roles.RoleParserTests -v`；预期合法 fixture 全部解析，无效 fixture 返回包含路径和原因的错误。

## T7：实现四层角色目录与覆盖

**文件：** `src/flickcode/subagents/roles.py`

**依赖：** T5

**步骤：**
1. 实现 project、user、builtin 和有序 plugin roots 的确定性发现。
2. 按项目、用户、内置、插件选择唯一生效定义，低层定义完整进入 shadowed。
3. 同一层同名定义产生冲突诊断且不得用遍历顺序决定胜者。
4. 实现基于签名缓存的 `prepare_refresh()` 与原子 `commit()`。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/roles.py`；预期编译通过。

## T8：测试角色来源优先级和事务刷新

**文件：** `tests/fixtures/subagents/project/**`、`tests/fixtures/subagents/user/**`、`tests/fixtures/subagents/builtin/**`、`tests/fixtures/subagents/plugin/**`、`tests/test_subagent_roles.py`

**依赖：** T7

**步骤：**
1. 为四层创建同名但内容不同的角色。
2. 逐层移除高优先级文件，断言回退顺序和非合并语义。
3. 覆盖同层冲突、generation 变化、无变化刷新和 stale candidate。
4. 覆盖刷新出现坏文件时上一份有效快照仍可用。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_roles.RoleCatalogTests -v`；预期覆盖、冲突和刷新用例通过。

## T9：实现角色二次校验和模型解析

**文件：** `src/flickcode/subagents/roles.py`、`src/flickcode/subagents/policy.py`

**依赖：** T3、T7

**步骤：**
1. 对生效角色的 allow 工具执行真实 Registry 校验；未知 allow 使角色无效，未知 deny 只警告。
2. 把 `inherit` 解析为父 Provider，把其余别名解析到配置命名的 Provider。
3. 角色模型别名未配置时返回可诊断调用错误，不猜测模型字符串。
4. 确保诊断脱敏 Provider 凭据和 base URL 中的 secret。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_roles.RoleValidatorTests tests.test_subagent_policy.ModelResolverTests -v`；预期未知工具与模型别名边界通过。

## T10：新增并打包内置角色

**文件：** `src/flickcode/subagents/builtins/general-purpose.md`、`src/flickcode/subagents/builtins/explore.md`、`pyproject.toml`、`tests/test_subagent_roles.py`

**依赖：** T6、T9

**步骤：**
1. 编写继承模型和权限的通用角色，只允许六个核心工具。
2. 编写 strict、只读的 explore 角色。
3. 将内置角色 Markdown 加入 wheel artifacts。
4. 测试两个角色可解析，且均不包含委派工具。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_roles.BuiltinRoleTests -v`；预期两个内置角色有效且工具边界正确。

## T11：实现多层工具过滤策略

**文件：** `src/flickcode/subagents/policy.py`

**依赖：** T2

**步骤：**
1. 从父 `ToolRegistryView` 依次应用固定禁止、配置追加禁止、角色 allow、角色 deny、后台 allow 和 AgentMode 限制。
2. 固定禁止集包含 `agent`、`load_skill`，且不能被任何 allow 恢复。
3. 空后台 allow 表示不额外限制；非空时取交集。
4. 返回新的不可变视图，不修改父 Registry 或父视图。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/policy.py`；预期编译通过。

## T12：实现权限收紧策略

**文件：** `src/flickcode/subagents/policy.py`

**依赖：** T1

**步骤：**
1. 定义 `strict > default > permissive` 的明确顺序。
2. `inherit` 返回父模式，其余选择父模式与角色模式中更严格者。
3. 拒绝未知值，保证角色不能放宽父权限。

**验证：** 运行短脚本遍历所有父模式和角色模式组合；预期没有任何组合比父模式更宽松。

## T13：测试工具与权限策略

**文件：** `tests/test_subagent_policy.py`

**依赖：** T11、T12

**步骤：**
1. 覆盖 allow/deny 冲突、固定禁止、后台交集和计划模式只读限制。
2. 伪造包含 `agent`、`load_skill` 的父视图，断言子视图始终移除。
3. 覆盖权限矩阵和父视图未被修改。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_policy -v`；预期全部策略测试通过。

## T14：实现父请求快照存储

**文件：** `src/flickcode/subagents/snapshots.py`

**依赖：** T2

**步骤：**
1. 实现消息深复制和不可变 `ParentRequestSnapshot` 构造。
2. 保存实际 system prompt、工具视图、模式、Provider、thinking、会话和轮次。
3. 实现线程安全的最近快照写入、读取和 reset。
4. 确保读取方不能反向修改存储内容。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/snapshots.py`；预期编译通过。

## T15：在 AgentLoop 记录真实请求快照

**文件：** `src/flickcode/agent.py`

**依赖：** T14

**步骤：**
1. 为 `AgentLoop` 增加可选 `request_snapshot_callback`。
2. 在上下文准备完成、Provider 调用开始前，以实际持久消息、system prompt 和 `ToolRegistryView` 建立快照。
3. 不把 transient whisper 或尚未完成响应写入快照。
4. 回调失败只产生诊断，不阻止正常父请求。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/agent.py` 和 `uv run python -m unittest tests.test_context tests.test_skills_executor -v`；预期编译及现有 Agent Loop 调用路径通过。

## T16：测试快照深复制与 Fork 前缀

**文件：** `tests/test_subagent_snapshots.py`

**依赖：** T15

**步骤：**
1. 用 fake Provider 捕获真实请求前的回调数据。
2. 断言 system、消息顺序和工具顺序与 Provider 请求一致。
3. 修改父消息和读取结果，断言存储快照不变。
4. 断言当前 assistant 半成品、transient whisper 和本次工具结果不在快照中。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_snapshots -v`；预期快照和缓存前缀测试通过。

## T17：贯通 Provider 缓存 Token 用量

**文件：** `src/flickcode/providers/base.py`、`src/flickcode/providers/anthropic.py`、`src/flickcode/providers/openai.py`、`src/flickcode/agent.py`

**依赖：** T2

**步骤：**
1. 统一 done usage 中的 `cache_creation_input_tokens` 和 `cache_read_input_tokens`。
2. Anthropic 透传已有字段；OpenAI 在响应提供 cached tokens 时映射为 cache read。
3. 扩展 `StreamCollector`、`AgentResult` 和 done/usage 事件累计字段。
4. Provider 未提供字段时保持零，现有 usage 字段不变。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/providers src/flickcode/agent.py` 和 `uv run python -m unittest tests.test_context -v`；预期 Provider/Agent 编译及现有上下文调用路径通过。

## T18：测试缓存用量累计

**文件：** `tests/test_subagent_provider_pool.py`

**依赖：** T17

**步骤：**
1. 构造包含缓存创建/读取字段的 Anthropic fake stream。
2. 构造包含和不包含 cached token details 的 OpenAI fake stream。
3. 验证多轮累计及缺省零值。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_provider_pool.ProviderUsageTests -v`；预期缓存用量结果准确。

## T19：实现 ProviderPool

**文件：** `src/flickcode/subagents/provider_pool.py`、`src/flickcode/providers/__init__.py`、`src/flickcode/providers/anthropic.py`、`src/flickcode/providers/openai.py`

**依赖：** T3

**步骤：**
1. 允许 Provider wrapper 接收已创建的底层 client。
2. 按协议、base URL 和凭据身份缓存 client，不把密钥放入日志或 repr。
3. 每次请求返回持有独立 `ProviderConfig` 的 wrapper。
4. 实现幂等 close，单个 client 关闭失败不阻止其他 client。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/providers src/flickcode/subagents/provider_pool.py`；预期编译通过。

## T20：测试 Provider 客户端共享与隔离

**文件：** `tests/test_subagent_provider_pool.py`

**依赖：** T19

**步骤：**
1. 相同连接配置不同模型应共享底层 client，但 wrapper 配置独立。
2. 不同协议、URL 或凭据应创建不同 client。
3. 测试并发获取、幂等关闭和异常隔离。
4. 扫描诊断，确认不含 fake API Key。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_provider_pool.ProviderPoolTests -v`；预期共享、隔离与关闭测试通过。

## T21：扩展 Hook Agent 元数据和事件 schema

**文件：** `src/flickcode/hooks/models.py`、`src/flickcode/hooks/events.py`

**依赖：** T2

**步骤：**
1. 增加 `AgentHookMetadata` 和五个 Agent 生命周期事件名。
2. 在公共 Hook context 中加入固定 `agent` 节点，父 Agent 使用空任务字段。
3. 为 started/backgrounded/completed/failed/cancelled 定义可校验 schema。
4. 保持现有事件字段和 `subagent` action 枚举不变。

**验证：** 运行 `uv run python -m unittest tests.test_hooks_loader tests.test_hooks_engine -v`；预期既有 Hook 测试通过。

## T22：拆分共享 Hook runtime 与隔离 HookScope

**文件：** `src/flickcode/hooks/scope.py`、`src/flickcode/hooks/engine.py`

**依赖：** T21

**步骤：**
1. 把规则快照、动作执行器和后台资源保留在共享 runtime。
2. 将 session、turn、prompt state 和 Agent 元数据移入 `HookScope`。
3. 让父 Session 使用默认 scope，子运行时通过工厂创建新 scope。
4. 保持 `HookEngine` 现有公共调用兼容，并确保 scope close 不关闭共享 runtime。

**验证：** 运行 `uv run python -m unittest tests.test_hooks_engine tests.test_hooks_integration -v`；预期现有 Hook 行为无回归。

## T23：测试 Hook scope 隔离和 Agent 生命周期

**文件：** `tests/test_subagent_hooks.py`

**依赖：** T22

**步骤：**
1. 创建父 scope 和两个子 scope，设置不同 session、turn 与 prompt。
2. 断言规则/执行设施共享，可变状态互不影响。
3. 覆盖五个生命周期事件、元数据关联和重复终态事件。
4. 确认原 `subagent` Hook action仍报告不可执行。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_hooks -v`；预期 scope 与生命周期测试通过。

## T24：为 AgentLoop 增加协作式取消

**文件：** `src/flickcode/agent.py`、`src/flickcode/subagents/foreground.py`

**依赖：** T2

**步骤：**
1. 实现线程安全 `CancellationToken`。
2. 为 AgentLoop 增加可选取消检查，并覆盖轮次、流事件、工具预检和工具批次边界。
3. 取消时产生 `USER_CANCELLED` done 事件并保留累计用量。
4. 默认未传取消检查时保持现有行为。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/agent.py` 和 `uv run python -m unittest tests.test_context tests.test_skills_executor -v`；预期编译及现有 Agent Loop 调用路径通过。

## T25：实现子 Agent 非交互权限反馈

**文件：** `src/flickcode/agent.py`

**依赖：** T24

**步骤：**
1. 增加默认关闭的 `non_interactive_permissions` 选项。
2. 子模式下将 undecided 和 deny 转为不可用工具结果，不调用 HITL callback。
3. 子模式错误文本要求模型改用其他方案，不提示向用户申请权限。
4. 父模式继续使用现有提示和回调。

**验证：** 运行 `uv run python -m unittest tests.test_permission_rules tests.test_skills_executor -v`；预期父权限与现有隔离 Skill 行为不变。

## T26：测试取消、轮次限制和非交互权限

**文件：** `tests/test_subagent_runtime.py`

**依赖：** T17、T24、T25

**步骤：**
1. 在各取消检查点触发 token，断言停止原因和用量。
2. 模拟持续工具调用达到最大轮次，断言 `MAX_ITERATIONS`。
3. 模拟 default undecided 和 strict deny，断言不调用用户 callback。
4. 验证 Provider 失败和未知工具停止原因保持可区分。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_runtime.AgentLoopExtensionTests -v`；预期取消和非交互测试通过。

## T27：实现通知收件箱

**文件：** `src/flickcode/subagents/notifications.py`

**依赖：** T2

**步骤：**
1. 实现线程安全 publish、peek/drain 和关闭状态。
2. 以 task ID 去重，重复回调不得重复排队。
3. 实现固定 `<agent-notification>` 摘要序列化，包含状态、停止原因、用量和查询提示。
4. 对摘要和错误执行长度限制与 secret 替换。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/notifications.py`；预期编译通过。

## T28：实现会话期完整结果存储

**文件：** `src/flickcode/subagents/result_store.py`

**依赖：** T3

**步骤：**
1. 使用受管临时目录保存超出 inline 上限的 UTF-8 结果。
2. 校验任务 ID，防止路径逃逸和符号链接目标。
3. 超出最大字符数时截断并附加明确标记。
4. 实现幂等关闭和目录清理；关闭后拒绝新写入。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/result_store.py`；预期编译通过。

## T29：测试通知去重、脱敏和结果边界

**文件：** `tests/test_subagent_notifications.py`

**依赖：** T27、T28

**步骤：**
1. 并发发布相同与不同 task ID，断言每个任务仅一条通知。
2. 断言序列化消息不含完整结果或 fake secret。
3. 覆盖 inline、外置、最大截断、未知 ID、关闭和路径逃逸。
4. 断言关闭后临时结果目录已清理。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_notifications -v`；预期通知和结果存储测试通过。

## T30：实现 ForegroundControl

**文件：** `src/flickcode/subagents/foreground.py`

**依赖：** T24

**步骤：**
1. 实现单个活动前台 task ID 的 begin/end。
2. 实现线程安全 detach 请求和一次性消费。
3. 拒绝未知任务和关闭后的信号。
4. 提供可替换时钟或轮询间隔，便于确定性测试。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/foreground.py`；预期编译通过。

## T31：实现 TUI 前台输入监视端口

**文件：** `src/flickcode/subagents/foreground.py`、`src/flickcode/tui.py`

**依赖：** T30

**步骤：**
1. 定义 `ForegroundInputMonitor` 端口和 no-op 管道实现。
2. 在交互 TUI 前台等待期间监听 `Ctrl+B` 并请求 detach。
3. 等待结束后释放输入监听，不与正常 PromptSession 同时读取 stdin。
4. 终端监听失败时记录诊断并继续依靠自动后台，不阻塞任务。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/tui.py src/flickcode/subagents/foreground.py`；预期编译通过。

## T32：测试前台 detach 控制

**文件：** `tests/test_subagent_tui.py`

**依赖：** T31

**步骤：**
1. 用 fake monitor 发送 `Ctrl+B`，断言活动 task ID 收到 detach。
2. 覆盖非活动任务、重复按键、监听异常和管道 no-op。
3. 断言监听器在完成、超时和异常后都被关闭。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_tui.ForegroundControlTests -v`；预期全部前台控制测试通过。

## T33：实现任务级读取缓存和工具视图

**文件：** `src/flickcode/subagents/runtime.py`

**依赖：** T11

**步骤：**
1. 实现以规范化路径、mtime 和大小为有效性键的任务级读取缓存。
2. 为 `read_file` 创建任务绑定包装器，其他无状态工具共享实现。
3. MCP 调用共享连接但不缓存结果。
4. 在执行前再次检查最终视图，拒绝伪造的已过滤工具调用。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/runtime.py`；预期编译通过。

## T34：测试读取缓存隔离和工具执行防线

**文件：** `tests/test_subagent_runtime.py`

**依赖：** T33

**步骤：**
1. 两个任务读取同一文件，断言缓存对象和命中计数独立。
2. 修改文件 mtime/大小后，断言旧缓存失效。
3. 伪造 `agent`、`load_skill` 和角色禁止工具调用，断言执行前拒绝。
4. 验证父工具实例和 Registry 未被修改。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_runtime.TaskScopedToolTests -v`；预期缓存和双层过滤测试通过。

## T35：实现定义式 ChildRuntimeFactory

**文件：** `src/flickcode/subagents/runtime.py`

**依赖：** T9、T12、T19、T22、T33

**步骤：**
1. 从空消息列表、角色正文、受控项目元数据和任务消息构造定义式运行时。
2. 解析 Provider、工具、权限和最大轮次。
3. 创建独立 ContextManager、PermissionEngine、HookScope、读取缓存、用量和取消令牌。
4. 明确排除父消息、临时提示、激活 Skill、父权限记忆和父 Token 状态。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_runtime.DefinedRuntimeTests -v`；预期定义式上下文和隔离断言通过。

## T36：实现 Fork 式 ChildRuntimeFactory

**文件：** `src/flickcode/subagents/runtime.py`

**依赖：** T13、T16、T19、T22、T33

**步骤：**
1. 深复制最近父请求快照消息并在末尾追加子任务。
2. 复用父 system prompt、Provider、thinking、模式和最大轮次默认值。
3. 对父工具视图应用固定禁止和后台白名单。
4. 没有快照时返回明确错误，不创建任务运行时。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_runtime.ForkRuntimeTests -v`；预期 Fork 前缀、继承和安全收紧测试通过。

## T37：实现 SubAgentRunner

**文件：** `src/flickcode/subagents/runtime.py`

**依赖：** T26、T35、T36

**步骤：**
1. 用任务专属依赖构造 AgentLoop，并设置非交互权限和取消检查。
2. 消费事件，累计最终文本、轮次、各类 Token、错误和停止原因。
3. 将 completed、max iterations、provider error 和 cancelled 映射到明确执行结果。
4. 捕获所有未处理异常并生成脱敏失败结果。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/runtime.py`；预期编译通过。

## T38：测试 Runner 终态与运行时隔离

**文件：** `tests/test_subagent_runtime.py`

**依赖：** T37

**步骤：**
1. 用 fake Provider 覆盖正常完成、轮次上限、Provider 失败、工具失败和取消。
2. 并发运行两个 runtime，断言消息、权限、缓存、用量和 Hook scope 互不影响。
3. 断言共享 Provider client、文件系统和无状态工具实现。
4. 扫描错误和摘要，确认不含凭据。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_runtime -v`；预期运行时全部测试通过。

## T39：实现任务管理器记录与有界提交

**文件：** `src/flickcode/subagents/tasks.py`

**依赖：** T2、T37

**步骤：**
1. 生成唯一、可校验的任务 ID，并建立 QUEUED 记录。
2. 用工作线程数加 pending 信号量限制容量。
3. worker 开始时原子迁移到 RUNNING；关闭后拒绝提交。
4. 容量耗尽时返回明确拒绝，不创建悬空记录或 Future。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/tasks.py`；预期编译通过。

## T40：实现终态提交、结果和通知

**文件：** `src/flickcode/subagents/tasks.py`

**依赖：** T27、T28、T39

**步骤：**
1. 将 Runner 结果映射为 COMPLETED、LIMITED、FAILED 或 CANCELLED。
2. 在锁内只提交一次终态、时间、用量、摘要、结果和错误。
3. 使用 ResultStore 处理 inline、外置和截断。
4. 仅后台任务发布通知；通知失败只记录诊断，不改变任务终态。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/tasks.py`；预期编译通过。

## T41：实现查询、取消、等待和 detach

**文件：** `src/flickcode/subagents/tasks.py`

**依赖：** T30、T40

**步骤：**
1. 实现冻结 `status()` 和不修改父消息的 `result()`。
2. `cancel()` 设置令牌；QUEUED 可直接取消，RUNNING 等 worker 观察。
3. `wait_or_detach()` 轮询 Future、超时、ForegroundControl 和关闭状态。
4. 转后台时只更新 background 标记并发出 lifecycle 事件，不更换任务 ID 或 Future。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/tasks.py`；预期编译通过。

## T42：实现任务管理器有界关闭

**文件：** `src/flickcode/subagents/tasks.py`

**依赖：** T41

**步骤：**
1. 原子停止接收新任务。
2. 取消排队和运行任务，并在配置期限内等待。
3. 超时后不无限阻塞；释放容量槽并保留诊断。
4. 关闭操作幂等，单个 Future 异常不阻止其他清理。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/tasks.py`；预期编译通过。

## T43：测试任务状态机、容量、取消和关闭

**文件：** `tests/test_subagent_tasks.py`

**依赖：** T42

**步骤：**
1. 覆盖所有合法状态迁移和非法终态回退。
2. 用可控 runner 阻塞 worker，验证并发、pending 和超量拒绝。
3. 覆盖 inline/外置结果、通知失败、重复完成和 Future 异常。
4. 覆盖显式后台、超时后台、detach、取消和有界关闭，断言 task ID 和用量连续。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_tasks -v`；预期任务管理器测试全部通过且无残留线程警告。

## T44：实现定义式启动协调

**文件：** `src/flickcode/subagents/coordinator.py`

**依赖：** T9、T13、T35、T43

**步骤：**
1. 严格校验 `start + defined` 的 task、role 和 background 参数。
2. 解析角色、Provider、工具与权限并构造 LaunchSpec。
3. 提交任务；显式后台立即返回，前台调用 `wait_or_detach()`。
4. 返回固定响应结构，前台完成也只包含有界摘要。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/coordinator.py`；预期编译通过。

## T45：实现 Fork、查询和取消协调

**文件：** `src/flickcode/subagents/coordinator.py`

**依赖：** T36、T43、T44

**步骤：**
1. 严格校验 Fork 禁止 role，并读取最近父请求快照。
2. 强制 Fork 后台，显式前台请求返回 `forced_background=true`。
3. 分流 status、result 和 cancel，只接受 task ID。
4. 统一未知任务、非法终态操作、容量耗尽和关闭错误格式。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/coordinator.py`；预期编译通过。

## T46：测试协调器两类路径和操作矩阵

**文件：** `tests/test_subagent_tool.py`

**依赖：** T45

**步骤：**
1. 覆盖 defined/fork 的所有合法与非法字段组合。
2. 断言 Fork 强制后台、定义式三种后台进入方式和 ID 连续。
3. 覆盖 status/result/cancel、未知任务和缺少快照。
4. 断言角色刷新不会改变协调入口结构。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_tool.CoordinatorTests -v`；预期操作矩阵全部通过。

## T47：实现稳定 AgentTool

**文件：** `src/flickcode/subagents/tool.py`、`src/flickcode/subagents/__init__.py`

**依赖：** T45

**步骤：**
1. 定义固定 `agent` ToolSpec 和完整 object input schema。
2. schema 包含 operation、type、task、role、background 和 task_id，不枚举动态角色名。
3. 将执行参数交给 Coordinator，并把响应稳定序列化为 ToolResult。
4. 绑定前拒绝调用，避免空 coordinator 产生异常。

**验证：** 运行 `uv run python -m compileall -q src/flickcode/subagents/tool.py`；预期编译通过。

## T48：测试 AgentTool schema 稳定性与执行分流

**文件：** `tests/test_subagent_tool.py`

**依赖：** T47

**步骤：**
1. 对比角色目录为空、增加、删除和覆盖后的 ToolSpec 深拷贝。
2. 验证 Anthropic/OpenAI formatter 均保留完整固定 schema。
3. 覆盖未绑定、协调成功、协调错误和异常脱敏。
4. 断言工具名始终只有 `agent`，不生成每角色工具。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_tool.AgentToolTests -v`；预期 schema 与执行测试通过。

## T49：在 Session 中组装子 Agent 子系统

**文件：** `src/flickcode/session.py`、`src/flickcode/tools/__init__.py`

**依赖：** T10、T20、T23、T29、T43、T47

**步骤：**
1. 按依赖顺序构造 ProviderPool、角色目录、快照存储、通知、结果存储、任务管理器和协调器。
2. 注册并绑定唯一 AgentTool；把它纳入主 Registry，但子策略固定过滤。
3. 提供角色安全刷新，失败保留旧快照并记录诊断。
4. 把当前 Session、Provider、权限、工具和 Hook scope provider 注入协调器。

**验证：** 运行 `uv run python -m unittest tests.test_command_integration tests.test_memory tests.test_skills_integration tests.test_mcp_unittest -v`；预期现有 Session、Registry、Skill 和 MCP 集成路径通过。

## T50：接入快照、通知、状态和关闭

**文件：** `src/flickcode/session.py`

**依赖：** T15、T27、T42、T49

**步骤：**
1. 主 AgentLoop 使用请求快照回调。
2. 在 Provider 请求安全边界排空通知并追加结构化摘要消息；完整结果不追加。
3. 扩展 status snapshot，加入角色 generation、任务状态计数和安全诊断。
4. 按 plan 顺序实现有界 close，并使 reset/resume 清理当前会话任务与快照。

**验证：** 运行 `uv run python -m unittest tests.test_memory tests.test_command_integration tests.test_skills_integration -v`；预期既有会话、恢复和命令集成测试通过。

## T51：新增 `/agent` 本地命令

**文件：** `src/flickcode/commands/builtin.py`、`tests/test_subagent_tui.py`

**依赖：** T41、T50

**步骤：**
1. 注册 `/agent status|result|cancel <task-id>`。
2. 解析子命令和 task ID，直接调用 Session 任务接口。
3. 完整结果只交给 UI 显示，不调用 `send_user_message()`，不追加主历史。
4. 对未知子命令、缺 ID 和任务错误给出稳定帮助。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_tui.AgentCommandTests tests.test_commands -v`；预期本地命令和既有命令测试通过。

## T52：接入 TUI 运行提示和异步完成显示

**文件：** `src/flickcode/tui.py`、`src/flickcode/renderer.py`

**依赖：** T31、T50、T51

**步骤：**
1. 前台任务开始时显示 task ID 和 `Ctrl+B` 提示。
2. 将输入监视器生命周期绑定到当前前台等待。
3. 使用 TUI 安全调度显示后台完成摘要，不由 worker 直接写 Renderer。
4. 管道模式以安全 stdout/stderr 显示通知，不启用快捷键或交互询问。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_tui -v`；预期 TUI、管道和 Renderer 适配测试通过。

## T53：测试 Session 组装、通知与关闭集成

**文件：** `tests/test_subagent_integration.py`

**依赖：** T52

**步骤：**
1. 用 fake Provider、临时角色目录和 fake Hook 构造完整 Session。
2. 断言 AgentTool 只注册一次，角色刷新不改变工具列表。
3. 让后台任务完成，断言 UI 即时摘要和下一请求结构化消息各一次，完整结果不在历史中。
4. 覆盖 reset、resume、close、重复 close 和关闭期间提交。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_integration.SessionIntegrationTests -v`；预期 Session 生命周期测试通过。

## T54：实现定义式端到端测试

**文件：** `tests/test_subagent_integration.py`

**依赖：** T53

**步骤：**
1. 父对话写入多轮历史、临时提示和权限记忆。
2. 通过真实 AgentTool 启动 `explore` 定义式任务。
3. fake Provider 捕获首请求，断言只有角色、受控环境和子任务。
4. 断言工具、模型、权限、最大轮次、摘要、结果查询和用量正确。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_integration.DefinedEndToEndTests -v`；预期定义式完整场景通过且不访问网络。

## T55：实现 Fork 与三种后台方式端到端测试

**文件：** `tests/test_subagent_integration.py`

**依赖：** T53

**步骤：**
1. 运行一次父请求并记录真实快照，再通过 AgentTool 启动 Fork。
2. 断言首请求消息/system 前缀稳定、子任务追加、工具安全收紧和缓存用量记录。
3. 分别验证显式后台、前台超时和 fake `Ctrl+B` detach。
4. 断言三条路径任务不重启、ID/消息/轮次/用量连续，Fork 强制后台有明确标记。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_integration.ForkAndBackgroundEndToEndTests -v`；预期 Fork 和后台完整场景通过。

## T56：实现安全、故障与 Hook 端到端测试

**文件：** `tests/test_subagent_integration.py`、`tests/test_subagent_hooks.py`

**依赖：** T53

**步骤：**
1. 并发运行成功、Provider 失败、权限拒绝和取消任务，断言故障隔离。
2. 伪造嵌套委派调用，断言模型视图和执行前两层均拒绝。
3. 覆盖容量耗尽、重复完成、通知失败和有界关闭。
4. 断言 Hook Agent 元数据、生命周期、诊断和 API Key/Authorization 脱敏。
5. 分别注入 fake 结果存储和 fake 文件隔离适配器，断言 AgentTool、启动和查询调用格式不变。

**验证：** 运行 `uv run python -m unittest tests.test_subagent_integration.SecurityAndFailureEndToEndTests tests.test_subagent_integration.ExtensionBoundaryTests tests.test_subagent_hooks -v`；预期安全、故障、扩展边界和 Hook 场景通过。

## T57：更新导出、README 和打包验证

**文件：** `src/flickcode/subagents/__init__.py`、`README.md`、`pyproject.toml`

**依赖：** T54、T55、T56

**步骤：**
1. 导出稳定公共接口，不导出内部 TaskRecord、锁或 Future。
2. 文档化角色格式、四层优先级、配置、统一 AgentTool、`/agent` 和 `Ctrl+B`。
3. 明确当前共享文件系统、单层 Agent、会话期任务和 Hook action 占位边界。
4. 验证 wheel 配置包含两个内置角色。

**验证：** 运行 `uv build` 后检查 wheel 内容包含 `flickcode/subagents/builtins/general-purpose.md` 和 `explore.md`；预期文档和内置资产均存在。

## T58：执行编译、专项测试与全量回归

**文件：** 全部本功能文件

**依赖：** T57

**步骤：**
1. 编译所有源码和测试。
2. 运行全部 `test_subagent_*` 专项测试。
3. 运行现有 Context、Commands、Skills、Hooks、MCP、Memory、Provider 与 Agent 测试。
4. 检查测试结束后无残留线程、临时结果目录或未关闭客户端警告。

**验证：** 依次运行 `uv run python -m compileall -q src tests`、`uv run python -m unittest discover -s tests -p 'test_subagent_*.py' -v`、`uv run python -m unittest discover -s tests -v`；预期全部退出码为 0。

## 执行顺序

```text
T1 → T2 ─┬→ T5 → T6 → T7 → T8 → T9 → T10
         ├→ T11 → T12 → T13
         ├→ T14 → T15 → T16
         ├→ T17 → T18
         ├→ T21 → T22 → T23
         └→ T24 → T25 → T26

T3 → T4 → T19 → T20

T27 → T29 ← T28
T30 → T31 → T32
T13 + T20 + T23 + T26 + T29 + T32
    → T33 → T34 → T35/T36 → T37 → T38
    → T39 → T40 → T41 → T42 → T43
    → T44 → T45 → T46 → T47 → T48
    → T49 → T50 → T51 → T52 → T53
    → T54/T55/T56 → T57 → T58
```
