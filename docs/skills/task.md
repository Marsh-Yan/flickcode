# FlickCode Skill 系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/flickcode/skills/__init__.py` | 导出 Skill 公共接口。 |
| 新建 | `src/flickcode/skills/models.py` | Skill、工具、Catalog、激活、诊断和结果模型。 |
| 新建 | `src/flickcode/skills/parser.py` | frontmatter、正文、目录包和工具声明解析。 |
| 新建 | `src/flickcode/skills/catalog.py` | 三级发现、覆盖、缓存和候选事务。 |
| 新建 | `src/flickcode/skills/validation.py` | 白名单、工具名和命令名校验。 |
| 新建 | `src/flickcode/skills/runtime.py` | 激活状态、工具并集、热更新协调。 |
| 新建 | `src/flickcode/skills/history.py` | 完整对话轮次选择。 |
| 新建 | `src/flickcode/skills/ports.py` | Executor 所需的会话 Protocol。 |
| 新建 | `src/flickcode/skills/executor.py` | 共享与独立执行。 |
| 新建 | `src/flickcode/skills/script_tool.py` | 专属 Python 脚本工具适配器。 |
| 新建 | `src/flickcode/skills/load_tool.py` | 系统级 `load_skill` 工具。 |
| 新建 | `src/flickcode/skills/commands.py` | 动态 Skill 命令生成与提交。 |
| 新建 | `src/flickcode/skills/builtins/commit.md` | 内置共享 commit Skill。 |
| 新建 | `src/flickcode/skills/builtins/test.md` | 内置共享 test Skill。 |
| 新建 | `src/flickcode/skills/builtins/review/SKILL.md` | 内置独立 review Skill。 |
| 新建 | `src/flickcode/skills/builtins/review/tools/project_snapshot.json` | review 专属工具 schema。 |
| 新建 | `src/flickcode/skills/builtins/review/scripts/project_snapshot.py` | review 只读统计脚本。 |
| 修改 | `src/flickcode/tools/registry.py` | 不可变 ToolRegistryView 与快照。 |
| 修改 | `src/flickcode/tools/__init__.py` | 导出 ToolRegistryView。 |
| 修改 | `src/flickcode/agent.py` | 每轮动态工具视图和同快照执行。 |
| 修改 | `src/flickcode/prompt/sections.py` | Skill Catalog 与 Active Skills 区块。 |
| 修改 | `src/flickcode/prompt/__init__.py` | 导出新增 Prompt 区块。 |
| 修改 | `src/flickcode/commands/registry.py` | 稳定/动态命令分区。 |
| 修改 | `src/flickcode/commands/adapters.py` | 增加 `run_skill()` 端口。 |
| 修改 | `src/flickcode/commands/builtin.py` | review 迁移、reset、audit 和 status。 |
| 修改 | `src/flickcode/commands/dispatcher.py` | 输入前刷新钩子。 |
| 修改 | `src/flickcode/session.py` | Skill 组合根、刷新、调用、恢复、重置。 |
| 修改 | `src/flickcode/tui.py` | 动态命令、补全和 TUI/Pipe 调用。 |
| 修改 | `src/flickcode/sessions/journal.py` | Skill 事件与 children 归档。 |
| 修改 | `src/flickcode/sessions/recovery.py` | Skill 状态重放。 |
| 修改 | `src/flickcode/sessions/__init__.py` | 导出新增归档模型。 |
| 修改 | `pyproject.toml` | 打包内置 Markdown、JSON 和脚本。 |
| 修改 | `README.md` | Skill 用户文档。 |
| 新建 | `tests/fixtures/skills/*` | 合法、非法和目录型测试资源。 |
| 新建 | `tests/test_skills_parser.py` | 模型、frontmatter、能力包和路径测试。 |
| 新建 | `tests/test_skills_catalog.py` | 发现、覆盖、回退和事务测试。 |
| 新建 | `tests/test_skills_validation.py` | 白名单和冲突测试。 |
| 新建 | `tests/test_skills_runtime.py` | 激活、并集和热更新测试。 |
| 新建 | `tests/test_skills_history.py` | 完整轮次选择测试。 |
| 新建 | `tests/test_skills_script_tool.py` | 脚本协议与安全失败测试。 |
| 新建 | `tests/test_skills_executor.py` | 共享/独立执行测试。 |
| 新建 | `tests/test_skills_commands.py` | 动态命令和补全测试。 |
| 新建 | `tests/test_skills_sessions.py` | 归档、恢复和 reset 测试。 |
| 新建 | `tests/test_skills_integration.py` | 两阶段加载、TUI/Pipe 和 Provider 集成。 |
| 修改 | `tests/test_commands.py` | 稳定/动态 registry 和 reset 回归。 |
| 修改 | `tests/test_command_integration.py` | review 迁移、run_skill 和补全回归。 |
| 修改 | `tests/test_context.py` | 统一 Agent Loop 与工具视图回归。 |
| 修改 | `tests/test_memory.py` | Session.chat 适配、恢复和记忆隔离回归。 |

## T1：建立 Skill 公共模型

**文件：** `src/flickcode/skills/models.py`、`src/flickcode/skills/__init__.py`、`tests/test_skills_parser.py`  
**依赖：** 无

**步骤：**

1. 定义 `SkillMode`、`SkillSource` 和 `SkillInvocationOrigin`。
2. 定义不可变的 Skill、工具、诊断、Catalog、激活、调用与执行结果数据类。
3. 定义 `SkillRuntimeCandidate`、`ChildSessionMetadata` 和 `ArchivedSkillActivation`。
4. 使用 Python 3.8 可解析的类型写法，不使用 `X | Y`。
5. 从包入口导出稳定公共名称。

