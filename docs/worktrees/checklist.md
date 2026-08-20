# FlickCode Worktree 隔离 Checklist

> 每项都通过运行测试、执行命令或观察临时仓库行为验证。实现前保持未勾选；开发完成后记录实际证据，不以代码阅读代替行为验证。

## 角色与范围

- [ ] `isolation: worktree` 的定义式角色可加载并启用独立工作区（验证：运行角色解析测试并启动最小定义式任务，观察 workspace isolation 为 `worktree`）。
- [ ] `isolation: shared` 和省略 isolation 的旧角色都继续使用主项目目录（验证：分别启动两类角色，比较 task workspace path 与 Session project root）。
- [ ] 非法 isolation 只拒绝对应角色，其他合法角色仍出现在目录中（验证：同一临时角色目录放入一合法一非法文件，刷新 catalog 后观察诊断与 effective roles）。
- [ ] Fork 式子 Agent 始终使用共享主目录（验证：启动 Fork 并查询 status，workspace disposition 为 `not_used` 且 cwd 为主项目目录）。
- [ ] Agent 工具输入 schema 未增加 isolation、path、branch 等调用字段（验证：序列化工具 schema 与功能前基线/预期字段集合比较）。

## 仓库与创建基线

- [ ] 合法 Git 仓库中的隔离任务从启动瞬间的完整 `HEAD` OID 创建独立分支（验证：记录主 `git rev-parse HEAD`，启动任务后在子目录执行同一命令并检查 metadata base commit）。
- [ ] 主目录未提交修改不会出现在新 Worktree（验证：主目录修改一个 tracked 文件但不提交，创建 Worktree 后比较子文件仍为 HEAD 内容）。
- [ ] 非 Git 目录请求 Worktree 时明确失败且没有在共享目录执行任务（验证：临时非 Git 项目启动隔离角色，检查 provider 未收到首次请求、主目录无任务写入）。
- [ ] 无可解析 `HEAD` 的空仓库不会创建半成品 Worktree（验证：在 `git init` 但无 commit 的仓库启动，观察阶段化失败与托管目录安全状态）。
- [ ] Worktree 专属仓库错误不影响 shared 角色、Fork 或父 Session（验证：同一非 Git Session 随后运行 shared 任务和普通请求，均成功响应）。

## 名称与路径安全

- [ ] 1–8 段、每段和总长均在边界内的嵌套名称可映射到固定托管根（验证：运行名称边界参数化测试，检查规范化目标位于 `.flickcode/worktrees`）。
- [ ] `.`、`..`、空段、反斜杠、绝对路径、盘符、前导/尾随斜杠、超长名称全部拒绝（验证：运行恶意名称表驱动测试，确认没有目录或 Git 调用产生）。
- [ ] 大小写不敏感平台上的折叠冲突不会创建两个目标（验证：注入大小写不敏感策略，依次申请冲突名并观察第二个拒绝）。
- [ ] 临时分支名只由受控任务身份和名称摘要生成，且通过 Git ref 校验（验证：对包含点/嵌套的合法名称生成分支，运行 `git check-ref-format --branch`）。
- [ ] 托管根由仓库本地 exclude 忽略，不修改 tracked `.gitignore`（验证：创建前后比较 `.gitignore` 内容/存在性，并运行 `git status --porcelain --untracked-files=all`）。
- [ ] 目录外路径、伪造 sidecar 和指向外部的 symlink 不会触发删除（验证：运行安全删除攻击用例，检查 delete fake 调用为零且目标内容仍存在）。

## 创建、元数据与快速恢复

