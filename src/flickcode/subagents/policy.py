"""Pure safety policies for models, tools, and permissions."""

from __future__ import annotations

from collections.abc import Collection, Mapping

from flickcode.config import ProviderConfig
from flickcode.permissions.models import PermissionMode
from flickcode.subagents.models import AgentModelAlias, AgentPermissionMode
from flickcode.tools.registry import ToolRegistryView

MANDATORY_DENIED_TOOLS = frozenset({"agent", "load_skill"})


class SubAgentToolPolicy:
    @staticmethod
    def resolve(
        parent_view: ToolRegistryView,
        role_allow: Collection[str] | None = None,
        role_deny: Collection[str] = (),
        additional_deny: Collection[str] = (),
        background_allow: Collection[str] | None = None,
        mode_read_tools: Collection[str] | None = None,
    ) -> ToolRegistryView:
        selected = set(parent_view.list_tools())
        selected -= MANDATORY_DENIED_TOOLS
        selected -= set(additional_deny)
        if role_allow is not None:
            selected &= set(role_allow)
        selected -= set(role_deny)
        if background_allow:
            selected &= set(background_allow)
        if mode_read_tools is not None:
            selected &= set(mode_read_tools)
        return parent_view.snapshot(selected)


class SubAgentPermissionPolicy:
    _RANK = {PermissionMode.PERMISSIVE: 0, PermissionMode.DEFAULT: 1, PermissionMode.STRICT: 2}

    @classmethod
    def resolve(cls, parent: PermissionMode, requested: AgentPermissionMode) -> PermissionMode:
        if requested is AgentPermissionMode.INHERIT:
            return parent
        requested_mode = PermissionMode(requested.value)
        return parent if cls._RANK[parent] >= cls._RANK[requested_mode] else requested_mode


class ModelResolver:
    @staticmethod
    def resolve(
        alias: AgentModelAlias,
        parent: ProviderConfig,
        providers: Mapping[str, ProviderConfig],
        aliases: Mapping[str, str],
    ) -> ProviderConfig:
        if alias is AgentModelAlias.INHERIT:
            return parent
        provider_name = aliases.get(alias.value)
        if not provider_name:
            raise ValueError(f"No provider configured for model alias {alias.value!r}")
        provider = providers.get(provider_name)
        if provider is None:
            raise ValueError(f"Unknown provider {provider_name!r} for model alias {alias.value!r}")
        return provider