**验证：** 运行 `python -m unittest tests.test_skills_parser.DefinitionModelTests`；预期模型不可变、枚举值和默认约束测试通过。

## T2：建立 Skill 测试 fixtures

**文件：** `tests/fixtures/skills/valid_shared.md`、`valid_isolated.md`、`invalid_frontmatter.md`、`package/**`、`tests/test_skills_parser.py`  
**依赖：** T1

**步骤：**

1. 创建合法共享和独立 Skill 文本。
2. 创建缺字段、未知字段和非法模式样例。
3. 创建目录型 echo schema 与 JSON stdin/stdout Python 脚本。
4. 保证 fixture 不访问网络、不依赖用户目录、不修改工作区。

**验证：** 运行 `python -m unittest tests.test_skills_parser.FixtureTests`；预期所有 fixture 存在且 UTF-8 可读。

## T3：解析 frontmatter 边界与正文

**文件：** `src/flickcode/skills/parser.py`、`tests/test_skills_parser.py`  
**依赖：** T1、T2

**步骤：**

1. 要求文件首行和结束边界均为独立 `---`。
2. 使用 `yaml.safe_load` 读取 mapping。
3. 将边界之后的 Markdown 作为正文并拒绝空正文。
4. 将 YAML、编码和边界错误转换为带路径的 Skill 解析异常。
5. 测试正文中的第二个 `---` 不会被误当作 frontmatter 结束之外的新结构。

**验证：** 运行 `python -m unittest tests.test_skills_parser.FrontmatterEnvelopeTests`；预期合法正文和所有边界错误结果稳定。

## T4：校验 Skill 字段组合并渲染输入

**文件：** `src/flickcode/skills/parser.py`、`src/flickcode/skills/models.py`、`tests/test_skills_parser.py`  
**依赖：** T3

**步骤：**

1. 严格接受 `name`、`description`、`tools`、`mode`、`history`、`model`。
2. 校验名称格式、单行说明、工具字符串列表及去重。
3. 共享模式拒绝 `history/model`；独立模式要求非负整数 `history`，`model` 可选且非空。
4. 实现对所有 `{{input}}` 的原样替换。
5. 覆盖空输入、多占位符、无占位符和内部多行空格。

**验证：** 运行 `python -m unittest tests.test_skills_parser.FieldValidationTests tests.test_skills_parser.RenderingTests`；预期 AC1 场景通过。

## T5：解析目录型工具声明

**文件：** `src/flickcode/skills/parser.py`、`tests/test_skills_parser.py`  
**依赖：** T4

**步骤：**

1. 将直属目录中的 `SKILL.md` 作为唯一入口。
2. 按稳定文件名顺序读取 `tools/*.json`。
3. 校验工具名称、说明、完整 object input schema 和 entrypoint。
4. 要求每个声明工具出现在所属 Skill 的白名单中。
5. 拒绝缺入口、缺脚本、非法 JSON、非法 schema 和同包工具重名。

**验证：** 运行 `python -m unittest tests.test_skills_parser.PackageManifestTests`；预期合法包成功、单个包错误整体失败。

## T6：固定路径安全与脚本快照

**文件：** `src/flickcode/skills/parser.py`、`tests/test_skills_parser.py`  
**依赖：** T5

**步骤：**

1. 解析 package root、schema 和 entrypoint 的绝对规范路径。
2. 拒绝 `..` 越界、绝对外部路径和路径链中的符号链接。
3. 读取入口脚本文本到 `SkillToolDefinition.script_source`。
4. 计算正文、schema 和脚本文本的 SHA-256 指纹。
5. 测试修改磁盘脚本不会改变已解析定义中的脚本文本。

**验证：** 运行 `python -m unittest tests.test_skills_parser.PathSafetyTests tests.test_skills_parser.ScriptSnapshotTests`；预期越界被拒绝且快照不可变。

## T7：发现三级 Skill 来源

**文件：** `src/flickcode/skills/catalog.py`、`tests/test_skills_catalog.py`  
**依赖：** T4、T6

**步骤：**

1. 接收项目、用户和内置三个根目录。
2. 只扫描每个根目录的直属 `*.md` 和直属含 `SKILL.md` 子目录。
3. 对路径排序后调用 Parser。
4. 不存在目录视为空来源；单条解析失败写诊断并继续。
5. 为定义附加正确来源。

**验证：** 运行 `python -m unittest tests.test_skills_catalog.CatalogDiscoveryTests`；预期递归外条目被忽略且三个来源均可发现。

## T8：实现同级冲突、覆盖和回退

**文件：** `src/flickcode/skills/catalog.py`、`tests/test_skills_catalog.py`  
**依赖：** T7

**步骤：**

1. 同级同名时排除该级全部冲突定义并记录路径。
2. 按项目、用户、内置顺序选择有效定义。
3. 记录被覆盖定义与实际来源。
4. 高级定义解析失败时采用低级有效定义。
5. 验证结果不依赖文件系统枚举顺序。

**验证：** 运行 `python -m unittest tests.test_skills_catalog.PrecedenceTests`；预期 AC3 的覆盖、删除和无效回退通过。

## T9：实现 Catalog 候选事务与缓存

**文件：** `src/flickcode/skills/catalog.py`、`tests/test_skills_catalog.py`  
**依赖：** T8

**步骤：**

1. 实现路径、大小和修改时间的快速签名。
2. 内容未变时复用已解析定义；可疑变化时重新计算内容指纹。
3. 实现 `prepare_refresh()`，返回 previous/current 和 added/changed/removed。
4. 实现显式 `commit()`，未提交候选不得改变 `snapshot()`。
5. 为错误候选、重复提交和稳定 generation 补充测试。

