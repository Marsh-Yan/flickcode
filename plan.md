# FlickCode 上下文管理 Plan

## 架构总览

采用“一个会话级 `ContextManager`，两个请求路径调用”的方案：

```text
Session
├─ messages: list[Message]
├─ context_manager: ContextManager
├─ chat()
│  └─ context_manager.prepare_before_request(...)
│     └─ provider.stream_chat(...)
└─ agent_chat()
   └─ AgentLoop(context_manager=...)
      └─ run()
         ├─ context_manager.prepare_before_request(...)
         └─ provider.stream_chat(...)

ContextManager
├─ ResultStore       工具结果/摘要文件存盘
├─ TokenEstimator    usage 锚点 + 字符增量估算
├─ ContextCompactor  消息选择、摘要替换、边界消息
└─ SummaryClient     独立摘要请求，tools=None，禁止递归进入主请求预检
```

### 核心边界

1. `ContextManager` 只处理内部 `Message` 历史，不参与 Anthropic/OpenAI 消息格式转换。
2. `Session` 持有一个会话级实例，保证普通对话、多个 Agent Loop 运行和 `/compact` 共享估算锚点、文件目录、熔断状态。
3. `Session.chat()` 和 `AgentLoop.run()` 在各自调用 `provider.stream_chat()` 前，都调用同一个 `prepare_before_request()`。
4. 工具结果在进入历史时做轻量存盘；请求前预检再次扫描历史，用于兼容已有历史和 Agent Loop 新增的 tool 消息。
5. 摘要调用由 `SummaryClient` 直接调用 Provider 的统一 `stream_chat()` 接口，传入专用摘要 Prompt、单条序列化历史用户消息、`tools=None`；摘要请求不再触发主上下文预检，也不把摘要调用消息写回主历史。
6. `ContextManager` 返回“可发送消息 + 诊断事件/状态”，调用方负责把处理后的消息继续用于当前 Provider 请求；主历史会同步替换为压缩后的历史，保证下一轮继续使用相同结果。

### 请求前流程

```text
Provider 请求前
    │
    ├─ 1. 轻量扫描 Message
    │     ├─ 单个 tool 内容超阈值 → ResultStore → 预览
    │     └─ 单条消息 tool 合计超阈值 → 按大小降序继续存盘
    │
    ├─ 2. TokenEstimator 估算
    │
    ├─ 3. 未超自动预算 → 原样请求
    │
    └─ 4. 超自动预算
          ├─ 熔断中 → 保留最小可发送历史；仍超预算则中止
          └─ 未熔断 → SummaryClient 最多尝试 3 次
                  ├─ 成功 → 替换旧消息 + 边界消息 + 重新估算
                  └─ 失败 → 记录失败；第 3 次进入熔断
```

## 核心数据结构

### `ContextConfig`

建议新增上下文配置对象，由 `Session` 创建并传给 `ContextManager`：

| 字段 | 默认值 | 用途 |
|---|---:|---|
| `context_window_tokens` | 由配置提供；无配置时使用保守默认值 | 模型上下文窗口上限 |
| `max_output_tokens` | 8192 | 为响应预留的输出空间 |
| `single_tool_result_chars` | 24000 | 单个工具结果存盘阈值 |
| `message_tool_result_chars` | 48000 | 单条工具批次合计阈值 |
| `automatic_safety_margin_tokens` | 13000 | 自动压缩安全余量 |
| `manual_safety_margin_tokens` | 3000 | `/compact` 安全余量 |
| `recent_target_tokens` | 10000 | 摘要后近期原文目标 |
| `recent_min_messages` | 5 | 摘要后近期原文最低条数 |
| `summary_max_retries` | 3 | 连续摘要失败上限 |
| `chars_per_token` | 4 | 字符到 Token 的近似换算 |
| `storage_dir` | `~/.flickcode/context/` | 上下文文件目录 |

`single_tool_result_chars` 和 `message_tool_result_chars` 是字符阈值，不是 Token 阈值。所有字段都应集中定义，并允许测试覆盖。

### `ContextState`

`ContextManager` 持有：

