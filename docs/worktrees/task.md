# FlickCode Worktree 隔离 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/flickcode/worktrees/__init__.py` | 导出 Worktree 公共模型与服务 |
| 新建 | `src/flickcode/worktrees/models.py` | 配置、仓库身份、元数据、工作区、租约、安全与处置模型 |
| 新建 | `src/flickcode/worktrees/config.py` | `.flickcode/worktrees.yaml` 严格加载 |
| 新建 | `src/flickcode/worktrees/paths.py` | 安全名称、托管布局、sidecar 路径和纯文件系统 repo probe |
| 新建 | `src/flickcode/worktrees/git.py` | 有界 GitRunner 与 GitRepository |
| 新建 | `src/flickcode/worktrees/bootstrap.py` | copy、symlink、ignored 与 hooks 初始化 |
| 新建 | `src/flickcode/worktrees/resources.py` | 绝对路径资源缓存与 Worktree 系统提示 |
| 新建 | `src/flickcode/worktrees/lifecycle.py` | create/enter/exit/inspect/delete 与活动租约 |
| 新建 | `src/flickcode/worktrees/cleanup.py` | 三层过滤后台 Janitor |
| 新建 | `src/flickcode/tools/paths.py` | 工具路径相对显式 cwd 解析 |
| 新建 | `src/flickcode/tools/cache.py` | 绝对路径和文件版本键的内容缓存 |
| 修改 | `src/flickcode/tools/base.py` | `execute(..., cwd=..., file_cache=...)` 契约 |
| 修改 | `src/flickcode/tools/read_file.py` | cwd 解析与文件缓存读取 |
| 修改 | `src/flickcode/tools/write_file.py` | cwd 解析与写后失效 |
| 修改 | `src/flickcode/tools/edit_file.py` | cwd 解析与编辑后失效 |
| 修改 | `src/flickcode/tools/glob_tool.py` | 绝对根搜索并移除 `chdir` |
| 修改 | `src/flickcode/tools/grep_tool.py` | 绝对根搜索并移除 `chdir` |
| 修改 | `src/flickcode/tools/execute_command.py` | 子进程显式 cwd |
| 修改 | `src/flickcode/mcp/adapter.py` | 接受统一 cwd 契约 |
| 修改 | `src/flickcode/skills/script_tool.py` | Skill 脚本使用调用方 cwd |
| 修改 | `src/flickcode/skills/load_tool.py` | 接受并传播统一 cwd 契约 |
| 修改 | `src/flickcode/skills/executor.py` | 隔离 Skill 的显式 cwd |
| 修改 | `src/flickcode/subagents/tool.py` | Agent 工具接受统一 cwd 契约，输入 schema 不变 |
| 修改 | `src/flickcode/agent.py` | AgentLoop 保存 cwd、缓存并传给权限/工具 |
| 修改 | `src/flickcode/permissions/engine.py` | 权限检查接收显式 cwd |
| 修改 | `src/flickcode/permissions/sandbox.py` | 相对路径始终绑定 sandbox 根 |
| 修改 | `src/flickcode/memory/models.py` | 指令 bundle 暴露绝对来源路径 |
| 修改 | `src/flickcode/memory/instructions.py` | 收集展开指令的绝对来源路径 |
| 修改 | `src/flickcode/hooks/actions.py` | Hook shell 动作使用 scope 项目 cwd |
| 修改 | `src/flickcode/subagents/models.py` | isolation、workspace request/status 与任务字段 |
| 修改 | `src/flickcode/subagents/roles.py` | 可选 `isolation` frontmatter 解析 |
| 修改 | `src/flickcode/subagents/runtime.py` | 租约工作区构造、资源提示、cwd 和退出 |
| 修改 | `src/flickcode/subagents/coordinator.py` | 定义式/共享/Fork workspace request |
| 修改 | `src/flickcode/subagents/tasks.py` | 记录运行中与终态工作区状态 |
| 修改 | `src/flickcode/subagents/notifications.py` | 序列化 Worktree 处置摘要 |
| 修改 | `src/flickcode/subagents/hooks.py` | 子工作区 Hook 根和元数据 |
| 修改 | `src/flickcode/session.py` | 主 Workspace、生命周期、Janitor 装配与关闭 |
| 新建 | `tests/test_worktree_paths.py` | 名称、布局、元数据与 repo probe 测试 |
| 新建 | `tests/test_worktree_config.py` | 配置 schema 与安全边界测试 |
| 新建 | `tests/test_worktree_git.py` | GitRunner、状态和远端包含性测试 |
| 新建 | `tests/test_worktree_bootstrap.py` | 初始化规则与上限测试 |
| 新建 | `tests/test_worktree_lifecycle.py` | 创建、恢复、租约、退出、删除测试 |
| 新建 | `tests/test_worktree_cleanup.py` | 过期、三层过滤和关闭测试 |
| 新建 | `tests/test_tools_workspace.py` | 工具 cwd、缓存与零 chdir 测试 |
| 新建 | `tests/test_worktree_integration.py` | 双子 Agent 端到端隔离测试 |
| 修改 | `tests/test_subagent_roles.py` | isolation 解析和旧角色兼容 |
| 修改 | `tests/test_subagent_runtime.py` | Workspace 注入与 prompt 内容 |
| 修改 | `tests/test_subagent_tasks.py` | workspace 状态单向更新 |
| 修改 | `tests/test_subagent_tool.py` | 工具显式 cwd 与响应扩展回归 |
| 修改 | `tests/test_subagent_integration.py` | Session Worktree 装配与共享/Fork 回归 |
| 修改 | `tests/test_permission_rules.py` | 子 Worktree sandbox 测试 |
| 修改 | `tests/test_hooks_integration.py` | Hook cwd 与 Worktree 元数据测试 |
| 修改 | `tests/test_skills_executor.py` | Skill 脚本 cwd 回归 |
| 修改 | `tests/test_context.py` | Worktree 上下文产物隔离测试 |
| 修改 | 现有直接调用工具的 `tests/test_*.py` | 为 `execute()` 补充显式临时 cwd |
| 修改 | `README.md` | 角色 isolation、初始化配置和保留/清理说明 |
| 新建 | `docs/worktrees/spec.md` | 已批准需求规格 |
| 新建 | `docs/worktrees/plan.md` | 技术设计 |
| 新建 | `docs/worktrees/task.md` | 本任务清单 |
| 新建 | `docs/worktrees/checklist.md` | 验收清单与证据位置 |

