# FlickCode Skill 系统 Checklist

> 每一项都必须通过运行测试或观察实际行为验证。实现完成前不预先勾选。

## 定义格式与发现

- [x] **[AC1] 合法定义与占位符**：共享和独立 Skill 的规定字段均能解析，正文中所有 `{{input}}` 被原样替换；空输入、多行输入和无占位符正文结果正确。（验证：运行 `python -m unittest tests.test_skills_parser.FieldValidationTests tests.test_skills_parser.RenderingTests`。）

- [x] **[AC1] 非法字段组合隔离**：非法名称、缺字段、未知字段、空正文、共享模式声明 `history/model`、独立模式缺 `history` 时，仅该定义失败并显示路径与原因。（验证：运行 `python -m unittest tests.test_skills_parser.FrontmatterEnvelopeTests tests.test_skills_parser.FieldValidationTests`。）

- [x] **[AC2] 单文件和目录型能力包**：直属 `*.md` 与直属含 `SKILL.md` 的目录均被发现；不递归发现更深层 Skill。（验证：运行 `python -m unittest tests.test_skills_catalog.CatalogDiscoveryTests`。）

- [x] **[AC2] 目录工具完整性**：合法 schema 与脚本形成一个专属工具；缺入口、缺脚本、非法 schema 或同包重名使整个能力包被跳过，其他 Skill 不受影响。（验证：运行 `python -m unittest tests.test_skills_parser.PackageManifestTests`。）

- [x] **[AC2][AC16] 路径与脚本快照安全**：绝对外部路径、`..` 越界和符号链接均被拒绝；解析后修改脚本文件不会改变运行中定义的脚本文本。（验证：运行 `python -m unittest tests.test_skills_parser.PathSafetyTests tests.test_skills_parser.ScriptSnapshotTests`。）

- [x] **[AC3] 三级覆盖与回退**：项目覆盖用户、用户覆盖内置；删除高级定义或使其无效后采用下一份有效定义，并显示实际来源。（验证：运行 `python -m unittest tests.test_skills_catalog.PrecedenceTests`。）

- [x] **[AC3] 同级冲突确定性**：同级同名定义全部从该级排除并报告所有路径，结果不随目录枚举顺序变化。（验证：运行 `python -m unittest tests.test_skills_catalog.PrecedenceTests` 中的同级冲突场景。）

- [x] **[AC12] Catalog 候选事务**：`prepare_refresh()` 不修改当前快照，只有 `commit()` 后 generation 和有效目录变化；未变化文件不重复解析。（验证：运行 `python -m unittest tests.test_skills_catalog.CatalogTransactionTests`。）

## 启动与两阶段加载

- [x] **[AC4] 启动摘要最小化**：首个模型请求只含有效 Skill 名称和一句说明，不含完整 SOP、`{{input}}` 渲染结果、schema 内容或脚本文本。（验证：运行 `python -m unittest tests.test_skills_integration.TwoPhaseStartupEndToEndTests`，检查 fake Provider 捕获的 system prompt。）

- [x] **[AC5] 白名单启动失败**：有效 Skill 引用不存在的基础/MCP 工具、其他 Skill 的专属工具或重名专属工具时，输入循环启动前失败并显示 Skill、工具和来源。（验证：运行 `python -m unittest tests.test_skills_validation.ToolWhitelistValidationTests tests.test_skills_integration.SkillStartupIntegrationTests`。）

- [x] **[AC5] 系统加载工具恒定可见**：无激活、有激活以及 PLAN 模式下，`load_skill` 都出现在模型 schema 和实际执行视图中，且无需写入 Skill 白名单。（验证：运行 `python -m unittest tests.test_context.AgentLoopToolExecutionSnapshotTests tests.test_skills_executor.LoadSkillToolTests`。）

- [x] **[AC6] 原子加载成功**：合法共享 Skill 加载后，激活记录、渲染 SOP、专属适配器和白名单在同一下一轮请求生效。（验证：运行 `python -m unittest tests.test_skills_runtime.SharedActivationTests tests.test_skills_integration.SharedSkillInvocationTests`。）