- [ ] 首次创建产生独立 Worktree、临时分支和 `ready` sidecar（验证：运行首次创建集成测试，检查 Git worktree list 与 metadata 必填字段）。
- [ ] metadata 位于托管根 state 区而非子 Worktree，且不制造子分支未跟踪状态（验证：定位 sidecar 并在子目录运行 `git status --porcelain --untracked-files=all`）。
- [ ] metadata 写入是原子的，截断/损坏/未知版本文件不会被接受（验证：注入写入故障并准备三类坏 JSON，观察恢复拒绝且旧文件不被半覆盖）。
- [ ] 已存在合法目录的快速恢复不调用 Git（验证：使用“调用即失败”的 Git fake 执行 create，结果 recovered=true 且 fake 调用数为 0）。
- [ ] 快速恢复不写文件、不更新 last-used、不重复初始化（验证：对目标/sidecar 做前后内容和 mtime 快照，bootstrap fake 调用为 0）。
- [ ] 缺失 sidecar、仓库身份不符、路径不符或非 ready 状态均拒绝接管（验证：分别篡改一项后恢复，目标目录哈希保持不变）。
- [ ] create 后 enter 才更新 last-used 并登记租约（验证：使用可控时钟比较 create/recover 与 enter 前后 metadata）。

## 环境初始化

- [ ] 无 `.flickcode/worktrees.yaml` 时使用 7 天和空初始化规则，不创建配置模板（验证：加载空项目并比较目录树前后）。
- [ ] 明确 copy 规则复制本地配置到子项目相同相对路径（验证：准备示例文件，初始化后比较内容与必要权限）。
- [ ] 明确 symlink 规则创建指向主项目源的大型依赖目录链接（验证：检查链接类型、解析目标和子进程从子 cwd 访问依赖成功）。
- [ ] 目录链接创建失败时初始化失败，不静默复制依赖（验证：mock `os.symlink` 失败，检查目标不是普通目录且错误包含规则）。
- [ ] ignored 规则只复制 Git 确认已忽略的普通文件（验证：同一 glob 同时匹配 ignored 和 tracked/untracked 文件，只观察 ignored 候选出现在计划/目标）。
- [ ] 未显式声明的 `.env`、凭据和本地文件不会复制（验证：主项目准备 `.env` 和 token 文件，使用空/无关规则初始化，扫描子目录不存在这些文件）。
- [ ] 绝对路径、遍历、反斜杠、规则重复和跨类别冲突在任何目标写入前拒绝（验证：配置安全测试比较目标目录写入调用为零）。
- [ ] 初始化复制受 2,000 文件和 512 MiB 上限约束（验证：注入小测试上限模拟超限，观察预检失败且不执行复制）。
- [ ] 子 Worktree 的有效 Git hooks 路径与主目录一致，设置不会覆盖另一 Worktree（验证：创建两个 Worktree，分别查询 worktree-local config 并比较主配置）。
- [ ] 初始化产物按规则被忽略，不会单独造成 dirty 判定（验证：初始化后立即运行安全检查，changed_paths 为空）。
- [ ] 初始化中途失败会阻止第一次模型请求并报告保留路径（验证：注入第二个复制动作失败，检查 provider 调用为 0、metadata failed、结果含绝对路径）。

## 显式 cwd 与工具隔离

- [ ] 产品中的每次工具执行都显式收到绝对 cwd（验证：记录型 fake tool 覆盖主 Agent、shared 子 Agent、Worktree 子 Agent 和隔离 Skill 调用）。
- [ ] 省略 cwd 的直接 BaseTool 调用被接口拒绝，产品代码没有隐式默认（验证：契约测试期望 TypeError，并扫描工具基类签名）。
- [ ] Read/Write/Edit 的相对路径都基于调用方 cwd（验证：两个 workspace 对同名相对文件并行读写，检查内容互不覆盖）。
- [ ] ExecuteCommand 与 Skill 脚本的实际子进程 cwd 是调用方工作区（验证：命令/脚本输出当前目录，比较规范化绝对路径）。
- [ ] Glob/Grep 在两个工作区只返回各自文件且不改变进程 cwd（验证：执行前后记录 `os.getcwd()`，并行搜索不同标记内容）。
- [ ] Worktree/工具/SubAgent/Hook 生产代码不调用 `os.chdir`（验证：运行 `rg -n "os\.chdir" src/flickcode/worktrees src/flickcode/tools src/flickcode/subagents src/flickcode/hooks`，期望无输出）。
- [ ] MCP 和系统工具仍使用原远端参数 schema，不把 cwd 暴露给模型或远端调用（验证：API tool schema 快照与 MCP call 参数 fake 比较）。

