# 长期团队协作 Plan

## 架构概览

新增独立的 `flickcode.teams` 包，复用现有 Provider、AgentLoop、ToolRegistry、PermissionEngine、worktree 和 Git 适配器，但不改变短生命周期 SubAgent 的默认路径。

```text
Session
├─ TeamCommand / Lead activation
├─ TeamLeadTool                  Lead 管理、派发、终止、合并
├─ TeamTaskTool                  Lead/成员共享任务 CRUD
├─ TeamMessageTool               Lead/成员邮箱收发
└─ TeamRuntimeManager
   ├─ TeamStore                  小组与成员元数据
   ├─ TaskStore                  原子任务清单
   ├─ NameRegistry               名称到邮箱/运行句柄
   ├─ MailboxStore               锁保护的邮箱文件
   ├─ ProtocolCodec              结构化消息
   ├─ MemberContextStore         成员上下文快照
   ├─ BackendSelector             后端探测与选择
   ├─ InProcessMemberBackend      进程内轻量运行
   ├─ PaneMemberBackend           独立窗格/进程运行
   ├─ ApprovalGate                计划审批状态机
   └─ TeamGitIntegrator           合并、冲突、回滚
```

Lead 激活采用本地命令建立显式身份边界：`/team create <name>` 创建并绑定新小组，`/team open <name>` 打开已有小组。绑定后，当前 Session 的动态工具视图增加 Lead 工具；普通会话和普通子 Agent 不增加团队工具。成员运行时使用独立的 `Session`/`AgentLoop` 配置，但通过团队身份获得受限的任务和消息工具。

## 核心数据结构

### `TeamRecord`

```python
@dataclass(frozen=True)
class TeamRecord:
    team_id: str
    name: str
    lead_member_id: str
    root: Path
    created_at: datetime
    updated_at: datetime
    status: TeamStatus
    coordinator_enabled: bool
```

`TeamStatus` 为 `active`、`closed`。`team_id` 用稳定随机标识，名称只用于用户选择和目录定位。

### `TeamMemberRecord`

```python
@dataclass(frozen=True)
class TeamMemberRecord:
    member_id: str
    name: str
    team_id: str
    role: str
    workdir: Path
    backend: MemberBackendKind
    backend_reason: str
    approval_required: bool
    state: MemberState
    mailbox_path: Path
    context_path: Path
    runtime_handle: str | None
    created_at: datetime
    updated_at: datetime
    last_error: str
```

`MemberState` 为 `registered`、`starting`、`busy`、`idle`、`stopped`、`failed`。成员 ID 不能因运行实例重启而改变。

### `TeamTaskRecord`

```python
@dataclass(frozen=True)
class TeamTaskRecord:
    task_id: str
    team_id: str
    title: str
    description: str
    assignee_id: str | None
    dependency_ids: tuple[str, ...]
    state: TeamTaskState
    created_by: str
    created_at: datetime
    updated_at: datetime
    result_summary: str
    error: str
```

`TeamTaskState` 为 `pending`、`blocked`、`ready`、`in_progress`、`completed`、`failed`、`cancelled`、`rolled_back`。只实现直接依赖和循环检查，不实现复杂表达式。

### `TeamMessage`

```python
@dataclass(frozen=True)
class TeamMessage:
    message_id: str
    team_id: str
    sender_id: str
    recipient_id: str | None
    kind: str
    body: str
    summary: str
    timestamp: datetime
    read: bool
    protocol_version: int
    payload: Mapping[str, Any]
```

`recipient_id=None` 表示广播。`kind` 使用受控协议名称，`payload` 存放任务 ID、审批请求 ID、计划摘要、决策和唤醒信息等结构化字段。

### `TeamRuntimeState`

```python
@dataclass
class TeamRuntimeState:
    team_id: str
    active_member_id: str | None
    selected_backend: MemberBackendKind | None
    runtime_handle: str | None
    last_wakeup_at: datetime | None
    last_error: str
```

运行态只作为可恢复诊断和唤醒线索保存；它不能替代成员身份或邮箱文件。

## 文件组织与持久化布局

```text
src/flickcode/teams/
├── __init__.py
├── models.py
├── paths.py
├── locking.py
├── store.py
├── tasks.py
├── registry.py
├── mailbox.py
├── protocol.py
├── context.py
├── backends.py
├── pane.py
├── runtime.py
├── approval.py
├── merge.py
├── policy.py
├── coordinator.py
└── tools.py

tests/
├── test_teams_models.py
├── test_teams_locking.py
├── test_teams_store.py
├── test_teams_tasks.py
├── test_teams_mailbox.py
├── test_teams_protocol.py
├── test_teams_backends.py
├── test_teams_runtime.py
├── test_teams_policy.py
├── test_teams_merge.py
└── test_teams_integration.py
```