- [x] **[AC6] 原子加载失败回滚**：渲染、工具视图或调用准备失败后，原激活顺序、SOP、白名单及动态命令均不变，不追加成功归档事件。（验证：运行 `python -m unittest tests.test_skills_runtime.SharedActivationTests tests.test_skills_executor.SharedExecutorTests` 的失败场景。）

## Prompt 与工具边界

- [x] **[AC7] 多 Skill 持续钉入**：依次激活两个共享 Skill 后，每轮 system prompt 都含两个完整 SOP；顺序按首次激活稳定，重绑只更新原位置。（验证：运行 `python -m unittest tests.test_skills_runtime.SkillPromptSectionTests tests.test_skills_integration.SharedHotReloadEndToEndTests`。）

- [x] **[AC4][AC7] Prompt 区块优先级**：项目指令、用户指令、Active Skills、Skill Catalog、通用指导按 Plan 规定顺序出现；空目录或空激活不产生空区块。（验证：运行 `python -m unittest tests.test_skills_runtime.SkillPromptSectionTests`。）

- [x] **[AC8] 无激活默认工具**：没有共享 Skill 激活时，模型仍看到原默认工具集合和 `load_skill`，普通 Agent 行为不变。（验证：运行 `python -m unittest tests.test_skills_runtime.RuntimeInitialStateTests tests.test_skills_integration.SkillPromptToolIntegrationTests`。）

- [x] **[AC8] 白名单并集与隐藏执行拒绝**：激活两个 Skill 后只暴露两份白名单并集和 `load_skill`；模型猜测隐藏工具时按未知工具处理，不能从主 registry 回退执行。（验证：运行 `python -m unittest tests.test_skills_runtime.RuntimeToolUnionTests tests.test_context.AgentLoopToolExecutionSnapshotTests`。）

- [x] **[AC8] 单轮工具视图一致**：Context 估算、Provider schema、未知工具判断和执行使用同一 `ToolRegistryView`；同批调用不能提前使用刚加载的工具。（验证：运行 `python -m unittest tests.test_context.AgentLoopToolViewTests tests.test_context.AgentLoopToolExecutionSnapshotTests`。）

- [x] **[AC16][AC18] 专属脚本成功协议**：Anthropic 与 OpenAI schema 均完整保留专属工具 object schema，JSON 参数通过 stdin 传入并得到规范 `ToolResult`。（验证：运行 `python -m unittest tests.test_skills_script_tool.ScriptToolProtocolTests tests.test_skills_integration.IsolatedProviderEndToEndTests`。）

- [x] **[AC16] 专属脚本失败与脱敏**：超时、非零退出、非法 JSON、空输出和非法结果均只返回失败 ToolResult；调用不经过 shell，错误和归档不含测试 secret 或完整环境。（验证：运行 `python -m unittest tests.test_skills_script_tool.ScriptToolFailureTests tests.test_skills_script_tool.ScriptToolEnvironmentTests`。）

- [x] **[AC16] 权限链保持**：专属工具继续经过现有 Permission Engine；拒绝结果不执行脚本，`load_skill` 仅按系统只读规则放行。（验证：运行 `python -m unittest tests.test_skills_integration.SkillPermissionIntegrationTests`。）

## 共享与独立执行

- [x] **[AC9] 共享斜杠执行**：`/<skill> 参数` 先激活 Skill，再将原始参数作为主会话用户意图；响应、工具调用和结果均进入主历史并使用主模型。（验证：运行 `python -m unittest tests.test_skills_integration.SharedSkillInvocationTests`。）

- [x] **[AC9] Agent 主动加载共享 Skill**：Agent 调用 `load_skill` 后，本轮工具结果进入主历史，下一迭代看到完整 SOP 和新工具；后续普通对话仍保留激活状态。（验证：运行 `python -m unittest tests.test_skills_integration.SharedSkillInvocationTests tests.test_context.AgentLoopToolExecutionSnapshotTests`。）

- [x] **[AC10] 最近 N 个完整轮次**：`history: 2` 只复制最近两个 user/assistant/tool 完整轮次，`history: 0` 不复制旧轮次，孤立或未闭合工具链不进入子会话。（验证：运行 `python -m unittest tests.test_skills_history.ConversationTurnSelectorTests`。）

