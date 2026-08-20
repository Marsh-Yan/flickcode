"""Configuration loading and management for FlickCode."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import yaml

from flickcode.context.models import ContextConfig
from flickcode.mcp.errors import MCPConfigError
from flickcode.mcp.models import MCPServerConfig


DEFAULT_CONFIG_DIR = Path.home() / ".flickcode"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"


@dataclass
class ProviderConfig:
    name: str
    protocol: str  # "anthropic" | "openai"
    model: str
    base_url: str
    api_key: str
    thinking: bool = False


@dataclass
class MemoryConfig:
    """Configuration for local instructions, sessions, and long-term memory."""

    instruction_filename: str = "AGENTS.md"
    include_max_depth: int = 5
    resume_time_gap_days: int = 7
    session_expiry_days: int = 30
    index_max_lines: int = 200
    index_max_bytes: int = 25 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.instruction_filename, str) or not self.instruction_filename:
            raise ValueError("instruction_filename must be a non-empty string")
        if Path(self.instruction_filename).name != self.instruction_filename:
            raise ValueError("instruction_filename must not contain a path")
        for field_name in (
            "include_max_depth",
            "resume_time_gap_days",
            "session_expiry_days",
            "index_max_lines",
            "index_max_bytes",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.index_max_lines > 200:
            raise ValueError("index_max_lines must not exceed 200")
        if self.index_max_bytes > 25 * 1024:
                raise ValueError("index_max_bytes must not exceed 25600")


@dataclass
class SubAgentConfig:
    """Bounded in-process SubAgent execution settings."""

    max_workers: int = 4
    max_pending: int = 16
    foreground_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 5.0
    result_inline_chars: int = 16_384
    result_max_chars: int = 1_000_000
    result_storage_dir: str = ".tmp/subagents"
    background_allowed_tools: tuple[str, ...] = ()
    additional_denied_tools: tuple[str, ...] = ()
    plugin_role_dirs: tuple[str, ...] = ()
    model_aliases: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("max_workers", "max_pending", "result_inline_chars", "result_max_chars"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"subagents.{name} must be a positive integer")
        for name in ("foreground_timeout_seconds", "shutdown_timeout_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"subagents.{name} must be positive")
        if self.result_max_chars < self.result_inline_chars:
            raise ValueError("subagents.result_max_chars must be >= result_inline_chars")
        if not isinstance(self.result_storage_dir, str) or not self.result_storage_dir:
            raise ValueError("subagents.result_storage_dir must be a non-empty string")
        for name in ("background_allowed_tools", "additional_denied_tools", "plugin_role_dirs"):
            values = tuple(getattr(self, name))
            if not all(isinstance(item, str) and item for item in values):
                raise ValueError(f"subagents.{name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"subagents.{name} must not contain duplicates")
            setattr(self, name, values)
        if not isinstance(self.model_aliases, dict):
            raise ValueError("subagents.model_aliases must be a map")
        invalid = sorted(set(self.model_aliases) - {"haiku", "sonnet", "opus"})
        if invalid:
            raise ValueError("Unsupported subagent model alias(es): " + ", ".join(invalid))
        if not all(isinstance(value, str) and value for value in self.model_aliases.values()):
            raise ValueError("subagents.model_aliases values must be provider names")


@dataclass
class TeamsConfig:
    """Durable team storage, backend and coordinator settings."""

    storage_dir: str = str(DEFAULT_CONFIG_DIR / "teams")
    backend_preference: tuple[str, ...] = ("pane", "in_process")
    pane_adapters: tuple[str, ...] = ("tmux", "windows_terminal")
    lock_retry_seconds: float = 2.0
    lock_stale_seconds: float = 30.0
    wake_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    coordinator_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.storage_dir, str) or not self.storage_dir.strip():
            raise ValueError("teams.storage_dir must be a non-empty string")
        for field_name in ("backend_preference", "pane_adapters"):
            values = tuple(getattr(self, field_name))
            if not values or not all(isinstance(item, str) and item for item in values):
                raise ValueError(f"teams.{field_name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"teams.{field_name} must not contain duplicates")
            setattr(self, field_name, values)
        if set(self.backend_preference) - {"pane", "in_process"}:
            raise ValueError("teams.backend_preference supports pane and in_process")
        if set(self.pane_adapters) - {"tmux", "windows_terminal"}:
            raise ValueError("teams.pane_adapters supports tmux and windows_terminal")
        if not isinstance(self.coordinator_enabled, bool):
            raise ValueError("teams.coordinator_enabled must be boolean")
        for field_name in (
            "lock_retry_seconds",
            "lock_stale_seconds",
            "wake_timeout_seconds",
            "shutdown_timeout_seconds",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"teams.{field_name} must be positive")


@dataclass
class Config:
    providers: List[ProviderConfig] = field(default_factory=list)
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    mcp_errors: list[str] = field(default_factory=list)
    context: ContextConfig = field(default_factory=ContextConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    subagents: SubAgentConfig = field(default_factory=SubAgentConfig)
    teams: TeamsConfig = field(default_factory=TeamsConfig)


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: str, server_name: str, field_name: str) -> str:
    def replace(match: re.Match[str]) -> str:
        variable = match.group(1)
        if variable not in os.environ:
            raise MCPConfigError(
                f"Environment variable {variable} is not defined for {field_name}",
                server_name=server_name,
                operation="config",
            )
        return os.environ[variable]

    return _ENV_PATTERN.sub(replace, value)


def _expanded_mapping(values: Any, server_name: str, field_name: str) -> dict[str, str]:
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise MCPConfigError(
            f"{field_name} must be a map", server_name, "config"
        )
    result: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise MCPConfigError(
                f"{field_name} keys and values must be strings",
                server_name,
                "config",
            )
        result[key] = _expand_env(value, server_name, f"{field_name}.{key}")
    return result


def _parse_mcp_server(name: str, raw: Any) -> MCPServerConfig:
    if not isinstance(raw, dict):
        raise MCPConfigError("server configuration must be a map", name, "config")
    transport = raw.get("transport")
    if transport not in ("stdio", "streamable_http"):
        raise MCPConfigError(
            "transport must be 'stdio' or 'streamable_http'", name, "config"
        )

    if transport == "stdio":
        command = raw.get("command")
        args = raw.get("args", [])
        if not isinstance(command, str) or not command:
            raise MCPConfigError("stdio server requires command", name, "config")
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise MCPConfigError("stdio args must be a list of strings", name, "config")
        return MCPServerConfig(
            name=name,
            transport=transport,
            command=_expand_env(command, name, "command"),
            args=[_expand_env(x, name, "args") for x in args],
            env=_expanded_mapping(raw.get("env"), name, "env"),
        )

    url = raw.get("url")
    if not isinstance(url, str) or not url:
        raise MCPConfigError("streamable_http server requires url", name, "config")
    return MCPServerConfig(
        name=name,
        transport=transport,
        url=_expand_env(url, name, "url"),
        headers=_expanded_mapping(raw.get("headers"), name, "headers"),
    )


def _parse_mcp_servers(raw: Any) -> tuple[dict[str, MCPServerConfig], list[str]]:
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        raise ValueError("mcp_servers must be a map keyed by server name")
    servers: dict[str, MCPServerConfig] = {}
    errors: list[str] = []
    for name, entry in raw.items():
        try:
            if not isinstance(name, str) or not name:
                raise MCPConfigError("server name must be a non-empty string")
            servers[name] = _parse_mcp_server(name, entry)
        except MCPConfigError as exc:
            errors.append(str(exc))
    return servers, errors


def _parse_context(raw: Any) -> ContextConfig:
    """Read optional conversation-context settings without affecting providers."""
    if raw is None:
        return ContextConfig()
    if not isinstance(raw, dict):
        raise ValueError("context must be a map")

    allowed = set(ContextConfig.__dataclass_fields__)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(
            "Unsupported context setting(s): " + ", ".join(unknown)
        )

    values = dict(raw)
    if "storage_dir" in values:
        if not isinstance(values["storage_dir"], str) or not values["storage_dir"]:
            raise ValueError("context.storage_dir must be a non-empty string")

    try:
        return ContextConfig(**values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid context configuration: {exc}") from exc


def _parse_memory(raw: Any) -> MemoryConfig:
    """Read optional local-memory settings without changing provider config."""
    if raw is None:
        return MemoryConfig()
    if not isinstance(raw, dict):
        raise ValueError("memory must be a map")

    allowed = set(MemoryConfig.__dataclass_fields__)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError("Unsupported memory setting(s): " + ", ".join(unknown))
    try:
        return MemoryConfig(**dict(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid memory configuration: {exc}") from exc


def _parse_subagents(raw: Any) -> SubAgentConfig:
    if raw is None:
        return SubAgentConfig()
    if not isinstance(raw, dict):
        raise ValueError("subagents must be a map")
    allowed = set(SubAgentConfig.__dataclass_fields__)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError("Unsupported subagents setting(s): " + ", ".join(unknown))
    try:
        return SubAgentConfig(**dict(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid subagents configuration: {exc}") from exc


def _parse_teams(raw: Any) -> TeamsConfig:
    if raw is None:
        return TeamsConfig()
    if not isinstance(raw, dict):
        raise ValueError("teams must be a map")
    allowed = set(TeamsConfig.__dataclass_fields__)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError("Unsupported teams setting(s): " + ", ".join(unknown))
    try:
        return TeamsConfig(**dict(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid teams configuration: {exc}") from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration root must be a map: {path}")
    return raw


def _merge_mcp_raw(base: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    base_servers = base.get("mcp_servers") or {}
    project_servers = project.get("mcp_servers") or {}
    if not isinstance(base_servers, dict) or not isinstance(project_servers, dict):
        raise ValueError("mcp_servers must be a map keyed by server name")
    servers = dict(base_servers)
    servers.update(project_servers)
    if servers:
        merged["mcp_servers"] = servers
    return merged


def load_config(path: Optional[str] = None) -> Config:
    """Load configuration from a YAML file.

    If path is None, defaults to ~/.flickcode/config.yaml.
    If the file does not exist, creates a default template and exits.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        init_default_config(config_path)
        print(
            f"Configuration file created at: {config_path}\n"
            f"Please edit it with your API keys and run flickcode again.",
            file=sys.stderr,
        )
        sys.exit(0)

    raw = _read_yaml(config_path)
    if not raw:
        raise ValueError("Configuration file is empty.")

    project_path = Path.cwd() / ".flickcode" / "config.yaml"
    if project_path != config_path:
        # Project configuration contributes MCP only, preserving the existing
        # explicit --config semantics for providers.
        raw = _merge_mcp_raw(raw, _read_yaml(project_path))

    providers_raw = raw.get("providers", [])
    if not providers_raw:
        raise ValueError(
            "No providers found in configuration. "
            "Add at least one provider entry under 'providers:'."
        )

    providers: List[ProviderConfig] = []
    required_fields = ["name", "protocol", "model", "base_url", "api_key"]

    for i, entry in enumerate(providers_raw):
        missing = [f for f in required_fields if f not in entry]
        if missing:
            raise ValueError(
                f"Provider entry #{i + 1} is missing required field(s): "
                f"{', '.join(missing)}. "
                f"Each provider needs: {', '.join(required_fields)}."
            )

        # Validate protocol value
        if entry["protocol"] not in ("anthropic", "openai"):
            raise ValueError(
                f"Provider '{entry['name']}' has unsupported protocol "
                f"'{entry['protocol']}'. Supported values: anthropic, openai."
            )

        providers.append(
            ProviderConfig(
                name=entry["name"],
                protocol=entry["protocol"],
                model=entry["model"],
                base_url=entry["base_url"],
                api_key=entry["api_key"],
                thinking=entry.get("thinking", False),
            )
        )

    mcp_servers, mcp_errors = _parse_mcp_servers(raw.get("mcp_servers"))
    context = _parse_context(raw.get("context"))
    memory = _parse_memory(raw.get("memory"))
    subagents = _parse_subagents(raw.get("subagents"))
    teams = _parse_teams(raw.get("teams"))
    provider_names = {provider.name for provider in providers}
    unknown_alias_targets = sorted(set(subagents.model_aliases.values()) - provider_names)
    if unknown_alias_targets:
        raise ValueError(
            "Subagent model alias references unknown provider(s): "
            + ", ".join(unknown_alias_targets)
        )
    return Config(
        providers=providers,
        mcp_servers=mcp_servers,
        mcp_errors=mcp_errors,
        context=context,
        memory=memory,
        subagents=subagents,
        teams=teams,
    )


def init_default_config(path: Path) -> None:
    """Create a default configuration file at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)

    template = {
        "providers": [
            {
                "name": "claude",
                "protocol": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "base_url": "https://api.anthropic.com",
                "api_key": "your-anthropic-api-key-here",
                "thinking": False,
            },
            {
                "name": "gpt",
                "protocol": "openai",
                "model": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
                "api_key": "your-openai-api-key-here",
            },
        ],
        "context": {
            "context_window_tokens": 128000,
            "max_output_tokens": 8192,
            "single_tool_result_chars": 24000,
            "message_tool_result_chars": 48000,
            "chars_per_token": 4,
            "storage_dir": str(DEFAULT_CONFIG_DIR / "context"),
        },
        "memory": {
            "include_max_depth": 5,
            "resume_time_gap_days": 7,
        },
        "teams": {
            "storage_dir": str(DEFAULT_CONFIG_DIR / "teams"),
            "backend_preference": ["pane", "in_process"],
            "pane_adapters": ["tmux", "windows_terminal"],
            "coordinator_enabled": False,
        },
        "mcp_servers": {},
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(template, f, default_flow_style=False, sort_keys=False)

    # Set restrictive permissions on Windows-compatible way
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass  # Best effort on Windows