**验证：** 运行 `python -m unittest tests.test_skills_catalog.CatalogTransactionTests`；预期准备无副作用、提交原子且未变文件不重解析。

## T10：校验启动工具白名单

**文件：** `src/flickcode/skills/validation.py`、`tests/test_skills_validation.py`  
**依赖：** T1、T9

**步骤：**

1. 接收基础/MCP 工具名称集合。
2. 允许 Skill 引用全局工具或自身专属工具。
3. 拒绝不存在工具和跨 Skill 专属工具引用。
4. 检测专属工具与全局工具或其他有效 Skill 工具重名。
5. 错误必须包含 Skill 名、工具名和来源。

**验证：** 运行 `python -m unittest tests.test_skills_validation.ToolWhitelistValidationTests`；预期未知工具和所有重名场景抛出 `SkillStartupError`。

## T11：校验命令冲突与运行时刷新

**文件：** `src/flickcode/skills/validation.py`、`tests/test_skills_validation.py`  
**依赖：** T10

**步骤：**

1. 将稳定内置命令名和别名作为保留集合。
2. 允许 `review` 仅由动态 Skill 提供，保留 `audit` 冲突保护。
3. 启动冲突抛出致命错误。
4. 运行时新增未知工具或命令冲突返回拒绝诊断，不抛出到输入循环。
5. 确认诊断不包含工具环境或脚本文本。

**验证：** 运行 `python -m unittest tests.test_skills_validation.CommandConflictTests tests.test_skills_validation.RefreshValidationTests`；预期启动与热更新错误边界不同。

## T12：建立不可变 ToolRegistryView

**文件：** `src/flickcode/tools/registry.py`、`src/flickcode/tools/__init__.py`、`tests/test_skills_runtime.py`  
**依赖：** 无

**步骤：**

1. 新增只读工具 mapping 快照。
2. 实现 `get()`、`list_tools()` 和两种 Provider schema 转换。
3. 防御性复制 input schema。
4. 禁止快照注册、替换或删除工具。
5. 保持现有 `ToolRegistry` 接口行为不变。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.ToolRegistryViewTests`；预期视图不可变且 Anthropic/OpenAI schema 与原 registry 一致。

## T13：按名称和额外实例创建工具快照

**文件：** `src/flickcode/tools/registry.py`、`tests/test_skills_runtime.py`  
**依赖：** T12

**步骤：**

1. 实现 `ToolRegistry.snapshot(names, extras)`。
2. 拒绝不存在名称、extras 内部重名及 extras 与主 registry 重名。
3. 对名称排序产生稳定视图。
4. 确认创建视图不修改主 registry。
5. 覆盖空集合和只含系统工具的场景。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.ToolRegistrySnapshotTests`；预期快照过滤和冲突保护通过。

## T14：让 Agent Loop 每轮获取工具视图

**文件：** `src/flickcode/agent.py`、`tests/test_context.py`  
**依赖：** T13

**步骤：**

1. 增加可选 `tool_view_provider`，保留无回调时原 registry 行为。
2. 每轮开始调用一次并保存本地视图。
3. 使用该视图生成 Context Manager 和 Provider 所需 schema。
4. 为两轮返回不同视图的 fake provider 增加测试。
5. 确认每轮只调用一次 provider。

**验证：** 运行 `python -m unittest tests.test_context.AgentLoopToolViewTests`；预期不同轮次看到不同工具且单轮无重复读取。

## T15：用同一视图校验和执行工具

**文件：** `src/flickcode/agent.py`、`tests/test_context.py`  
**依赖：** T14

**步骤：**

1. 将本轮视图传入未知工具检测和 `_execute_tools()`。
2. 模型猜测隐藏工具时按未知工具处理，不从主 registry 回退。
3. 计划模式与只读集合取交集后始终加入 `load_skill`。
4. 并列 `load_skill` 与新工具调用时，新工具在当前批次失败、下一轮可用。
5. 保持权限检查和读写工具执行顺序。

**验证：** 运行 `python -m unittest tests.test_context.AgentLoopToolExecutionSnapshotTests`；预期 schema、校验和执行严格同源。

## T16：实现专属脚本工具成功协议

**文件：** `src/flickcode/skills/script_tool.py`、`tests/test_skills_script_tool.py`  
**依赖：** T1、T2

**步骤：**

1. 将 `SkillToolDefinition` 转换为现有 `ToolSpec`。
2. 以 `[sys.executable, "-c", script_source]` 启动进程，不启用 shell。
3. 通过 stdin 写入 UTF-8 JSON 参数。
4. 解析 stdout 的 success/output/error object。
5. 将合法结果转换为 `ToolResult`。

**验证：** 运行 `python -m unittest tests.test_skills_script_tool.ScriptToolProtocolTests`；预期 echo fixture 收到原参数并返回稳定结果。

## T17：限制脚本环境并处理失败

**文件：** `src/flickcode/skills/script_tool.py`、`tests/test_skills_script_tool.py`  
**依赖：** T16

**步骤：**

1. 设置 60 秒超时和项目根工作目录。
2. 构造 Windows/POSIX 可启动的最小环境，不传入测试 secret。
3. 处理超时、非零退出、空输出、非法 JSON 和非法结果字段。
4. 限制 stderr 诊断长度并脱敏，不将原环境写入错误。
5. 再次确认定义中的入口来源位于包根且不是符号链接。

**验证：** 运行 `python -m unittest tests.test_skills_script_tool.ScriptToolFailureTests tests.test_skills_script_tool.ScriptToolEnvironmentTests`；预期所有失败返回 `success=False` 且 secret 不出现。

## T18：建立 Runtime 初始快照

**文件：** `src/flickcode/skills/runtime.py`、`tests/test_skills_runtime.py`  
**依赖：** T9、T11、T13

