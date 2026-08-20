# FlickCode

> 轻量、可扩展的终端 AI 编程助手。
> A lightweight, extensible CLI coding agent for terminal conversations with LLMs.

[中文](#中文说明) · [English](#english)

> **项目状态 / Project status**：早期开发阶段。公共接口、命令细节和本地数据格式可能随版本演进。
> Early-stage software. Public APIs, command details, and local data formats may change between releases.

## 中文说明

### 简介

FlickCode 是一个基于 Python 的终端 AI 编程助手，提供交互式 TUI、流式模型输出和本地工具调用能力。它可通过 MCP、Skills、Hooks、SubAgents、持久化 Teams 和 Git Worktree 隔离进行扩展。

### 核心能力

| 能力 | 说明 |
| --- | --- |
| 交互式 TUI | 支持多行输入、历史记录、流式输出、命令补全和快捷键。 |
| 多模型提供商 | 支持 Anthropic 兼容与 OpenAI 兼容的配置。 |
| 上下文管理 | 根据用量估算上下文，自动或手动压缩，并把过大的工具结果外置保存。 |
| MCP | 启动时发现本地或远程的 Model Context Protocol 工具。 |
| Skills | 通过 Markdown SOP 定义按需加载、工具范围受限的共享或隔离能力。 |
| Hooks | 通过声明式规则注入提示词、运行 shell/HTTP 动作或拦截工具调用。 |
| SubAgents | 支持固定角色和会话分叉，支持前台/后台运行、结果存储与通知。 |
| Teams | 支持持久化团队、任务依赖、邮箱、锁、审批以及窗格/进程内后端。 |
| Worktree 隔离 | 固定角色可选用每任务 Git Worktree，并带有初始化和安全清理机制。 |
| 本地优先安全 | 包含权限控制、项目可信任机制、路径沙箱、会话恢复和项目/用户记忆。 |

## 环境要求

- Python 3.8 或更高版本
- 推荐使用 [uv](https://docs.astral.sh/uv/)，也可使用 `pip`
- 至少配置一个模型提供商的 API Key

## 安装

### 使用 uv（推荐）

```bash
git clone https://github.com/Marsh-Yan/flickcode.git
cd flickcode
uv sync
uv run flick --help
```

### 使用 pip

```bash
git clone https://github.com/Marsh-Yan/flickcode.git
cd flickcode
python -m pip install -e .
flick --help
```

## 配置

首次运行时，FlickCode 会在 `~/.flickcode/config.yaml` 创建配置模板；也可通过 `--config PATH` 指定其他配置文件。

不要将真实密钥写入仓库。以下示例使用环境变量引用：

```yaml
providers:
  - name: claude
    protocol: anthropic
    model: claude-sonnet-4-20250514
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"
    thinking: false

  - name: gpt
    protocol: openai
    model: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_API_KEY}"
```

启动前在 shell 中设置对应变量：

```bash
# macOS / Linux
export ANTHROPIC_API_KEY='your-key'
export OPENAI_API_KEY='your-key'
```

```powershell
# PowerShell
$env:ANTHROPIC_API_KEY = 'your-key'
$env:OPENAI_API_KEY = 'your-key'
```

| 配置项 | 是否必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 提供商唯一名称，供 `--provider` 使用。 |
| `protocol` | 是 | `anthropic` 或 `openai`。 |
| `model` | 是 | 提供商模型标识。 |
| `base_url` | 是 | API 端点基础 URL。 |
| `api_key` | 是 | 密钥或 `${环境变量}` 引用。 |
| `thinking` | 否 | 在支持时启用 Anthropic 扩展思考。 |

## 基础用法

```bash
# 使用配置中的第一个提供商
flick

# 使用指定名称的提供商
flick --provider gpt

# 使用其他配置文件
flick --config /path/to/config.yaml

# 查看版本或帮助
flick --version
flick --help
```

### 快捷键

| 快捷键 | 操作 |
| --- | --- |
| `Meta+Enter` | 发送当前多行消息。 |
| `Ctrl+C` | 取消当前操作，或确认退出。 |
| `Ctrl+D` | 立即退出。 |
| `Ctrl+B` | 分离当前前台 SubAgent。 |
| `上` / `下` | 浏览输入历史。 |
| `Tab` | 补全斜杠命令。 |

### 内置斜杠命令

在 TUI 中输入 `/help` 或 `/help <command>` 可查看当前完整说明。

| 命令 | 用途 |
| --- | --- |
| `/plan [task]`、`/do` | 开始规划，或执行当前规划。 |
| `/compact` | 手动压缩对话上下文。 |
| `/clear`、`/reset` | 清空终端显示，或重置会话状态。 |
| `/session`、`/resume <id>` | 列出并恢复已保存会话。 |
| `/memory` | 查看项目和用户记忆状态。 |
| `/permission` | 查看权限与可信任状态。 |
| `/status` | 显示安全的运行状态快照。 |
| `/agent` | 管理 SubAgent 任务并读取结果。 |
| `/team` | 创建、打开、查看或离开持久化 Team。 |
| `/commit`、`/review`、`/test`、`/audit` | 内置 Skill 命令（被发现后可用）。 |
| `/exit` 或 `/quit` | 退出交互会话。 |

## 扩展能力

### MCP 服务器

可在用户配置或项目级 `.flickcode/config.yaml` 中声明 MCP 服务器。若同名，项目级定义会覆盖用户级定义。

```yaml
mcp_servers:
  local_files:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env:
      API_KEY: "${MCP_API_KEY}"

  remote_search:
    transport: streamable_http
    url: "https://example.com/mcp"
    headers:
      Authorization: "Bearer ${SEARCH_TOKEN}"
```

环境变量缺失或服务器连接失败时，FlickCode 会报告并跳过该服务器，不会阻止主程序启动。发现的工具会注册为 `mcp__<server>__<tool>`。

### Skills

Skills 是包含 YAML frontmatter 的 Markdown SOP，按以下优先级发现：

1. `<项目>/.flickcode/skills/`
2. `~/.flickcode/skills/`
3. 内置 `flickcode/skills/builtins/`

共享模式 Skill 示例：

```markdown
---
name: explain-change
description: Explain a code change for reviewers.
tools:
  - read_file
  - grep
mode: shared
---
Inspect the relevant files and explain: {{input}}
```

有效的 Skill 会变成如 `/explain-change` 的斜杠命令。它们可以在主对话中以 `shared` 方式运行，也可以在受限子对话中以 `isolated` 方式运行；目录式 Skill 还可包含 JSON 工具定义与 Python 脚本。

### 生命周期 Hooks

Hooks 从 `~/.flickcode/hooks.yaml`、`.flick/hooks.yaml` 与 `.flick/hooks.local.yaml` 加载。项目内 Hook 需要先在交互会话中被信任。

```yaml
hooks:
  - name: protect-production
    event: tool.before
    if:
      all:
        - field: tool.name
          exact: shell
        - field: tool.arguments.command
          regex: "(?i)production"
    action:
      type: prompt
      prompt: "Confirm that production operations are authorized."
      scope: turn
```

支持 `shell`、`prompt`、`http` 和保留的 `subagent` 动作。拦截事件不支持异步动作；非致命 Hook 错误会被报告，但不会中断主 Agent。

### SubAgents、Worktrees 与 Teams

稳定的 `agent` 工具支持两种委派模式：

- **Defined** SubAgent 使用固定角色提示词和干净历史启动。
- **Fork** SubAgent 继承已完成父请求的前缀，并始终在后台运行。
- 可使用 `/agent status <task-id>`、`/agent result <task-id>`、`/agent cancel <task-id>` 管理任务。

固定角色可在 frontmatter 中加入 `isolation: worktree` 来启用隔离。Worktree 位于 `.flickcode/worktrees/`，只有在干净且不存在未推送提交时才会自动清理。

```yaml
# .flickcode/worktrees.yaml
version: 1
expiry_days: 7
bootstrap:
  copy: [".local/config.toml"]
  symlink: ["node_modules"]
  ignored: [".cache/*.json"]
```

Teams 会持久保存成员身份、消息、任务、依赖关系、审批与运行快照：

```text
/team create release-prep
/team status
/team leave
```

启动持久化 Team 成员进程时可使用 `flick --team NAME --team-member MEMBER_ID`。

## 上下文、会话与记忆

FlickCode 会在每次模型请求前估算上下文用量。过大的工具输出可以外置保存，旧历史可以在保留最近消息的前提下被摘要压缩；`/compact` 可请求手动压缩。

项目指令按以下顺序加载：

1. 项目根目录的 `AGENTS.md`
2. 项目内的 `.flickcode/AGENTS.md`
3. 当前用户的 `~/.flickcode/AGENTS.md`

会话以 JSONL 文件保存在项目的 `sessions/` 目录。长期记忆保存在项目 `memory/` 或用户级 `~/.flickcode/memory/` 中。两者均属于本地运行数据，已被项目 `.gitignore` 排除。

## 安全建议

- 使用环境变量或本地未跟踪配置文件保存密钥。
- 不要提交 `.env`、私钥、会话归档、`.flickcode/` 运行状态或本地编辑器/Agent 设置。
- 信任项目前请先审查其中的 shell 或 HTTP Hook。
- MCP 服务器和 Skills 可能执行你显式启用的能力；安装第三方定义前请先审计。

## 开发

### 运行测试

```bash
python -m unittest discover -s tests -v
```

### 项目结构

```text
src/flickcode/
├── commands/      # 斜杠命令解析与分发
├── context/       # 上下文估算、压缩与结果存储
├── hooks/         # 生命周期 Hook 加载与执行
├── mcp/           # MCP 传输、客户端与工具适配
├── memory/        # 项目指令、笔记与更新
├── permissions/   # 信任、权限与沙箱策略
├── providers/     # Anthropic 与 OpenAI 提供商适配器
├── skills/        # Skill 发现、解析与执行
├── subagents/     # 委派与任务生命周期
├── teams/         # 持久化协作运行时
├── tools/         # 内置本地工具
└── worktrees/     # Git Worktree 生命周期管理
tests/             # 单元与集成测试
docs/              # 设计、计划、任务与检查清单文档
```

### 添加新提供商

1. 新建 `src/flickcode/providers/your_provider.py`。
2. 实现提供商约定，包括流式对话支持。
3. 在 `src/flickcode/providers/__init__.py` 中注册协议。
4. 在 `tests/` 中添加聚焦测试。

## 贡献

请保持改动聚焦；变更行为时补充或更新测试；不要提交密钥或本地生成状态。提交 Pull Request 前请运行完整测试集。

## 许可证

当前仓库未包含许可证文件。在项目所有者发布许可证前，请不要假定代码具有可自由复用的授权。

---

## English

### Overview

FlickCode is a Python command-line coding agent with an interactive terminal
UI. It streams model responses, invokes local tools, and can be extended with
MCP servers, Skills, Hooks, SubAgents, durable Teams, and optional Git
Worktree isolation.

### Highlights

| Capability | What it provides |
| --- | --- |
| Interactive TUI | Multi-line input, history, streaming output, command completion, and keyboard controls. |
| Multiple providers | Anthropic-compatible and OpenAI-compatible provider configurations. |
| Context management | Usage-aware context estimation, automatic/manual compaction, and external storage for oversized tool results. |
| MCP | Startup discovery of local or remote Model Context Protocol tools. |
| Skills | Lazy-loaded Markdown operating procedures with scoped tool access and shared or isolated execution. |
| Hooks | Declarative lifecycle rules for prompts, shell/HTTP actions, and tool interception. |
| SubAgents | Defined roles and conversation forks, foreground/background execution, result storage, and notifications. |
| Teams | Durable teams with task dependencies, mailboxes, locks, approvals, and pane or in-process backends. |
| Worktree isolation | Optional per-task Git Worktrees for defined SubAgent roles, with bootstrap and safe cleanup rules. |
| Local-first safety | Permission controls, project trust, path sandboxing, session recovery, and project/user memory. |

## Requirements

- Python 3.8 or newer
- [uv](https://docs.astral.sh/uv/) (recommended) or `pip`
- An API key for at least one configured provider

## Installation

### With uv (recommended)

```bash
git clone https://github.com/Marsh-Yan/flickcode.git
cd flickcode
uv sync
uv run flick --help
```

### With pip

```bash
git clone https://github.com/Marsh-Yan/flickcode.git
cd flickcode
python -m pip install -e .
flick --help
```

## Configuration

On its first run, FlickCode creates a template at
`~/.flickcode/config.yaml`. Use `--config PATH` to select another file.

Never put a real key in a repository. The example below expands values from
environment variables instead:

```yaml
providers:
  - name: claude
    protocol: anthropic
    model: claude-sonnet-4-20250514
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"
    thinking: false

  - name: gpt
    protocol: openai
    model: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_API_KEY}"
```

Set the values in your shell before starting FlickCode:

```bash
# macOS / Linux
export ANTHROPIC_API_KEY='your-key'
export OPENAI_API_KEY='your-key'
```

```powershell
# PowerShell
$env:ANTHROPIC_API_KEY = 'your-key'
$env:OPENAI_API_KEY = 'your-key'
```

| Provider field | Required | Description |
| --- | --- | --- |
| `name` | Yes | Unique provider identifier used by `--provider`. |
| `protocol` | Yes | `anthropic` or `openai`. |
| `model` | Yes | Provider model identifier. |
| `base_url` | Yes | API endpoint base URL. |
| `api_key` | Yes | Key or `${ENVIRONMENT_VARIABLE}` reference. |
| `thinking` | No | Enables Anthropic extended thinking when supported. |

## Basic usage

```bash
# Use the first configured provider
flick

# Select a named provider
flick --provider gpt

# Use an alternate configuration file
flick --config /path/to/config.yaml

# Inspect the installed version or options
flick --version
flick --help
```

### Keyboard controls

| Key | Action |
| --- | --- |
| `Meta+Enter` | Send the current multi-line message. |
| `Ctrl+C` | Cancel the current operation or confirm quitting. |
| `Ctrl+D` | Exit immediately. |
| `Ctrl+B` | Detach an active foreground SubAgent. |
| `Up` / `Down` | Browse input history. |
| `Tab` | Complete a slash command. |

### Built-in slash commands

Use `/help` or `/help <command>` in the TUI for the current command details.

| Command | Purpose |
| --- | --- |
| `/plan [task]` and `/do` | Start planning or execute the active plan. |
| `/compact` | Compact conversation context manually. |
| `/clear` and `/reset` | Clear terminal output or reset the session state. |
| `/session`, `/resume <id>` | List and restore saved conversations. |
| `/memory` | Inspect project and user memory state. |
| `/permission` | Inspect permission and trust state. |
| `/status` | Show a safe runtime snapshot. |
| `/agent` | Manage SubAgent tasks and retrieve results. |
| `/team` | Create, open, inspect, or leave a durable Team. |
| `/commit`, `/review`, `/test`, `/audit` | Bundled Skill commands (available when discovered). |
| `/exit` or `/quit` | Leave the interactive session. |

## Extensibility

### MCP servers

Declare MCP servers in the user configuration or in a project-level
`.flickcode/config.yaml`. Project servers with the same name override the
user-level declaration.

```yaml
mcp_servers:
  local_files:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env:
      API_KEY: "${MCP_API_KEY}"

  remote_search:
    transport: streamable_http
    url: "https://example.com/mcp"
    headers:
      Authorization: "Bearer ${SEARCH_TOKEN}"
```

Undefined environment variables and unavailable servers are reported and
skipped; they do not prevent FlickCode from starting. Discovered tools are
registered as `mcp__<server>__<tool>`.

### Skills

Skills are Markdown SOPs with YAML frontmatter. FlickCode searches these
locations from highest to lowest priority:

1. `<project>/.flickcode/skills/`
2. `~/.flickcode/skills/`
3. Bundled `flickcode/skills/builtins/`

Example shared Skill:

```markdown
---
name: explain-change
description: Explain a code change for reviewers.
tools:
  - read_file
  - grep
mode: shared
---
Inspect the relevant files and explain: {{input}}
```

Valid Skills become slash commands such as `/explain-change`. They may run in
the main conversation (`shared`) or a bounded child conversation (`isolated`).
Directory Skills may additionally package JSON tool schemas and Python scripts.

### Lifecycle Hooks

Hooks are loaded from `~/.flickcode/hooks.yaml`, `.flick/hooks.yaml`, and
`.flick/hooks.local.yaml`. Project Hooks require project trust in the
interactive session.

```yaml
hooks:
  - name: protect-production
    event: tool.before
    if:
      all:
        - field: tool.name
          exact: shell
        - field: tool.arguments.command
          regex: "(?i)production"
    action:
      type: prompt
      prompt: "Confirm that production operations are authorized."
      scope: turn
```

Supported actions are `shell`, `prompt`, `http`, and the reserved `subagent`
placeholder. Interception events do not allow asynchronous actions; non-fatal
Hook failures are reported without stopping the main Agent.

### SubAgents, Worktrees, and Teams

The stable `agent` tool supports both defined roles and conversation forks:

- **Defined** SubAgents start from a fixed role prompt and clean history.
- **Fork** SubAgents inherit a completed parent request prefix and always run
  in the background.
- Use `/agent status <task-id>`, `/agent result <task-id>`, and
  `/agent cancel <task-id>` to control tasks.

Defined roles can opt into isolation by adding `isolation: worktree` to their
frontmatter. Worktrees live under `.flickcode/worktrees/` and are cleaned up
only when they are clean and have no unpushed commits.

```yaml
# .flickcode/worktrees.yaml
version: 1
expiry_days: 7
bootstrap:
  copy: [".local/config.toml"]
  symlink: ["node_modules"]
  ignored: [".cache/*.json"]
```

Teams persist member identities, messages, tasks, dependency state, approvals,
and runtime snapshots:

```text
/team create release-prep
/team status
/team leave
```

Use `flick --team NAME --team-member MEMBER_ID` when starting a durable Team
member process.

## Context, sessions, and memory

FlickCode estimates context usage on every provider request. It can store large
tool outputs outside the conversation and summarize older history while keeping
recent messages. `/compact` requests a manual compaction.

Project instructions are loaded in this order:

1. `AGENTS.md` in the project root
2. `.flickcode/AGENTS.md` in the project
3. `~/.flickcode/AGENTS.md` for the current user

Sessions are stored as JSONL files under the project `sessions/` directory.
Long-term notes live under the project `memory/` directory or
`~/.flickcode/memory/`. Treat both locations as local runtime data, not source
code; they are ignored by the included `.gitignore`.

## Security notes

- Keep keys in environment variables or a local untracked config file.
- Do not commit `.env`, private keys, session archives, `.flickcode/` runtime
  state, or local editor/agent settings.
- Review any shell or HTTP Hook before trusting a project.
- MCP servers and Skills can execute capabilities you explicitly enable; audit
  third-party definitions before installation.

## Development

### Run the test suite

```bash
python -m unittest discover -s tests -v
```

### Project layout

```text
src/flickcode/
├── commands/      # Slash-command parsing and dispatch
├── context/       # Context estimation, compaction, and result storage
├── hooks/         # Lifecycle Hook loading and execution
├── mcp/           # MCP transports, clients, and tool adapters
├── memory/        # Project instructions, notes, and updates
├── permissions/   # Trust, permission, and sandbox policies
├── providers/     # Anthropic and OpenAI provider adapters
├── skills/        # Skill discovery, parsing, and execution
├── subagents/     # Delegation and task lifecycle
├── teams/         # Durable collaboration runtime
├── tools/         # Built-in local tools
└── worktrees/     # Git Worktree lifecycle management
tests/             # Unit and integration tests
docs/              # Design, plan, task, and checklist documents
```

### Add a provider

1. Create `src/flickcode/providers/your_provider.py`.
2. Implement the provider contract, including streaming chat support.
3. Register the protocol in `src/flickcode/providers/__init__.py`.
4. Add focused tests under `tests/`.

## Contributing

Please keep changes focused, add or update tests for behavior changes, and
avoid committing secrets or generated local state. Run the test suite before
opening a pull request.

## License

No license file is currently included. Do not assume reuse rights until the
project owner publishes a license.
