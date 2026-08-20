# FlickCode 命令注册与分发 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/flickcode/commands/__init__.py` | 导出命令公共接口和默认 registry 工厂。 |
| 新建 | `src/flickcode/commands/models.py` | 命令类型、模式、规格、解析结果、上下文和结果模型。 |
| 新建 | `src/flickcode/commands/parser.py` | 斜杠命令解析。 |
| 新建 | `src/flickcode/commands/registry.py` | 注册、大小写索引、冲突检测、帮助和补全。 |
| 新建 | `src/flickcode/commands/adapters.py` | `CommandUI` Protocol、Token 状态快照及共享适配辅助。 |
| 新建 | `src/flickcode/commands/dispatcher.py` | `InputRouter` 与 `CommandDispatcher`。 |
| 新建 | `src/flickcode/commands/builtin.py` | 十个内置命令及兼容命令。 |
| 修改 | `src/flickcode/session.py` | 提供命令所需的只读状态快照或安全访问方法。 |
| 修改 | `src/flickcode/renderer.py` | 必要的清屏/状态栏展示辅助。 |
| 修改 | `src/flickcode/tui.py` | 统一 TUI/pipe 分流，接入命令 UI、补全和状态栏。 |
| 新建 | `tests/test_commands.py` | 命令模型、解析、注册、帮助、补全和分发单元测试。 |
| 新建 | `tests/test_command_integration.py` | TUI/pipe 共享路由、Session fake、内置命令和兼容行为测试。 |
| 修改 | `README.md` | 更新命令列表、模式标记和补全说明。 |

## T1：建立命令模型和公共包

**文件**：`src/flickcode/commands/models.py`、`src/flickcode/commands/__init__.py`

**依赖**：无

**步骤**：

1. 创建 `CommandType`，包含 `LOCAL`、`UI_STATE`、`PROMPT`。
2. 创建 `InteractionMode`，包含 `DEFAULT`、`PLAN`，并提供展示标签映射 `[DEFAULT]`、`[PLAN]`。
3. 创建 `CommandSpec`，包含规范名称、别名、描述、用法、类型、参数提示、隐藏标记和处理函数。
4. 创建 `ParsedCommand`、`CommandResult`、`CommandContext` 和 `TokenStatus` 数据结构。
5. 为命令处理函数声明统一类型别名，避免 handler 自行解析输入。
6. 校验命令元数据的基本输入：名称/别名不能含 `/` 或空白，展示字段不能是空字符串。
7. 在 `__init__.py` 暴露后续模块会使用的公共类型名称，不在此阶段导入具体内置命令造成循环依赖。

**验证**：运行 `python -m unittest tests.test_commands -k Model`；预期模型构造和基础校验测试通过。

## T2：实现纯命令解析器

**文件**：`src/flickcode/commands/parser.py`、`tests/test_commands.py`

**依赖**：T1

**步骤**：

1. 实现 `CommandParser.parse(raw_input)`。
2. 对 `None` 或只含空白的输入返回空结果，不产生命令。
3. 对普通文本返回非命令结果或由调用方识别为普通文本，不能误切命令。
4. 对 `/STATUS arg  text` 解析出命令名 `status` 和参数 `arg  text`，命令名小写化，参数内部空格保持不变。
5. 对 `/` 和 `/   ` 返回斜杠输入错误，不回退普通文本。
6. 对 `/resume id`、别名和多行参数保留首个空白后的参数内容。

**验证**：运行 `python -m unittest tests.test_commands -k Parser`；预期覆盖空输入、普通输入、大小写、参数和非法斜杠输入。

## T3：实现注册中心和冲突检测

**文件**：`src/flickcode/commands/registry.py`、`tests/test_commands.py`

**依赖**：T1

**步骤**：