## 缓存、提示、指令与记忆隔离

- [ ] 文件内容缓存键包含规范化绝对路径和文件版本（验证：检查 cache trace，两个根的相同相对名产生两个 key）。
- [ ] Write/Edit 后再次 Read 返回新内容，不命中旧缓存（验证：读→写/编辑→读序列测试）。
- [ ] 删除并重建同一绝对路径后不会返回旧内容（验证：保持路径相同、改变 inode/mtime/size，读取新标记）。
- [ ] 两个 Worktree 的同名 `AGENTS.md` 与 include 文件各自进入本目录 InstructionBundle（验证：构造不同内容并比较 bundle source_paths 和 prompt）。
- [ ] 两个 Worktree 的项目 `memory/index.md` 各自进入本目录提示（验证：放置不同项目记忆标记，首次模型请求只含本目录标记）。
- [ ] 用户指令和用户记忆仍从用户绝对路径共享，但缓存 key 不与项目路径混淆（验证：cache trace 与两次提示内容对比）。
- [ ] 系统提示缓存 key 包含绝对项目根、角色/资源版本和日期（验证：同角色在两个 Worktree 及资源变更前后产生不同 key）。
- [ ] Worktree 切换不执行全量缓存清理也能得到正确内容（验证：在共享→子 A→子 B→子 A 顺序调用，cache 实例保持但输出正确）。

## 权限、Hook 与上下文产物

- [ ] Worktree 子 Agent 的权限沙箱根是子项目目录（验证：读取子目录相对文件允许，读取主目录绝对路径拒绝）。
- [ ] 指向主目录或外部的 symlink 不能让文件工具逃离子沙箱（验证：创建测试链接并调用 ReadFile，观察 sandbox deny）。
- [ ] 每个 Worktree 的权限临时状态互不共享（验证：对子 A 建立会话许可后，在子 B 检查同操作仍按其自身策略判定）。
- [ ] 子 Agent Hook shell 动作在子项目 cwd 执行（验证：Hook 写相对标记文件，只在子 Worktree 出现）。
- [ ] Hook 事件包含任务、隔离模式、路径和分支，但不包含复制文件内容或令牌（验证：捕获事件 JSON 并做字段/敏感标记扫描）。
- [ ] 每个子 Agent 的上下文产物存入其 Worktree 的绝对 `.tmp/subagents/context/<task-id>`（验证：触发 oversized tool result，比较结果路径前缀）。
- [ ] 一个 Worktree 的 context/summary 产物不会出现在另一 Worktree 或主目录（验证：三个根目录快照对比）。

## 退出与变更保护

- [ ] 正常完成、轮次受限、失败和取消均恰好执行一次退出（验证：参数化四终态并检查 lifecycle exit 计数）。
- [ ] 清理失败不会改写子 Agent 原终态（验证：注入 exit 异常，任务仍保持对应 completed/limited/failed/cancelled，workspace reason 单独记录）。
- [ ] 暂存修改使默认/自动删除拒绝（验证：`git add` 后 exit，观察 retained_changes 和目录存在）。
- [ ] 未暂存修改使默认/自动删除拒绝（验证：修改 tracked 文件后 exit，观察 retained_changes）。
- [ ] 未跟踪文件使默认/自动删除拒绝（验证：新建未忽略文件后 exit，观察 retained_changes）。
- [ ] 自创建基线新增且未被任何远端引用包含的 commit 使删除拒绝（验证：无 upstream 的本地 commit 后 exit，观察 retained_unpushed）。
- [ ] 未推送判定不要求 upstream，并检查所有 `refs/remotes/*`（验证：创建多个远端跟踪引用，检查 commit 包含性组合）。
- [ ] 新增 commit 被任意一个远端跟踪引用包含后不再视为未推送（验证：创建本地 remote-tracking ref 包含 commit，再次 inspect）。
- [ ] 主分支在创建前已有但未推送的 base commit 不被误算为 Worktree 新 commit（验证：从本地主分支 commit 创建后不新增 commit，unique_commits 为空）。
- [ ] status、rev-list 或远端包含性查询任一失败时保守保留（验证：逐阶段注入 Git error，观察 retained_check_failed 且无 remove 调用）。
- [ ] 干净且无未推送 commit 的 Worktree 在退出后自动删除（验证：无修改任务完成后检查路径、临时分支和 sidecar 均不存在）。
- [ ] 推送但未合并的新增 commit 可按规则清理，系统不执行 merge（验证：让远端 ref 包含 commit，退出后删除本地 Worktree/临时分支，同时主分支 HEAD 不变）。
- [ ] 有修改的任务保留不是任务失败，结果给出绝对路径和准确原因（验证：completed 任务制造修改，检查 state completed + retained_changes）。

