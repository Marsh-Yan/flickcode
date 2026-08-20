"""Rich-based message renderer for FlickCode TUI.

Provides role tags (You/AI), coloured side bars, Markdown rendering,
code syntax highlighting, and streaming-aware output.
"""

import enum
import shutil
from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text


class MessageRole(enum.Enum):
    USER = "You"
    ASSISTANT = "AI"


@dataclass
class RenderStyle:
    """Visual configuration for a message role."""

    tag: str
    tag_style: str
    bar_style: str
    text_style: str


ROLE_STYLES = {
    MessageRole.USER: RenderStyle("You", "bold blue", "blue", "default"),
    MessageRole.ASSISTANT: RenderStyle("AI", "bold green", "green", "default"),
}


class Renderer:
    """Renders chat messages with styling, Markdown, and code highlighting.

    The renderer works in two modes:
      - **Complete rendering** (render_user): renders the entire message at once.
      - **Streaming rendering** (render_assistant_stream_*): tag first, then
        stream text content, optionally detecting and highlighting code blocks.
    """

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console(highlight=False)
        self._code_block_buffer: list[str] = []
        self._in_code_block = False
        self._code_lang = ""
        self._streaming_active = False
        self._streamed_text = ""
        self._sidebar_output = ""

    # ── User messages (simple, complete text) ─────────────────────────

    def render_user(self, text: str) -> None:
        """Render a complete user message with blue sidebar and *You* tag."""
        style = ROLE_STYLES[MessageRole.USER]
        self._render_text_with_sidebar(text, style)

    # ── Assistant streaming helpers ───────────────────────────────────

    def render_assistant_init(self) -> None:
        """Print the AI tag + sidebar start line.

        Must be called **once** before the first streamed chunk.
        """
        style = ROLE_STYLES[MessageRole.ASSISTANT]
        tag_text = f"  {style.tag}  "
        self.console.print(
            Text.assemble(
                ("│ ", style.bar_style),
                (tag_text, style.tag_style),
            ),
            end="",
        )
        self._streaming_active = True
        self._streamed_text = ""

    def render_assistant_stream(self, chunk: str) -> None:
        """Stream a text chunk for the current assistant message.

        Detects and buffers code blocks (`` ``` `` … `` ``` ``) so they
        can be rendered with syntax highlighting once closed.
        """
        if not self._streaming_active:
            return
        self._streamed_text += chunk
        self._streaming_write(chunk)

    def render_assistant_end(self) -> None:
        """Finalise the current assistant message and print the separator."""
        self._streaming_active = False
        self._in_code_block = False
        self._code_block_buffer = []
        self.console.print()
        self.console.print()
        self.render_separator()

    def render_assistant_full(self, text: str) -> None:
        """Render a complete assistant message with Markdown.

        Used when the full message is already available (non-streaming).
        """
        style = ROLE_STYLES[MessageRole.ASSISTANT]
        self._render_markdown_with_sidebar(text, style)

    # ── Agent Loop utilities ─────────────────────────────────────────

    def render_tool_call(self, name: str, args: dict) -> None:
        """Render a tool-call notification."""
        arg_summary = ", ".join(f"{k}={v!r}" for k, v in args.items())
        self.console.print(
            f"[bold yellow][tool] Using {name}({arg_summary})[/bold yellow]"
        )

    def render_tool_result(self, name: str, success: bool, summary: str) -> None:
        """Render a tool execution result."""
        if success:
            self.console.print(f"[dim]OK {summary}[/dim]")
        else:
            self.console.print(
                f"[bold red]FAIL {name} error: {summary}[/bold red]"
            )

    def render_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        thinking_tokens: int = 0,
    ) -> None:
        """Render token usage information."""
        parts = [
            f"in: {input_tokens}",
            f"out: {output_tokens}",
        ]
        if thinking_tokens:
            parts.append(f"thinking: {thinking_tokens}")
        self.console.print(
            f"[dim]Tokens — {' | '.join(parts)}[/dim]"
        )

    def render_progress(self, text: str) -> None:
        """Render Agent Loop progress information."""
        self.console.print(f"[dim italic]{text}[/dim italic]")

    # ── Utilities ────────────────────────────────────────────────────

    def render_thinking(self, text: str) -> None:
        """Render thinking content in gray italic."""
        self.console.print(text, style="dim italic")

    def render_error(self, text: str) -> None:
        """Render error message in bold red."""
        self.console.print(f"Error: {text}", style="bold red")

    def render_separator(self) -> None:
        """Print a thin horizontal separator spanning the terminal width."""
        width = shutil.get_terminal_size().columns
        self.console.print("─" * width, style="bright_black")

    # ── Internal helpers ─────────────────────────────────────────────

    def _render_text_with_sidebar(self, text: str, rs: RenderStyle) -> None:
        """Render plain text with a coloured sidebar and role tag."""
        lines = text.rstrip("\n").split("\n")
        for i, line in enumerate(lines):
            if i == 0:
                self.console.print(
                    Text.assemble(
                        ("│ ", rs.bar_style),
                        (f"  {rs.tag}  ", rs.tag_style),
                        (line, rs.text_style),
                    )
                )
            else:
                self.console.print(
                    Text.assemble(
                        ("│ ", rs.bar_style),
                        (line, rs.text_style),
                    )
                )

    def _render_markdown_with_sidebar(
        self, text: str, rs: RenderStyle
    ) -> None:
        """Render Markdown text with a coloured sidebar and role tag."""
        # First line: tag + sidebar
        self.console.print(
            Text.assemble(
                ("│ ", rs.bar_style),
                (f"  {rs.tag}  ", rs.tag_style),
            ),
        )
        # Render full Markdown content with Rich's block-level renderer
        md = Markdown(text)
        self.console.print(md)

    def _streaming_write(self, text: str) -> None:
        """Write text during streaming, handling code blocks."""
        # Check for code fence boundaries
        if "```" in text:
            parts = text.split("```")
            for idx, part in enumerate(parts):
                if idx % 2 == 0:
                    # Outside code block
                    if self._in_code_block:
                        # Closing fence — render buffered code
                        self._code_block_buffer.append(part)
                        self._flush_code_block()
                        self._in_code_block = False
                    else:
                        self.console.print(part, end="")
                else:
                    # Inside code block — might be opening or lang
                    if not self._in_code_block:
                        # Opening fence; line content after ``` might be lang
                        first_line = part.split("\n")[0] if "\n" in part else part
                        remaining = (
                            part[len(first_line) :]
                            if "\n" in part
                            else ""
                        )
                        self._code_lang = first_line.strip()
                        self._in_code_block = True
                        self._code_block_buffer = []
                        if remaining:
                            self._code_block_buffer.append(remaining)
                    else:
                        # Odd case — nested ``` inside code block
                        self._code_block_buffer.append("```" + part)
        else:
            if self._in_code_block:
                self._code_block_buffer.append(text)
            else:
                self.console.print(text, end="")

    def _flush_code_block(self) -> None:
        """Flush the buffered code block with syntax highlighting."""
        code = "".join(self._code_block_buffer)
        try:
            syntax = Syntax(
                code,
                self._code_lang or "text",
                theme="monokai",
                line_numbers=False,
                word_wrap=True,
            )
            self.console.print(syntax)
        except Exception:
            # Fallback: print as plain text
            self.console.print(code, style="green")
        self._code_block_buffer = []