## T1：建立 Worktree 核心模型

**文件：** `src/flickcode/worktrees/models.py`、`src/flickcode/worktrees/__init__.py`、`tests/test_worktree_paths.py`  
**依赖：** 无

**步骤：**
1. 定义 `AgentIsolationMode`、`WorktreeBootstrapConfig`、`WorktreeConfig`、`RepositoryIdentity`、`WorktreeMetadata`、`WorkspaceContext` 和 `WorkspaceRequest`。
2. 定义 `WorktreeHandle`、`WorktreeLease`、`WorktreeSafetyReport`、`WorktreeDisposition`、`WorktreeOutcome`、`WorkspaceStatus` 和诊断/报告模型。
3. 在 `WorkspaceContext` 与 metadata 构造后校验所有路径绝对化、项目根包含性、状态枚举和时间时区。
4. 从包入口只导出 plan.md 规定的稳定类型。
5. 新增模型构造的成功/失败测试，覆盖共享与 Worktree 两种上下文。

**验证：** 运行 `python -m unittest tests.test_worktree_paths.WorktreeModelTests -v`；期望合法模型可构造，非绝对路径和越界项目根被拒绝。

## T2：实现安全逻辑名称

**文件：** `src/flickcode/worktrees/paths.py`、`tests/test_worktree_paths.py`  
**依赖：** T1

**步骤：**
1. 实现 `WorktreeName.parse()` 的 ASCII 字符、首字符、段长、总长、最多 8 段和空段检查。
2. 显式拒绝 `.`, `..`、反斜杠、盘符、绝对路径、前导/尾随斜杠和大小写折叠冲突键。
3. 实现 `target(managed_root)`，先按段拼接再用规范化绝对路径复核仍在根内。
4. 为边界长度和恶意名称建立表驱动测试，不执行任何文件删除。

**验证：** 运行 `python -m unittest tests.test_worktree_paths.WorktreeNameTests -v`；期望合法嵌套名通过，AC3 中全部危险输入被拒绝。

## T3：实现托管布局与原子元数据存储

**文件：** `src/flickcode/worktrees/paths.py`、`src/flickcode/worktrees/models.py`、`tests/test_worktree_paths.py`  
**依赖：** T1、T2

**步骤：**
1. 实现固定 `.flickcode/worktrees` 根、`.state/<sha256>.json` 和确定性分支名定位。
2. 分支名只由受控 task ID、名称摘要构成，并设置长度上限。
3. 实现 metadata 严格 JSON 编解码，拒绝未知版本、缺字段、相对路径、仓库/名称/目标不匹配。
4. 实现临时文件、flush/fsync、`os.replace()` 原子写入和只读加载。
5. 验证 sidecar 不位于子 Worktree 内，metadata 不会成为子分支未跟踪文件。

**验证：** 运行 `python -m unittest tests.test_worktree_paths.WorktreeLayoutTests tests.test_worktree_paths.WorktreeMetadataTests -v`；期望路径稳定，篡改 JSON 全部拒绝且原文件不被覆盖。

## T4：实现纯文件系统仓库探测

**文件：** `src/flickcode/worktrees/paths.py`、`tests/test_worktree_paths.py`  
**依赖：** T3

**步骤：**
1. 从项目目录向上有界查找 `.git` 目录或 linked-worktree `.git` 文件。
2. 严格解析 `gitdir:` 与 `commondir`，拒绝循环、缺失和逃离可接受仓库结构的值。
3. 计算规范化 repository root、common Git dir、项目相对路径和稳定 fingerprint。
4. 用普通仓库、子目录启动、linked-worktree 结构和伪造 `.git` 文件测试 probe 全程不创建子进程。

**验证：** 运行 `python -m unittest tests.test_worktree_paths.RepositoryProbeTests -v`；期望四类结构得到确定结果，mock subprocess 未被调用。

## T5：实现 Worktree 项目配置加载

