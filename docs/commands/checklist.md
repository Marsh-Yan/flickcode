# FlickCode 命令注册与分发 Checklist

> 每一项都必须通过运行测试、编译命令或观察可见行为来勾选。实现阶段应记录实际结果和证据，不以代码阅读或“应该可以”代替验证。

## 实现完整性

- [ ] [命令模型] `CommandType`、`InteractionMode`、`CommandSpec`、`ParsedCommand`、`CommandContext`、`CommandResult` 和 `TokenStatus` 已实现并可从 commands 公共包导入（验证：`python -c "from flickcode.commands import CommandSpec, CommandType, InteractionMode, ParsedCommand, CommandResult"`）。
- [ ] [命令注册中心] 默认 registry 已注册十个高频命令及兼容命令（验证：运行 registry 枚举测试，确认 `help/compact/clear/plan/do/session/memory/permission/status/review` 和 `resume/exit` 存在）。
- [ ] [唯一元数据来源] 帮助、解析、补全和冲突检查均从同一个 registry 读取，没有第二份命令列表（验证：集成测试替换 registry 后，帮助与补全候选同步变化）。
- [ ] [处理器隔离] 命令核心不直接导入 `prompt_toolkit`、Rich Renderer 或真实 Provider（验证：检查 commands 模块依赖，运行纯命令单元测试时不创建终端或 Provider）。
- [ ] [统一输入入口] TUI 回车和 pipe 行输入均调用同一个 `InputRouter.handle()`（验证：集成测试对两种入口注入相同输入，比较命令名、参数、Agent 调用次数和模式变化）。
- [ ] [启动校验] 默认 registry 在第一个输入前完成 `validate()`（验证：启动装配测试使用冲突 registry，确认进程在读取输入前报告致命错误）。

## 注册、解析与帮助

- [ ] [AC1 冲突快速失败] 两个规范名称、两个别名、规范名称与别名、大小写不同的名称发生冲突时，注册立即抛出 `CommandRegistrationError` 并指出冲突词（验证：运行冲突测试，确认异常发生在 `register()`，不是 `resolve()`）。
- [ ] [大小写不敏感] `/STATUS`、`/Status`、`/status` 和对应别名解析为同一个 `CommandSpec`（验证：解析与 registry 测试）。
- [ ] [参数保留] `/STATUS arg  text` 的命令名为 `status`，参数保留内部双空格；多行参数不被截断（验证：Parser 测试比较完整参数字符串）。
- [ ] [空输入] 空字符串、只含空格或换行的输入直接返回，不调用 handler 和 Agent（验证：Router fake 记录调用次数为 0）。
- [ ] [普通文本] 不以 `/` 开头的非空输入不解析为命令，并按当前模式发送给 Agent（验证：Router 测试记录 `AgentMode.FULL`/`PLAN`）。
- [ ] [斜杠边界] `/` 和只含命令分隔空白的输入显示命令格式错误，不进入 Agent（验证：Router 测试检查错误消息和 Agent 调用次数）。
- [ ] [未知命令] `/unknown` 和 `/unknown args` 显示未知命令及 `/help` 引导，交互循环继续（验证：Dispatcher 测试确认 `continue_loop=True` 且无 Agent 调用）。
- [ ] [AC3 帮助列表] `/help` 显示十个高频命令的规范名称、别名、描述、用法，并标识本地/UI/提示词类型（验证：命令输出捕获测试）。
- [ ] [帮助隐藏过滤] `hidden=True` 的命令不出现在 `/help` 列表和补全候选中，但仍可通过精确名称解析（验证：Registry 测试）。
- [ ] [帮助详情] `/help STATUS` 和 `/help` 的别名查询显示 `/status` 详情；未知帮助对象显示错误并引导 `/help`（验证：Help handler 测试）。

## 补全

- [ ] [AC4 单候选] 在 `/st` 后 Tab 直接补全为 `/status`，不调用 Agent（验证：prompt_toolkit completer 测试，检查 completion text 和 start position）。
- [ ] [多候选菜单] 在共享前缀存在多个可见命令时，补全器返回全部候选而不是自动选中第一个（验证：Completion 测试检查候选集合）。
- [ ] [别名补全] 别名前缀可以被解析；如果作为候选展示，展示名称与 registry 保持一致（验证：别名 completion 测试）。
- [ ] [无候选不改写] 无匹配前缀时补全器返回空，不改变 buffer 文本（验证：Completion 测试）。
- [ ] [参数区域停止] 光标位于第一个空白之后时不再返回命令名候选，参数原文保持不变（验证：Completion 测试）。

