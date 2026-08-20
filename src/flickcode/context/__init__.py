"""Public context-management API for FlickCode sessions."""

from typing import TYPE_CHECKING

from flickcode.context.models import (
    ContextConfig,
    ContextDiagnostic,
    ContextPreparation,
    ContextState,
    SafetyMode,
    StoredResult,
    SummaryResult,
    TokenEstimate,
)

if TYPE_CHECKING:
    from flickcode.context.manager import ContextManager

__all__ = [
    "ContextConfig",
    "ContextDiagnostic",
    "ContextManager",
    "ContextPreparation",
    "ContextState",
    "SafetyMode",
    "StoredResult",
    "SummaryResult",
    "TokenEstimate",
]


def __getattr__(name: str):
    """Delay manager import so config parsing cannot create an import cycle."""
    if name == "ContextManager":
        from flickcode.context.manager import ContextManager

        return ContextManager
    raise AttributeError(name)