**文件：** `src/flickcode/worktrees/config.py`、`tests/test_worktree_config.py`  
**依赖：** T1、T2

**步骤：**
1. 从 `<project>/.flickcode/worktrees.yaml` 读取版本 1、`expiry_days` 与 bootstrap 三类列表。
2. 对未知字段、错误类型、重复项、路径遍历、反斜杠、绝对路径和跨类别目标冲突返回诊断。
3. 文件不存在时返回 `expiry_days=7` 和空规则，不创建模板或目录。
4. 确保加载错误仅禁用 Worktree 请求，不抛出使 Session 无法启动的全局异常。

**验证：** 运行 `python -m unittest tests.test_worktree_config -v`；期望默认、示例配置和所有非法 schema 的结果符合 plan.md。

## T6：建立有界 GitRunner

**文件：** `src/flickcode/worktrees/git.py`、`tests/test_worktree_git.py`  
**依赖：** T1

**步骤：**
1. 实现仅接收参数数组、绝对 cwd、`shell=False` 和 30 秒默认超时的 `GitRunner.run()`。
2. 捕获不可执行、超时、非零退出和输出解码错误，生成阶段化 `WorktreeGitError`。
3. 限制 stdout/stderr 保留长度，错误消息不包含环境变量或文件内容。
4. 用 fake subprocess 检查任何输入都不会拼接 shell 命令，cwd 每次显式传递。

**验证：** 运行 `python -m unittest tests.test_worktree_git.GitRunnerTests -v`；期望成功、非零、超时和启动失败均有确定结果，`shell` 恒为 `False`。

## T7：实现仓库身份、HEAD、分支和本地排除

**文件：** `src/flickcode/worktrees/git.py`、`tests/test_worktree_git.py`  
**依赖：** T3、T4、T6

**步骤：**
1. 实现 Git 顶层/common dir 与 `RepositoryIdentity` 的交叉验证。
2. 实现完整 `HEAD` OID 解析和 `git check-ref-format --branch` 包装。
3. 在 common Git dir 的 `info/exclude` 原子追加唯一的 `/.flickcode/worktrees/` 规则，重复调用不重复写。
4. 用 `git check-ignore` 验证托管根确实被排除；失败时禁止创建。
5. 在临时真实仓库验证不会修改工作树 `.gitignore` 或制造 Git 状态变更。

**验证：** 运行 `python -m unittest tests.test_worktree_git.RepositoryIdentityTests tests.test_worktree_git.ManagedExcludeTests -v`；期望身份不匹配拒绝、exclude 幂等且 `git status --porcelain` 为空。

## T8：实现 Worktree add、列表与 hooks 配置

**文件：** `src/flickcode/worktrees/git.py`、`tests/test_worktree_git.py`  
**依赖：** T7

**步骤：**
1. 实现从精确 base OID 创建新分支与 Worktree，并把目标路径作为单独参数传递。
2. 解析 `git worktree list --porcelain -z` 为规范化路径、HEAD、branch 记录。
3. 读取主目录有效 hooks 路径；启用 worktree config 后只在子 Worktree 设置该绝对路径。
4. 实现受控 Worktree remove 与精确临时分支删除原语，但不在本模块内决定是否安全。
5. 在真实临时仓库验证两个 Worktree 分支独立、hooks 有效值一致、主分支 config 未被子值覆盖。

**验证：** 运行 `python -m unittest tests.test_worktree_git.WorktreeCommandTests tests.test_worktree_git.HookConfigTests -v`；期望创建/列表/删除及 worktree-local hooks 行为通过。

## T9：实现变更和未推送 commit 查询

**文件：** `src/flickcode/worktrees/git.py`、`tests/test_worktree_git.py`  
**依赖：** T8

**步骤：**
1. 解析 `status --porcelain=v1 -z --untracked-files=all`，保留安全的相对路径摘要。
2. 用创建基线限定 `base_commit..HEAD` 的唯一 commit 列表。
3. 对每个唯一 commit 查询所有 `refs/remotes/*` 包含引用；不读取或要求 upstream。
4. 将 Git 查询失败作为显式未知结果，不能返回“安全”。
5. 构造无 upstream、有一个远端包含、部分 commit 未包含和远端查询失败测试。

**验证：** 运行 `python -m unittest tests.test_worktree_git.WorktreeSafetyQueryTests -v`；期望 AC10/AC11 的 commit 判定全部通过。

## T10：实现初始化预检

**文件：** `src/flickcode/worktrees/bootstrap.py`、`tests/test_worktree_bootstrap.py`  
**依赖：** T5、T7

**步骤：**
1. 将 copy、symlink 和 ignored 规则解析到主/子项目绝对路径，复核源和目标根边界。
2. 拒绝 copy 源符号链接、缺失 symlink 源、已存在冲突目标和三类展开后的目标重叠。
3. 有界展开 ignored glob，并调用 Git 确认每个普通文件被忽略。
4. 在写入前统计文件数与字节数，超过 2,000 或 512 MiB 立即失败。
5. 返回不可变初始化计划，使执行阶段不重新扩展规则。

**验证：** 运行 `python -m unittest tests.test_worktree_bootstrap.BootstrapPlanningTests -v`；期望越界、链接、冲突、非 ignored 和上限案例均在零目标写入下失败。