- `last_input_tokens: int | None`：最近一次主 Provider 请求的输入 Token；
- `anchor_message_count: int`：usage 锚点对应的消息数量；
- `anchor_message_fingerprint: str`：锚点对应历史快照指纹，检测旧消息被压缩或替换；
- `summary_failure_count: int`：连续摘要失败次数；
- `summary_circuit_open: bool`：是否熔断；
- `last_summary_path: Path | None`：最近一次摘要存盘路径；
- `last_result_paths: list[Path]`：最近一次工具结果存盘路径；
- `last_diagnostic: ContextDiagnostic`：供 TUI 或日志显示的最近状态。

### `ContextDiagnostic`

每次预检返回结构化诊断：

- `action`：`unchanged`、`stored_tool_result`、`compacted`、`summary_failed`、`circuit_open`、`blocked`；
- `estimated_input_tokens`；
- `context_window_tokens`；
- `safety_margin_tokens`；
- `stored_paths`；
- `summary_path`；
- `message`：用户可见的简短说明。

### `SummaryResult`

摘要调用只返回：

- `content: str`：正式结构化摘要；
- `attempts: int`；
- `success: bool`；
- `error: str | None`；
- `path: Path | None`：可选摘要文件路径。

内部分析草稿不进入该结构，不写文件，不回填消息。

### `ContextManager`

```python
class ContextManager:
    def prepare_before_request(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        safety_mode: SafetyMode = SafetyMode.AUTOMATIC,
        force_compact: bool = False,
    ) -> ContextPreparation:
        """轻量预防、估算并按需压缩，返回可发送历史。"""

    def record_usage(
        self,
        input_tokens: int,
        output_tokens: int = 0,
        thinking_tokens: int = 0,
        message_snapshot: list[Message] | None = None,
    ) -> None:
        """记录主 Provider usage，并更新增量估算锚点。"""

    def compact(
        self,
        messages: list[Message],
        *,
        safety_mode: SafetyMode = SafetyMode.MANUAL,
    ) -> ContextPreparation:
        """显式触发压缩；复用同一套预防、摘要和边界消息。"""

    def reset_summary_circuit(self) -> None:
        """显式清除摘要熔断状态和连续失败计数。"""
```

`ContextPreparation` 包含：

- `messages: list[Message]`：处理后可直接发送的历史；
- `blocked: bool`：是否必须中止主请求；
- `diagnostic: ContextDiagnostic`；
- `changed: bool`：是否修改了历史；
- `summary_content: str | None`。

### `SummaryClient`

```python
class SummaryClient:
    def summarize(
        self,
        history_text: str,
        *,
        system_prompt: str,
    ) -> SummaryResult:
        """使用 tools=None 生成摘要，不修改主历史。"""
```

实现约束：

- 摘要输入是序列化为纯文本的历史，不直接发送可能包含孤立 tool 消息的内部 `Message` 列表；
- 摘要请求使用 `messages=[Message(role="user", content=history_text)]`、专用 system prompt、`tools=None`；
- 只消费 `text`、`done`、`error` 事件；
- 不把摘要请求的消息加入主 `Session.messages`；
- 摘要调用不能再次调用 `ContextManager.prepare_before_request()`；
- 成功结果必须包含六个固定结构标题，缺少标题视为失败。

### `ResultStore`

```python
class ResultStore:
    def store_tool_result(
        self,
        *,
        session_id: str,
        message_index: int,
        tool_call_id: str,
        tool_name: str,
        content: str,
    ) -> StoredResult:
        """保存完整工具输出并返回可嵌入消息的预览。"""

    def store_summary(
        self,
        *,
        session_id: str,
        summary: str,
    ) -> Path:
        """保存摘要副本，便于诊断和恢复。"""
```

`StoredResult` 包含 `path`、`preview`、`original_chars`、`content_hash`。

## 模块设计

### Context Manager 模块（新建 `src/flickcode/context/`）

**职责：** 提供上下文配置、状态管理、请求前预检、工具结果扫描、Token 估算、压缩协调和摘要失败熔断。

**对外接口：** `ContextConfig`、`ContextManager`、`ContextPreparation`、`ContextDiagnostic`、`SafetyMode`。

**依赖：** `Message`、`BaseProvider`、文件系统存储；不依赖 TUI、AgentLoop 或具体 Provider。