**步骤：**

1. 让 Runtime 持有已提交 Catalog、主工具 registry 和系统工具名。
2. 无激活 Skill 时返回默认工具集合加 `load_skill`。
3. 实现只读 `snapshot()` 和 `prompt_context()` 基础结构。
4. 保证调用方不能修改 active list、allowed set 或 diagnostics。
5. 为初始空状态和非空 Catalog 增加测试。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.RuntimeInitialStateTests`；预期无激活状态保持默认工具且只注入目录摘要。

## T19：实现共享 Skill 原子激活

**文件：** `src/flickcode/skills/runtime.py`、`tests/test_skills_runtime.py`  
**依赖：** T18

**步骤：**

1. 根据名称锁定当前有效共享定义。
2. 渲染 `{{input}}` 并创建候选 `ActiveSkill`。
3. 首次激活追加稳定顺序；重复激活保留位置并更新内容。
4. 失败时不修改 active list、diagnostics 或工具状态。
5. 记录可供 Session 归档的激活/重绑结果。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.SharedActivationTests`；预期多 Skill 顺序、重复绑定和失败回滚通过。

## T20：计算白名单并集和专属适配器

**文件：** `src/flickcode/skills/runtime.py`、`tests/test_skills_runtime.py`  
**依赖：** T17、T19

**步骤：**

1. 至少一个激活 Skill 时取所有白名单并集。
2. 始终加入 `load_skill`。
3. 只为已激活 Skill 的自有工具创建 `SkillScriptTool`。
4. 使用 `ToolRegistry.snapshot()` 同时验证名称和 extras。
5. 为 mode 过滤提供 FULL/EXECUTE/PLAN 三种视图。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.RuntimeToolUnionTests`；预期 AC8 的默认、并集、隐藏和计划模式场景通过。

## T21：协调有效与暂时无效热更新

**文件：** `src/flickcode/skills/runtime.py`、`tests/test_skills_runtime.py`  
**依赖：** T20

**步骤：**

1. 实现 `prepare_reconcile()`，不直接修改当前 Runtime。
2. 有效定义改变时更新渲染 SOP、来源和白名单。
3. 激活来源仍存在但解析失败时保留最后有效 `ActiveSkill`。
4. 新调用继续按候选 Catalog 的有效定义解析。
5. 实现显式 `commit()` 并验证旧快照仍可被运行中调用持有。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.RuntimeValidRefreshTests tests.test_skills_runtime.RuntimeInvalidEditTests`；预期有效更新生效、半写入不破坏激活状态。

## T22：处理删除、模式变化与刷新拒绝

**文件：** `src/flickcode/skills/runtime.py`、`tests/test_skills_runtime.py`  
**依赖：** T21

**步骤：**