## T11：执行初始化计划

**文件：** `src/flickcode/worktrees/bootstrap.py`、`tests/test_worktree_bootstrap.py`  
**依赖：** T8、T10

**步骤：**
1. 按预检快照复制普通文件/目录，保留必要权限且不跟随源符号链接。
2. 使用 `os.symlink(..., target_is_directory=True)` 创建目录链接；失败时返回错误，不回退复制。
3. 复制已经确认 ignored 的普通文件，确保目标父目录位于子项目根。
4. 最后配置 Worktree hooks，并记录每类已完成数量和错误规则。
5. 验证未声明 `.env` 不复制，初始化产物不会使 `git status` 变脏。

**验证：** 运行 `python -m unittest tests.test_worktree_bootstrap.BootstrapExecutionTests -v`；期望 copy/link/ignored/hooks 示例通过，链接失败和中途失败报告包含保留路径。

## T12：实现首次创建流程

**文件：** `src/flickcode/worktrees/lifecycle.py`、`tests/test_worktree_lifecycle.py`  
**依赖：** T3、T5、T8、T11

**步骤：**
1. 注入 layout、repository、bootstrapper、配置、clock 与每名称锁，不在构造时改变 cwd。
2. 对目标不存在路径执行名称/身份/HEAD/分支/exclude 检查，再调用 Worktree add。
3. 依次写 `creating` metadata、执行 bootstrap、原子更新为 `ready`。
4. 任一阶段失败时标记 `failed`（若可写）并返回阶段化错误；不递归删除不确定目录。
5. 验证主目录未提交修改不出现在新 Worktree，子分支 base OID 精确等于创建瞬间 HEAD。

**验证：** 运行 `python -m unittest tests.test_worktree_lifecycle.WorktreeCreateTests -v`；期望首次创建、非 Git、detached/无 HEAD、初始化失败和主目录脏状态案例符合 AC2/AC4。

## T13：实现零 Git 快速恢复

**文件：** `src/flickcode/worktrees/lifecycle.py`、`tests/test_worktree_lifecycle.py`  
**依赖：** T4、T12

**步骤：**
1. 在 `create()` 最前面检查目标存在，进入独立恢复分支。
2. 只读取 repo probe、target `.git` 和 sidecar，交叉验证 fingerprint、逻辑名、绝对路径和 `ready` 状态。
3. 恢复时不更新 metadata、不执行 bootstrap、不调用 `GitRunner`。
4. 缺 metadata、损坏 JSON、failed 状态、路径篡改和 repo fingerprint 不符全部拒绝且不修改目标。
5. 使用会在任何调用时报错的 Git fake 证明合法恢复仍成功。

**验证：** 运行 `python -m unittest tests.test_worktree_lifecycle.WorktreeFastRecoveryTests -v`；期望 Git 调用为 0、文件系统写入为 0，篡改案例全部保留原目录。

## T14：实现进入和活动租约

**文件：** `src/flickcode/worktrees/lifecycle.py`、`tests/test_worktree_lifecycle.py`  
**依赖：** T13

**步骤：**
1. 为 shared 请求构造主项目 `WorkspaceContext`，不访问 Git 或托管根。
2. 为 worktree 请求调用 create，登记唯一活动 lease，再原子更新 `last_used_at`。
3. 同名 create/enter 使用同一锁；重复 enter 不返回两个可独立释放的活动租约。
4. 实现幂等 lease release，并提供只读 `is_active(path)` 给删除和 Janitor。
5. 用并发 barrier 验证同名进入只有一个受控 Worktree，不同名称可并行。

**验证：** 运行 `python -m unittest tests.test_worktree_lifecycle.WorktreeLeaseTests -v`；期望 shared 零 Git、同名互斥、不同名并行、last_used 仅在 enter 更新。

## T15：实现安全检查、删除与退出

**文件：** `src/flickcode/worktrees/lifecycle.py`、`tests/test_worktree_lifecycle.py`  
**依赖：** T9、T14

**步骤：**
1. `inspect()` 先复核 metadata、目标路径、Git worktree 列表和仓库身份，再查询 status 与 commit 远端包含性。
2. 按 changes → unpushed → check_failed 的明确优先级生成安全报告/处置。
3. `delete()` 拒绝活动 lease、不安全报告和身份不符；安全时依次 Git remove、删除精确临时分支、删除 sidecar。
4. `exit()` 在同名锁内释放 lease、inspect、按条件删除或保留，重复调用返回同一处置且不重复删除。
5. 覆盖暂存、未暂存、未跟踪、无 upstream 未推送、已被远端包含、Git 查询失败和删除中途失败。

**验证：** 运行 `python -m unittest tests.test_worktree_lifecycle.WorktreeExitTests tests.test_worktree_lifecycle.WorktreeDeleteTests -v`；期望 AC9–AC13、AC16 的生命周期行为通过。

## T16：实现三层后台清理

**文件：** `src/flickcode/worktrees/cleanup.py`、`tests/test_worktree_cleanup.py`  
**依赖：** T5、T15

