# 会话恢复与分层记忆 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/flickcode/config.py` | `MemoryConfig`、YAML 解析及默认配置 |
| 新建 | `src/flickcode/memory/__init__.py` | 记忆模块公共导出 |
| 新建 | `src/flickcode/memory/models.py` | 记忆、指令与更新的数据结构 |
| 新建 | `src/flickcode/memory/instructions.py` | 三层 `AGENTS.md` 与安全 include 展开 |
| 新建 | `src/flickcode/memory/notes.py` | frontmatter 笔记、受限索引、原子写入 |
| 新建 | `src/flickcode/memory/updater.py` | LLM 更新提案与后台调度器 |
| 新建 | `src/flickcode/sessions/__init__.py` | 会话模块公共导出 |
| 新建 | `src/flickcode/sessions/journal.py` | JSONL 追加、扫描、列出与清理 |
| 新建 | `src/flickcode/sessions/recovery.py` | JSONL 历史修复与时间提醒 |
| 修改 | `src/flickcode/prompt/sections.py` | 指令和记忆提示 section |
| 修改 | `src/flickcode/prompt/__init__.py` | 导出新增 prompt section |
| 修改 | `src/flickcode/agent.py` | 可选历史追加和 prompt context 回调 |
| 修改 | `src/flickcode/session.py` | 生命周期、归档、恢复、前台提示与异步笔记编排 |
| 修改 | `src/flickcode/tui.py` | `/sessions`、`/resume` 与诊断呈现 |
| 修改 | `tests/test_context.py` | 适配共享 Session/Agent 路径辅助测试 |
| 新建 | `tests/test_memory.py` | 指令、会话、记忆、集成和异步行为测试 |
| 修改 | `README.md` | 用户指令、会话和记忆使用说明 |
| 修改 | `docs/memory/checklist.md` | 实现完成前的可观察验收项 |

## T1：增加记忆配置与默认值

**文件：** `src/flickcode/config.py`  
**依赖：** 无

**步骤：**

1. 定义 `MemoryConfig`，包含 `instruction_filename`、include 最大深度、恢复时间跨度天数、会话过期天数以及索引行数/字节上限。
2. 为正整数配置值添加解析与校验；确保索引上限不能超过 200 行、25 KB 的规范边界。
3. 在 `Config` 中加入 `memory`，并让旧配置在没有 `memory:` 时使用默认值。
4. 在默认 YAML 模板中写出可配置的 include 深度和 7 天时间跨度默认值，保留其余安全限制的默认策略。

**验证：** 在 `tests/test_memory.py` 中以包含和不包含 `memory:` 的临时 YAML 调用 `load_config()`；确认默认值、合法覆盖值和无效值的异常分别正确。

## T2：定义跨模块记忆与归档模型

**文件：** `src/flickcode/memory/models.py`、`src/flickcode/memory/__init__.py`、`src/flickcode/sessions/__init__.py`  
**依赖：** T1

**步骤：**

1. 定义指令、笔记、记忆更新、归档和恢复所需的 dataclass、枚举及诊断类型。
2. 定义四个且仅四个 `MemoryCategory` 值，及受 scope 限制的 `MemoryChange`。
3. 定义 `SessionSummary`、`ResumeResult`、`ArchiveDiagnostic` 和指令/记忆诊断结构，避免用未结构化字符串传递状态。
4. 在两个包的 `__init__.py` 中只导出 Session、提示和测试所需的公共类型，避免循环导入。

**验证：** 运行 `python -m unittest tests.test_memory.MemoryModelTests`；确认允许的类别、默认字段和公共导入可用。

## T3：实现三层指令与受限 include 加载

**文件：** `src/flickcode/memory/instructions.py`、`tests/test_memory.py`  
**依赖：** T1、T2

**步骤：**