默认根目录为 `~/.flickcode/teams/`，每个小组使用安全化名称目录：

```text
~/.flickcode/teams/<team-slug>/
├── team.json
├── team.lock
├── tasks.json
├── tasks.lock
├── registry.json
├── members/<member-id>/
│   ├── member.json
│   ├── mailbox.ndjson
│   ├── mailbox.lock
│   ├── context.json
│   └── runtime.json
└── diagnostics.ndjson
```

元数据和任务清单用临时文件加 `os.replace` 原子更新；邮箱使用锁内 NDJSON 追加和按消息 ID 标记已读的原子重写。所有时间统一写成带时区的 ISO 8601 字符串。

## 模块设计

### `models.py`

**职责：** 定义团队、成员、任务、消息、状态和后端枚举，提供序列化字典与严格反序列化。

**对外接口：** `TeamRecord`、`TeamMemberRecord`、`TeamTaskRecord`、`TeamMessage`、状态枚举及 `to_dict/from_dict`。

**依赖：** 标准库 dataclasses、datetime、pathlib；不得依赖 Session 或 TUI。

### `paths.py`

**职责：** 规范化小组和成员名称，生成团队布局和受控文件路径。

**对外接口：** `TeamLayout.from_root()`、`TeamLayout.for_name()`、`member_layout()`。

**依赖：** `Path`、安全名称校验。

### `locking.py`

**职责：** 提供跨线程/跨进程的锁文件，处理重试、超时、过期锁和释放。

**对外接口：** `FileLock.acquire()`、`FileLock.release()`、`locked(path, ...)`。

锁通过排他创建锁文件获得，锁内容包含进程标识和创建时间。旧锁清理必须再次确认文件未被更新，避免删除新持有者的锁。

### `store.py`

**职责：** 管理团队元数据、成员注册和持久化加载。

**对外接口：**

```python
class TeamStore:
    def create(self, name: str, lead_name: str, ...) -> TeamRecord: ...
    def open(self, name: str) -> TeamRecord: ...
    def save(self, team: TeamRecord) -> TeamRecord: ...
    def add_member(self, team_id: str, member: TeamMemberRecord) -> TeamMemberRecord: ...
    def update_member(self, member: TeamMemberRecord) -> TeamMemberRecord: ...
    def list_members(self, team_id: str) -> tuple[TeamMemberRecord, ...]: ...
```

所有写操作在团队锁内完成，并同步更新名称注册表。

### `tasks.py`

**职责：** 对共享任务清单提供带依赖校验的 CRUD、状态迁移和就绪判断。

**对外接口：** `create_task()`、`get_task()`、`list_tasks()`、`update_task()`、`complete_task()`、`cancel_task()`、`ready_tasks()`。

任务写入前校验任务 ID、成员归属、依赖存在性和新增边是否形成环；状态迁移使用显式合法迁移表。

### `registry.py`

**职责：** 实现名称到稳定成员 ID、邮箱路径和运行句柄的两段式解析。

**对外接口：** `NameRegistry.register()`、`resolve()`、`update_runtime()`、`remove()`。

注册表只保存路由和诊断元数据，不保存消息正文。发送流程必须先解析注册表，再调用 `MailboxStore` 写入邮箱。

### `mailbox.py`

**职责：** 读写成员邮箱，支持点对点、广播、未读查询和已读标记。

**对外接口：** `send()`、`broadcast()`、`list_messages()`、`mark_read()`、`count_unread()`。

广播通过注册表得到当时有效的成员快照，逐个追加到目标邮箱；单个邮箱失败不回滚已成功投递的邮箱，但返回逐目标结果。

### `protocol.py`

**职责：** 编码和校验结构化协作消息及审批协议。

协议最低包含：`task.assign`、`task.status`、`approval.request`、`approval.decision`、`member.idle`、`task.completed`、`member.wakeup`。

```python
class ProtocolCodec:
    def encode(self, kind: str, payload: Mapping[str, Any], ...) -> TeamMessage: ...
    def decode(self, message: TeamMessage) -> ProtocolEnvelope: ...
    def validate_approval(self, envelope: ProtocolEnvelope, request: ApprovalRequest) -> bool: ...
```

### `context.py`

**职责：** 保存和恢复成员 Agent 的消息上下文，确保恢复使用原成员身份。

**对外接口：** `load()`、`save()`、`append()`、`checkpoint()`。

上下文快照包含序列化后的消息、最近任务 ID 和摘要元数据。恢复时忽略并报告损坏尾记录，但不生成新的成员 ID。

### `backends.py` 与 `pane.py`

**职责：** 探测并运行成员后端。

```python
class MemberBackend:
    def start(self, member: TeamMemberRecord, launch: MemberLaunch) -> BackendHandle: ...
    def wake(self, handle: BackendHandle, reason: str) -> WakeResult: ...
    def stop(self, handle: BackendHandle) -> None: ...

class BackendSelector:
    def choose(self, preference: tuple[MemberBackendKind, ...]) -> BackendSelection: ...
```