## 三类执行路径

- [ ] [LOCAL 路径] `/help`、`/session`、`/memory`、`/permission`、`/status` 执行本地 handler，不调用 `send_user_message()`（验证：Memory UI fake 检查 Agent 调用次数）。
- [ ] [UI_STATE 路径] `/clear` 只调用 `clear_display()` 和状态刷新，不删除 Session 历史、计划上下文或文件（验证：fake Session 前后状态比较）。
- [ ] [PROMPT 路径] `/plan <task>`、`/do`、`/review` 通过统一 `send_user_message()` 发送预设意图，而非重新进入普通文本分支（验证：fake UI 记录完整发送文本和 Agent mode）。
- [ ] [本地命令低开销] LOCAL/UI_STATE 命令不额外调用 LLM 或 Provider（验证：FakeProvider calls 保持为空）。
- [ ] [异常边界] handler 抛出普通异常时显示错误、返回继续循环；注册冲突仍在启动阶段抛出（验证：Dispatcher 和启动装配测试）。

## 模式和状态栏

- [ ] [AC5 UI 抽象] Memory UI fake 能观察消息、进度、错误、Agent 发送、模式读写、Token 查询、状态刷新和清屏调用（验证：`test_commands` UI 端口测试）。
- [ ] [AC6 默认模式] 会话初始化后的状态标签为 `[DEFAULT]`（验证：TUI/pipe adapter 初始化测试）。
- [ ] [无参 `/plan`] 执行 `/plan` 后标签变为 `[PLAN]`，不调用 Provider，后续普通文本使用 `AgentMode.PLAN`（验证：模式集成测试）。
- [ ] [带参 `/plan`] 执行 `/plan <task>` 后先切换 `[PLAN]`，再以 `AgentMode.PLAN` 发送原始任务并保留计划上下文（验证：FakeProvider/Session 集成测试）。
- [ ] [有计划 `/do`] 有 `plan_context` 时 `/do` 切换 `[DEFAULT]`，以 `AgentMode.EXECUTE` 发送 `Execute the plan.`，并复用已有计划（验证：Do handler 测试）。
- [ ] [无计划 `/do`] 没有 `plan_context` 时 `/do` 只显示错误，模式保持原值且不调用 Provider（验证：Do handler 测试）。
- [ ] [执行失败保留状态] `/do` 的 Agent 失败后计划上下文仍存在，用户可以再次 `/do` 或发送普通输入（验证：失败 fake Provider 集成测试）。
- [ ] [状态立即刷新] 每次模式变化后状态栏/pipe 输出立即出现对应标签（验证：适配器调用顺序测试）。

## 内置命令行为

- [ ] [`/compact`] 调用 `Session.compact_context()`，展示真实 action、估算 Token、预算、摘要/工具结果路径和错误；不把 `/compact` 追加到主会话（验证：Fake ContextManager/Session 测试）。
- [ ] [`/clear`] 清理可见界面，不删除或重置 Session messages、plan_context、sessions、memory 或项目文件（验证：临时项目目录状态比较）。
- [ ] [`/session`] 展示当前会话和可恢复会话摘要；空列表有可读提示（验证：Fake Session list 测试）。
- [ ] [`/sessions`] 作为兼容别名保持 `/session` 行为（验证：别名分发测试）。
- [ ] [`/resume`] 保留 `<session-id>` 参数、恢复成功/失败、诊断和路径安全语义（验证：现有 Session recovery 测试 + 命令集成测试）。
- [ ] [`/memory`] 只读展示项目/用户记忆索引和 instruction 诊断，缺失目录不报致命错误，不写入记忆（验证：临时 memory 目录测试）。
- [ ] [`/permission`] 展示当前 PermissionMode 和规则摘要，不修改规则文件，不新增命令级 ACL（验证：规则文件哈希/内容前后比较）。
- [ ] [`/status`] 展示 Provider/model、交互模式、计划上下文、Token/上下文诊断、MCP 数量和会话诊断（验证：状态快照输出测试）。
- [ ] [`/review`] 发送固定审查提示词，参数作为审查关注点追加，固定使用 `AgentMode.FULL`，不把 `/review` 原文重复发送（验证：Fake UI 发送内容测试）。
- [ ] [`/exit`/`/quit`] 返回结束循环结果并保留已有退出确认行为（验证：TUI/pipe 退出集成测试）。

