# FlickCode

A lightweight CLI AI coding agent for terminal conversations with LLMs.

> **⚠️ Early development stage.** Interfaces and local file formats may still evolve.

## Features

- **Interactive TUI** — Multi-line input, command history, streaming output
- **Multi-provider** — Supports Anthropic Claude and OpenAI
- **Claude Extended Thinking** — View Claude's reasoning chain in the terminal
- **Streaming** — See responses token by token, no waiting for full generation
- **Extensible** — Unified provider interface for adding new backends
- **Reusable Skills** — Markdown SOPs with lazy loading, scoped tools, and shared or isolated execution
- **Lifecycle Hooks** — Declarative event rules for commands, prompt injection, HTTP callbacks, and tool interception
- **Isolated SubAgents** — Delegate defined roles or cached conversation forks through one stable tool
- **Git Worktree isolation** — Defined roles can opt into per-task Worktrees with explicit cwd propagation, bootstrap rules, and safe cleanup

### Worktree-isolated SubAgents

Add `isolation: worktree` to a defined role's frontmatter when the role must
work in its own Git Worktree. The default is `shared`; Fork SubAgents always
remain shared. Worktrees are created under `.flickcode/worktrees/` and are
removed automatically only when clean and free of unpushed commits. A retained
Worktree's absolute path and reason are included in the task status/result.

Project-local setup is opt-in through `.flickcode/worktrees.yaml`:

```yaml
version: 1
expiry_days: 7
bootstrap:
  copy: [".local/config.toml"]
  symlink: ["node_modules"]
  ignored: [".cache/*.json"]
```

## Installation

### Prerequisites

- Python 3.8+
- `uv` (recommended) or `pip`

### Install with uv

```bash
# Install from local source
cd flick
uv sync
```

### Install with pip

```bash
cd flick
pip install -e .
```

## Configuration

FlickCode uses a YAML configuration file at `~/.flickcode/config.yaml`.

On first run, a template configuration is automatically created. Edit it with your API keys:

```yaml
providers:
  - name: claude
    protocol: anthropic
    model: claude-sonnet-4-20250514
    base_url: https://api.anthropic.com
    api_key: your-anthropic-api-key-here
    thinking: false

  - name: gpt
    protocol: openai
    model: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: your-openai-api-key-here
```

### Configuration fields

| Field      | Required | Description                                    |
|------------|----------|------------------------------------------------|
| `name`     | Yes      | Unique identifier for this provider entry      |
| `protocol` | Yes      | `anthropic` or `openai`                        |
| `model`    | Yes      | Model name (e.g., `claude-sonnet-4-20250514`)  |
| `base_url` | Yes      | API endpoint URL                               |
| `api_key`  | Yes      | Authentication key                             |
| `thinking` | No       | Enable Claude Extended Thinking (`true`/`false`)|

### MCP servers

FlickCode can discover external MCP tools at startup. Declare servers as a map
under `mcp_servers` in `~/.flickcode/config.yaml` or the project-level
`.flickcode/config.yaml`. Project entries with the same server name replace the
user-level entry.

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

Environment variables use `${VAR}` syntax. An undefined variable or a failed
server connection only disables that server; FlickCode continues starting and
reports the skipped server. Discovered tools are registered as
`mcp__<server>__<tool>` and use the normal Agent tool-call flow.

### Lifecycle Hooks

Hooks are loaded from `~/.flickcode/hooks.yaml`, `.flick/hooks.yaml`, and
`.flick/hooks.local.yaml`. Project hooks require trust in interactive sessions.
Each rule declares an event, an optional condition, and an action:

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
      type: shell
      command: >-
        python -c "import json; print(json.dumps({'allow': False,
        'reason': 'production commands require manual approval'}))"
      timeout: 5

  - event: turn.started
    action:
      type: prompt
      prompt: "Keep changes focused on {{ project.path }}."
      scope: turn
```

Supported actions are `shell`, `prompt`, `http`, and the reserved `subagent`
placeholder. Rules may set `once`, `async`, and action-specific `timeout`
controls; interception events reject asynchronous actions. Hook failures are
logged and never stop the main Agent flow. Use `/status` to inspect loaded rules
and recent Hook diagnostics.

### SubAgents

The model uses one stable `agent` tool for both delegation styles and task
management. A `defined` SubAgent starts with a clean conversation and a fixed
role prompt; a `fork` inherits the last completed parent request prefix and is
always sent to the background. Background completions inject one bounded
notification into the next parent request. Retrieve the full output with
`/agent result <task-id>` or the tool's `result` operation.

Roles are Markdown files discovered in this order (highest priority first):

1. `<project>/.flickcode/agents/`
2. `~/.flickcode/agents/`
3. bundled roles
4. configured plugin role directories

```markdown
---
name: investigator
description: Inspect a problem without changing files.
tools:
  allow: [read_file, glob, grep]
  deny: [write_file, edit_file, execute_command]