`InProcessMemberBackend` 在当前进程的轻量调度器中运行成员 Agent，并在消息处理边界主动让出控制权。`PaneMemberBackend` 通过 `PaneAdapter` 启动独立实例，并保存窗格/进程句柄。首选顺序来自配置；选择结果必须包含候选探测结果、实际后端和原因。

`PaneAdapter` 为可替换接口，至少提供平台终端复用工具适配器和 Windows Terminal/系统终端适配器；测试使用 FakePaneAdapter。适配器不可用时返回能力错误，由选择器显式记录后再考虑下一候选。

### `runtime.py`

**职责：** 管理成员状态、审批前置、邮箱轮询/唤醒、上下文恢复和自然停止。

```python
class TeamMemberRuntime:
    def start_or_resume(self, member_id: str, task_id: str | None = None) -> RuntimeSnapshot: ...
    def deliver(self, message: TeamMessage) -> DeliveryResult: ...
    def stop(self, member_id: str, reason: str) -> RuntimeSnapshot: ...
    def status(self, member_id: str) -> RuntimeSnapshot: ...
```

成员正常完成任务后写入 `member.idle`，状态变为空闲；下一条分配消息通过邮箱恢复上下文并进入忙碌。成员执行异常进入失败态，保留邮箱和上下文供诊断。

### `approval.py`

**职责：** 管理审批请求生命周期，按请求 ID、计划摘要和发送者身份进行匹配。

批准结构至少包含 `request_id`、`decision=approve`、`plan_digest` 和 Lead 身份；普通文本、过期请求或摘要不匹配都返回拒绝。

### `merge.py`

**职责：** 使用现有明确 cwd 的 Git 适配器，把成员工作目录的提交按确定顺序合并到目标分支，并在失败时恢复合并前提交。

**对外接口：** `preview()`、`merge_all()`、`resolve_safe_conflicts()`、`rollback()`。

合并前保存目标 HEAD 和成员变更快照；任何不可处理冲突、目标分支变化或 Git 命令失败都会触发回滚并返回冲突报告。

### `policy.py`

**职责：** 计算团队身份的工具视图和 coordinator 工具视图。

规则顺序为：

```text
基础工具集
  ∩ Lead 工具集 / Member 工具集
  − 普通子 Agent 禁止集
  − 成员角色拒绝集
  − coordinator 写入工具集（双锁开启时）
= 最终工具视图
```

执行前再次校验工具名和当前团队身份。coordinator 的两把锁分别为配置字段 `teams.coordinator_enabled` 和环境变量 `FLICKCODE_COORDINATOR=1`，环境变量名称作为稳定接口集中定义。

### `coordinator.py`

**职责：** 连接 TeamStore、TaskStore、MailboxStore、RuntimeManager、ApprovalGate、TeamGitIntegrator 和权限策略，提供 Lead 的高层操作。

**对外接口：** `activate_lead()`、`create_member()`、`assign()`、`terminate()`、`send_message()`、`team_status()`、`merge()`、`coordinator_state()`。

Lead 工具负责调用这些接口，Lead 的任务拆解仍由 Agent 根据用户目标完成；服务层负责持久化、身份校验、依赖检查和运行时调度。

### `tools.py`

新增三个工具实例：

- `team_lead`：只对 Lead 可见，负责成员、派发、终止、状态和合并。
- `team_tasks`：对 Lead 和成员可见，负责共享任务 CRUD。
- `team_message`：对 Lead 和成员可见，负责点对点、广播、收件和已读。

普通主入口不会默认注册到当前 API 工具视图；激活 Lead 后通过动态 `ToolRegistryView` 增加对应工具。成员运行时使用仅包含成员操作的视图。所有工具 execute 路径都检查团队 ID、成员 ID、操作权限和 coordinator 状态。

## 关键交互

### Lead 建队与派发

```text
/team create backend-team
    → TeamStore.create()
    → Session 绑定 Lead 身份
    → 动态工具视图暴露 team_lead/team_tasks/team_message

Lead Agent 分析用户目标
    → team_tasks.create(... dependency_ids=...)
    → team_lead.create_member/start_member
    → ProtocolCodec(task.assign)
    → NameRegistry.resolve(member_name)
    → MailboxStore.send()
    → BackendSelector/RuntimeManager.start_or_resume()
```

### 成员审批与执行

```text
成员收到 task.assign
    → ApprovalGate.requires_approval()
    → 需要审批：发送 approval.request，保持 idle/blocked
    → Lead 发送合法 approval.decision
    → ApprovalGate.approve()
    → Runtime 恢复 context.json，执行任务
    → 更新 task.status / task.completed
    → 写入 member.idle 并通知 Lead
```