- [x] **[AC10] 独立模型与 Runtime 隔离**：子会话仅替换声明的模型名，继承协议/端点；只激活目标 Skill，父模型、消息、工具和激活状态执行前后相同。（验证：运行 `python -m unittest tests.test_skills_executor.IsolatedContextConstructionTests tests.test_skills_integration.IsolatedSkillInvocationTests`。）

- [x] **[AC10] 子会话持久化与摘要回流**：子过程完整写入 `sessions/children/*.jsonl` 并关联父 ID；主历史只保留规范化调用记录和不超过 8192 字符的摘要。（验证：运行 `python -m unittest tests.test_skills_executor.IsolatedAgentLoopTests tests.test_skills_sessions.ChildSessionJournalTests`。）

- [x] **[AC16] 独立失败终态**：Provider 错误、权限拒绝、最大轮次或取消均写入 child finished 事件，并向父会话返回包含 child ID 的失败摘要，不触发长期记忆更新。（验证：运行 `python -m unittest tests.test_skills_executor.IsolatedSummaryTests tests.test_skills_integration.IsolatedProviderEndToEndTests`。）

## 动态命令与热更新

- [x] **[AC11] 动态命令帮助与补全**：每个有效 Skill 都出现在 `/<name>` 帮助和 Tab 补全中；新增、删除和覆盖后下一次补全使用新快照。（验证：运行 `python -m unittest tests.test_skills_commands.SkillCommandManagerTests tests.test_skills_commands.RefreshHookTests`。）

- [x] **[AC11] 参数原样传递**：无参数调用得到空字符串；多行、连续空格和首尾内容按命令解析约定传给 `{{input}}`，不会被 Skill adapter 二次折叠。（验证：运行 `python -m unittest tests.test_command_integration.SkillCommandUIIntegrationTests tests.test_skills_commands.SkillCommandManagerTests`。）

- [x] **[AC17] review 迁移唯一性**：`/review` 只由当前有效 `review` Skill 注册；`/audit` 委托同一 Skill，稳定 registry 不再包含硬编码 review handler。（验证：运行 `python -m unittest tests.test_command_integration.SkillBuiltinCommandTests tests.test_skills_integration.BuiltinReviewSkillTests`。）

- [x] **[AC12] 有效热更新**：运行中新增或有效修改 Skill 后，无需重启，下一次提交/加载/补全采用新目录、命令、SOP 和白名单；已开始调用继续使用旧快照。（验证：运行 `python -m unittest tests.test_skills_runtime.RuntimeValidRefreshTests tests.test_skills_integration.SharedHotReloadEndToEndTests`。）

- [x] **[AC13] 暂时无效更新**：已激活来源变成无效 YAML 时继续使用最后有效激活对象并显示诊断，新调用按当前有效 Catalog 结果解析。（验证：运行 `python -m unittest tests.test_skills_runtime.RuntimeInvalidEditTests`。）

- [x] **[AC13] 删除回退与停用**：删除已激活来源后，有低级定义则切换并报告来源，无回退则停用且专属工具下一轮不可调用。（验证：运行 `python -m unittest tests.test_skills_runtime.RuntimeDeletionTests`。）

- [x] **[AC12][AC13] 三组件事务回滚**：热更新产生未知工具或动态命令冲突时，Catalog、Runtime 和命令 registry 都保留旧 generation，输入循环继续。（验证：运行 `python -m unittest tests.test_skills_integration.SkillRefreshTransactionTests`。）

## 会话、重置与诊断

- [x] **[AC14] clear 保持原语义**：执行 `/clear` 只清除显示，主历史、PlanContext、Session ID 和激活 Skill 均不变。（验证：运行 `python -m unittest tests.test_command_integration.SkillBuiltinCommandTests tests.test_skills_sessions.SessionResetTests`。）

- [x] **[AC14] reset 创建干净主会话**：执行 `/reset` 后旧会话已追加 reset 事件，新 Session ID、空历史、空 PlanContext 和空激活状态可观察；Catalog、动态命令、Provider、MCP 和记忆保留。（验证：运行 `python -m unittest tests.test_skills_sessions.SessionResetTests`。）