## 安全删除与并发

- [ ] 删除前再次验证名称、路径、metadata、仓库 Worktree 列表和活动租约（验证：分别破坏一项，每次都观察零物理删除调用）。
- [ ] 安全删除只移除 metadata 指向的精确 Worktree 和临时分支（验证：同仓库准备第二 Worktree/分支，删除后确认第二个完整）。
- [ ] Worktree remove 成功但分支删除失败时记录部分失败，重复调用不会删除无关分支（验证：注入分支删除错误后重试）。
- [ ] 同名并发 create/enter 只产生一个受控 Worktree（验证：线程 barrier + Git add 调用计数为 1）。
- [ ] 不同名称可以并行且不共享租约或 file cache（验证：两个并发任务记录不同 handle、cache identity 和目标路径）。
- [ ] 活动租约期间显式 delete 与 Janitor 都拒绝删除（验证：阻塞 Agent 运行，触发两种删除后检查目录仍在）。
- [ ] 重复 exit、完成回调和 cleanup 不会重复删除或使状态回退（验证：并发重复调用，remove 计数不超过 1、task state 保持终态）。

## 后台过期清理

- [ ] 默认最后使用不足 7 天的候选不进入 Git 检查（验证：可控时钟设置 6 天 23:59，Git fake 调用数为 0）。
- [ ] 默认超过 7 天的候选进入三层过滤（验证：设置 7 天加最小时间增量，观察过滤计数）。
- [ ] 项目配置其他正整数 expiry 后边界随之变化（验证：配置 2 天并测试边界两侧）。
- [ ] 路径过滤失败候选被跳过且不读取任意目录内容（验证：目录外/非法名 sidecar，观察 path skip 和零 Git）。
- [ ] 归属过滤失败或活动租约候选被跳过（验证：错误 fingerprint、路径不符和 active 三个案例）。
- [ ] Git/变更过滤失败候选被保留（验证：非当前 repo Worktree、dirty、unpushed 和查询异常案例）。
- [ ] 合法、过期、干净且无未推送 commit 的候选被删除（验证：Janitor run_once 后检查路径/分支/sidecar）。
- [ ] 单个候选异常不会中止后续合法候选（验证：排序在前的 fake 抛错，排序在后的安全候选仍删除）。
- [ ] 每轮最多处理 256 个候选，不进行无限扫描（验证：注入 257+ sidecar，检查 report processed 上限与剩余文件）。
- [ ] Janitor 首扫异步且不阻塞 Session 启动（验证：阻塞 janitor fake，Session start 仍在短时限内返回）。
- [ ] Janitor 等待可被关闭 Event 唤醒，Session close 在 5 秒内结束（验证：计时 close 并确认 worker 不存活）。

## 兼容、构建与回归

- [ ] 普通主 Agent 对话、共享子 Agent、Fork、Skill、Hook、MCP、权限、上下文和命令测试全部通过（验证：运行全量 unittest）。
- [ ] Worktree 配置损坏不阻止 Session 启动或 shared/Fork 任务（验证：放入非法 YAML，观察诊断后运行两类非 Worktree 操作）。
- [ ] 新 package 被构建系统包含，安装后可导入 `flickcode.worktrees`（验证：构建 wheel/执行 editable install 环境导入测试）。
- [ ] Python 3.8 兼容编译通过（验证：在项目支持的最低版本环境执行 compileall 与测试；没有运行环境时明确记录缺口）。
- [ ] 全部测试通过（验证：运行 `python -m unittest discover -s tests -v`，记录实际测试数和退出码 0）。
- [ ] 源码编译通过（验证：运行 `python -m compileall -q src tests`，退出码 0）。
- [ ] 文档和实现不存在 `TODO`、`TBD` 或未解决占位符（验证：运行 `rg -n "TODO|TBD|待定|占位" docs/worktrees src/flickcode/worktrees`，人工排除仅用于测试字符串的命中）。
- [ ] 日志/响应不泄露 `.env` 内容、API Key、Authorization header 或复制文件正文（验证：用哨兵秘密跑失败路径，扫描捕获日志、task result 和通知）。

