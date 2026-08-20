"""Tool registry — centralised tool registration and lookup."""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Collection, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from flickcode.tools.base import BaseTool, ToolResult


class ToolRegistry:
    """Central registry that holds all available tools.

    Provides registration, lookup by name, and conversion to
    LLM-API-specific tool definition formats.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    # ── Registration ────────────────────────────────────────────────

    def register(self, tool_cls: type[BaseTool]) -> None:
        """Register a single tool class (instantiated once)."""
        instance = tool_cls()
        self.register_instance(instance)

    def register_instance(self, tool: BaseTool) -> None:
        """Register an already-created tool instance.

        Runtime-discovered tools, such as MCP tools, are instances rather
        than classes.  Registration is intentionally strict: a duplicate
        name must never silently replace an existing tool.
        """
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"Tool name already registered: {name}")
        self._tools[name] = tool

    def register_all(self, tool_cls_list: list[type[BaseTool]]) -> None:
        """Register multiple tool classes at once."""
        for cls in tool_cls_list:
            self.register(cls)

    # ── Lookup ──────────────────────────────────────────────────────

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name.  Returns None when not found."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Return whether a tool with ``name`` is registered."""
        return name in self._tools

    def list_tools(self) -> list[str]:
        """Return the names of all registered tools, sorted."""
        return sorted(self._tools)

    def snapshot(
        self,
        names: Collection[str] | None = None,
        extras: Collection[BaseTool] = (),
    ) -> "ToolRegistryView":
        """Create an immutable filtered view without mutating this registry."""
        selected_names = set(self._tools) if names is None else set(names)
        missing = sorted(selected_names - set(self._tools))
        if missing:
            raise ValueError("Unknown tool name(s): " + ", ".join(missing))
        combined = {name: self._tools[name] for name in sorted(selected_names)}
        extra_names: set[str] = set()
        for tool in extras:
            name = tool.spec.name
            if name in extra_names:
                raise ValueError(f"Duplicate extra tool name: {name}")
            if name in self._tools:
                raise ValueError(f"Extra tool conflicts with registered tool: {name}")
            extra_names.add(name)
            combined[name] = tool
        return ToolRegistryView(combined)

    # ── Format conversion ───────────────────────────────────────────

    def to_api_tools(
        self,
        api_format: str = "anthropic",
    ) -> list[dict]:
        """Convert all registered tools to an LLM-API-specific definition list.

        Args:
            api_format: ``"anthropic"`` or ``"openai"``.

        Returns:
            A list of tool definition dicts suitable for the target API.
        """
        if api_format == "anthropic":
            return self._to_anthropic_tools()
        if api_format == "openai":
            return self._to_openai_tools()
        msg = f"Unsupported api_format: {api_format!r}"
        raise ValueError(msg)

    # ── Internal formatters ─────────────────────────────────────────

    def _to_anthropic_tools(self) -> list[dict]:
        tools = []
        for tool in self._tools.values():
            spec = tool.spec
            input_schema = self._input_schema(spec)
            tools.append({
                "name": spec.name,
                "description": spec.description,
                "input_schema": input_schema,
            })
        return tools

    def _to_openai_tools(self) -> list[dict]:
        tools = []
        for tool in self._tools.values():
            spec = tool.spec
            input_schema = self._input_schema(spec)
            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": input_schema,
                },
            })
        return tools

    @staticmethod
    def _input_schema(spec: "ToolSpec") -> dict:
        """Return a defensive copy of a tool's complete input schema."""
        if spec.input_schema is not None:
            return deepcopy(spec.input_schema)

        properties = {}
        required = []
        for p in spec.parameters:
            properties[p.name] = {
                "type": p.type,
                "description": p.description,
            }
            if p.required:
                required.append(p.name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }


class ToolRegistryView:
    """Immutable tool mapping used for one complete agent iteration."""

    def __init__(self, tools: Mapping[str, BaseTool]) -> None:
        self._tools = MappingProxyType(dict(sorted(tools.items())))

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[str]:
        return list(self._tools)

    def to_api_tools(self, api_format: str = "anthropic") -> list[dict]:
        if api_format == "anthropic":
            return [
                {
                    "name": tool.spec.name,
                    "description": tool.spec.description,
                    "input_schema": ToolRegistry._input_schema(tool.spec),
                }
                for tool in self._tools.values()
            ]
        if api_format == "openai":
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.spec.name,
                        "description": tool.spec.description,
                        "parameters": ToolRegistry._input_schema(tool.spec),
                    },
                }
                for tool in self._tools.values()
            ]
        raise ValueError(f"Unsupported api_format: {api_format!r}")

    def snapshot(
        self,
        names: Collection[str] | None = None,
        extras: Collection["BaseTool"] = (),
    ) -> "ToolRegistryView":
        selected = set(self._tools) if names is None else set(names)
        missing = sorted(selected - set(self._tools))
        if missing:
            raise ValueError("Unknown tool name(s): " + ", ".join(missing))
        combined = {name: self._tools[name] for name in selected}
        for tool in extras:
            name = tool.spec.name
            if name in combined:
                raise ValueError(f"Extra tool conflicts with selected tool: {name}")
            combined[name] = tool
        return ToolRegistryView(combined)