model: inherit
max_turns: 15
permission_mode: strict
---
You are a focused read-only investigator. Return concise evidence.
```

Optional configuration:

```yaml
subagents:
  max_workers: 4
  max_pending: 16
  foreground_timeout_seconds: 30
  shutdown_timeout_seconds: 5
  result_storage_dir: .tmp/subagents
  background_allowed_tools: []
  additional_denied_tools: []
  plugin_role_dirs: []
  model_aliases:
    haiku: claude-haiku
    sonnet: claude-sonnet
    opus: claude-opus
```

An empty background allow-list adds no restriction; `agent` and `load_skill`
are still always removed from child tool views. Child results and context
artifacts default to the project-local `.tmp/subagents/` directory.

## Usage

```bash
# Start interactive chat (uses first provider in config)
flick

# Use a specific provider
flick --provider gpt

# Use a custom config file
flick --config /path/to/config.yaml

# Show version
flick --version

# Show help
flick --help
```

### Key bindings

| Key            | Action                    |
|----------------|---------------------------|
| `Meta+Enter`   | Send message              |
| `Ctrl+C`       | Cancel / Confirm quit     |
| `Ctrl+D`       | Exit immediately          |
| `/exit`/`/quit`| Exit from input prompt    |
| `/compact`     | Compact conversation context manually |
| `Ctrl+B`       | Detach an active foreground SubAgent (interactive control API) |
| `↑`/`↓`        | Navigate input history    |

### Slash commands

Commands are handled locally before ordinary text reaches the Agent. Use `/help`
to see the complete list and `/help <command>` for details. Built-in commands
include `/compact`, `/clear`, `/reset`, `/plan`, `/do`, `/session`, `/memory`,
`/permission`, `/status`, and `/agent`. Use `/agent status <task-id>`,
`/agent result <task-id>`, or `/agent cancel <task-id>` for local task control.
Valid Skills are added dynamically as commands;
the bundled set provides `/commit`, `/review`, and `/test`. `/audit` delegates
to the currently effective `review` Skill.

`/plan <task>` starts planning immediately. `/plan` without a task switches the
prompt to `[PLAN]` mode for subsequent messages. `/do` executes the existing plan
and returns to `[DEFAULT]`. `/sessions` remains an alias for `/session`, and
`/resume <session-id>` restores a saved conversation. Press Tab to complete a
slash command.

### Skills

A Skill packages a reusable AI operation as YAML frontmatter plus a Markdown
SOP. FlickCode discovers definitions from three locations, highest priority
first:

1. `<project>/.flickcode/skills/`
2. `~/.flickcode/skills/`
3. the built-in `flickcode/skills/builtins/` package directory

An invalid higher-priority file is diagnosed and skipped, so a valid lower
definition can still be used. Same-name definitions in one tier are all
excluded from that tier. Other valid Skills continue to load.

A standalone Skill is a direct `*.md` child of a skills directory:

```markdown
---
name: explain-change
description: Explain a code change for reviewers
tools:
  - read_file
  - grep
mode: shared
---
Inspect the relevant code and explain this request: {{input}}
```

`name` must match `^[a-z][a-z0-9-]*$`. `description` is one line, and
`tools` is the complete visible-tool whitelist. `mode` is `shared` or
`isolated`. Isolated Skills additionally require a non-negative `history`
count and may specify `model`; shared Skills cannot specify either field. Every
literal `{{input}}` in the SOP is replaced with the raw slash-command/tool
input.

Directory Skills are immediate child directories with this layout:

```text
my-skill/
├── SKILL.md
├── tools/
│   └── lookup.json
└── scripts/
    └── lookup.py