1. 实现 `InstructionLoader.load(project_root)`，按项目根、`.flickcode`、用户目录的稳定优先顺序寻找 `AGENTS.md`。
2. 实现行级 `@include` 解析并在原位置展开内容。
3. 使用真实路径解析、`relative_to()`、递归计数和 visited 集合，限制 include 于各自允许根内、阻止循环/重复，并限制深度。
4. 将根文件和 include 的缺失、不可读、非 Markdown、越界、循环和超深情况写入诊断，同时继续收集其他合法内容。
5. 以临时项目根和 mock 用户目录覆盖优先级、嵌套展开、循环、`..` 逃逸和读取错误用例。

**验证：** 运行 `python -m unittest tests.test_memory.InstructionLoaderTests`；确认两个项目文本在用户文本之前、包含内容按位置展开、所有拒绝场景有诊断且没有越界内容。

## T4：实现 JSONL 会话创建、追加与会话列表扫描

**文件：** `src/flickcode/sessions/journal.py`、`tests/test_memory.py`  
**依赖：** T2

**步骤：**

1. 定义会话 ID 正则和生成器，生成 `YYYYMMDD-HHMMSS-xxxx` 格式且在同一秒多次调用时不冲突。
2. 实现 `SessionJournal` 的目录约束、延迟创建、`session_started`/`session_resumed` 事件与消息 JSONL 追加；每次写入 flush 并把写失败转成诊断。
3. 序列化/反序列化内部 `Message` 全部可恢复字段，不复制 Provider 专用格式。
4. 实现独立文件扫描，直接从 JSONL 推导首条用户标题、消息数、最后活动时间与可恢复原因，不产生 meta 文件。
5. 限制扫描对象为 `sessions` 根目录下符合严格 ID 和 `.jsonl` 后缀的普通文件；单文件损坏不影响其他列表条目。

**验证：** 运行 `python -m unittest tests.test_memory.SessionJournalTests`；确认文件逐行追加、没有 meta 文件、列表字段可推导、损坏文件和非会话文件被隔离处理。

## T5：实现会话恢复修复、时间提醒与 30 天清理

**文件：** `src/flickcode/sessions/recovery.py`、`src/flickcode/sessions/journal.py`、`tests/test_memory.py`  
**依赖：** T4

**步骤：**

1. 实现按行 JSONL 反序列化，跳过无效 JSON、未知事件、无效时间或不完整消息，并生成带行号诊断。
2. 实现工具调用完整性状态机：跳过孤立 tool 结果；当工具调用缺少结果时，删除该 assistant 调用和之后的消息。
3. 根据最后活动时间，在超过默认 7 天或配置阈值时追加仅内存存在的时间跨度提醒。
4. 实现 `prune_expired(active_session_id)`，只处理命名合法的归档文件；在删除前根据最后活动时间或回退修改时间判定是否超过 30 天，且始终跳过当前活动会话。
5. 为坏行、缺失工具结果、孤立工具结果、完整工具批次、7 天边界、非法会话 ID、过期/保留/当前会话清理添加测试。

**验证：** 运行 `python -m unittest tests.test_memory.SessionRecoveryTests`；确认输出 history 是合法工具序列，且恢复和清理均不会访问或删除目录外文件。

## T6：实现分层 Markdown 笔记、索引与原子更新

**文件：** `src/flickcode/memory/notes.py`、`tests/test_memory.py`  
**依赖：** T1、T2

**步骤：**

1. 实现 `MemoryRepository` 的项目/用户根目录初始化、`index.md` 读取、frontmatter 笔记解析和诊断。
2. 实现仅接受允许类别、有效 ID 和非空正文的 `MemoryChange` 应用逻辑；未知更新 ID、错误 scope 或无效笔记不写入文件。
3. 使用同目录临时文件和原子替换写入单个笔记；以目录粒度锁保证同一 repository 的应用与索引重建串行。
4. 从有效笔记稳定重建索引，按最近更新时间排序；在写入前确保索引不超过 200 行和 25 KB，笔记文件本身不可因索引裁剪而删除。
5. 测试用户与项目仓库互不影响、frontmatter round-trip、无效变更拒绝、索引读错不阻断、行数/字节双上限和索引裁剪后原笔记仍存在。

**验证：** 运行 `python -m unittest tests.test_memory.MemoryRepositoryTests`；确认更新结果、索引上限及所有笔记文件的保留状态。