1. 实现 `CommandRegistry.register()`，为规范名称和别名建立统一小写索引。
2. 规范名称和别名指向同一个 `CommandSpec`，不复制元数据。
3. 检测规范名称、别名之间的大小写不敏感冲突，并抛出 `CommandRegistrationError`。
4. 实现 `resolve()`、`all(include_hidden)` 和稳定顺序的可见命令读取。
5. 实现 `help_for()`：列出规范名称、别名、描述、用法、参数提示、执行类型和 AI 触发标记。
6. 实现 `completions(prefix)`：不区分大小写匹配，过滤隐藏命令，去重并返回稳定候选。
7. 为重复注册、空名称、空别名和规范名称/别名相撞补充测试。

**验证**：运行 `python -m unittest tests.test_commands -k Registry`；预期冲突在注册时立即失败，帮助和补全不出现隐藏命令。

## T4：定义 CommandUI 端口与状态快照

**文件**：`src/flickcode/commands/adapters.py`、`tests/test_commands.py`

**依赖**：T1

**步骤**：

1. 定义 `CommandUI` Protocol，包含消息、进度、错误、Agent 消息发送、模式读写、Token 状态、状态刷新和清屏接口。
2. 定义不依赖 Rich 的 `TokenStatus` 快照字段，至少覆盖输入/输出/思考 Token、估算输入 Token、预算、余量和上下文诊断文本。
3. 定义命令 UI fake，记录每个调用、发送的 Agent mode 和模式变化，供后续命令测试复用。
4. 确认适配端口类型导入不会引入 `tui.py`、Renderer 或真实 Provider 的循环依赖。

**验证**：运行 `python -m unittest tests.test_commands -k UI`；预期 fake 可以记录清屏、消息、模式、状态刷新和 Agent 发送调用。

## T5：实现分发器和统一输入路由

**文件**：`src/flickcode/commands/dispatcher.py`、`tests/test_commands.py`

**依赖**：T2、T3、T4

**步骤**：

1. 实现 `CommandDispatcher.dispatch()`，按 registry 查找命令并构造 `CommandContext`。
2. 未知命令显示错误和 `/help` 引导，返回已处理结果，不调用 Agent。
3. 处理 handler 普通异常，转换为 UI 错误并让交互循环继续；不吞掉注册阶段异常。
4. 实现 `InputRouter.handle()`：空输入忽略、普通文本按当前交互模式发送、斜杠输入走命令分发。
5. 普通输入在 `[PLAN]` 下发送 `AgentMode.PLAN`，在 `[DEFAULT]` 下发送 `AgentMode.FULL`。
6. handler 执行完成后根据结果刷新状态栏，退出结果可以让入口结束循环。
7. 测试未知命令、普通文本不以命令方式发送、斜杠未知输入不进 Agent、handler 异常不退出循环。

**验证**：运行 `python -m unittest tests.test_commands -k Dispatch`；预期所有分流路径和错误边界通过。

## T6：实现帮助、清屏和压缩命令

**文件**：`src/flickcode/commands/builtin.py`、`tests/test_commands.py`

**依赖**：T3、T4、T5

**步骤**：

1. 创建 `help` handler：无参数列出所有可见命令，有参数查询规范名称或别名。
2. 创建 `clear` handler：只调用 `ui.clear_display()` 和必要的状态刷新，不修改 Session 历史或计划上下文。
3. 创建 `compact` handler：调用 `session.compact_context()`，展示 `ContextPreparation.diagnostic` 的 action、估算、预算、摘要路径、工具结果路径和错误。
4. 确认以上三个命令不调用 `ui.send_user_message()`。
5. 使用 fake Session 和 fake UI 覆盖成功、无可压缩历史、摘要失败/熔断和未知帮助对象。

**验证**：运行 `python -m unittest tests.test_commands -k "Help or Clear or Compact"`；预期本地命令不产生 Agent 调用。

## T7：实现模式、计划和执行命令

**文件**：`src/flickcode/commands/builtin.py`、`tests/test_commands.py`

**依赖**：T5、T6

**步骤**：

