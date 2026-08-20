# 长期团队协作 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/flickcode/teams/__init__.py` | 团队公共导出 |
| 新建 | `src/flickcode/teams/models.py` | 团队、成员、任务、消息和运行态模型 |
| 新建 | `src/flickcode/teams/paths.py` | 持久化布局和安全路径 |
| 新建 | `src/flickcode/teams/locking.py` | 锁文件、重试和过期锁 |
| 新建 | `src/flickcode/teams/store.py` | 团队与成员元数据存储 |
| 新建 | `src/flickcode/teams/tasks.py` | 共享任务清单与依赖校验 |
| 新建 | `src/flickcode/teams/registry.py` | 名称注册表和运行句柄 |
| 新建 | `src/flickcode/teams/protocol.py` | 协作与审批协议 |
| 新建 | `src/flickcode/teams/mailbox.py` | 邮箱文件读写与广播 |
| 新建 | `src/flickcode/teams/context.py` | 成员上下文快照 |
| 新建 | `src/flickcode/teams/pane.py` | 终端窗格适配器 |
| 新建 | `src/flickcode/teams/backends.py` | 后端选择与成员启动 |
| 新建 | `src/flickcode/teams/approval.py` | 审批门禁 |
| 新建 | `src/flickcode/teams/runtime.py` | 成员生命周期与恢复 |
| 新建 | `src/flickcode/teams/merge.py` | Git 合并、冲突和回滚 |
| 新建 | `src/flickcode/teams/policy.py` | Lead、成员和 coordinator 工具策略 |
| 新建 | `src/flickcode/teams/coordinator.py` | Lead 高层编排 |
| 新建 | `src/flickcode/teams/tools.py` | `team_lead`、`team_tasks`、`team_message` |
| 修改 | `src/flickcode/config.py` | `TeamsConfig` 和配置解析 |
| 修改 | `src/flickcode/session.py` | 团队服务装配、Lead 身份和动态工具视图 |
| 修改 | `src/flickcode/commands/builtin.py` | `/team` 本地命令 |
| 修改 | `src/flickcode/commands/dispatcher.py` | 注入团队命令上下文（如当前实现需要） |
| 修改 | `src/flickcode/agent.py` | 确保成员运行可使用受限团队工具视图 |
| 新建 | `tests/test_teams_models.py` | 模型与序列化测试 |
| 新建 | `tests/test_teams_locking.py` | 锁并发、重试和过期测试 |
| 新建 | `tests/test_teams_store.py` | 团队、成员和路径持久化测试 |
| 新建 | `tests/test_teams_tasks.py` | 任务 CRUD、依赖和状态测试 |
| 新建 | `tests/test_teams_protocol.py` | 协议和审批消息测试 |
| 新建 | `tests/test_teams_mailbox.py` | 邮箱、路由和广播测试 |
| 新建 | `tests/test_teams_backends.py` | 后端选择、窗格替身和失败诊断测试 |
| 新建 | `tests/test_teams_runtime.py` | 成员空闲、恢复和上下文测试 |
| 新建 | `tests/test_teams_policy.py` | 工具视图和 coordinator 双锁测试 |
| 新建 | `tests/test_teams_merge.py` | Git 合并、冲突和回滚测试 |
| 新建 | `tests/test_teams_integration.py` | Lead 到成员的端到端流程测试 |

## T1：建立团队模型与安全布局

**文件：** `models.py`、`paths.py`、`__init__.py`

**依赖：** 无

**步骤：**

1. 定义团队、成员、任务、消息、运行态及状态枚举。
2. 为模型实现严格的 `to_dict/from_dict`，拒绝缺字段、错误枚举和不安全路径。
3. 实现按用户目录、小组安全名称和成员 ID 计算的布局对象。
4. 导出后续模块需要的公共类型。

**验证：** `uv run python -m unittest tests.test_teams_models -v`，模型往返序列化一致，`..`、路径分隔符和空名称被拒绝。

## T2：实现跨进程文件锁

**文件：** `locking.py`、`tests/test_teams_locking.py`

**依赖：** T1

**步骤：**

1. 使用排他创建实现锁文件获取和释放。
2. 写入持有者标识、创建时间和随机 token。
3. 实现有限重试、最大等待和旧锁判断。
4. 确保释放只删除当前 token 持有的锁。

**验证：** `uv run python -m unittest tests.test_teams_locking -v`，第二个持有者按策略等待，旧锁可恢复，超时返回明确错误。

## T3：实现团队与成员元数据存储

**文件：** `store.py`、`registry.py`、`tests/test_teams_store.py`

**依赖：** T1、T2

**步骤：**

1. 实现创建、打开和保存团队元数据。
2. 实现成员登记、更新、查询和删除保护。
3. 使用临时文件加原子替换写入 `team.json`、`member.json` 和 `registry.json`。
4. 在成员变更时同步名称注册表和邮箱/上下文路径。
5. 拒绝同名成员、跨团队成员和路径越界。

**验证：** `uv run python -m unittest tests.test_teams_store -v`，重新创建 Store 后数据一致，恶意名称不能离开团队根目录。

## T4：实现共享任务清单

