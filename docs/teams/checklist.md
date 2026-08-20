# 长期团队协作 Checklist

> 每项都通过运行测试、检查持久化文件或观察用户可见行为验证。

## 实现完整性

- [x] 团队、成员、任务、消息和运行态模型可序列化与恢复（验证：运行 `uv run python -m unittest tests.test_teams_models -v`，往返结果一致）。
- [x] 小组按安全名称写入用户目录，成员邮箱、元数据、上下文和运行态文件路径受控（验证：运行 `uv run python -m unittest tests.test_teams_store -v`，路径穿越输入被拒绝）。
- [x] 锁文件支持有界重试、过期锁处理和 token 校验释放（验证：运行 `uv run python -m unittest tests.test_teams_locking -v`）。
- [x] 共享任务支持增删查改、直接依赖、循环拒绝和合法状态迁移（验证：运行 `uv run python -m unittest tests.test_teams_tasks -v`）。
- [x] 协作协议覆盖任务、审批、状态、空闲、完成和唤醒消息（验证：运行 `uv run python -m unittest tests.test_teams_protocol -v`）。
- [x] 邮箱默认补时间戳和未读状态，并支持点对点、广播、未读读取和已读标记（验证：运行 `uv run python -m unittest tests.test_teams_mailbox -v`）。
- [x] 成员上下文可保存、恢复和在尾记录损坏时有界恢复（验证：运行 `uv run python -m unittest tests.test_teams_runtime -v`）。
- [x] 终端窗格和进程内后端实现统一启动、唤醒、停止和错误接口（验证：运行 `uv run python -m unittest tests.test_teams_backends -v`）。
- [x] 后端选择公开探测结果，不可用时不会静默降级（验证：使用 FakePaneAdapter 运行后端矩阵测试，观察选择原因字段）。
- [x] 审批门禁只接受匹配请求 ID、计划摘要和 Lead 身份的批准（验证：运行 `uv run python -m unittest tests.test_teams_protocol tests.test_teams_runtime -v`）。
- [x] Git 合并服务支持成功合并、冲突报告和失败回滚（验证：运行 `uv run python -m unittest tests.test_teams_merge -v`）。

## 权限与身份

- [x] 未激活 Lead 的普通会话看不到团队工具（验证：运行 `uv run python -m unittest tests.test_teams_policy -v`，工具视图不包含 `team_lead`、`team_tasks`、`team_message`）。
- [x] Lead 可获得管理、任务和消息工具，成员只获得成员允许的任务和消息操作（验证：运行团队策略矩阵测试）。
- [x] 普通子 Agent 无法通过配置或伪造调用获得团队工具（验证：运行团队策略测试中的执行前拒绝用例）。
- [x] coordinator 只有配置开关和 `FLICKCODE_COORDINATOR=1` 同时满足时才开启（验证：运行双锁四象限测试）。
- [x] coordinator 开启后写文件和编辑文件工具不可见且不可执行，读类工具、shell、派人、终止、消息和合并仍可用（验证：运行 `uv run python -m unittest tests.test_teams_policy -v`）。

## 生命周期与协作集成

- [ ] `/team create` 创建并绑定小组，`/team open` 恢复已有小组，`/team leave` 不删除磁盘数据（验证：运行 `uv run python -m unittest tests.test_teams_integration -v`）。
- [x] 名称注册表先解析目标，再写入目标邮箱；不存在的名称不会生成邮箱文件（验证：运行邮箱路由测试）。
- [ ] 独立窗格成员收到消息时触发目标窗格唤醒，唤醒失败时消息仍保留并产生诊断（验证：运行 FakePaneAdapter 集成测试）。
- [x] 成员完成任务后进入 idle 并通知 Lead（验证：运行成员运行时测试，观察成员状态和 Lead 邮箱）。
- [x] Lead 再次派发时复用原成员 ID、工作目录、邮箱和上下文，不新增成员记录（验证：关闭并重新建立运行时后运行恢复测试）。
- [ ] 多个独立任务可由多个成员并行处理，依赖未完成任务保持 blocked（验证：运行团队端到端测试）。
- [x] 未知协议、过期审批、错误成员身份和跨团队 ID 不改变任务授权或终态（验证：运行协议、策略和集成失败测试）。

## 编译、测试与回归

- [x] 全部团队专项测试通过（验证：运行 `uv run python -m unittest discover -s tests -p 'test_teams_*.py' -v`）。
- [x] Python 源码和测试无语法/导入错误（验证：运行 `uv run python -m compileall -q src tests`）。
- [x] 现有 SubAgent、worktree、权限、命令、上下文、MCP、Skill 和 Hook 测试通过（验证：运行 `uv run python -m unittest discover -s tests -v`）。
- [x] 团队持久化测试在无真实模型、无真实终端和无网络环境下通过（验证：所有团队测试使用 Fake Provider、Fake PaneAdapter 和临时目录）。
- [ ] 诊断、邮箱正文、工具响应和异常中不出现 API Key、Authorization 或其他凭据（验证：运行安全脱敏回归测试并扫描输出）。

## 端到端场景

- [ ] **场景 1：Lead 建队并行派发**：用户执行 `/team create` → Lead 创建成员和带依赖任务 → 多个成员收到任务并并行运行 → 任务状态和邮箱消息可查询（验证：运行 `tests.test_teams_integration.TeamLeadFlowTests`）。
- [x] **场景 2：审批与恢复**：需要审批的成员提交结构化计划 → Lead 批准 → 成员执行并进入 idle → Lead 发送新任务 → 原成员从磁盘恢复上下文后继续工作（验证：运行 `tests.test_teams_integration.TeamApprovalRecoveryTests`）。
- [ ] **场景 3：窗格唤醒与广播**：独立窗格成员空闲 → Lead 广播消息 → 名称注册表解析多个成员 → 邮箱分别追加 → 每个窗格收到唤醒，失败窗格仍保留消息（验证：运行 `tests.test_teams_integration.TeamWakeupTests`）。
- [ ] **场景 4：coordinator 合并**：两把锁开启 → 发起方写文件工具被收紧但 shell 和团队管理工具仍可用 → 成员完成 → Lead 合并成功；模拟冲突时目标分支回滚并上报（验证：运行 `tests.test_teams_integration.TeamCoordinatorMergeTests`）。