### Result Store 模块（`src/flickcode/context/store.py`）

**职责：** 创建上下文目录，安全写入工具结果和摘要，生成不覆盖用户文件的稳定路径、预览和内容哈希。

**依赖：** `pathlib`、`hashlib`、`uuid` 或单调序列；不依赖 Provider。

### Token Estimator 模块（`src/flickcode/context/estimator.py`）

**职责：** 根据 usage 锚点、历史指纹、字符增量、system prompt 和工具定义计算近似输入 Token，并在历史变更后重建锚点。

**依赖：** `Message` 和 `ContextConfig`；不依赖 LLM。

### Summary Client 模块（`src/flickcode/context/summary.py`）

**职责：** 将待摘要历史序列化成纯文本，使用无工具的独立 Provider 请求生成结构化摘要，校验固定标题并返回结果。

**依赖：** `BaseProvider`、`Message`、摘要 Prompt 常量；不得依赖 `ContextManager`。

### Session 集成（修改 `src/flickcode/session.py`）

**职责：** 创建会话级 `ContextManager`，在 `chat()` 请求前调用预检，记录 usage，并提供 `/compact` 所需的公共方法。

**交互：** 工具结果仍由现有工具执行逻辑生成；上下文管理器只在消息进入历史后替换过大结果，不改变工具执行语义。

### Agent Loop 集成（修改 `src/flickcode/agent.py`）

**职责：** 接收可选的 `ContextManager`，在每轮 Provider 调用前预检，并在每轮 `done` 后记录 usage。

**交互：** whisper/system 内容继续只存在当前调用；上下文管理只处理主历史，临时 whisper 不写入摘要历史。压缩会通过原列表切片同步回 Session 持有的消息。

### 配置集成（修改 `src/flickcode/config.py`）

**职责：** 读取可选 `context` 配置节，填充 `ContextConfig` 所需字段；未配置时使用默认值。

**示例：**

```yaml
context:
  context_window_tokens: 128000
  max_output_tokens: 8192
  single_tool_result_chars: 24000
  message_tool_result_chars: 48000
  chars_per_token: 4
  storage_dir: "~/.flickcode/context"
```

### TUI 集成（修改 `src/flickcode/tui.py`）

**职责：** 识别 `/compact`，调用 Session 的公共压缩入口，显示压缩、摘要、存盘、熔断或阻断诊断；更新欢迎文案。

**边界：** 管道模式不新增交互式 `/compact` 语义，普通输入仍走现有 `Session.chat()`，从而保持管道兼容。

### 测试模块（新建 `tests/test_context.py`）

**职责：** 使用 FakeProvider 和临时目录验证估算、存盘、压缩、摘要失败状态机、普通对话接入、Agent Loop 接入和 TUI 命令分支。

## 模块交互

### 普通对话流程

```text
Session.chat()
  ├─ append user Message
  ├─ ContextManager.prepare_before_request(messages)
  │    ├─ store oversized tool results
  │    ├─ estimate request budget
  │    └─ compact if needed
  ├─ provider.stream_chat(prepared_messages, tools=...)
  ├─ execute tool calls
  ├─ append assistant/tool/thinking messages
  └─ record_usage(done.usage)
```

### Agent Loop 流程

```text
AgentLoop.run()
  └─ for each round
       ├─ build temporary whisper/system content
       ├─ ContextManager.prepare_before_request(messages)
       ├─ prepend whisper only to call_messages
       ├─ provider.stream_chat(call_messages, tools=..., system=...)
       ├─ append assistant/tool results to messages
       └─ record_usage(done.usage)
```

### 工具结果识别

当前内部 `Message` 中工具结果表现为 `role="tool"`，内容在 `content`，工具名通过前置 assistant 的 `tool_calls` 关联。因此扫描器必须：

1. 遍历 `Message` 历史；
2. 为每个 `tool` 消息根据 `tool_call_id` 回查最近的 assistant tool call；
3. 计算单个 tool 内容大小；
4. 按 assistant tool-call 消息及其关联 tool result 组成工具批次并汇总；
5. 替换 `tool.content`，保留 `role` 和 `tool_call_id` 不变。