**文件：** `tasks.py`、`tests/test_teams_tasks.py`

**依赖：** T1、T2、T3

**步骤：**

1. 实现任务创建、查询、列表、更新、完成和取消。
2. 在团队锁内读取并保存 `tasks.json`。
3. 校验负责人属于当前团队、依赖存在且不会形成环。
4. 实现阻塞任务、就绪任务和合法状态迁移。
5. 让重复完成和终态回退保持幂等或返回明确错误。

**验证：** `uv run python -m unittest tests.test_teams_tasks -v`，未知依赖、环和非法迁移均被拒绝。

## T5：实现协议编码与邮箱存储

**文件：** `protocol.py`、`mailbox.py`、`tests/test_teams_protocol.py`、`tests/test_teams_mailbox.py`

**依赖：** T2、T3、T4

**步骤：**

1. 定义任务、状态、审批、空闲、完成和唤醒协议常量。
2. 实现消息编码、解码、字段校验和审批计划摘要校验。
3. 实现按成员邮箱 NDJSON 追加、读取未读消息和原子标记已读。
4. 发送时先解析名称注册表，再写入目标邮箱。
5. 实现广播逐成员投递和逐目标结果。

**验证：** `uv run python -m unittest tests.test_teams_protocol tests.test_teams_mailbox -v`，消息默认未读且有时间戳，未知协议保留并不改变授权状态。

## T6：实现成员上下文快照

**文件：** `context.py`、`tests/test_teams_runtime.py`

**依赖：** T1、T3

**步骤：**

1. 将现有消息对象序列化到成员 `context.json`。
2. 实现临时文件原子保存、加载和追加检查点。
3. 保存最近任务、状态和摘要元数据。
4. 对损坏快照保留可恢复前缀并产生诊断，不生成新成员 ID。

**验证：** `uv run python -m unittest tests.test_teams_runtime -v`，保存后新实例可恢复相同消息与任务上下文。

## T7：实现后端探测与选择

**文件：** `pane.py`、`backends.py`、`tests/test_teams_backends.py`

**依赖：** T1、T3

**步骤：**

1. 定义 `MemberBackend`、`BackendSelector`、`BackendHandle` 和 `PaneAdapter` 端口。
2. 实现 FakePaneAdapter 需要的能力探测、启动、唤醒和停止接口。
3. 实现 tmux 与 Windows Terminal 的命令探测适配器，所有命令使用参数数组和显式 cwd。
4. 按配置优先级选择后端并记录每个候选的可用性和原因。
5. 当所有候选不可用时返回失败，不静默降级。

**验证：** `uv run python -m unittest tests.test_teams_backends -v`，模拟三种环境观察选择、降级诊断和全失败结果。

## T8：实现进程内与终端窗格成员后端

**文件：** `backends.py`、`pane.py`、`tests/test_teams_backends.py`

**依赖：** T6、T7

**步骤：**

1. 实现进程内轻量调度器，复用成员上下文并在消息处理边界让出控制权。
2. 实现窗格后端启动独立 Agent 实例，并记录运行句柄。
3. 将唤醒操作接到 PaneAdapter，唤醒失败不删除邮箱消息。
4. 统一 stop、failure、idle 和 handle 清理语义。

**验证：** `uv run python -m unittest tests.test_teams_backends -v`，FakePaneAdapter 可观察 start/wake/stop 顺序，进程内后端不创建外部进程。

## T9：实现审批门禁与成员运行时

**文件：** `approval.py`、`runtime.py`、`tests/test_teams_runtime.py`

**依赖：** T5、T6、T8

**步骤：**

1. 实现审批请求、批准、驳回、过期和摘要不匹配状态。
2. 实现成员启动/恢复、忙碌、空闲、停止和失败状态迁移。
3. 收到任务分配时先检查审批，再加载上下文并启动后端。
4. 任务自然完成时保存上下文、写入空闲通知并保留运行句柄信息。
5. 新消息到达时复用成员 ID、邮箱和上下文。

**验证：** `uv run python -m unittest tests.test_teams_runtime -v`，未批准任务不执行，批准后可执行，完成后恢复不创建新成员。

## T10：实现 Git 合并与回滚

**文件：** `merge.py`、`tests/test_teams_merge.py`

**依赖：** T3、T4

**步骤：**

1. 基于现有 `GitRunner/GitRepository` 定义团队合并入口。
2. 合并前保存目标 HEAD、成员顺序和工作目录状态。
3. 实现预览、合并、可安全处理的非重叠变更和报告。
4. 对不可处理冲突、目标 HEAD 变化和命令失败执行回滚。
5. 保留成员目录和冲突诊断，不删除用户变更。

**验证：** `uv run python -m unittest tests.test_teams_merge -v`，成功合并产生预期提交，失败后目标 HEAD 恢复。

## T11：实现团队配置与 coordinator 双锁

**文件：** `src/flickcode/config.py`、`tests/test_teams_policy.py`

**依赖：** T1、T7

**步骤：**