### 消息与独立窗格唤醒

```text
发送名称
    → NameRegistry.resolve()
    → MailboxStore 取得 mailbox.lock
    → 追加 TeamMessage(timestamp, read=false)
    → 若成员后端为 pane：PaneAdapter.wake(runtime_handle)
    → 唤醒结果写入 diagnostics，邮箱消息始终保留
```

### Git 集成

```text
Lead 查询所有任务为 completed
    → TeamGitIntegrator.preview()
    → 保存目标 HEAD
    → 按成员顺序合并
    → 安全冲突可处理：继续并记录
    → 其他错误：rollback(saved HEAD)
    → 返回 merged/rolled_back 与文件报告
```

## 配置与本地命令

在现有配置中新增：

```yaml
teams:
  storage_dir: ~/.flickcode/teams
  backend_preference: [pane, in_process]
  pane_adapters: [tmux, windows_terminal]
  lock_retry_seconds: 2.0
  lock_stale_seconds: 30.0
  wake_timeout_seconds: 5.0
  shutdown_timeout_seconds: 5.0
  coordinator_enabled: false
```

`FLICKCODE_COORDINATOR=1` 是第二把锁。未知键、非法路径、重复后端、非正数超时和未知 pane adapter 在配置加载时返回明确错误。

新增本地命令：

- `/team create <name>`：创建小组并把当前会话设为 Lead。
- `/team open <name>`：打开已有小组并绑定为 Lead。
- `/team status`：显示当前小组、成员、任务、后端和 coordinator 状态。
- `/team leave`：解除当前会话 Lead 绑定，不删除持久化小组。

这些命令直接调用 TeamCoordinator，不把命令文本送给模型。

## 依赖方向

```text
models ← paths ← locking
models ← protocol ← mailbox ← coordinator
models ← store ← registry
models ← tasks ← coordinator
models ← context ← runtime
models ← pane ← backends ← runtime
runtime ← coordinator
policy ← tools ← session
merge ← coordinator
```

`teams` 低层模块不得导入 `Session`、TUI 或 `AgentLoop`。Session 只负责装配、身份绑定和动态工具视图；成员运行时通过既有 AgentLoop 端口执行。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 持久化格式 | 元数据/任务 JSON，邮箱 NDJSON | 便于人工诊断、追加消息和跨进程恢复，依赖最少 |
| 并发保护 | 锁文件 + 有界重试 + 过期判断 | 满足独立进程共享目录，且在 Windows 与 Unix 上可实现 |
| 路由方式 | 名称注册表先解析，再写邮箱 | 将用户名称与物理邮箱/窗格句柄解耦，符合两段式消息要求 |
| Lead 激活 | 显式 `/team` 本地命令 | 不让普通主入口默认获得团队工具，身份边界清晰 |
| 工具划分 | Lead、任务、消息三个工具 | Lead 管理能力与成员协作能力可独立过滤和测试 |
| 成员恢复 | 稳定成员 ID + context.json 快照 | 物理进程可回收，但对外仍是同一成员，不重复登记 |
| 后端选择 | 配置优先级 + 能力探测 | 支持环境差异，同时将降级和失败显式化 |
| 轻量后端 | 进程内协作调度器 | 避免为每个成员创建完整终端进程，降低本地资源开销 |
| 隔离后端 | PaneAdapter 抽象 | 可接入 tmux、Windows Terminal 或测试替身，不绑定单一终端 |
| 审批 | 请求 ID + 计划摘要匹配 | 防止旧批准、错发批准或普通文本绕过审批 |
| Git 集成 | 受管 Git 适配器 + 保存 HEAD + 回滚 | 保证冲突失败时不污染 Lead 分支，并复用现有安全 cwd 能力 |
| coordinator 双锁 | 配置字段与环境变量同时满足 | 让能力开关和用户主动启用相互独立，避免误启用 |
| 普通行为兼容 | 默认不装配团队工具视图 | 不改变现有短生命周期子 Agent 和普通 Session |

## Spec 覆盖

| 需求 | 设计归属 |
|---|---|
| F1-F3 | `TeamStore`、`TeamLayout`、`/team` 命令 |
| F4 | `BackendSelector`、`PaneAdapter`、`InProcessMemberBackend` |
| F5-F6 | `TeamPolicy`、动态 `ToolRegistryView`、`TeamTools` |
| F7-F10 | `TeamMessage`、`NameRegistry`、`MailboxStore`、`ProtocolCodec`、`FileLock` |
| F11 | `ApprovalGate`、`team_message` |
| F12-F13 | `TeamCoordinator`、`TeamMemberRuntime`、`MemberContextStore` |
| F14 | `TeamGitIntegrator`、现有 `GitRunner` |
| F15-F16 | `TeamsConfig`、`TeamPolicy`、Session 工具视图 |