## T7：实现受 schema 约束的 LLM 笔记更新与异步调度

**文件：** `src/flickcode/memory/updater.py`、`tests/test_memory.py`  
**依赖：** T2、T6

**步骤：**

1. 定义无工具的更新 system prompt，要求模型以 JSON 变更数组输出，并要求按用户偏好、纠正反馈、项目知识、参考资料四类判断、去重和 scope。
2. 实现 `MemoryUpdateClient.propose()`，向 Provider 传递本轮消息快照及已存在的两套笔记，解析 text/done/error 流，验证 JSON、scope、action、类别、ID 和内容限制。
3. 实现单线程 `MemoryUpdateScheduler`：捕获消息快照，在后台依次调用 client 并把验证变更应用到两个 repository；将错误写入线程安全诊断队列。
4. 实现非阻塞关闭，确保后台失败不会向前台生成器抛出异常。
5. 使用 fake provider 测试有效更新、重复 `discard`、非法 LLM 输出、Provider 错误、执行顺序和 `submit()` 不等待 Provider 返回。

**验证：** 运行 `python -m unittest tests.test_memory.MemoryUpdaterTests`；确认只有验证通过的变更落盘，且前台调用不会等待后台 Provider 响应。

## T8：增加项目指令与记忆索引的系统提示 section

**文件：** `src/flickcode/prompt/sections.py`、`src/flickcode/prompt/__init__.py`、`tests/test_memory.py`  
**依赖：** T3、T6

**步骤：**

1. 新增项目指令、用户指令、项目记忆和用户记忆四个 `PromptSection`，从 builder context 读取对应字符串。
2. 使用优先级 1、2、80、81，确保项目规则和项目记忆均位于用户同类内容前；记忆 section 明确标注为参考事实，不能覆盖当前用户请求或系统规则。
3. 空文本不渲染，避免未配置记忆或指令改变现有系统提示。
4. 导出新增 section，并测试渲染顺序、空内容行为及“记忆不是可执行指令”的边界文本。

**验证：** 运行 `python -m unittest tests.test_memory.PromptMemorySectionTests`；确认 `SystemPromptBuilder.build()` 的稳定 prompt 顺序与边界说明正确。

## T9：为 Agent Loop 提供可选的 Session 回调

**文件：** `src/flickcode/agent.py`、`tests/test_context.py`、`tests/test_memory.py`  
**依赖：** T8

**步骤：**

1. 扩展 `AgentLoop` 构造参数，支持可选 `append_messages(messages)` 与 `prompt_context_provider(mode, iteration)` 回调，默认均为 `None`。
2. 在每轮 builder 调用前合并 prompt-context 回调返回的字典，同时保留现有 mode、iteration 和项目元数据。
3. 通过单一内部追加助手将无工具最终消息、未知工具阈值前保留的消息和成功工具批次交给 `append_messages`；回调缺失时维持原地追加行为。
4. 保证 context preparation、usage 记录、事件顺序和已有独立 `AgentLoop` 调用保持不变。
5. 为回调接收的消息批次、每轮动态 prompt、默认回退路径和无工具 `COMPLETED` 停止条件增加测试。

**验证：** 运行 `python -m unittest tests.test_context.RequestPathIntegrationTests tests.test_memory.AgentLoopCallbackTests`；既有请求路径测试及新增回调测试均通过。

## T10：在 Session 中集成创建、注入、归档与显式恢复

**文件：** `src/flickcode/session.py`、`tests/test_context.py`、`tests/test_memory.py`  
**依赖：** T3、T4、T5、T6、T7、T8、T9

**步骤：**

