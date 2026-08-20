"""Data models used by FlickCode context management."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class SafetyMode(str, Enum):
    """Controls the safety margin used when preparing a request."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


@dataclass
class ContextConfig:
    """Configurable limits for one FlickCode conversation."""

    context_window_tokens: int = 128_000
    max_output_tokens: int = 8_192
    single_tool_result_chars: int = 24_000
    message_tool_result_chars: int = 48_000
    automatic_safety_margin_tokens: int = 13_000
    manual_safety_margin_tokens: int = 3_000
    recent_target_tokens: int = 10_000
    recent_min_messages: int = 5
    summary_max_retries: int = 3
    chars_per_token: int = 4
    message_overhead_tokens: int = 4
    preview_chars: int = 400
    storage_dir: Path = field(
        default_factory=lambda: Path.home() / ".flickcode" / "context"
    )

    def __post_init__(self) -> None:
        self.storage_dir = Path(self.storage_dir).expanduser()

        positive_values = {
            "context_window_tokens": self.context_window_tokens,
            "max_output_tokens": self.max_output_tokens,
            "single_tool_result_chars": self.single_tool_result_chars,
            "message_tool_result_chars": self.message_tool_result_chars,
            "recent_target_tokens": self.recent_target_tokens,
            "recent_min_messages": self.recent_min_messages,
            "chars_per_token": self.chars_per_token,
            "message_overhead_tokens": self.message_overhead_tokens,
            "preview_chars": self.preview_chars,
        }
        for name, value in positive_values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"context.{name} must be a positive integer")

        non_negative_values = {
            "automatic_safety_margin_tokens": self.automatic_safety_margin_tokens,
            "manual_safety_margin_tokens": self.manual_safety_margin_tokens,
            "summary_max_retries": self.summary_max_retries,
        }
        for name, value in non_negative_values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"context.{name} must be a non-negative integer")


@dataclass
class StoredResult:
    """A full tool result stored outside the conversation history."""

    path: Path
    preview: str
    original_chars: int
    content_hash: str


@dataclass
class SummaryResult:
    """The result of one isolated summary request."""

    content: str = ""
    attempts: int = 0
    success: bool = False
    error: Optional[str] = None
    path: Optional[Path] = None


@dataclass
class TokenEstimate:
    """An inspectable approximate token estimate."""

    input_tokens: int
    message_tokens: int
    extra_tokens: int
    anchored: bool


@dataclass
class ContextDiagnostic:
    """Compact status information suitable for logs or TUI output."""

    action: str = "unchanged"
    estimated_input_tokens: int = 0
    context_window_tokens: int = 0
    safety_margin_tokens: int = 0
    request_budget_tokens: int = 0
    stored_paths: list[Path] = field(default_factory=list)
    summary_path: Optional[Path] = None
    message: str = "Context unchanged."
    errors: list[str] = field(default_factory=list)


@dataclass
class ContextPreparation:
    """The prepared history and outcome of a pre-request check."""

    messages: list["Message"]
    blocked: bool = False
    diagnostic: ContextDiagnostic = field(default_factory=ContextDiagnostic)
    changed: bool = False
    summary_content: Optional[str] = None


@dataclass
class ContextState:
    """Mutable, conversation-scoped context-management state."""

    last_input_tokens: Optional[int] = None
    last_output_tokens: int = 0
    last_thinking_tokens: int = 0
    anchor_message_count: int = 0
    anchor_message_fingerprint: str = ""
    anchor_extra_chars: int = 0
    summary_failure_count: int = 0
    summary_circuit_open: bool = False
    last_summary_path: Optional[Path] = None
    last_result_paths: list[Path] = field(default_factory=list)
    last_diagnostic: ContextDiagnostic = field(default_factory=ContextDiagnostic)