1. 创建 `plan` handler：无参数切换 `InteractionMode.PLAN`，不发送 Agent；有参数先切换计划模式，再以 `AgentMode.PLAN` 发送原始任务。
2. 创建 `do` handler：先检查 `session.plan_context`；无计划时报错且模式不变；有计划切换 `[DEFAULT]` 并以 `AgentMode.EXECUTE` 发送固定意图 `Execute the plan.`。
3. 确认 `/plan <task>` 仍由 `Session.agent_chat()` 生成或更新 `PlanContext`，`/do` 不要求重复粘贴计划。
4. 在模式变化后调用 `ui.refresh_status()`，并验证 Agent 失败时保留计划上下文。
5. 覆盖默认模式、计划模式、无参 `/plan`、带参数 `/plan`、有/无计划 `/do` 及大小写调用。

**验证**：运行 `python -m unittest tests.test_commands -k "Plan or Do or Mode"`；预期模式标签和 Agent mode 与设计一致。

## T8：实现会话和恢复命令

**文件**：`src/flickcode/commands/builtin.py`、`tests/test_commands.py`

**依赖**：T4、T5、T6

**步骤**：

1. 创建 `session` handler，调用 `Session.list_sessions()` 展示当前会话与可恢复摘要；注册 `sessions` 兼容别名。
2. 保留 `resume <session-id>` handler，复用 `Session.resume_session()`，维持参数错误、恢复成功/失败和诊断输出。
3. 处理列表为空、恢复参数缺失、恢复失败和诊断输出，不让错误退出交互循环。
4. 确认会话命令不调用 `ui.send_user_message()`，恢复行为只使用现有 Session API。
5. 为当前会话列表、兼容别名和恢复失败补充测试。

**验证**：运行 `python -m unittest tests.test_commands -k "Session or Resume"`；预期会话列表、恢复和兼容别名测试通过，且错误不退出循环。

## T9：实现记忆、权限和状态命令

**文件**：`src/flickcode/commands/builtin.py`、`tests/test_commands.py`

**依赖**：T4、T5、T6

**步骤**：

1. 创建 `memory` handler，只读展示 instruction bundle、项目记忆索引、用户记忆索引及诊断，不写入记忆。
2. 创建 `permission` handler，展示 `PermissionMode` 和现有规则来源/数量；只读调用规则加载接口，不新增命令 ACL。
3. 创建 `status` handler，聚合 Provider 名称/模型、交互模式、计划上下文、Token 快照、上下文诊断、MCP 统计和会话诊断。
4. 如直接读取 Session 内部字段会造成命令层耦合，记录需要的只读快照字段，交给 T11 实现。
5. 为记忆目录缺失、权限规则为空、诊断存在和敏感字段脱敏补充测试。

**验证**：运行 `python -m unittest tests.test_commands -k "Memory or Permission or Status"`；预期命令只读且输出不包含 API Key。

## T10：实现审查、退出和默认注册装配

**文件**：`src/flickcode/commands/builtin.py`、`src/flickcode/commands/__init__.py`、`tests/test_commands.py`

**依赖**：T7、T8、T9

**步骤**：

1. 创建 `review` handler，固定使用审查提示词和 `AgentMode.FULL`，参数作为审查关注点追加。
2. 创建 `exit` handler，并以 `quit` 作为兼容别名；返回 `continue_loop=False`，由入口保留必要的确认交互。
3. 在 `build_default_registry()` 中按稳定顺序注册十个高频命令和兼容命令 `resume`。
4. 注册 `/help` 的 `?` 别名、`/session` 的 `/sessions` 别名和 `/do` 的 `execute` 别名，并验证没有命名冲突。
5. 在 registry 构建完成后显式调用 `validate()`，使启动阶段完成冲突检查。
6. 验证十个高频命令全部可解析、帮助可见、类型和处理函数匹配 spec。

**验证**：运行 `python -m unittest tests.test_commands -k Builtin`；预期默认 registry 注册完整且无冲突。

