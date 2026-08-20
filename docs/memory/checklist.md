# 会话恢复与分层记忆 Checklist

> 每项均以实际运行命令或可观察行为验证。自动化测试应使用临时目录和 fake Provider，不依赖真实 API Key 或网络。

## 指令加载与安全边界

- [ ] 三层 `AGENTS.md` 同时存在时，系统提示中 `<project>/AGENTS.md` 与 `<project>/.flickcode/AGENTS.md` 的内容均位于 `~/.flickcode/AGENTS.md` 内容之前。（验证：运行 `python -m unittest tests.test_memory.InstructionLoaderTests`，检查优先级断言。）
- [ ] 缺失任意或全部指令文件时，Session 仍能创建并请求 Provider。（验证：运行 `python -m unittest tests.test_memory.SessionMemoryIntegrationTests.test_missing_instruction_files_do_not_block_request`。）
- [ ] `@include` 的嵌套内容在指令原位置按稳定顺序展开。（验证：运行 `python -m unittest tests.test_memory.InstructionLoaderTests.test_nested_include_expands_in_place`。）
- [ ] 循环、重复、超深、缺失、不可读和越界 include 均被拒绝并带诊断，其他合法内容仍被加载。（验证：运行 `python -m unittest tests.test_memory.InstructionLoaderTests.test_rejected_includes_are_diagnostic_and_non_blocking`。）
- [ ] 项目指令无法经 `..` 或绝对路径读出项目根外文件，用户指令无法读出 `~/.flickcode` 外文件。（验证：运行 `python -m unittest tests.test_memory.InstructionLoaderTests.test_include_cannot_escape_allowed_root`。）

## JSONL 会话归档与列表

- [ ] 首条需要持久化的消息创建一个名为 `YYYYMMDD-HHMMSS-xxxx.jsonl` 的文件，连续多次生成 ID 不重复。（验证：运行 `python -m unittest tests.test_memory.SessionJournalTests.test_new_ids_are_valid_and_unique`。）
- [ ] 同一会话的开始、恢复和消息事件以独立 JSONL 行追加；写入后已有行未被改写。（验证：运行 `python -m unittest tests.test_memory.SessionJournalTests.test_messages_append_as_jsonl_without_meta_file`。）
- [ ] 归档目录没有会话 meta 文件，扫描 JSONL 可推导会话 ID、首条用户标题、消息数与最后活动时间。（验证：运行 `python -m unittest tests.test_memory.SessionJournalTests.test_list_derives_metadata_from_jsonl_only`。）
- [ ] 单个损坏归档在 `/sessions` 中标记不可恢复或带原因，但不阻止其他合法会话显示；非匹配文件不会列入。（验证：运行 `python -m unittest tests.test_memory.SessionJournalTests.test_listing_isolates_invalid_and_non_session_files`。）
- [ ] 归档追加失败时内存中的消息保留，且 Session 诊断队列出现写入失败原因。（验证：运行 `python -m unittest tests.test_memory.SessionMemoryIntegrationTests.test_archive_write_failure_preserves_memory_history`。）

## 显式恢复、历史修复与清理