**步骤：**
1. 扫描 `.state/*.json`，每轮按稳定顺序最多取 256 个，不递归枚举任意目录。
2. 实现路径层、归属/租约层、Git/变更层过滤，并分别累计 skip reason。
3. 用可注入 UTC clock 判断默认 7 天及配置值，只对前两层通过且过期的候选调用 Git。
4. 实现 daemon worker 的立即异步首扫、60 分钟 Event 等待和 5 秒有界关闭。
5. 单候选异常捕获后继续下一项；关闭时不使用不可中断长 sleep。

**验证：** 运行 `python -m unittest tests.test_worktree_cleanup -v`；期望 AC14/AC15/AC19 的过期边界、三层失败、继续扫描和关闭行为通过。

## T17：扩展角色 isolation 解析

**文件：** `src/flickcode/subagents/models.py`、`src/flickcode/subagents/roles.py`、`src/flickcode/subagents/builtins/*.md`、`tests/test_subagent_roles.py`  
**依赖：** T1

**步骤：**
1. 从 `flickcode.worktrees.models` 导入 `AgentIsolationMode` 并接到 `AgentRoleDefinition`，保持依赖单向。
2. 把 `isolation` 加入允许字段但不加入旧角色必填字段，省略时设为 shared。
3. 解析 shared/worktree，非法值产生现有单角色诊断。
4. 保持角色 fingerprint 覆盖完整原文，因此 isolation 变化会触发 catalog generation。
5. 内置角色可显式写 shared 或保持省略，验证两者行为一致。

**验证：** 运行 `python -m unittest tests.test_subagent_roles -v`；期望 AC1 通过，现有覆盖/刷新/验证测试无回归。

## T18：扩展子任务工作区状态模型

**文件：** `src/flickcode/subagents/models.py`、`tests/test_subagent_tasks.py`  
**依赖：** T1、T17

**步骤：**
1. 在 `SubAgentLaunchSpec` 增加不可变 `WorkspaceRequest`。
2. 在 record/snapshot/response/notification 增加 `WorkspaceStatus`，默认 `NOT_USED`。
3. 保持 Agent 工具请求模型与输入 schema 不变。
4. 序列化路径为字符串，限制 reason 长度，避免把初始化文件内容写入响应。
5. 更新模型构造 fake 和状态比较测试。

**验证：** 运行 `python -m unittest tests.test_subagent_tasks.SubAgentWorkspaceModelTests -v`；期望默认 shared 状态、Worktree 状态和 JSON 序列化稳定。

## T19：建立显式工具 cwd 契约

**文件：** `src/flickcode/tools/base.py`、`src/flickcode/tools/paths.py`、`src/flickcode/tools/cache.py`、`tests/test_tools_workspace.py`  
**依赖：** T1

**步骤：**
1. 将 `BaseTool.execute()` 改为要求关键字 `cwd: Path`，并接受可选 `FileContentCache`。
2. 实现 `resolve_tool_path(cwd, raw)`：验证 cwd 绝对、相对输入拼接 cwd、绝对输入保留并规范化。
3. 实现以绝对路径和 `(mtime_ns, size)` 为版本的 `FileContentCache`，支持读取、失效和同路径重建刷新。
4. 更新 fake tools 和直接 tool 单测 helper，所有调用显式传临时 cwd，不引入 `Path.cwd()` 默认。

**验证：** 运行 `python -m unittest tests.test_tools_workspace.ToolContractTests tests.test_tools_workspace.FileContentCacheTests -v`；期望省略 cwd 立即 TypeError，两个根的同名文件不串缓存。

## T20：迁移读写编辑工具

**文件：** `src/flickcode/tools/read_file.py`、`src/flickcode/tools/write_file.py`、`src/flickcode/tools/edit_file.py`、`tests/test_tools_workspace.py`、相关现有工具测试  
**依赖：** T19

**步骤：**
1. 三个工具统一用 `resolve_tool_path()`，错误消息显示解析后的目标但不泄露文件内容。
2. Read 使用调用方 runtime 的 file cache；offset/limit 在完整文本读取后保持现有语义。
3. Write/Edit 成功后失效精确绝对路径缓存，失败不改变缓存。
4. 两个临时 workspace 并行用相同相对路径读写，验证内容互不覆盖。

**验证：** 运行 `python -m unittest tests.test_tools_workspace.FileToolWorkspaceTests tests.test_commands tests.test_matching -v`；期望相对路径隔离、写后读取新值，现有文件工具调用回归通过。

## T21：移除 Glob/Grep 的进程目录切换

**文件：** `src/flickcode/tools/glob_tool.py`、`src/flickcode/tools/grep_tool.py`、`tests/test_tools_workspace.py`  
**依赖：** T19

**步骤：**
1. Glob 用绝对 root 与 `glob`/Path 组合搜索，再显式生成相对输出。
2. Grep 的 include 与递归枚举都基于绝对 root，不执行 `os.chdir()`。
3. 保持排序、无匹配文本、正则错误和 unreadable 文件跳过语义。
4. 并行搜索两个同结构 workspace，监控 `os.getcwd()` 在整个执行中不变。

**验证：** 运行 `python -m unittest tests.test_tools_workspace.SearchToolWorkspaceTests -v`，随后运行 `rg -n "os\.chdir" src/flickcode/tools`；期望测试通过且扫描无匹配。

