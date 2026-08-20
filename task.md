# FlickCode 上下文管理 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/flickcode/context/__init__.py` | 导出上下文管理公共类型和入口 |
| 新建 | `src/flickcode/context/models.py` | 配置、状态、诊断、准备结果和枚举 |
| 新建 | `src/flickcode/context/store.py` | 工具结果和摘要安全存盘 |
| 新建 | `src/flickcode/context/estimator.py` | usage 锚点、字符增量估算、历史指纹 |
| 新建 | `src/flickcode/context/summary.py` | 摘要 Prompt、历史序列化、摘要调用与结构校验 |
| 新建 | `src/flickcode/context/compactor.py` | 工具批次识别、轻量预防、消息选择和压缩构造 |
| 新建 | `src/flickcode/context/manager.py` | 预检协调、熔断状态和对外接口 |
| 新建 | `tests/test_context.py` | 单元测试、FakeProvider 集成测试 |
| 修改 | `src/flickcode/config.py` | 读取 `context` 配置节并暴露上下文设置 |
| 修改 | `src/flickcode/session.py` | 创建会话级管理器，接入普通 chat 和手动 compact |
| 修改 | `src/flickcode/agent.py` | Agent Loop 每轮请求前接入和 usage 回写 |
| 修改 | `src/flickcode/tui.py` | `/compact` 命令、状态反馈和欢迎文案 |
| 修改 | `README.md` | `/compact` 和 context 配置说明 |
| 不修改 | `src/flickcode/providers/*.py` | 继续使用现有统一 Provider 接口和协议转换 |

## T1：定义上下文模型与配置

**文件：** `src/flickcode/context/models.py`、`src/flickcode/context/__init__.py`  
**依赖：** 无

**步骤：**

1. 定义 `SafetyMode`，至少包含 `AUTOMATIC` 和 `MANUAL`。
2. 定义 `ContextConfig`，包含窗口、输出预留、工具结果阈值、字符换算、近期保留、重试次数和存储目录。
3. 定义 `ContextState`，包含 usage 锚点、历史指纹、摘要失败计数、熔断状态和最近诊断。
4. 定义 `StoredResult`、`SummaryResult`、`ContextDiagnostic`、`ContextPreparation`。
5. 为可选路径统一转为 `Path`，为可变字段使用 `default_factory`。
6. 在 `__init__.py` 导出公共类型和 `ContextManager` 的延迟入口，避免循环导入。

**验证：**

```powershell
uv run python -c "from flickcode.context import ContextConfig, ContextState, SafetyMode; print(ContextConfig())"
```

预期：成功导入并打印默认配置；不触发 Provider 或文件写入。

## T2：实现上下文结果安全存盘

**文件：** `src/flickcode/context/store.py`  
**依赖：** T1

**步骤：**

1. 实现 `ResultStore`，初始化时创建或延迟创建配置目录。
2. 为工具结果生成包含 session、消息索引、tool call ID 和内容哈希的文件名。
3. 对文件名组件做安全清洗；禁止路径穿越和覆盖已存在文件。
4. 使用 UTF-8 写入完整原文；预览只保留固定短文本和恢复提示。
5. 实现摘要副本存盘，返回路径。
6. 存盘失败抛出可识别异常或返回结构化失败结果，不吞掉原文。
7. 确保重复写入同一结果不会覆盖用户文件。

**验证：** 使用 `TemporaryDirectory` 调用 `ResultStore`，验证生成完整工具结果和摘要文件、内容与输入一致，并模拟写入异常确认原文仍在调用方内存中。

## T3：实现近似 Token 估算与 usage 锚点

**文件：** `src/flickcode/context/estimator.py`  
**依赖：** T1

**步骤：**

1. 实现消息和可选 system/tools 定义的字符计数。
2. 实现无锚点时的全量估算。
3. 实现记录 `input_tokens`、消息数量和历史指纹。
4. 实现锚点后的增量估算；检测历史被替换、压缩或长度回退时重建锚点。
5. 实现自动预算和手动预算计算，扣除输出空间与安全余量。
6. 保持纯本地计算，不导入 tokenizer。
7. 暴露估算明细，供诊断显示。

**验证：** 运行 estimator 单元测试，确认相同锚点下新增消息只增加增量估算、修改旧消息重建估算、自动与手动余量分别为 13000 和 3000。

## T4：实现独立摘要客户端

**文件：** `src/flickcode/context/summary.py`  
**依赖：** T1

**步骤：**

1. 定义六段固定摘要标题和摘要 system Prompt。
2. 实现内部 `Message` 历史到纯文本的序列化，保留角色、消息索引、工具名、调用 ID 和路径信息。
3. 实现 `SummaryClient.summarize()`，只发送一条 user 消息、`tools=None`、摘要 system Prompt。
4. 消费 `text`、`done`、`error` 事件，拼接正式摘要。
5. 检查六段标题；缺少任一标题视为失败。
6. 不把摘要请求消息、usage 或草稿写入主历史。
7. 不调用 `ContextManager`，避免递归预检。

