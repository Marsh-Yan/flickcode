"""Base interfaces for the Tool system.

Defines the abstract base class that every tool implements,
along with the data structures for tool specifications, parameters,
and execution results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from flickcode.tools.cache import FileContentCache


@dataclass
class ToolParameter:
    """Definition of a single parameter accepted by a tool."""

    name: str
    type: str  # "string" | "integer" | "boolean" | "array" | "object"
    description: str
    required: bool = False
    default: Any = None


@dataclass
class ToolSpec:
    """Metadata specification for a tool.

    Carried as a class attribute by every BaseTool subclass.
    """

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    # MCP and other runtime-discovered tools may provide a complete JSON
    # Schema.  Legacy tools continue to use ``parameters``.
    input_schema: dict[str, Any] | None = None


@dataclass
class ToolResult:
    """Structured result returned by tool execution."""

    success: bool
    output: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }


class BaseTool(ABC):
    """Abstract base class that every tool must implement.

    Subclasses set *spec* as a class attribute and override *execute*.
    """

    spec: ToolSpec

    @abstractmethod
    def execute(
        self,
        params: dict[str, Any],
        *,
        cwd: Optional[Path] = None,
        file_cache: Optional[FileContentCache] = None,
    ) -> ToolResult:
        """Execute the tool with the given parameters.

        Args:
            params: Dictionary of parameter values keyed by name.

        Returns:
            A ToolResult indicating success or failure.
        """
        ...