## T22：迁移命令、Skill、MCP 与系统工具

**文件：** `src/flickcode/tools/execute_command.py`、`src/flickcode/skills/script_tool.py`、`src/flickcode/skills/load_tool.py`、`src/flickcode/skills/executor.py`、`src/flickcode/mcp/adapter.py`、`src/flickcode/subagents/tool.py`、相关测试  
**依赖：** T19

**步骤：**
1. ExecuteCommand 的 `subprocess.run()` 使用显式 cwd，保留 timeout、stdout/stderr 和风险扫描语义。
2. SkillScriptTool 使用调用时 cwd，定义 package 路径校验仍针对不可变 skill source。
3. MCP、LoadSkill、Agent adapter 接受 cwd/file_cache 契约；不向远端 schema 注入 cwd。
4. SkillExecutor 调用其 AgentLoop/工具时传隔离 Skill 的绝对项目根。
5. 更新所有直接工具调用测试，确认 Agent 工具 input schema 字节级/结构级未增加参数。

**验证：** 运行 `python -m unittest tests.test_tools_workspace.CommandToolWorkspaceTests tests.test_skills_executor tests.test_subagent_tool tests.test_mcp_unittest -v`；期望命令/Skill 落在指定目录，MCP 与 Agent schema 无回归。

## T23：把 cwd 贯穿 AgentLoop 与 Session

**文件：** `src/flickcode/agent.py`、`src/flickcode/session.py`、相关 Agent/Session 测试  
**依赖：** T19–T22

**步骤：**
1. `AgentLoop` 构造时保存规范化绝对 cwd 和 runtime-private file cache。
2. 每次权限检查与 tool.execute 使用相同 cwd/file_cache，不根据消息参数切换根。
3. Session 主循环和备用流式执行路径都显式传 `self.project_root`。
4. 所有 AgentLoop 构造点（主 Session、Skill、SubAgent、测试 fake）补齐 cwd。
5. 用记录型 fake tool 证明每轮、每个工具都收到绝对 cwd。

**验证：** 运行 `python -m unittest tests.test_tools_workspace.AgentLoopWorkspaceTests tests.test_command_integration tests.test_context -v`；期望 fake 捕获的 cwd 一致且现有 Agent 行为通过。

## T24：绑定权限沙箱到显式工作区

**文件：** `src/flickcode/permissions/engine.py`、`src/flickcode/permissions/sandbox.py`、`tests/test_permission_rules.py`、`tests/test_tools_workspace.py`  
**依赖：** T23

**步骤：**
1. `PermissionEngine.check()` 接受调用方 cwd，并验证它等于/位于引擎项目根预期范围。
2. `PathSandbox.check()` 对相对路径使用自身项目根，不调用 `Path(path).resolve()` 的进程 cwd 语义。
3. 保持绝对越界路径和解析到主 Worktree 的 symlink 被拒绝。
4. 两个子 Worktree 各自引擎检查同一相对路径，确认结果只依赖各自根。

**验证：** 运行 `python -m unittest tests.test_permission_rules tests.test_tools_workspace.PermissionWorkspaceTests -v`；期望子 Worktree 内允许、主目录绝对路径与逃逸 symlink 拒绝。

## T25：实现绝对路径资源缓存

**文件：** `src/flickcode/worktrees/resources.py`、`src/flickcode/memory/models.py`、`src/flickcode/memory/instructions.py`、`tests/test_worktree_integration.py`、`tests/test_context.py`  
**依赖：** T1、T19

**步骤：**
1. 让 InstructionLoader 在 bundle 中记录实际读取的全部绝对 source paths，包括 include 文件。
2. 实现项目指令、用户指令、项目/用户 memory index 的绝对路径+文件版本缓存。
3. 实现 system prompt cache key，包含绝对项目根、角色 fingerprint、资源 fingerprint、平台和日期。
4. 同一路径文件改变或 Worktree 路径重建时版本改变；不能回退使用主 Worktree 同名资源。
5. 两个 workspace 放置不同 AGENTS.md/memory/index.md，验证缓存和提示各自返回正确内容。

**验证：** 运行 `python -m unittest tests.test_worktree_integration.WorkspaceResourceIsolationTests tests.test_context -v`；期望 AC7 的四类资源隔离和重建刷新通过。

## T26：扩展 Worktree 子 Agent 系统提示

**文件：** `src/flickcode/worktrees/resources.py`、`src/flickcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`  
**依赖：** T17、T25

**步骤：**
1. `WorkspacePromptFactory` 按角色→指令→记忆→环境顺序构造定义式提示。
2. Worktree 环境写入 child project、worktree root、main project、branch 与 isolation；共享环境只写主项目根和 shared。
3. `ChildRuntimeFactory.create()` 接受 `WorkspaceContext`，用其 project root 构造 ContextManager、PermissionEngine 和 AgentLoop cwd。
4. 子 context storage 使用 `<child-project>/.tmp/subagents/context/<task-id>` 绝对路径。
5. 确保提示不复制父普通消息或临时 Hook prompt。