- [x] **[AC15] 激活事件恢复**：恢复主会话时重放激活、重绑、停用和 reset，按当前 Catalog 恢复名称与输入绑定，不从归档加载 SOP 或脚本。（验证：运行 `python -m unittest tests.test_skills_sessions.SkillRecoveryReplayTests tests.test_skills_sessions.SessionSkillResumeTests`。）

- [x] **[AC15] 恢复来源变化和缺失**：归档来源变化时使用当前优先级定义并报告；定义缺失时只跳过该 Skill；恢复准备失败时当前会话保持原状。（验证：运行 `python -m unittest tests.test_skills_sessions.SessionSkillResumeTests`。）

- [x] **[AC16] 坏归档与写入失败隔离**：坏 Skill 事件、未知未来事件或归档写失败不破坏可恢复消息和内存会话，诊断不包含 SOP、脚本或 secret。（验证：运行 `python -m unittest tests.test_skills_sessions.MainSkillJournalTests tests.test_skills_sessions.SkillRecoveryReplayTests`。）

- [x] **[N7] 状态可观察**：`/status` 能显示有效/激活 Skill、来源、白名单并集、最近刷新和子会话终态摘要，不读取内部对象或泄露凭据。（验证：运行 `python -m unittest tests.test_command_integration.SkillBuiltinCommandTests`。）

## 内置样板、打包与兼容性

- [x] **[AC17] 三个内置样板可用**：全新安装能发现 `commit`、`review`、`test`；项目或用户同名定义按优先级覆盖；三个样板通过普通 Parser 和 Validator。（验证：运行 `python -m unittest tests.test_skills_integration.BuiltinSharedSkillTests tests.test_skills_integration.BuiltinReviewSkillTests`。）

- [x] **[AC17] review 专属工具只读**：`review_project_snapshot` 只返回文件类型、数量和大小，不修改项目、不跟随符号链接、不访问网络、不要求 Git。（验证：运行 `python -m unittest tests.test_skills_integration.BuiltinReviewSkillTests`，并对临时目录执行前后文件哈希进行比较。）

- [x] **[AC17] wheel 包含内置资源**：构建后的 wheel 包含三个 Markdown、review schema 和脚本，安装后 Catalog 能发现它们。（验证：运行 `python -m unittest tests.test_skills_integration.SkillPackagingDocumentationTests`。）

- [x] **[AC18] TUI 与 Pipe 一致**：相同输入序列在 TUI fake 和 Pipe fake 中得到相同的目录刷新、命令匹配、原始参数、执行模式和摘要；`/clear`、`/reset`、退出命令仍正常。（验证：运行 `python -m unittest tests.test_skills_integration.SkillTUIPipeTests tests.test_command_integration`。）

- [x] **[AC18] Anthropic 与 OpenAI 兼容**：两个 Provider 格式均能看到正确过滤的基础/MCP/专属 schema，并完成一次专属工具调用。（验证：运行 `python -m unittest tests.test_skills_integration.IsolatedProviderEndToEndTests tests.test_skills_runtime.ToolRegistryViewTests`。）

- [x] **[N6] 普通非 Skill 对话兼容**：无自定义 Skill、无激活 Skill 时，普通 Agent、计划/执行、上下文压缩、权限、MCP、Session 和记忆测试保持通过。（验证：运行 `python -m unittest tests.test_context tests.test_memory tests.test_commands tests.test_command_integration tests.test_mcp_unittest`。）

- [x] **[N6] Session.chat 统一且不重复记账**：`chat()` 与 `agent_chat()` 使用同一 Agent Loop 和白名单语义，事件类型兼容，Token/Context/记忆调度只记录一次。（验证：运行 `python -m unittest tests.test_context tests.test_memory` 中的 Chat 与 Agent Loop 集成测试。）

- [x] **[文档] README 行为一致**：README 完整说明路径、frontmatter、目录包、两阶段加载、两种模式、白名单、热更新、动态命令、子归档、clear/reset 和明确不做事项。（验证：运行 `python -m unittest tests.test_skills_integration.SkillPackagingDocumentationTests`，并人工阅读 Skill 章节。）