不拆开 assistant tool-call 与其 tool result，避免生成非法 Provider 消息序列。

## 历史压缩算法

1. 先完成轻量工具结果存盘。
2. 将历史划分为可保留单元：普通单条消息、assistant tool-call 与其 tool result 集合、已有摘要/边界消息。
3. 从尾部向前累计近似 Token，直到达到 `recent_target_tokens`。
4. 若不足 `recent_min_messages=5`，继续向前保留完整消息单元。
5. 较早部分交给 `SummaryClient`。
6. 成功后用一条 `Message(role="assistant", content=summary)` 替换较早部分；内容带固定摘要标记。
7. 紧接着追加一条 `Message(role="user", content=boundary_notice)`。边界提示使用普通 user 消息，而不是 system 消息，避免被 Anthropic 提取到稳定 system 参数或被 OpenAI 提前插入请求头部。
8. 追加近期原文。
9. 重新估算；若仍超预算，扩大摘要范围并再次生成，但单次预检最多执行一轮摘要，避免内部无限循环。
10. 如果摘要失败或熔断，保留原始历史；仅在能安全构造最小消息集合且不超预算时发送，否则阻止主请求。

## Token 估算

```text
estimated_input_tokens
  = anchor_input_tokens
  + estimate_chars(messages_after_anchor) / chars_per_token
  + fixed_message_overhead
  + estimate_chars(system_prompt + tool_definitions) / chars_per_token
```

- `anchor_input_tokens` 是最近一次主 Provider usage 的 `input_tokens`；
- `anchor_message_count` 与历史指纹标记锚点位置；
- 没有 usage 锚点时，对整个历史做字符估算；
- 历史被压缩、截断或工具结果被替换后，重建锚点；
- 摘要请求的 usage 不更新主会话锚点。

自动预算为 `context_window_tokens - max_output_tokens - automatic_safety_margin_tokens`；手动预算为 `context_window_tokens - max_output_tokens - manual_safety_margin_tokens`。自动模式仅在估算超过预算时摘要；手动 `/compact` 强制进入压缩流程。

## 摘要 Prompt 与安全约束

摘要输入先序列化为纯文本，例如：

```text
[message 12][user]
原始用户消息...

[message 13][assistant]
...

[message 14][tool name=read_file id=...]
工具结果内容...
```

摘要 system prompt 固定要求：

```text
你是 FlickCode 的上下文摘要器。
你只能根据输入的历史文本生成摘要，禁止调用任何工具。
先在内部完成分析草稿，再只输出正式摘要；不要输出草稿。
草稿不得写入会话、文件或最终摘要。
不得补写输入中不存在的代码细节；不确定内容必须标注“不确定”。

正式摘要必须严格包含以下部分：
1. 用户目标与明确约束
2. 已完成的工作
3. 关键决策与理由
4. 当前状态、未完成事项与阻塞点
5. 涉及的文件、路径与重要细节
6. 后续建议或下一步
```

只消费 `text`、`done`、`error` 事件，不把草稿或摘要请求消息写入主历史。

## 熔断状态机

```text
摘要失败
  ├─ failure_count < 3 → 记录原因，允许下一次摘要请求重试
  └─ failure_count == 3 → circuit_open = true

摘要成功
  └─ failure_count = 0，circuit_open = false

用户显式 reset
  └─ failure_count = 0，circuit_open = false
```

单次预检内最多尝试 3 次；熔断后自动和手动流程都不再调用摘要 Provider。摘要失败不会覆盖主历史，存盘失败不会删除原始工具结果。

## 文件组织