**验证：** 运行 `python -m unittest tests.test_subagent_runtime -v`；期望 Worktree 四项路径/分支说明、共享路径和现有 defined/fork 消息继承规则通过。

## T27：生成定义式与 Fork 的 WorkspaceRequest

**文件：** `src/flickcode/subagents/runtime.py`、`src/flickcode/subagents/coordinator.py`、`tests/test_subagent_runtime.py`、`tests/test_subagent_integration.py`  
**依赖：** T18、T26

**步骤：**
1. 定义式 spec 从角色 isolation 生成请求，Worktree 名固定为 `agents/<task-id>`。
2. shared 定义式和 Fork spec 固定使用 shared 请求；Fork 强制后台规则不变。
3. Worktree 配置错误只在 worktree 请求开始时返回失败，shared/Fork 不访问该错误。
4. AgentTool 输入 schema 保持 operation/type/task/role/background/task_id 原集合。

**验证：** 运行 `python -m unittest tests.test_subagent_runtime tests.test_subagent_integration.SubAgentWorkspaceRequestTests -v`；期望定义式两种模式正确，Fork 永远 shared，schema 无新增字段。

## T28：在 Runner 中管理租约与退出

**文件：** `src/flickcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`、`tests/test_worktree_integration.py`  
**依赖：** T15、T27

**步骤：**
1. `SubAgentRunner` 注入 lifecycle 与 workspace event callback。
2. 运行前再次检查取消，只有实际开始的任务调用 enter。
3. enter 成功后回调路径/分支/recovered，再构造 ChildRuntime 并执行 AgentLoop。
4. 在唯一 finally 路径调用 exit，回调 disposition/reason；退出异常转为 retained_check_failed 诊断。
5. 保留 Agent 原 stop reason 和 state，不让清理异常覆盖 completed/limited/failed/cancelled。

**验证：** 运行 `python -m unittest tests.test_subagent_runtime.SubAgentWorktreeRunnerTests tests.test_worktree_integration.RunnerTerminalStateTests -v`；期望 AC8/AC9 四终态退出一次且排队取消零创建。

## T29：记录和通知工作区处置

**文件：** `src/flickcode/subagents/tasks.py`、`src/flickcode/subagents/notifications.py`、`src/flickcode/subagents/models.py`、`tests/test_subagent_tasks.py`、`tests/test_subagent_notifications.py`  
**依赖：** T18、T28

**步骤：**
1. 增加锁内 `record_workspace(task_id, status)`，只允许 NOT_USED→entered→terminal disposition 的单向更新。
2. 任务运行时 status 可见 path/branch/recovered；完成后保留历史路径与处置，即使目录已删除。
3. AgentToolResponse 和一次性通知加入有界摘要，不自动读取 Worktree 文件或完整 Git 输出。
4. 重复 entered/exited 回调保持幂等，终态后不能退回活动状态。

**验证：** 运行 `python -m unittest tests.test_subagent_tasks tests.test_subagent_notifications -v`；期望工作区状态单向、重复回调无副作用、通知仍只发送一次。

## T30：让 Hook 在子工作区执行

**文件：** `src/flickcode/subagents/hooks.py`、`src/flickcode/hooks/actions.py`、`tests/test_hooks_integration.py`、`tests/test_subagent_hooks.py`  
**依赖：** T26、T28

**步骤：**
1. `SubAgentHookScope` 接收 WorkspaceContext，以 child project root 构造执行 scope。
2. Hook shell runner 的 subprocess 显式使用 scope cwd，不读进程 cwd。
3. Hook 元数据加入 isolation/path/branch，继续复用父 catalog 和后台执行设施。
4. 验证 Hook 在子目录写的相对测试文件不会出现在主目录，且敏感初始化内容不进入事件。

**验证：** 运行 `python -m unittest tests.test_subagent_hooks tests.test_hooks_integration -v`；期望 shared 回归通过，Worktree Hook cwd 与元数据正确。

## T31：在 Session 装配生命周期与 Janitor

**文件：** `src/flickcode/session.py`、`src/flickcode/worktrees/__init__.py`、`tests/test_subagent_integration.py`、`tests/test_worktree_cleanup.py`  
**依赖：** T5、T16、T27–T30

**步骤：**
1. Session 构造主 `WorkspaceContext`，加载 Worktree 配置和诊断，创建 layout/repository/bootstrap/lifecycle/resource cache。
2. 将 lifecycle 注入 SubAgentRunner，并在 TaskManager 建立后绑定 workspace callback。
3. Session `start()` 后异步启动 Janitor；非 Git 项目也能启动 Session，仅 Worktree 请求失败。
4. Session `close()` 先停止接收任务并等待/取消子任务，再有界关闭 Janitor，最后关闭共享设施。
5. 重复 close 保持幂等，清理错误只进入统一诊断。

**验证：** 运行 `python -m unittest tests.test_subagent_integration tests.test_worktree_cleanup.SessionJanitorIntegrationTests -v`；期望合法装配、非 Git shared/Fork、启动/关闭顺序和重复 close 通过。

## T32：完成工具契约全仓迁移

**文件：** 所有 `src/flickcode/**` 工具调用点与直接调用工具的 `tests/test_*.py`  
**依赖：** T22–T24、T31