## Session、记忆、权限和安全

- [ ] [状态快照只读] Session 状态快照不会修改 messages、plan_context、ContextState 或会话归档（验证：快照调用前后深比较）。
- [ ] [Token 脱敏] `/status`、`/permission`、`/memory` 和错误消息不包含 Provider API Key、Authorization header 或完整敏感配置（验证：输出扫描测试）。
- [ ] [上下文诊断完整] `/status` 和 `/compact` 能区分 unchanged、stored tool result、compacted、summary failure/circuit-open 和 blocked（验证：构造各类 `ContextDiagnostic` 的输出测试）。
- [ ] [权限路径不绕过] 提示词命令触发的 Agent 工具仍经过既有 PermissionEngine 和高风险确认（验证：Fake Agent tool + permission callback 集成测试）。
- [ ] [未知斜杠安全] 任意未命中的 `/...` 输入都不作为普通用户问题发给 Agent（验证：随机未知命令参数化测试）。
- [ ] [`/clear` 安全] `/clear` 不执行文件删除、不清理会话目录、不修改 memory 目录（验证：临时目录快照和工具调用 mock）。

## 兼容性与集成

- [ ] [AC9 普通对话] 普通用户文本仍能进入现有 Agent Loop，流式文本、tool call、tool result、usage、done 和 error 事件渲染不变（验证：FakeProvider 集成测试）。
- [ ] [兼容会话命令] `/sessions`、`/resume <id>`、`/exit`、`/quit` 在 TUI 和 pipe 中均可用（验证：两种入口的兼容性测试）。
- [ ] [命令历史边界] LOCAL/UI_STATE 命令文本不写入 Session 主对话历史；PROMPT 命令只写入预设用户消息一次（验证：Session.messages 和 Journal 追加事件检查）。
- [ ] [TUI/pipe 一致] 同一输入序列在两种入口的命令解析、别名匹配、模式变化和 Agent 调用次数一致，差异仅限输出格式（验证：共享 fake 场景比较）。
- [ ] [启动无冲突] 默认命令集合在真实应用启动时无名称/别名冲突，首次输入前可成功创建路由器（验证：CLI/TUI 启动装配测试）。
- [ ] [旧功能回归] Context、Memory、MCP、Permission、Session recovery 现有测试全部保持通过（验证：全量 unittest）。

## 编译与测试

- [ ] [命令单元测试] 新增命令模型、解析、registry、dispatcher、内置 handler 和 completer 测试全部通过（验证：`python -m unittest tests.test_commands`）。
- [ ] [命令集成测试] 新增 TUI/pipe、Session snapshot、兼容性和端到端 fake Provider 测试全部通过（验证：`python -m unittest tests.test_command_integration`）。
- [ ] [全量单元测试] 项目现有和新增测试全部通过（验证：`python -m unittest discover -s tests -p 'test*.py'`）。
- [ ] [编译检查] 源码和测试可编译，无语法错误或循环导入导致的导入失败（验证：`python -m compileall src tests`）。
- [ ] [依赖检查] 命令核心在最小 fake 环境可导入，不要求真实 Provider key 或终端（验证：禁用网络/终端的单元测试运行）。
- [ ] [质量检查] 若仓库有既有 lint 配置则运行对应 lint；否则完成未使用导入、公共导出和类型循环的人工/工具检查（验证：记录实际 lint 或检查结果）。

## 端到端场景