**验证：** 使用 FakeProvider 确认 `tools is None`、仅收到一条 user 消息、Prompt 含“禁止调用工具”和草稿限制；缺少标题的返回被判为失败，正确结构的返回只包含正式摘要。

## T5：实现工具批次识别与压缩算法

**文件：** `src/flickcode/context/compactor.py`  
**依赖：** T1、T2、T3、T4

**步骤：**

1. 实现 assistant tool-call 与 tool result 的关联索引。
2. 将工具调用及结果分组为不可拆分的工具批次。
3. 实现单结果超过阈值时存盘替换为预览。
4. 实现批次合计超过阈值时按结果大小降序存盘。
5. 存盘失败时保留原始结果并返回诊断。
6. 实现从历史尾部反向选择近期消息，目标约 10K Token 且至少 5 条。
7. 保证 assistant/tool 配对不被拆开。
8. 实现摘要消息和普通 user 边界消息的构造。
9. 压缩后重新计算历史指纹，供 estimator 重建锚点。
10. 单次调用最多完成一轮摘要，避免内部无限循环。

**验证：** 使用临时目录和固定消息列表，确认最大工具结果先存盘、用户消息不变、tool 的 role 和 ID 不变、assistant/tool 始终成组、边界消息为 user 角色、近期消息满足目标或最低条数、存盘失败不改变原 tool 内容。

## T6：实现 ContextManager 预检与熔断

**文件：** `src/flickcode/context/manager.py`、`src/flickcode/context/__init__.py`  
**依赖：** T2、T3、T4、T5

**步骤：**

1. 初始化 `ContextManager`、`ContextState`、`ResultStore`、`TokenEstimator`、`SummaryClient`。
2. 实现 `prepare_before_request()`，固定执行轻量扫描、估算、阈值判断和必要摘要。
3. 实现 `record_usage()`，仅记录主 Provider 请求 usage。
4. 实现 `compact()`，强制使用手动安全余量。
5. 实现单次最多 3 次摘要重试和连续失败计数。
6. 第 3 次连续失败后设置熔断；熔断期间不调用摘要 Provider。
7. 摘要成功或 `reset_summary_circuit()` 后清零失败状态。
8. 压缩发生时用 `messages[:]` 同步调用方持有的列表。
9. 超预算且无法安全发送时返回 `blocked=True`，不删除消息。
10. 输出包含估算、余量、存盘路径、摘要路径和阻断原因的结构化诊断。

**验证：** 使用 Fake Summary Provider 验证连续失败三次后熔断、熔断期间调用次数不增加、成功或 reset 后恢复、摘要失败时主消息历史不被覆盖。

## T7：接入 context 配置

**文件：** `src/flickcode/config.py`、`tests/test_context.py`  
**依赖：** T1

**步骤：**

1. 在 `Config` 增加 `context` 配置对象或等价字段。
2. 解析 YAML 的 `context` 节，使用 `ContextConfig` 默认值填充缺省字段。
3. 校验数值字段为正数，安全余量和重试次数满足非负约束。
4. 展开 `storage_dir`，支持 `~`，但不改变已有 Provider/MCP 配置语义。
5. 在默认配置模板中加入 context 配置示例或保持可选。
6. 确保旧配置没有 `context` 节时仍可正常加载。

**验证：**

```powershell
uv run python -m unittest tests.test_context.ContextConfigTests
```

预期：旧配置使用默认值，自定义配置准确覆盖，非法值给出明确错误。

## T8：Session 普通对话接入与 usage 回写

**文件：** `src/flickcode/session.py`  
**依赖：** T6、T7

**步骤：**

1. 在 `Session.__init__` 创建会话级 `ContextManager`，目录和配置来自 `self.config.context`。
2. 在 `chat()` 将用户消息追加后调用 `prepare_before_request()`。
3. 如果返回 `blocked=True`，产生 `StreamEvent("error", ...)` 并不调用 Provider。
4. 使用准备后的消息列表调用现有 `provider.stream_chat()`，保留工具定义和 thinking 参数。
5. 在 `done` 事件解析 usage，并调用 `context_manager.record_usage()`。
6. 工具结果追加到历史后不改工具执行流程；下一次请求前由 ContextManager 扫描并存盘。
7. 增加 `compact_context()` 公共方法，调用 `ContextManager.compact(self.messages)` 并返回诊断或准备结果。
8. 提供上下文诊断访问方式，供 TUI 显示。
9. Provider 或预检失败时保持当前错误事件语义，不吞掉原始历史。

**验证：** 使用 FakeProvider 运行一次普通对话，确认未超阈值时只调用一次 Provider 且不调用摘要、done usage 更新锚点、阻断时 Provider 调用数不增加、工具结果仍按原顺序写回历史。