## 端到端场景

- [ ] **并行隔离主场景**：在同一临时 Git 仓库启动两个 `isolation: worktree` 的定义式子 Agent，同时通过相对路径修改同一文件名；两边各自读回自己的内容，主目录文件保持不变（验证：运行 `python -m unittest tests.test_worktree_integration.WorktreeParallelEndToEndTests -v` 并记录三个目录的文件摘要）。
- [ ] **干净自动回收场景**：隔离任务只读并正常结束，目录、临时分支和 sidecar 自动删除，任务保持 completed 且 disposition 为 removed（验证：端到端测试 + `git worktree list`/`git branch --list` 观察）。
- [ ] **修改保护场景**：隔离任务修改文件后正常结束，任务保持 completed，Worktree 保留并返回绝对路径/reason；主 Agent 可从该路径检查修改（验证：端到端测试后在返回路径执行 `git status --short`）。
- [ ] **未推送 commit 保护场景**：隔离任务提交但不设置 upstream、不创建远端包含 ref，退出后目录保留为 retained_unpushed（验证：返回路径和 `git log base..HEAD` 对比）。
- [ ] **快速恢复场景**：模拟进程内 handle 丢失但保留合法目录/sidecar，再次 create 只读恢复；随后 enter/exit 正常管理（验证：Git fake 零调用阶段与最终处置记录）。
- [ ] **过期清理场景**：保留的安全 Worktree 最后使用时间超过配置值后由后台三层过滤删除；脏或未推送候选仍保留（验证：可控 clock 集成测试和 CleanupReport 计数）。

## 验收标准覆盖

| 验收标准 | Checklist 覆盖区域 |
|---|---|
| AC1 | 角色与范围 |
| AC2 | 仓库与创建基线 |
| AC3 | 名称与路径安全 |
| AC4 | 创建、元数据与快速恢复 |
| AC5 | 环境初始化 |
| AC6 | 显式 cwd 与工具隔离 |
| AC7 | 缓存、提示、指令与记忆隔离 |
| AC8 | 创建基线、环境初始化、端到端首次请求 |
| AC9 | 退出与变更保护 |
| AC10 | 退出与变更保护的 dirty/unpushed 条目 |
| AC11 | 退出与变更保护的远端包含/错误条目 |
| AC12 | 安全删除与并发 |
| AC13 | 退出与变更保护、端到端修改保护 |
| AC14 | 后台过期清理的边界条目 |
| AC15 | 后台过期清理的三层失败条目 |
| AC16 | 安全删除与并发 |
| AC17 | 角色与范围、兼容回归 |
| AC18 | 显式 cwd、路径安全、跨平台链接行为 |
| AC19 | 初始化/清理上限、快速恢复、构建关闭 |
| AC20 | 并行隔离主场景 |

所有 spec 验收标准至少映射到一个可运行或可观察条目，并包含多个完整端到端场景。

## 开发验证记录

当前实现已完成基础生命周期、显式 cwd、缓存隔离和子 Agent 接入；已执行：

- `.venv\\Scripts\\python.exe -m compileall -q src tests`
- `.venv\\Scripts\\python.exe -m unittest discover -s tests -q`：161 tests，1 skipped，全部通过
- `tests.test_worktree_core`：真实临时 Git 仓库创建、脏目录保留、非 Git 拒绝、快速恢复零 Git 调用
- 真实临时 Git 仓库端到端：隔离子 Agent 使用独立 Worktree/cwd，修改后返回 `retained_changes`；干净目录由 Janitor 过期扫描删除