- [ ] 新建 Session 后历史为空，且不会自动读取、选择或恢复项目中现存的 JSONL；只有 `/resume <会话ID>` 会启动恢复。（验证：运行 `python -m unittest tests.test_memory.SessionMemoryIntegrationTests.test_new_session_does_not_auto_resume`。）
- [ ] `/resume` 只接受合法会话 ID，并且只能读取当前项目 `sessions` 目录内对应文件；路径、后缀和遍历输入均被拒绝。（验证：运行 `python -m unittest tests.test_memory.SessionRecoveryTests.test_resume_id_cannot_escape_sessions_directory`。）
- [ ] 恢复扫描跳过坏 JSON、未知记录与不完整消息，并在结果中保留行号和跳过原因。（验证：运行 `python -m unittest tests.test_memory.SessionRecoveryTests.test_invalid_jsonl_lines_are_skipped_with_diagnostics`。）
- [ ] 恢复遇到孤立工具结果时跳过该结果；遇到未配对工具调用时，在发起该调用的 assistant 消息前截断，结果可直接交给任一 Provider。（验证：运行 `python -m unittest tests.test_memory.SessionRecoveryTests.test_tool_sequences_are_repaired_before_resume`。）
- [ ] 恢复历史超预算时只启动一次恢复编排压缩；压缩成功才替换历史，压缩后仍超限则保留恢复前的内存会话。（验证：运行 `python -m unittest tests.test_memory.SessionMemoryIntegrationTests.test_resume_context_budget_is_atomic_and_compacts_once`。）
- [ ] 最后活动时间早于当前时间超过 7 天时，恢复历史追加可观察的时间跨度提醒；恰好 7 天或更短时间时不追加。（验证：运行 `python -m unittest tests.test_memory.SessionRecoveryTests.test_time_gap_notice_uses_configured_threshold`。）
- [ ] 清理时仅删除超过 30 天、名称合法且不为当前活跃 ID 的会话文件；近期、当前和用户自定义文件均被保留。（验证：运行 `python -m unittest tests.test_memory.SessionRecoveryTests.test_prune_only_removes_expired_managed_sessions`。）
- [ ] 无法读取或删除某个清理候选文件时，启动继续且记录诊断。（验证：运行 `python -m unittest tests.test_memory.SessionRecoveryTests.test_prune_failure_is_non_blocking`。）

## 分层长期记忆与请求注入

- [ ] 用户级与项目级笔记分别存放在各自 `memory/` 根目录，每条笔记均含类别、创建时间和更新时间 frontmatter。（验证：运行 `python -m unittest tests.test_memory.MemoryRepositoryTests.test_scopes_and_frontmatter_are_independent`。）
- [ ] 仅用户偏好、纠正反馈、项目知识和参考资料可被写入；非法类别、scope、ID 或空正文不产生文件修改。（验证：运行 `python -m unittest tests.test_memory.MemoryRepositoryTests.test_invalid_changes_are_rejected`。）
- [ ] 索引从笔记重建，按最近更新时间输出，且每份始终不超过 200 行与 25 KB；被裁剪的笔记文件仍可在磁盘找到。（验证：运行 `python -m unittest tests.test_memory.MemoryRepositoryTests.test_index_limits_preserve_note_files`。）
- [ ] 索引或单条笔记不可读时，其他可读记忆仍被加载，前台请求仍会发送，且有诊断。（验证：运行 `python -m unittest tests.test_memory.MemoryRepositoryTests.test_read_failures_are_non_blocking`。）
- [ ] Chat 和 Agent Loop 每次 Provider 请求前均读取索引并注入；项目记忆 section 位于用户记忆 section 之前，且标明仅作参考事实。（验证：运行 `python -m unittest tests.test_memory.SessionMemoryIntegrationTests.test_both_request_paths_inject_memory_indexes`。）
- [ ] 没有任何指令或索引内容时，新增 prompt section 不产生空提示或改变已有 prompt 的可见内容。（验证：运行 `python -m unittest tests.test_memory.PromptMemorySectionTests.test_empty_sections_are_omitted`。）

## Agent Loop 自动笔记更新

- [ ] Agent Loop 以无工具调用最终回复完成时，`done` 事件和最终文本先到达前台，记忆更新在后台开始。（验证：运行 `python -m unittest tests.test_memory.SessionMemoryIntegrationTests.test_completed_agent_schedules_memory_update_after_done`。）
- [ ] Provider 错误、取消、迭代上限、未知工具和上下文阻断均不安排笔记更新。（验证：运行 `python -m unittest tests.test_memory.SessionMemoryIntegrationTests.test_non_completed_agent_stops_do_not_schedule_memory_update`。）
- [ ] LLM 返回的 `discard` 不创建重复笔记；有效 `upsert` 只写到对应的用户或项目仓库。（验证：运行 `python -m unittest tests.test_memory.MemoryUpdaterTests.test_valid_changes_update_only_their_scope`。）
- [ ] LLM 的非 JSON、非法字段或 Provider 错误不会修改笔记，也不会使下一轮聊天或 Agent 请求失败。（验证：运行 `python -m unittest tests.test_memory.MemoryUpdaterTests.test_invalid_or_failed_updates_are_non_blocking`。）
- [ ] 提交后台更新不会等待 Provider 完成，同一 Session 的多个更新按提交顺序执行。（验证：运行 `python -m unittest tests.test_memory.MemoryUpdaterTests.test_submit_is_non_blocking_and_serial`。）