## T11：接入 Session 只读状态快照

**文件**：`src/flickcode/session.py`、`tests/test_command_integration.py`

**依赖**：T8、T9

**步骤**：

1. 增加返回 Provider、模型、当前 Session ID、计划上下文存在性、权限模式和诊断摘要的只读方法或数据类。
2. 暴露上下文管理器的安全状态：最近估算、预算、余量、最近 action、摘要/工具结果路径和错误。
3. 暴露记忆和 instruction 的只读索引访问结果，保持现有 `MemoryRepository` 和诊断语义。
4. 暴露 MCP 启动报告的数量级统计，不返回 headers、API Key 或其他敏感配置。
5. 为构造最小 fake Session 和真实 Session 空状态分别验证快照稳定，不修改 Session 历史。

**验证**：运行 `python -m unittest tests.test_command_integration -k Snapshot`；预期状态命令需要的信息均可读取且敏感值不出现。

## T12：实现 TUI 命令适配和模式状态

**文件**：`src/flickcode/tui.py`、`src/flickcode/renderer.py`、`tests/test_command_integration.py`

**依赖**：T5、T10、T11

**步骤**：

1. 实现 `TUICommandUI`，把消息/进度/错误映射到现有 Renderer，把 Agent 消息发送映射到 `_consume_agent_events()`。
2. 为 TUI 维护当前 `InteractionMode`，提示符或独立状态栏显示 `[DEFAULT]`/`[PLAN]`，模式变化后立即刷新。
3. 实现清屏适配，不删除 Session 历史、计划上下文、会话归档或项目文件。
4. 保留高风险命令确认、HITL 权限回调、Ctrl+C/Ctrl+D 和退出确认行为。

**验证**：运行 `python -m unittest tests.test_command_integration -k "TUI or Mode"`；使用内存输出或 mock PromptSession 验证适配，不连接真实 Provider。

## T13：迁移 TUI 到统一命令入口

**文件**：`src/flickcode/tui.py`、`tests/test_command_integration.py`

**依赖**：T5、T10、T12

**步骤**：

1. 创建默认 registry、dispatcher 和 router，在进入第一个输入循环前完成注册校验。
2. 删除 TUI 输入循环中按命令名硬编码的旧分支，统一调用 `router.handle()`。
3. 将命令路由异常转换为现有 Renderer 错误，不影响 Ctrl+C/Ctrl+D 和退出确认。
4. 使用 fake UI/Session 验证普通输入、未知命令、本地命令和提示词命令均走统一路由。

**验证**：运行 `python -m unittest tests.test_command_integration -k TUI`；预期 TUI 不再维护按命令名分支。

## T14：接入 Tab 补全

**文件**：`src/flickcode/tui.py`、`tests/test_command_integration.py`

**依赖**：T3、T12、T13

**步骤**：

1. 在创建 `PromptSession` 时接入 `prompt_toolkit` completer 适配器。
2. 只接受当前输入首个非空字符为 `/` 的命令候选，并在第一个空白后停止补全。
3. 调用 `registry.completions(prefix)`，过滤隐藏命令，保持大小写不敏感。
4. 单候选只替换命令 token，多候选交给 prompt_toolkit 展示菜单，不覆盖参数。
5. 为单候选、多候选、无候选、别名前缀、隐藏命令和参数区域补全补充测试。

**验证**：运行 `python -m unittest tests.test_command_integration -k Completion`；预期补全候选与 registry 内容一致。

## T15：迁移 pipe 输入到同一命令入口

**文件**：`src/flickcode/tui.py`、`tests/test_command_integration.py`

**依赖**：T5、T10、T13

**步骤**：