**步骤：**
1. 用 `rg` 找出全部 `.execute(` 工具调用点，逐一传入绝对 cwd；测试使用临时目录，不使用隐式进程 cwd。
2. 检查全部 BaseTool 子类签名一致，MCP/Skill/Agent adapters 不漏关键字参数。
3. 删除 Glob/Grep 旧 `os.chdir()` 和 try/finally cwd 恢复代码。
4. 扫描 Worktree、工具、子 Agent、Hook 产品代码，确保没有新增 `os.chdir()`。

**验证：** 运行 `rg -n "os\.chdir" src/flickcode/worktrees src/flickcode/tools src/flickcode/subagents src/flickcode/hooks`，期望无输出；再运行 `python -m unittest discover -s tests -p 'test_*tool*.py' -v`，期望全部通过。

## T33：补齐安全与并发集成测试

**文件：** `tests/test_worktree_lifecycle.py`、`tests/test_worktree_cleanup.py`、`tests/test_tools_workspace.py`  
**依赖：** T16、T31、T32

**步骤：**
1. 并发启动同名/不同名创建，使用 barrier 和记录型 Git fake 验证锁粒度。
2. 在活动 lease 期间触发 Janitor，确认第三方不能删除；lease 退出后按安全状态决定。
3. 伪造目录外 metadata、错误 common dir、case collision 和 symlink 目标，确认零删除调用。
4. 注入 Git timeout、metadata 原子写失败、remove 成功/branch delete 失败，检查幂等恢复和诊断。
5. 对超限候选、文件数、字节数和关闭时间做确定性测试。

**验证：** 运行 `python -m unittest tests.test_worktree_lifecycle tests.test_worktree_cleanup tests.test_tools_workspace -v`；期望所有安全/竞态/上限案例通过且无测试残留进程。

## T34：实现双子 Agent 端到端场景

**文件：** `tests/test_worktree_integration.py`  
**依赖：** T25–T33

**步骤：**
1. 创建临时真实 Git 仓库、最小 FlickCode 配置和 `isolation: worktree` 角色。
2. 用可控 fake Provider 同时启动两个定义式子 Agent，让它们通过相对路径修改同一个文件名并读回。
3. 断言两个子目录内容不同、主目录原文件不变、每个权限根/Hook cwd/context path 指向本 Worktree。
4. 让一个 Agent 恢复干净状态并自动清理，另一个保留未提交修改；验证 task result 的 disposition/path/reason。
5. 另测 shared 角色与 Fork 均使用主目录且 Agent 工具 schema 不变。

**验证：** 运行 `python -m unittest tests.test_worktree_integration -v`；期望 AC20 完整通过，保留目录只出现在预期任务。

## T35：更新 README 与示例

**文件：** `README.md`、`src/flickcode/subagents/builtins/*.md`  
**依赖：** T17、T31、T34

**步骤：**
1. 在 SubAgents 章节说明可选 `isolation: shared|worktree`，并给出最小 Worktree 角色例子。
2. 说明 `.flickcode/worktrees.yaml` 的 copy/symlink/ignored allowlist，强调默认不复制 `.env`。
3. 说明目录/分支位置、显式 cwd、任务结束保留/删除规则、7 天后台清理和未推送判定。
4. 明确 Fork shared、无自动 merge/push/同步、链接失败语义和如何从任务结果找到保留路径。

**验证：** 运行 `rg -n "isolation: worktree|worktrees.yaml|7 天|refs/remotes|Fork" README.md`；期望五类说明均可定位，示例 YAML 能被 `WorktreeConfigLoader` 测试解析。

## T36：执行全量回归与验收

**文件：** `docs/worktrees/checklist.md`、全部实现与测试文件  
**依赖：** T33–T35

**步骤：**
1. 运行全量 unittest，记录测试数量、耗时和失败信息。
2. 运行 py_compile/项目现有 build 检查，确认 Python 3.8 兼容语法和打包包含新 package。
3. 扫描 `TODO|TBD`、`os.chdir`、未显式 cwd 的工具调用和敏感值输出。
4. 按 `docs/worktrees/checklist.md` 逐项执行，写入实际命令、结果与必要的临时仓库观察证据。
5. 任一失败先修复并重跑关联测试与全量套件，再标记通过。

**验证：** 运行 `python -m unittest discover -s tests -v` 与 `python -m compileall -q src tests`；期望退出码均为 0。随后 checklist 每项均有实际证据或明确未通过记录。

## 执行顺序

```text
T1 → T2 → T3 → T4
 │    └────→ T5
 └────────→ T6 → T7 → T8 → T9
                    └→ T10 → T11
T3 + T5 + T8 + T11 → T12 → T13 → T14 → T15 → T16

T1 → T17 → T18
T1 → T19 → T20 → T21
              └────→ T22 → T23 → T24
T19 → T25 → T26
T18 + T26 → T27
T15 + T27 → T28 → T29
                 └→ T30
T5 + T16 + T27..T30 → T31 → T32 → T33 → T34 → T35 → T36
```

T2–T11 的纯 Worktree 基础设施可与 T17–T24 的角色/工具 cwd 迁移分支并行；T25 之后需要两边接口稳定后再集成。依赖图无循环。