1. 删除激活来源时切换到低优先级有效定义。
2. 无回退时停用并更新白名单。
3. 共享定义改为独立模式时停用并记录诊断。
4. Validator 拒绝候选时不提交 Catalog、Runtime 或命令状态。
5. 覆盖删除后专属工具不可调用。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.RuntimeDeletionTests tests.test_skills_runtime.RuntimeRefreshRejectionTests`；预期 AC13 和原子回滚通过。

## T23：增加 Skill Prompt 区块

**文件：** `src/flickcode/prompt/sections.py`、`src/flickcode/prompt/__init__.py`、`tests/test_skills_runtime.py`  
**依赖：** T18、T19

**步骤：**

1. 增加 priority 3 的 `ActiveSkillsSection`。
2. 以清晰名称边界按 activation order 渲染完整 SOP。
3. 增加 priority 4 的 `SkillCatalogSection`，只渲染名称和一句说明。
4. 空 Catalog 或空激活集合时省略对应区块。
5. 验证它们位于通用内置指导之前且每轮读取新上下文。

**验证：** 运行 `python -m unittest tests.test_skills_runtime.SkillPromptSectionTests`；预期两阶段内容、顺序和空状态通过。

## T24：选择最近完整对话轮次

**文件：** `src/flickcode/skills/history.py`、`tests/test_skills_history.py`  
**依赖：** T1

**步骤：**

1. 以 user 消息作为轮次起点。
2. 保留所属 assistant 消息、tool_calls 和匹配 tool result。
3. 排除 system 和 thinking 消息。
4. 跳过或截断不完整尾部，不返回孤立 tool result。
5. 实现 count=0、历史不足和多轮反向选择。

**验证：** 运行 `python -m unittest tests.test_skills_history.ConversationTurnSelectorTests`；预期 AC10 的 N 轮和工具链完整性通过。

## T25：追加主会话 Skill 生命周期事件

**文件：** `src/flickcode/sessions/journal.py`、`src/flickcode/sessions/__init__.py`、`tests/test_skills_sessions.py`  
**依赖：** T1

**步骤：**

1. 增加激活、重绑、停用和 reset 的类型化追加方法。
2. 事件保存名称、原始输入、来源和必要状态，不保存 SOP 或脚本。
3. 复用现有 session ID 与路径安全检查。
4. 保持追加失败只返回诊断。
5. 让列表扫描忽略非 message 事件的消息计数。

**验证：** 运行 `python -m unittest tests.test_skills_sessions.MainSkillJournalTests`；预期事件顺序、payload 最小化和原列表兼容通过。

## T26：建立隔离子会话归档

**文件：** `src/flickcode/sessions/journal.py`、`tests/test_skills_sessions.py`  
**依赖：** T25

**步骤：**

1. 在 `sessions/children/` 下创建受管子路径。
2. 增加 `skill_child_started`、message 和 `skill_child_finished` 写入。
3. started 记录父 ID、Skill、来源和模型；finished 记录终态。
4. 拒绝非法 ID、符号链接和越界路径。
5. 普通 `list_sessions()` 不枚举 children。

**验证：** 运行 `python -m unittest tests.test_skills_sessions.ChildSessionJournalTests`；预期父子元数据完整且子会话不出现在普通列表。

## T27：在恢复时重放 Skill 状态

**文件：** `src/flickcode/sessions/recovery.py`、`src/flickcode/sessions/__init__.py`、`tests/test_skills_sessions.py`  
**依赖：** T25

**步骤：**

1. 在读取消息时同时重放激活、重绑、停用和 reset。
2. 计算归档结束时的 `ArchivedSkillActivation` 列表。
3. reset 清空此前激活状态。
4. 坏事件只记录诊断；未知未来事件忽略且不破坏消息恢复。
5. 保持现有孤立 tool result 和不完整尾部修复。

**验证：** 运行 `python -m unittest tests.test_skills_sessions.SkillRecoveryReplayTests tests.test_memory.SessionRecoveryTests`；预期激活重放和原恢复测试均通过。

## T28：定义 Executor 端口并准备调用

**文件：** `src/flickcode/skills/ports.py`、`src/flickcode/skills/executor.py`、`tests/test_skills_executor.py`  
**依赖：** T18、T24、T26

**步骤：**

1. 定义不导入具体 Session 的 `SkillExecutionHost` Protocol。
2. Executor 刷新并锁定当前 `SkillDefinition`。
3. 验证名称、模式、原始输入、父 Session ID 和 AgentMode。
4. 构造不可变 `SkillInvocation`。
5. 为不存在 Skill 和刷新失败保证父状态不变。

**验证：** 运行 `python -m unittest tests.test_skills_executor.InvocationPreparationTests`；预期工具和斜杠来源使用同一准备逻辑。

## T29：实现 Executor 共享激活

**文件：** `src/flickcode/skills/executor.py`、`tests/test_skills_executor.py`  
**依赖：** T19、T25、T28

**步骤：**

1. 只允许 `SHARED` 调用进入共享激活。
2. 调用 Runtime 并转换为 `SkillExecutionResult`。
3. 成功时要求 Host 追加激活或重绑事件。
4. 归档失败只加入诊断，不回滚已经可用的内存会话。
5. 失败时不追加成功事件。

**验证：** 运行 `python -m unittest tests.test_skills_executor.SharedExecutorTests`；预期统一结果、归档事件和失败边界通过。

## T30：构造隔离 Provider、历史与上下文

**文件：** `src/flickcode/skills/executor.py`、`tests/test_skills_executor.py`  
**依赖：** T20、T23、T24、T28

**步骤：**

1. 只允许 `ISOLATED` 进入子会话路径。
2. 用 Turn Selector 复制指定轮次并追加本次输入。
3. 克隆父 ProviderConfig，仅在声明时替换 model。
4. 创建独立 Provider、Context Manager、Permission Engine 和 Runtime。
5. 子 Runtime 只预激活目标 Skill，且总是包含 `load_skill`。

**验证：** 运行 `python -m unittest tests.test_skills_executor.IsolatedContextConstructionTests`；预期 history=0/N、模型覆盖和父状态隔离通过。

## T31：运行并持久化子 Agent Loop

**文件：** `src/flickcode/skills/executor.py`、`tests/test_skills_executor.py`  
**依赖：** T15、T26、T30

**步骤：**

1. 在开始前写 `skill_child_started`。
2. 将子消息通过 child journal 追加。
3. 用子 Runtime 的 Prompt 和工具视图运行 Agent Loop。
4. 收集 stop reason、最终助手文本、usage 和诊断。
5. 无论成功、失败或取消都写 `skill_child_finished`。

**验证：** 运行 `python -m unittest tests.test_skills_executor.IsolatedAgentLoopTests`；预期子消息完整落盘且每条路径都有终态。

## T32：生成并限制独立摘要

**文件：** `src/flickcode/skills/executor.py`、`tests/test_skills_executor.py`  
**依赖：** T31

**步骤：**

1. 为子 Prompt 增加结果、改动、失败和后续事项交接约束。
2. 正常结束时采用最终交接文本。
3. Provider/权限/超时/最大轮次时本地构造失败摘要。
4. 将摘要限制为 8192 字符，截断时附 child ID。
5. 不触发父或子长期记忆更新。

**验证：** 运行 `python -m unittest tests.test_skills_executor.IsolatedSummaryTests`；预期成功、失败、截断和无记忆调度通过。

## T33：实现系统级 load_skill

**文件：** `src/flickcode/skills/load_tool.py`、`src/flickcode/skills/__init__.py`、`tests/test_skills_executor.py`  
**依赖：** T29、T32

**步骤：**

1. 定义 name 必填、input 可选的完整 object schema。
2. 共享模式返回激活确认。
3. 独立模式同步运行并返回摘要与 child ID。
4. 将所有准备/执行错误转换为 `ToolResult`。
5. 标记为系统只读操作，供权限与 mode 过滤识别。

**验证：** 运行 `python -m unittest tests.test_skills_executor.LoadSkillToolTests`；预期两种模式、缺参数、未知 Skill 和系统可见性通过。

## T34：把命令 registry 分为稳定区与动态区

**文件：** `src/flickcode/commands/registry.py`、`tests/test_commands.py`  
**依赖：** 无

**步骤：**

1. 保持 `register()` 用于稳定命令。
2. 增加独立动态 spec 集合和索引。
3. 实现 `replace_dynamic()`：先完整冲突校验，再一次替换。
4. `resolve/all/help/completions` 读取合并快照。
5. 动态替换失败时稳定区和旧动态区均不变。

**验证：** 运行 `python -m unittest tests.test_commands.DynamicRegistryTests`；预期替换、删除、帮助、补全和回滚通过。

## T35：生成动态 Skill 命令

**文件：** `src/flickcode/skills/commands.py`、`tests/test_skills_commands.py`  
**依赖：** T9、T34

**步骤：**

1. 为每个有效 Skill 构造 `/<name>` CommandSpec。
2. 描述、模式和参数用法来自同一 Catalog 快照。
3. handler 保留原始参数并调用 `ui.run_skill()`。
4. 实现 `prepare()` 和 `commit()`，不在 prepare 阶段修改 registry。
5. 为新增、删除、覆盖和冲突回滚增加测试。

**验证：** 运行 `python -m unittest tests.test_skills_commands.SkillCommandManagerTests`；预期 AC11 的注册和事务通过。

## T36：扩展 CommandUI Skill 调用端口

**文件：** `src/flickcode/commands/adapters.py`、`tests/test_commands.py`、`tests/test_command_integration.py`  
**依赖：** T35

**步骤：**

1. 在 Protocol 增加 `run_skill(name, input, mode)`。
2. InMemory UI 记录名称、原始输入和 AgentMode。
3. 不改变现有 `send_user_message()` 语义。
4. 更新 fake UI 与类型导入，避免引入 Session 循环。
5. 测试多行与连续空格不被 adapter 改写。

**验证：** 运行 `python -m unittest tests.test_commands.UIProtocolTests tests.test_command_integration.SkillCommandUIIntegrationTests`；预期端口记录和既有 UI 行为通过。

## T37：在输入与补全前刷新 Skill

**文件：** `src/flickcode/commands/dispatcher.py`、`src/flickcode/tui.py`、`tests/test_skills_commands.py`  
**依赖：** T35、T36

**步骤：**

1. 为 Input Router 增加可选 before-handle 回调。
2. 在空输入判断之后、命令解析之前执行刷新。
3. 为 Command Completer 增加 before-complete 回调。
4. 刷新错误保留旧命令并进入诊断，不使输入或补全崩溃。
5. 确认一次提交和一次补全各只刷新一次。

**验证：** 运行 `python -m unittest tests.test_skills_commands.RefreshHookTests`；预期新增命令下一次输入/补全可见，失败时旧快照仍可用。

## T38：迁移 review 并增加 reset、audit、status

**文件：** `src/flickcode/commands/builtin.py`、`tests/test_commands.py`、`tests/test_command_integration.py`  
**依赖：** T35、T36

**步骤：**

1. 从稳定内置列表移除硬编码 `review`。
2. 增加 `reset` handler，调用 Session reset 并将 UI mode 设回 DEFAULT。
3. 增加 `audit` 兼容 handler，委托当前有效 `review` Skill。
4. 扩展 `status` 显示有效/激活 Skill、来源、白名单和最近刷新。
5. 保持 `clear` 只清屏。

**验证：** 运行 `python -m unittest tests.test_commands.BuiltinCommandTests tests.test_command_integration.SkillBuiltinCommandTests`；预期只有动态 `/review`、`/audit` 可用且 clear/reset 语义分离。

## T39：在 Session 启动时装配 Skill 系统

**文件：** `src/flickcode/session.py`、`tests/test_skills_integration.py`  
**依赖：** T10、T18、T28、T33、T34、T35、T38

**步骤：**

1. 在基础与 MCP 工具发现后创建稳定命令 registry。
2. 构造三级 Catalog 根目录并准备初始候选。
3. 用实际工具名和保留命令做启动校验。
4. 创建 Runtime、Executor、`load_skill` 并提交动态命令。
5. 启动致命错误在输入循环前抛出；解析诊断进入 Session 队列。

**验证：** 运行 `python -m unittest tests.test_skills_integration.SkillStartupIntegrationTests`；预期两阶段目录建立、MCP 名称校验和启动错误边界通过。

## T40：把 Skill Prompt 与工具视图接入 Session

**文件：** `src/flickcode/session.py`、`src/flickcode/prompt/sections.py`、`tests/test_skills_integration.py`  
**依赖：** T14、T20、T23、T39

**步骤：**

1. 将两个 Skill Section 加入默认 Prompt Builder。
2. 在 `_prompt_context()` 合并 Runtime 的目录和激活数据。
3. 给 Agent Loop 传入 Runtime tool view provider。
4. Context compact/status 使用当前视图而不是全局 registry。
5. 无激活 Skill 时比较旧 Prompt 与普通工具行为。

**验证：** 运行 `python -m unittest tests.test_skills_integration.SkillPromptToolIntegrationTests tests.test_context`；预期每轮 SOP/工具同步且旧上下文测试通过。

## T41：实现 Session 热更新事务

**文件：** `src/flickcode/session.py`、`src/flickcode/skills/runtime.py`、`src/flickcode/skills/commands.py`、`tests/test_skills_integration.py`  
**依赖：** T22、T35、T39

**步骤：**

1. 实现 `Session.refresh_skills()`。
2. 依次准备 Catalog、Runtime 和动态命令候选。
3. 全部通过后按一个请求边界提交三者。
4. 提交后追加来源切换/停用诊断和必要归档事件。
5. 任一步骤失败时三个当前快照均保持不变。

**验证：** 运行 `python -m unittest tests.test_skills_integration.SkillRefreshTransactionTests`；预期新增、有效修改、半写入、删除回退和冲突回滚通过。

## T42：实现 Session 共享 Skill 调用

**文件：** `src/flickcode/session.py`、`tests/test_skills_integration.py`  
**依赖：** T29、T36、T40、T41

**步骤：**

1. 实现 `Session.invoke_skill()` 的共享分支。
2. 通过 Executor prepare/activate，不复制命令语义。
3. 激活后将原始参数交给 `agent_chat()`。
4. 无参数时保留空字符串调用。
5. 保证工具来源和斜杠来源都使用同一激活记录。

**验证：** 运行 `python -m unittest tests.test_skills_integration.SharedSkillInvocationTests`；预期 AC7、AC9 及多轮持续激活通过。

## T43：实现 Session 独立 Skill 调用

**文件：** `src/flickcode/session.py`、`tests/test_skills_integration.py`  
**依赖：** T32、T36、T42

**步骤：**

1. 为斜杠来源运行独立 Executor。
2. 父历史追加规范化调用记录和一条助手摘要。
3. 不追加子工具调用或完整消息。
4. 将摘要作为 UI 可消费的 AgentEvent 流输出。
5. load tool 来源继续只通过 ToolResult 回流。

**验证：** 运行 `python -m unittest tests.test_skills_integration.IsolatedSkillInvocationTests`；预期两种来源的主历史形态与父状态隔离通过。

## T44：实现 Session reset

**文件：** `src/flickcode/session.py`、`src/flickcode/skills/runtime.py`、`tests/test_skills_sessions.py`  
**依赖：** T25、T38、T39、T41

**步骤：**

1. 在当前归档追加 reset 事件。
2. 清空 Runtime 激活、主消息和 PlanContext。
3. 创建新 Context Manager 与 Session ID。
4. 保留 Catalog、动态命令、Provider、MCP 和长期记忆。
5. 归档写失败时记录诊断但仍完成明确请求的内存 reset。

**验证：** 运行 `python -m unittest tests.test_skills_sessions.SessionResetTests`；预期 AC14 全部状态和保留项准确。

## T45：恢复主会话激活状态

**文件：** `src/flickcode/session.py`、`src/flickcode/skills/runtime.py`、`src/flickcode/sessions/recovery.py`、`tests/test_skills_sessions.py`  
**依赖：** T27、T41、T44

**步骤：**

1. 恢复前刷新 Catalog 并读取归档激活引用。
2. 按当前定义重建 Runtime 候选。
3. 来源变化时采用当前来源并记录诊断。
4. 缺失定义时跳过；不读取归档 SOP 或执行脚本。
5. 消息预算和 Runtime 均准备成功后一次提交恢复状态。

**验证：** 运行 `python -m unittest tests.test_skills_sessions.SessionSkillResumeTests tests.test_memory.SessionRecoveryTests`；预期 AC15 和既有恢复回归通过。

## T46：统一 Session.chat 与 Agent Loop

**文件：** `src/flickcode/session.py`、`tests/test_context.py`、`tests/test_memory.py`  
**依赖：** T40

**步骤：**

1. 将 `chat()` 改为 `agent_chat(FULL)` 的 StreamEvent 兼容适配。
2. 保留 text/thinking/tool/done/error 的对外事件类型。
3. 删除或停用重复单轮工具执行路径。
4. 确认 Context Manager 统计和记忆调度只发生一次。
5. 更新只依赖旧单轮内部细节的测试。

**验证：** 运行 `python -m unittest tests.test_context tests.test_memory`；预期原 Chat/Agent 行为、上下文和记忆测试通过。

## T47：接入 TUI 与 Pipe 动态命令

**文件：** `src/flickcode/tui.py`、`tests/test_command_integration.py`、`tests/test_skills_integration.py`  
**依赖：** T37、T42、T43、T44

**步骤：**

1. TUI/Pipe 使用 `session.command_registry`，不自行构建 registry。
2. Input Router 与 Completer 绑定 Session refresh。
3. TUICommandUI/PipeCommandUI 实现 `run_skill()`。
4. 共享调用消费主 AgentEvent；独立调用只显示摘要与诊断。
5. 保留 Ctrl+C、Ctrl+D、高风险确认和既有命令行为。

**验证：** 运行 `python -m unittest tests.test_command_integration tests.test_skills_integration.SkillTUIPipeTests`；预期两个入口的发现、参数和执行模式一致。

## T48：编写 commit 与 test 内置 Skill

**文件：** `src/flickcode/skills/builtins/commit.md`、`src/flickcode/skills/builtins/test.md`、`tests/test_skills_integration.py`  
**依赖：** T4、T10

**步骤：**

1. commit 使用共享模式和最小 Git 读取/执行工具白名单。
2. test 使用共享模式和查找、读取、执行测试所需白名单。
3. 两个正文包含清晰 SOP 和 `{{input}}`。
4. 不声明模型或 history。
5. 通过普通 Parser 和 Validator 测试，不使用硬编码定义。

**验证：** 运行 `python -m unittest tests.test_skills_integration.BuiltinSharedSkillTests`；预期两个样板有效、可覆盖且白名单最小。

## T49：编写 review 目录型内置 Skill

**文件：** `src/flickcode/skills/builtins/review/SKILL.md`、`tools/project_snapshot.json`、`scripts/project_snapshot.py`、`tests/test_skills_integration.py`  
**依赖：** T5、T17

**步骤：**

1. review 使用独立模式、只读白名单和明确 history。
2. 定义 `review_project_snapshot` 的 object schema。
3. 脚本只统计项目文件扩展名、数量和字节数。
4. 排除符号链接，不修改文件、不访问网络、不调用 Git。
5. 让测试通过实际 `SkillScriptTool` 执行该工具。

**验证：** 运行 `python -m unittest tests.test_skills_integration.BuiltinReviewSkillTests`；预期 `/review` 定义有效、专属工具只读并返回稳定统计。

## T50：打包内置资源并更新 README

**文件：** `pyproject.toml`、`README.md`、`tests/test_skills_integration.py`  
**依赖：** T48、T49

**步骤：**

1. 配置 wheel 包含内置 `.md`、`.json` 和脚本。
2. README 说明三级路径、格式、字段和目录型布局。
3. 说明两阶段加载、共享/独立模式、白名单并集和 `load_skill`。
4. 说明动态命令、热更新、`/clear`、`/reset` 和子归档。
5. 明确市场与版本管理不在本阶段。

**验证：** 运行 `python -m unittest tests.test_skills_integration.SkillPackagingDocumentationTests`；预期构建资源清单和 README 关键行为检查通过。

## T51：验证启动、解析隔离与两阶段加载

**文件：** `tests/test_skills_integration.py`  
**依赖：** T39、T40、T48、T49

**步骤：**

1. 用临时项目/用户目录和内置目录启动 fake Session。
2. 同时放置无效、覆盖和有效 Skill。
3. 断言首轮 Prompt 只有名称/说明。
4. 加载后断言完整 SOP 和专属 schema 下一轮出现。
5. 验证未知白名单工具在输入循环前失败。

**验证：** 运行 `python -m unittest tests.test_skills_integration.TwoPhaseStartupEndToEndTests`；预期 AC2–AC6、AC16 的启动部分通过。

## T52：验证共享组合与热更新端到端

**文件：** `tests/test_skills_integration.py`  
**依赖：** T41、T42、T47

**步骤：**

1. 激活两个白名单不同的共享 Skill。
2. 断言每轮完整 SOP 顺序稳定且工具取并集。
3. 重绑其中一个，断言位置不变。
4. 修改、半写入、删除和添加回退定义。
5. 验证执行中旧快照、下一轮新快照及冲突回滚。

**验证：** 运行 `python -m unittest tests.test_skills_integration.SharedHotReloadEndToEndTests`；预期 AC7–AC9、AC12–AC13 通过。

## T53：验证独立模式与 Provider 格式端到端

**文件：** `tests/test_skills_integration.py`  
**依赖：** T43、T47、T49

**步骤：**

1. 建立含工具调用的三轮父历史并运行 history=2 Skill。
2. 断言子历史完整、模型覆盖仅在子 Provider。
3. 分别验证成功、Provider 失败和最大轮次。
4. 断言父历史只有调用/摘要，children 归档包含完整过程。
5. 在 Anthropic 与 OpenAI schema 下各执行一个专属工具调用。

**验证：** 运行 `python -m unittest tests.test_skills_integration.IsolatedProviderEndToEndTests`；预期 AC10、AC16、AC18 通过。

## T54：完成全量回归与质量检查

**文件：** 所有新增/修改文件  
**依赖：** T45、T46、T47、T50、T51、T52、T53

**步骤：**

1. 运行全部 unittest，记录并修复失败。
2. 运行 compileall 检查语法和导入。
3. 单独导入 Skill 公共接口、Session、ToolRegistryView。
4. 运行 CLI help，确认无配置读取副作用。
5. 搜索未使用的旧硬编码 review 路径、未完成标记和调试输出。
6. 重新运行全部测试，保留实际证据给 checklist。

**验证：** 运行 `python -m unittest discover -s tests -p "test*.py"`、`python -m compileall -q src tests`、`python -c "from flickcode.skills import SkillRuntime; from flickcode.session import Session; from flickcode.tools import ToolRegistryView; print('imports ok')"`、`python -m flickcode --help`；预期全部退出码为 0。

## 执行顺序

```text
T1 → T2 → T3 → T4 ─┬→ T5 → T6 ─┬→ T7 → T8 → T9 → T10 → T11
                    │             │
                    │             └→ T16 → T17
                    └───────────────────────────────┐