## 编译与测试

- [x] Skill 公共接口、Session 和 ToolRegistryView 可导入。（验证：运行 `python -c "from flickcode.skills import SkillRuntime; from flickcode.session import Session; from flickcode.tools import ToolRegistryView; print('imports ok')"`，期望输出 `imports ok`。）

- [x] 项目源码和测试全部可编译。（验证：运行 `python -m compileall -q src tests`，期望退出码 0。）

- [x] 全部 unittest 通过且不需要网络、真实 API Key 或既有用户 Skill。（验证：运行 `python -m unittest discover -s tests -p "test*.py"`，期望退出码 0。）

- [x] CLI 帮助可用，加载包资源不会在 `--help` 路径执行 Skill 脚本。（验证：运行 `python -m flickcode --help`，期望退出码 0 且无脚本副作用。）

- [x] 源码不存在遗留硬编码 review handler、未完成标记或调试输出。（验证：使用 `rg` 搜索旧 handler 名称及未完成标记，并人工确认命中均为文档或测试预期。）

## 端到端场景

- [x] **场景 1：项目覆盖 + Agent 主动加载**：内置 `test` 被用户级和项目级同名定义覆盖 → 启动 Prompt 只显示项目级名称/说明 → Agent 调用 `load_skill` → 下一迭代看到项目级完整 SOP 和白名单 → 工具结果与最终响应进入主历史。（验证：运行 `python -m unittest tests.test_skills_integration.TwoPhaseStartupEndToEndTests`。）

- [x] **场景 2：共享组合 + 热更新**：调用两个共享 Skill → 每轮 SOP 稳定且工具取并集 → 修改其中一个 SOP/白名单 → 下一轮生效 → 写入半截 YAML 时保留最后有效激活 → 删除后自动回退。（验证：运行 `python -m unittest tests.test_skills_integration.SharedHotReloadEndToEndTests`。）

- [x] **场景 3：独立 review**：`/review focus` → 子会话携带最近 N 个完整轮次 → 使用只读工具和可选模型运行 → 完整过程写入 children 归档 → 父历史仅留下调用和摘要 → `/audit` 走同一当前有效 Skill。（验证：运行 `python -m unittest tests.test_skills_integration.IsolatedProviderEndToEndTests tests.test_skills_integration.BuiltinReviewSkillTests`。）

- [x] **场景 4：失败、恢复与 reset**：独立 Provider 失败仍产生 child finished 和失败摘要 → 主共享 Skill 保持激活 → 恢复归档按当前目录重建 → `/clear` 不清状态 → `/reset` 归档并创建干净会话。（验证：运行 `python -m unittest tests.test_skills_sessions.SessionSkillResumeTests tests.test_skills_sessions.SessionResetTests tests.test_skills_executor.IsolatedSummaryTests`。）

- [x] **场景 5：双入口双 Provider**：同一共享和独立 Skill 输入分别经 TUI/Pipe、Anthropic/OpenAI fake 执行 → 参数、Prompt、schema、工具调用、摘要和诊断保持一致。（验证：运行 `python -m unittest tests.test_skills_integration.SkillTUIPipeTests tests.test_skills_integration.IsolatedProviderEndToEndTests`。）

## 完成证据（2026-08-19）

- `.venv\Scripts\python.exe -m unittest discover -s tests -p "test*.py"`：117 项通过，1 项既有平台条件测试跳过。
- `.venv\Scripts\python.exe -m compileall -q src tests`：退出码 0。
- Skill 公共接口、`Session`、`ToolRegistryView` 导入：输出 `imports ok`。
- `.venv\Scripts\python.exe -m flickcode --help`：退出码 0，未初始化 Session 或执行 Skill 脚本。
- `uv build --wheel`：成功生成 `flickcode-0.1.0-py3-none-any.whl`。
- wheel 资源检查：包含 `commit.md`、`test.md`、`review/SKILL.md`、`project_snapshot.json` 和 `project_snapshot.py`，不包含 `__pycache__` 或 `.pyc`。
- 源码审计：稳定命令 registry 中不存在硬编码 `review`；`/review` 仅由当前 Catalog 动态生成，`/audit` 委托该 Skill。