## T9：Agent Loop 每轮请求接入与 usage 回写

**文件：** `src/flickcode/agent.py`、`src/flickcode/session.py`  
**依赖：** T6、T8

**步骤：**

1. 为 `AgentLoop.__init__` 增加可选 `context_manager` 参数。
2. 每轮构建 whisper/system 后，对主 `messages` 调用 `prepare_before_request()`。
3. 若压缩修改历史，确保 Session 与 AgentLoop 共享的原列表同步更新。
4. 将临时 whisper 消息与准备后的主历史组合成 `call_messages`。
5. 若 `blocked=True`，yield AgentEvent error/done，停止当前 Agent Loop，不调用 Provider。
6. 在每轮 `done` 解析 usage 后调用 `record_usage()`。
7. 在 `Session.agent_chat()` 构造 AgentLoop 时传入同一个 Session ContextManager。
8. 保持工具执行、权限检查、并发/串行策略和 plan context 逻辑不变。

**验证：** FakeProvider 构造两轮 Agent Loop，确认第一轮 tool 结果追加后第二轮收到预检处理后的历史、每轮 usage 更新、触发摘要时 Session 与 AgentLoop 消息一致、blocked 时不进入下一轮。

## T10：实现 TUI `/compact` 与诊断反馈

**文件：** `src/flickcode/tui.py`  
**依赖：** T8、T9

**步骤：**

1. 更新欢迎文案，列出 `/compact`。
2. 在交互命令分支识别精确的 `/compact`，避免把普通用户消息误判为命令。
3. 调用 `session.compact_context()`，即使未达到自动阈值也强制压缩。
4. 根据诊断显示是否压缩、摘要或工具结果文件路径、失败/熔断状态，以及仍超预算时的阻断原因。
5. 熔断期间显示明确提示，不绕过 ContextManager 状态机。
6. 保持 `/plan`、`/do`、`/exit`、`/quit` 行为不变。
7. 管道模式仍把普通输入交给 `Session.chat()`；不引入需要交互反馈的 `/compact` 行为。

**验证：**

```powershell
uv run python -m unittest tests.test_context.TUICompactTests
```

预期：`/compact` 调用 Session 压缩入口并显示诊断；其他命令分支不受影响。

## T11：上下文模块单元与 FakeProvider 集成测试

**文件：** `tests/test_context.py`  
**依赖：** T1–T10 的相应实现完成

**步骤：**

1. 建立临时目录 fixture，所有存盘测试不写入真实用户目录。
2. 建立 FakeProvider，记录每次请求的 messages、system、tools 和返回 usage。
3. 覆盖 `ContextConfig` 默认值、自定义值和非法值。
4. 覆盖 ResultStore 原文保留、路径安全、重复文件不覆盖。
5. 覆盖单结果和批次存盘，验证按大小降序。
6. 覆盖 estimator usage 锚点、增量和历史变更重建。
7. 覆盖摘要 Prompt、纯文本序列化、六段标题校验和 `tools=None`。
8. 覆盖摘要成功、失败三次熔断、成功/reset 恢复。
9. 覆盖压缩后的摘要/边界/近期消息顺序和工具批次配对。
10. 覆盖 `Session.chat()` 和 `AgentLoop.run()` 两条路径的请求前预检。

**验证：**

```powershell
uv run python -m unittest tests.test_context -v
```

预期：所有上下文单元测试和 FakeProvider 集成测试通过，无真实网络调用。

## T12：回归、文档和端到端验证

**文件：** `README.md`、`tests/test_context.py`，必要时修改既有测试  
**依赖：** T7–T11

**步骤：**

1. 在 README 增加 `/compact` 命令说明、context 配置字段和存盘目录说明。
2. 运行现有 MCP 测试，确认 Provider、工具、权限和 Agent Loop 行为未回归。
3. 运行全量单元测试。
4. 运行静态导入和编译检查，确认项目现有 Python 3.8 基线的兼容性。
5. 使用 FakeProvider 完成端到端场景：大工具结果存盘、历史摘要与边界消息、三次失败熔断、未达到自动阈值的 `/compact`。
6. 记录命令输出和实际文件路径，作为 checklist 验收证据。

**验证：**

```powershell
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
```

预期：全量测试通过、编译检查通过，README 与实现行为一致。

## 执行顺序

```text
T1
├─ T2 ─┐
├─ T3 ─┼─> T5 ─> T6 ─> T7 ─> T8 ─> T9 ─> T10
└─ T4 ─┘                    └──────────────> T11 ─> T12
```

说明：

- T2、T3、T4 可以并行；
- T5 依赖三个底层能力；
- T6 完成统一预检后，T7–T10 依次接入配置、普通对话、Agent Loop 与 TUI；
- T11 集中覆盖单元和集成测试；
- T12 完成回归、文档与端到端验证。