1. 新增 `TeamsConfig` 数据类及默认值。
2. 解析 storage、后端优先级、pane adapter、锁和唤醒超时。
3. 解析 `coordinator_enabled`，拒绝未知键、非法值和重复后端。
4. 添加统一环境变量检查，只有配置开关和 `FLICKCODE_COORDINATOR=1` 同时满足才返回启用。

**验证：** `uv run python -m unittest tests.test_teams_policy -v`，逐一关闭双锁验证 coordinator 始终关闭。

## T12：实现团队工具策略

**文件：** `policy.py`、`tools.py`、`tests/test_teams_policy.py`

**依赖：** T4、T5、T9、T11

**步骤：**

1. 实现 Lead、成员和普通会话的工具集合计算。
2. coordinator 开启时从发起方集合移除写文件和编辑文件工具。
3. 保留读类工具、shell、派人、终止、消息和合并操作。
4. 为 `team_lead`、`team_tasks`、`team_message` 实现严格 schema 和执行前身份校验。
5. 伪造工具名、跨团队 ID 和越权操作返回安全错误。

**验证：** `uv run python -m unittest tests.test_teams_policy -v`，比较四种身份的 API 工具视图和执行结果。

## T13：实现 Lead 协调器

**文件：** `coordinator.py`、`tests/test_teams_integration.py`

**依赖：** T3、T4、T5、T9、T10、T12

**步骤：**

1. 组合 Store、TaskStore、MailboxStore、Runtime、ApprovalGate 和 Merge 服务。
2. 实现 Lead 激活、成员创建/唤醒、任务派发、终止、消息、状态和合并操作。
3. 派发前校验依赖、成员状态和团队归属。
4. 汇总成员空闲、完成、失败和唤醒诊断。
5. 将高层结果转换为现有工具可序列化的响应。

**验证：** `uv run python -m unittest tests.test_teams_integration -v`，Lead 可完成创建、派发、恢复和合并流程。

## T14：接入 Session 与动态工具视图

**文件：** `src/flickcode/session.py`、`src/flickcode/agent.py`

**依赖：** T12、T13

**步骤：**

1. 在 Session 中按配置装配 TeamStore、TeamCoordinator 和 TeamRuntimeManager。
2. 增加当前 Lead 身份和当前团队状态。
3. 只在 Lead 激活后把团队工具加入动态工具视图。
4. 为成员运行时创建受限工具视图和团队身份上下文。
5. 在 Session.close() 中有界停止成员运行时并保留持久化数据。

**验证：** `uv run python -m unittest tests.test_teams_integration tests.test_subagent_runtime -v`，未激活团队的既有子 Agent 测试保持通过。

## T15：接入 `/team` 本地命令

**文件：** `src/flickcode/commands/builtin.py`、`src/flickcode/commands/dispatcher.py`、`tests/test_teams_integration.py`

**依赖：** T13、T14

**步骤：**

1. 注册 `team create/open/status/leave` 命令。
2. 将命令直接连接到 Session 团队控制器，不发送给模型。
3. create/open 成功后刷新 Lead 动态工具视图。
4. status 输出小组、成员、任务、后端和 coordinator 的有界摘要。
5. leave 只解除当前会话绑定，不删除磁盘数据。

**验证：** `uv run python -m unittest tests.test_teams_integration tests.test_command_integration -v`，命令结果稳定且不新增模型消息。

## T16：补齐专项单元测试

**文件：** `tests/test_teams_models.py`、`test_teams_locking.py`、`test_teams_store.py`、`test_teams_tasks.py`、`test_teams_protocol.py`、`test_teams_mailbox.py`、`test_teams_backends.py`、`test_teams_runtime.py`、`test_teams_policy.py`、`test_teams_merge.py`

**依赖：** T2-T12

**步骤：**

1. 为每个存储和协议边界补齐失败、并发和损坏输入测试。
2. 为后端选择、唤醒失败、恢复和审批补齐 fake 运行时测试。
3. 为 coordinator 双锁和工具收缩补齐矩阵测试。
4. 为 Git 合并补齐成功、冲突和回滚测试。

**验证：** `uv run python -m unittest discover -s tests -p 'test_teams_*.py' -v` 全部通过。

## T17：补齐端到端与回归测试

**文件：** `tests/test_teams_integration.py`、必要时修改既有测试夹具

**依赖：** T13-T16

**步骤：**

1. 构造 Lead 创建团队、拆任务、并发派发和邮箱协作场景。
2. 覆盖审批、空闲、恢复、窗格唤醒和失败诊断。
3. 覆盖 coordinator 双锁开启后的权限收缩。
4. 运行既有 SubAgent、worktree、权限、命令和上下文测试，确认默认路径无回归。

**验证：** `uv run python -m unittest tests.test_teams_integration -v` 以及 `uv run python -m unittest discover -s tests -v` 通过。

## 执行顺序

```text
T1 → T2 → T3 → T4 → T5 → T6
                         ↘
                          T7 → T8 → T9
T3 + T4 ───────────────────────→ T10
T1 + T7 ────────────────────────→ T11 → T12
T5 + T9 + T10 + T12 ────────────→ T13
T13 + T12 ──────────────────────→ T14 → T15
T2-T12 ─────────────────────────→ T16 → T17
```