1. 在 `Session.__init__` 初始化项目根、指令 bundle、用户/项目笔记仓库、journal、未落盘会话 ID、后台调度器和诊断队列；启动时调用受限过期清理，但不恢复任何会话。
2. 注册四个 prompt section，实现每次请求读取两份索引并生成 builder context；指令只使用启动时加载的内容，索引读取失败只进入诊断队列。
3. 实现 `_append_history_messages()`，先扩展内存历史，再逐条追加 JSONL；写入错误不撤销内存消息。
4. 调整 `chat()`，让用户、assistant、thinking 与工具结果经统一追加入口落盘；为纯聊天路径调用同一 prompt builder 并传递 stable system 与短暂动态消息。
5. 调整 `agent_chat()`，通过 T9 回调对用户消息和 Agent 产生消息统一落盘，并让每轮使用动态记忆索引 context。
6. 实现 `list_sessions()`、`resume_session()` 与 `drain_diagnostics()`；恢复使用临时 ContextManager 和当前提示/工具定义进行一次压缩预检，只有成功才替换 messages、上下文管理器和活跃 ID，再追加恢复事件。
7. 包装 Agent `done` 事件：只在 `COMPLETED` 已返回后，提交深拷贝历史至后台更新器；其他停止原因不提交。
8. 扩展 `close()`，关闭 MCP 和后台更新调度器，且多次调用安全。
9. 以 `Session.__new__` 或可注入依赖的测试构造辅助函数覆盖：不自动恢复、两请求路径注入、JSONL 落盘、失败恢复原子性、成功恢复、超预算一次压缩、跨 7 天提醒及异步触发/不触发。

**验证：** 运行 `python -m unittest tests.test_context tests.test_memory.SessionMemoryIntegrationTests`；确认原 context 行为与新增 Session 行为均通过，且 fake Provider 调用记录中的 system prompt 含正确的项目/用户指令与索引顺序。

## T11：实现 `/sessions`、`/resume` 和管道模式命令解析

**文件：** `src/flickcode/tui.py`、`tests/test_memory.py`  
**依赖：** T10

**步骤：**

1. 提取内置命令分发函数，让交互循环和 `_run_piped_loop()` 使用同一逻辑，不把 `/sessions`、`/resume` 发给模型。
2. 新增 `/sessions` 分支，渲染每条 `SessionSummary` 的 ID、标题、消息数、最后活动时间及可恢复状态；扫描诊断显示为错误但不中止循环。
3. 新增 `/resume <会话ID>` 分支；缺参数显示用法，成功显示消息数和修复摘要，失败显示原因且不改变前台会话。
4. 更新欢迎信息，包含两个新增命令。
5. 消费 Session 同步/异步诊断并经 renderer 展示，不干扰标准对话和 `/compact`、`/plan`、`/do`、退出命令。
6. 用 fake Session/Renderer 验证交互和管道模式的列出、恢复、用法错误、失败原子性和现有命令的回归行为。

**验证：** 运行 `python -m unittest tests.test_memory.TUIMemoryCommandTests tests.test_context.TUICompactTests`；确认命令渲染正确、没有命令被 Provider 接收，并且 `/compact` 测试仍通过。

## T12：完成文档、执行完整测试并更新验收结果

**文件：** `README.md`、`docs/memory/checklist.md`、`tests/test_memory.py`、`tests/test_context.py`  
**依赖：** T1–T11

**步骤：**

1. 在 README 说明三层 `AGENTS.md`、受限 `@include`、会话和记忆目录、`/sessions`、`/resume`、7 天提醒、30 天清理、四类自动笔记以及本章不包含 RAG/向量库。
2. 将批准的验收清单逐项映射到实际测试命令和可观察结果；不将实现细节或临时输出作为验收条件。
3. 运行全部 unittest，并修复由本章改动造成的回归失败。
4. 执行 README 中至少一个最小可观察流程：创建/追加会话 → `/sessions` 可见 → 显式恢复；将结果填入 checklist 的验收报告。

**验证：** 运行 `python -m unittest discover -s tests -v`；期望所有测试通过。随后按 `docs/memory/checklist.md` 逐项执行并记录实际证据。

## 执行顺序

```text
T1 ─┬─> T2 ─┬─> T3 ─┬─> T8 ─> T9 ─┐
    │      │       │                │
    │      │       └─> T6 ─> T7 ────┤
    │      └─> T4 ─> T5 ────────────┤
    └────────────────────────────────> T10 ─> T11 ─> T12
```

T3、T4 与 T6 在 T1/T2 完成后可以并行；实现期间仍按每项验证结果再推进后续依赖。