```

Each tool JSON declares `name`, `description`, a complete object
`input_schema`, and a relative Python `entrypoint`. FlickCode snapshots the
script source while parsing and executes that immutable text with JSON on
stdin/stdout, a 60-second timeout, no shell, and a minimal environment. Scripts
must not depend on `__file__`, package-relative imports, or bundled runtime
resources in this release.

Skill loading is two-stage. At startup the model sees only each name and one-line
description. The always-visible system tool `load_skill` loads the complete SOP
and any package tools only when needed. Active shared SOPs are pinned into every
subsequent system prompt. With active shared Skills, visible tools are the union
of their whitelists plus `load_skill`; PLAN mode further intersects that set
with read-only tools. Schema generation, unknown-tool checks, and execution use
one immutable view for an entire Agent iteration.

Shared Skills continue in the main conversation, and multiple shared Skills can
remain active together. Isolated Skills copy only the configured number of
recent complete user/assistant/tool turns, optionally use a different model,
and run in a child conversation. Their full records are stored under
`sessions/children/*.jsonl`; only the invocation and a bounded summary return to
the main history.

Every valid Skill is also available as `/<name> [input]`. Discovery refreshes
lazily before input, loading, and completion, so adding or editing a definition
does not require restart. Refresh is transactional across the catalog, active
runtime, and command registry. An invalid edit to an active Skill keeps its last
valid snapshot; deleting it selects a lower-priority fallback or deactivates it.

`/clear` only clears terminal output. `/reset` archives the boundary, creates a
new session ID, and clears messages, plan state, and active Skills while keeping
the catalog, provider, MCP connections, and memory. Skill activation events are
stored in the main session archive and replayed against current definitions on
`/resume`.

This release intentionally does not include a Skill marketplace, remote
distribution, dependency resolution, or Skill version management.

### Context management

FlickCode stores oversized tool output under `~/.flickcode/context/` and
replaces it in conversation history with a preview and recovery path. Before
each provider request, it estimates context from the latest API usage and new
message characters. When needed it summarizes older history while retaining
recent messages. Use `/compact` in the interactive TUI to request compaction
before the automatic threshold is reached.

The optional `context` configuration block controls these limits:

```yaml
context:
  context_window_tokens: 128000
  max_output_tokens: 8192
  single_tool_result_chars: 24000
  message_tool_result_chars: 48000
  chars_per_token: 4
  storage_dir: "~/.flickcode/context"
```

Automatic compaction reserves a 13K-token safety margin. Manual `/compact`
uses a 3K-token margin. Context artifacts are recovery aids for the active
conversation and are not project source files.

### Project instructions, sessions, and memory

At startup FlickCode reads optional Markdown instructions in this order:

1. `AGENTS.md` at the project root;
2. `.flickcode/AGENTS.md` in the project;
3. `~/.flickcode/AGENTS.md` for the current user.

Project instructions are placed before user instructions in the system prompt.
An instruction file can include another Markdown file with
`@include relative/path.md`. Includes are limited in depth, reject cycles, and
cannot leave the project root (or `~/.flickcode` for user instructions).

Conversation events are appended to `sessions/<session-id>.jsonl` inside the
current project. FlickCode never resumes a previous conversation automatically:

```text
/sessions                 # list saved project conversations
/resume 20260813-163000-a1b2
```

`/resume` skips malformed JSONL lines and drops incomplete tool-call tails so
that the restored history is valid for the provider. If a restored conversation
was inactive for more than seven days, FlickCode adds a reminder to re-check
time-sensitive state. Archives older than 30 days are cleaned up during startup;
only managed `sessions/*.jsonl` files are candidates.

Long-term notes live separately in `memory/` for the project and
`~/.flickcode/memory/` for the user. Each note is Markdown with frontmatter and
is one of: user preference, correction feedback, project knowledge, or reference.
Their bounded `index.md` files (at most 200 lines / 25 KB) are injected before
each request, project index first. After an Agent Loop naturally ends with a
tool-free final answer, FlickCode updates these notes asynchronously; it never
delays the visible final response. This release intentionally does not provide
vector databases, embeddings, RAG retrieval, or team-memory synchronization.

## Project Structure

```
flick/
├── pyproject.toml
├── README.md
└── src/
    └── flick/
        ├── __init__.py           # Package metadata
        ├── __main__.py           # python -m flick entry
        ├── cli.py                # Argument parsing
        ├── config.py             # YAML configuration management
        ├── session.py            # Conversation orchestration
        ├── tui.py                # Interactive terminal UI
        └── providers/
            ├── __init__.py       # Provider factory
            ├── base.py           # Abstract base class
            ├── anthropic.py      # Anthropic Claude provider
            └── openai.py         # OpenAI provider
```

## Adding a New Provider

1. Create `src/flick/providers/your_provider.py`
2. Implement `YourProvider(BaseProvider)` with a `stream_chat()` method
3. Update `src/flick/providers/__init__.py` `create_provider()` to handle your protocol name

## License

MIT