1. 实现 `PipeCommandUI`，复用现有安全 stdout/stderr 输出和 AgentEvent 消费逻辑。
2. 将 `_run_piped_loop()` 的 `/sessions`、`/resume` 和普通文本分支替换为 `router.handle()`。
3. 确保本地命令不连接 Provider；提示词命令复用 `Session.agent_chat()` 和现有事件输出。
4. 在 pipe 模式下输出可观察的 `[PLAN]`/`[DEFAULT]` 状态变化，清屏不假设真实终端。
5. 保留 `/exit`、`/quit`、空行跳过、错误写 stderr 和诊断输出行为。
6. 验证同一批输入在 TUI fake 与 pipe fake 中得到相同的命令匹配、Agent 调用次数和模式变化。

**验证**：运行 `python -m unittest tests.test_command_integration -k Pipe`；预期 pipe 与 TUI 共享同一路由且没有旧分支回归。

## T16：补充兼容性、帮助和文档

**文件**：`README.md`、`tests/test_command_integration.py`

**依赖**：T10、T14、T15

**步骤**：

1. 更新 README 命令表，列出 `/help`、`/compact`、`/clear`、`/plan`、`/do`、`/session`、`/memory`、`/permission`、`/status`、`/review`。
2. 说明 `/plan <task>` 立即规划、无参 `/plan` 切换模式、`/do` 执行已有计划。
3. 说明 `/sessions`、`/resume`、`/exit`、`/quit` 兼容行为和 Tab 补全。
4. 增加端到端 fake Provider 场景：普通对话、未知命令、`/help`、`/plan`、`/do`、`/compact`、会话恢复和退出。
5. 验证命令文本不会被错误追加到主会话历史；只有提示词命令会生成预期用户消息。

**验证**：运行 `python -m unittest tests.test_command_integration -k Compatibility`；预期 README 行为与测试结果一致。

## T17：完成全量测试和质量检查

**文件**：`tests/test_commands.py`、`tests/test_command_integration.py`，必要时修复实现文件

**依赖**：T13、T14、T15、T16

**步骤**：

1. 运行新增命令单元测试和集成测试，记录失败项。
2. 运行现有全量测试，重点关注 `tests/test_context.py`、`tests/test_memory.py`、MCP 和 Session 行为。
3. 运行 `python -m compileall src tests`，确认 Python 3.8 兼容语法未被破坏。
4. 若项目环境提供 lint，运行既有 lint 命令；否则至少检查未使用导入、循环依赖和公共导出。
5. 修复回归后重新运行新增测试与全量测试，不以“代码看起来正确”作为完成依据。
6. 将实际命令输出和结果留给 `checklist.md` 的验收记录，不在 task 文档中提前标记完成。

**验证**：运行 `python -m unittest discover -s tests -p 'test*.py'`、`python -m compileall src tests`；预期全量测试通过且编译无错误。

## 执行顺序

```text
T1 ─┬─> T2 ─┐
    ├─> T3 ─┼─> T5 ─┬─> T6 ─> T7 ─┬─> T10 ─> T11 ─> T12 ─> T13 ─┐
    └─> T4 ─┘       ├─> T8 ───────┤                  └─> T14 ─────┤
                    └─> T9 ───────┘                  └─> T15 ─────┤
                                                                  └─> T16 ─> T17
```

可并行任务：

- T2、T3、T4 在 T1 完成后可并行；
- T2、T3、T4 在 T1 完成后可并行；
- T6、T8、T9 在 T5 完成后可并行；
- T12、T14、T15 在各自前置任务完成后可部分并行；
- T16 必须等待 T13、T14、T15 完成。

## 任务自检

- 每个任务都限定了文件范围、依赖、具体步骤和验证命令。
- 所有 plan 模块均至少对应一个任务；`commands` 核心、内置命令、Session 快照、TUI、pipe、文档和测试均有覆盖。
- 每个任务都引用了已定义的任务编号，未留下模糊的实现步骤。
- TUI 与 pipe 的统一分流在 T11/T12 中分别验证，避免只测试单一入口。
- 每个任务粒度聚焦一个工作单元；T14 只负责最终全量验证和回归收口。