- [ ] [场景 1：帮助发现] 启动应用 → 输入 `/help` → 看到十个高频命令、别名、用途和 AI 触发标识；Provider 调用次数为 0（验证：端到端 fake Provider 运行输入序列并断言输出与调用计数）。
- [ ] [场景 2：未知命令] 输入 `/does-not-exist arg` → 看到未知命令和 `/help` 引导 → 应用仍等待下一条输入 → Provider 调用次数不变（验证：端到端 fake UI/Provider 检查错误、`continue_loop` 和调用计数）。
- [ ] [场景 3：计划模式] 启动显示 `[DEFAULT]` → 输入 `/plan` → 显示 `[PLAN]` → 输入普通任务 → Agent 以 PLAN mode 处理（验证：端到端模式序列断言状态输出和 Agent mode）。
- [ ] [场景 4：立即规划] 输入 `/plan add a parser` → 显示规划过程 → 产生 PlanContext → 保持 `[PLAN]`（验证：FakeProvider 返回规划事件后检查 Session.plan_context 和模式）。
- [ ] [场景 5：执行计划] 存在 PlanContext → 输入 `/do` → 显示 `[DEFAULT]` → Agent 以 EXECUTE mode 执行已有计划（验证：端到端 fake Provider 检查固定意图、Agent mode 和模式标签）。
- [ ] [场景 6：清屏安全] 有会话历史和计划上下文 → 输入 `/clear` → 终端显示被清理 → 再输入 `/status` 仍能看到会话/计划状态（验证：临时 Session/UI fake 比较清屏前后状态和后续 status 输出）。
- [ ] [场景 7：上下文压缩] 构造可压缩历史 → 输入 `/compact` → 看到压缩 action、Token 估算和路径 → `/compact` 文本未进入主会话（验证：Fake ContextManager 和 Session.messages/Journals 断言）。
- [ ] [场景 8：会话恢复] 输入 `/session` 查看归档 → 输入 `/resume <id>` → 成功恢复或显示可诊断失败 → 交互循环继续（验证：临时 SessionJournal 构造归档并运行恢复输入序列）。
- [ ] [场景 9：补全] 输入 `/st` → Tab → 直接出现 `/status`；输入共享前缀 → 展示多候选菜单；输入参数后 → 不再修改参数（验证：prompt_toolkit Completion 对每个 cursor position 断言候选和替换范围）。
- [ ] [场景 10：双入口一致] 用同一输入序列分别运行 TUI fake 和 pipe fake → 命令解析、Agent 调用和模式变化一致，输出渠道不同但语义一致（验证：比较两个适配器记录的规范命令、参数、Agent mode 和状态转换）。

## 验收映射

| Spec 验收标准 | Checklist 覆盖 |
|---|---|
| AC1 启动冲突快速失败 | 注册、解析与帮助 / AC1；启动无冲突 |
| AC2 解析规则正确 | 大小写、参数、空输入、普通文本、斜杠边界、未知命令 |
| AC3 帮助完整且隐藏可控 | AC3 帮助列表、帮助隐藏过滤、帮助详情 |
| AC4 补全行为正确 | AC4 单候选、多候选、别名、无候选、参数区域 |
| AC5 界面抽象可用 | AC5 UI 抽象、TUI/pipe 适配测试 |
| AC6 模式状态正确 | 默认模式、无参/带参 `/plan`、有/无计划 `/do`、状态刷新 |
| AC7 本地命令不进主对话 | 三类执行路径、本地命令低开销、命令历史边界 |
| AC8 提示词命令走统一会话 | PROMPT 路径、`/review`、普通对话和工具事件 |
| AC9 兼容行为保持 | 兼容会话命令、TUI/pipe 一致、旧功能回归 |
| AC10 错误边界正确 | 未知命令、异常边界、启动校验、Token 脱敏 |

## 验收记录

### 通过（5/5）

- [x] 命令核心与内置命令测试通过（证据：`.venv\Scripts\python.exe -m unittest tests.test_commands tests.test_command_integration`，24 tests，OK）。
- [x] 全量测试通过（证据：`.venv\Scripts\python.exe -m unittest discover -s tests -p 'test*.py'`，80 tests，OK，1 skipped）。
- [x] 源码和测试编译通过（证据：`.venv\Scripts\python.exe -m compileall -q src tests`，退出码 0）。
- [x] TUI completer、统一 TUI/pipe router、模式切换和 Session 状态快照已接入（证据：命令集成测试覆盖 `CommandCompleter`、`InputRouter`、`/plan`、`/do`、状态快照）。
- [x] README 已补充 slash command、模式和 Tab 补全说明（证据：README 的 `Slash commands` 小节存在）。

### 未通过/待人工观察

- [ ] 真实交互式终端的清屏、状态栏视觉布局和 Tab 菜单仍需人工运行观察（自动化测试已覆盖路由、候选和调用记录；验证：在真实 TTY 启动 `flick`，执行 `/help`、`/plan`、Tab 和 `/clear`）。
- [ ] 逐项将上方 72 个行为检查映射到产品验收记录（当前自动化证据已覆盖核心路径，剩余项目需在真实 Provider/终端环境复核；验证：按 checklist 逐项执行并填写输出摘要）。

### 环境说明

- 仓库目录没有可用的 Git 元数据，因此未提供 `git diff` 统计；文件和测试结果均直接基于当前工作区验证。
- 全量测试中的 1 个 skipped 为既有测试环境条件，不是本次命令功能失败。