## 命令与端到端行为

- [ ] `/sessions` 显示当前项目每个可管理会话的 ID、标题、消息数、最后活动时间和状态/原因，且不发送 Provider 请求。（验证：运行 `python -m unittest tests.test_memory.TUIMemoryCommandTests.test_sessions_command_lists_without_provider_request`。）
- [ ] `/resume <会话ID>` 成功时显示恢复消息数、跳过/截断/压缩/时间提醒摘要；失败时显示原因且当前会话仍可继续。（验证：运行 `python -m unittest tests.test_memory.TUIMemoryCommandTests.test_resume_command_reports_result_and_preserves_failure_state`。）
- [ ] 交互与管道模式均会识别 `/sessions` 和 `/resume`，不会把命令文本作为模型消息；`/compact`、`/plan`、`/do` 和退出命令仍可用。（验证：运行 `python -m unittest tests.test_memory.TUIMemoryCommandTests.test_commands_are_not_forwarded_in_either_loop tests.test_context.TUICompactTests`。）
- [ ] 最小端到端流程可用：发送一条消息 → `sessions/` 产生 JSONL → `/sessions` 显示该会话 → 新 Session 中 `/resume <会话ID>` 恢复该消息。（验证：运行 `python -m unittest tests.test_memory.EndToEndMemoryTests.test_explicit_resume_workflow`。）

## 回归与文档

- [ ] README 说明三层 `AGENTS.md`、安全 include、存储位置、`/sessions`、`/resume`、7 天提醒、30 天清理、四类自动笔记及不包含 RAG/向量库。（验证：运行 `python -m unittest tests.test_memory.DocumentationTests.test_readme_documents_memory_feature`，并人工打开 README 确认说明可读。）
- [ ] 全部测试在没有真实 API Key、网络或既有用户文件的情况下通过。（验证：运行 `python -m unittest discover -s tests -v`，期望 exit code 为 0。）

## 验收报告

> 实现完成后填写。每项应记录实际命令、日期和观察到的结果；未通过项写明实际行为与修复后复验结果。

### 通过（核心自动化验收）

- [x] 分层指令优先级、嵌套 include、循环/越界拒绝和缺失文件容错。（证据：`InstructionLoaderTests`。）
- [x] JSONL 追加、无 meta 扫描、坏行跳过、工具调用修复、7 天提醒和 30 天清理。（证据：`SessionJournalTests`、`SessionRecoveryTests`。）
- [x] 用户/项目笔记隔离、frontmatter、索引 200 行/25 KB 限制与后台更新校验。（证据：`MemoryRepositoryTests`、`MemoryUpdaterTests`。）
- [x] Chat 与 Agent Loop 的预请求注入、JSONL 落盘、显式恢复原子性与自然结束后的异步调度。（证据：`SessionMemoryIntegrationTests`。）
- [x] `/sessions` 与 `/resume` 不会发送 Provider 请求。（证据：`TUIMemoryCommandTests`。）
- [x] 全量测试通过。（证据：2026-08-13 运行 `PYTHONPATH=src .venv\\Scripts\\python.exe -m unittest discover -s tests -v`：56 passed，1 skipped；跳过项是当前 Windows 环境不允许创建符号链接时的 symlink 防护测试。）

### 未通过（如有）

- [ ] 无。

### 端到端

- [x] fake Provider 流程：发送消息 → 创建 JSONL → `/sessions` 列表 → `/resume` 恢复，且恢复命令不调用 Provider。（证据：`SessionMemoryIntegrationTests.test_chat_injects_memory_archives_and_explicitly_resumes`、`TUIMemoryCommandTests.test_sessions_and_resume_commands_do_not_call_provider`。）