T12 → T13 → T14 → T15                            │
                                                  ▼
T9 + T11 + T13 → T18 → T19 → T20 → T21 → T22 → T41
                         └→ T23

T1 → T24
T1 → T25 → T26
          └→ T27

T18 + T24 + T26 → T28
T19 + T25 + T28 ─────→ T29
T20 + T23 + T24 + T28 → T30 → T31 → T32 → T33

T34 → T35 → T36 → T37
              └──────→ T38

T11 + T18 + T28 + T33 + T34 + T35 + T38 → T39 → T40
                                             ├→ T42 → T43
T22 + T35 + T39 ─────────────────────→ T41 ─┤
T25 + T38 + T39 + T41 ───────────────→ T44 → T45
T40 ─────────────────────────────────→ T46
T37 + T42 + T43 + T44 ───────────────→ T47

T4 + T10 → T48
T5 + T17 → T49
T48 + T49 → T50

T39 + T40 + T48 + T49 → T51
T41 + T42 + T47 → T52
T43 + T47 + T49 → T53
T45 + T46 + T47 + T50 + T51 + T52 + T53 → T54
```

可并行任务：

- T7 与 T16 可在 Parser 基础完成后并行。
- T12–T15 可与 Catalog/Validator 工作并行。
- T23、T24、T25 可在各自依赖满足后并行。
- T29 与 T30 可在 T28 后并行准备。
- T34–T38 可与 Executor 开发并行。
- T48 与 T49 可并行。
- T51、T52、T53 在各自集成依赖满足后可并行。

## 任务自检

- Plan 中每个新组件至少对应一个实现任务和一个验证任务。
- F1–F14 分别由 T1–T53 覆盖；全量收口由 T54 完成。
- 每个任务给出具体文件、依赖、步骤和可执行验证。
- 依赖链不存在循环，Session 装配发生在低层模块完成之后。
- Catalog/Runtime/动态命令事务在 T9、T21、T35、T41 分层验证。
- 共享和独立模式均包含单元、集成和端到端验证。
- 脚本快照、路径、环境、超时和脱敏均有专门任务。
- 没有市场、版本、远程分发或命名参数任务。