```text
src/flickcode/
├─ context/
│  ├─ __init__.py       # 对外导出 ContextConfig、ContextManager 等
│  ├─ manager.py        # ContextManager、ContextPreparation、预检协调
│  ├─ models.py         # 配置、状态、诊断、结果数据结构、SafetyMode
│  ├─ store.py          # ResultStore、StoredResult、安全路径和文件写入
│  ├─ estimator.py      # usage 锚点、增量字符估算、历史指纹
│  ├─ compactor.py      # 工具批次扫描、近期消息选择、摘要替换
│  └─ summary.py        # SummaryClient、Prompt、摘要结构校验
├─ config.py            # 读取 context 配置节
├─ session.py           # 创建 ContextManager、普通 chat 接入、手动 compact
├─ agent.py             # AgentLoop 每轮请求前接入、usage 回写
└─ tui.py               # /compact 命令和诊断显示

tests/
└─ test_context.py      # 单元测试、FakeProvider 集成测试和端到端命令分支
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 上下文管理位置 | 会话级 `ContextManager`，由两条请求路径调用 | 共享锚点、熔断和存盘状态，覆盖每一轮 Agent 请求 |
| Provider 改造范围 | 不改协议转换，仅使用现有 `stream_chat(..., system=..., tools=...)` | 保持 Anthropic/OpenAI 适配稳定，满足内部 Message 解耦 |
| 工具结果存盘时机 | 进入历史后轻量扫描，请求前再次兜底扫描 | 覆盖新旧历史，避免遗漏非 Agent 路径产生的 tool 消息 |
| 工具批次定义 | assistant tool-call 与关联 tool result 集合 | 保持工具调用协议顺序和消息合法性 |
| 摘要输入格式 | 序列化纯文本，摘要请求只发一条 user 消息 | 避免把孤立 tool 消息传给不同 Provider，隔离摘要调用 |
| 摘要调用工具 | `tools=None`，不允许递归预检 | 满足摘要安全约束，避免摘要模型执行工具或死循环 |
| 摘要消息角色 | `assistant` + 固定摘要标记 | 兼容现有 Provider 转换器，明确其为历史摘要 |
| 边界消息角色 | `user` | 不被 Anthropic 提取为 system，也不被 OpenAI 提前插入 system 头部 |
| Token 估算 | usage 锚点 + 字符增量，固定 `chars_per_token` | 满足本阶段近似估算要求，避免 tokenizer 依赖 |
| 自动/手动余量 | 自动 13K，手动 3K | 区分后台防护和用户主动压缩 |
| 近期保留策略 | 尾部反向累计约 10K，至少 5 条，按完整工具批次保留 | 保留最新工作上下文且不破坏工具消息配对 |
| 摘要失败策略 | 单次最多 3 次，连续失败熔断 | 防止上下文预检重试死循环 |
| 存盘目录 | `~/.flickcode/context/` 可配置 | 与项目源码隔离，便于恢复和诊断 |
| 手动入口 | TUI `/compact` | 与现有 `/plan`、`/do` 命令风格一致，语义明确 |
| 配置承载 | 独立 `context` 配置节 | 不把上下文策略混入 Provider 凭据配置 |

## Spec 覆盖自检

| Spec 要求 | 设计归属 |
|---|---|
| F1 统一请求前预检 | `Session.chat()`、`AgentLoop.run()`、`ContextManager.prepare_before_request()` |
| F2 工具结果轻量预防 | `compactor.py`、`store.py`、工具批次扫描 |
| F3 近似 Token 估算 | `estimator.py`、usage 锚点和安全余量 |
| F4 整体历史摘要 | `compactor.py`、尾部保留和边界消息 |
| F5 结构化摘要 | `summary.py`、固定 Prompt 和标题校验 |
| F6 失败保护熔断 | `models.py`、`manager.py` 状态机 |
| F7 `/compact` | `session.py`、`tui.py` |
| F8 两条路径一致 | 会话级 ContextManager 共享 |
| N1-N7 | 内部 Message 解耦、ResultStore、诊断、FakeProvider 测试 |

## 验证策略

实现阶段必须至少覆盖：

- 配置默认值和自定义值解析；
- 单个结果存盘、批次按大小降序存盘、存盘失败保留原文；
- usage 锚点、增量估算、历史变更后重建锚点；
- 近期消息目标和最少消息数；
- assistant/tool 配对和 Anthropic/OpenAI 可接受消息顺序；
- 摘要 Prompt 禁止工具、内部草稿和六段结构；
- 摘要成功、三次失败熔断、成功或 reset 恢复；
- `Session.chat()` 和 `AgentLoop.run()` 每轮请求前均调用预检；
- `/compact` 成功、未达阈值强制执行、熔断提示；
- 未触发阈值时普通对话、Agent Loop 和管道模式不产生额外摘要调用。
