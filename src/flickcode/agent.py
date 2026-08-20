"""Agent Loop engine for FlickCode — ReAct-style autonomous loop.

Transforms FlickCode from single-turn conversation into a
fully autonomous agent that can think, act, observe, and iterate
until a task is done.
"""

from __future__ import annotations

import json
import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, Optional

from flickcode.providers.base import Message, StreamEvent
from flickcode.tools.base import ToolResult
from flickcode.tools.cache import FileContentCache
from flickcode.tools.paths import normalize_cwd
from flickcode.tools.registry import ToolRegistry, ToolRegistryView
from flickcode.permissions import PermissionEngine
from flickcode.permissions.models import CheckResult, PermissionMode
from flickcode.context import ContextManager
from flickcode.prompt import SystemPromptBuilder
from flickcode.prompt.whisper import (
    make_mode_instruction,
    make_whisper_message,
    should_inject_full_mode_instruction,
)
from flickcode.hooks.models import HookEventName


# ── Stop reasons ─────────────────────────────────────────────────────

class StopReason(str, Enum):
    """Why the Agent Loop stopped."""
    COMPLETED = "completed"             # Model finished (no more tool calls)
    MAX_ITERATIONS = "max_iterations"   # Hit iteration ceiling
    USER_CANCELLED = "user_cancelled"   # User pressed Ctrl+C
    UNKNOWN_TOOL = "unknown_tool"       # Consecutive unknown tool calls
    PROVIDER_ERROR = "provider_error"   # Provider stream error
    ERROR = "error"                     # Agent internal error


# ── Agent mode ───────────────────────────────────────────────────────

class AgentMode(str, Enum):
    """Operational mode for the Agent Loop.

    Determines which tools are exposed to the model.
    """
    FULL = "full"       # All registered tools available
    PLAN = "plan"       # Read-only tools only (read_file, glob, grep)
    EXECUTE = "do"      # All tools available (same as FULL for now)


# ── Agent events ─────────────────────────────────────────────────────

@dataclass
class AgentEvent:
    """An event emitted by the Agent Loop, consumed by the UI layer.

    ``type`` may be one of:
        "text"        — A text content delta (streamed to UI in real time).
        "tool_call"   — The model issued a tool call (JSON with id/name/args).
        "tool_result" — A tool execution result (JSON with tool_call_id/result).
        "usage"       — Token usage information (JSON with input/output/thinking).
        "progress"    — Loop status updates (e.g. "Round N of M").
        "done"        — The Agent Loop finished (JSON with stop_reason/usage).
        "error"       — An agent-level error (content is the message).
    """
    type: str
    content: str


# ── Configuration ────────────────────────────────────────────────────

@dataclass
class AgentConfig:
    """Configuration for the Agent Loop.

    Attributes:
        max_iterations: Maximum number of ReAct iterations (safety ceiling).
        unknown_tool_threshold: Consecutive unknown tool calls before aborting.
        read_tools: Set of tool names considered read-only (safe to parallelise).
    """
    max_iterations: int = 25
    unknown_tool_threshold: int = 3
    read_tools: set[str] = field(
        default_factory=lambda: {"read_file", "glob", "grep"}
    )


# ── Stream collector ────────────────────────────────────────────────

@dataclass
class StreamCollector:
    """Dual-path collector: streams text to UI in real time while
    accumulating the full response for the next ReAct iteration.

    One Collector is created per loop iteration.
    """

    text_parts: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add_text(self, chunk: str) -> None:
        """Append a text delta."""
        self.text_parts.append(chunk)

    def add_tool_call(self, tc: dict) -> None:
        """Record a tool-call request.

        ``tc`` has keys *id*, *name*, *arguments*.
        """
        self.tool_calls.append(tc)

    def add_thinking(self, chunk: str) -> None:
        """Append a thinking / thinking_delta chunk."""
        self.thinking_parts.append(chunk)

    def set_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        thinking_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        """Record token usage for this iteration."""
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.thinking_tokens = thinking_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens

    def has_tool_calls(self) -> bool:
        """Return True when the model requested at least one tool."""
        return len(self.tool_calls) > 0

    @property
    def full_text(self) -> str:
        """The complete accumulated text for this iteration."""
        return "".join(self.text_parts)

    @property
    def full_thinking(self) -> str:
        """The complete accumulated thinking text."""
        return "".join(self.thinking_parts)

    def to_result(
        self,
        stop_reason: StopReason,
        total_rounds: int,
    ) -> "AgentResult":
        """Package the collector state into a final AgentResult."""
        return AgentResult(
            content=self.full_text,
            tool_calls=list(self.tool_calls),
            stop_reason=stop_reason,
            total_rounds=total_rounds,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            thinking_tokens=self.thinking_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
        )


# ── Agent result ─────────────────────────────────────────────────────

@dataclass
class AgentResult:
    """Structured summary produced when the Agent Loop finishes."""

    content: str
    tool_calls: list[dict]
    stop_reason: StopReason
    total_rounds: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


# ── Plan context ─────────────────────────────────────────────────────

@dataclass
class PlanContext:
    """Context carried from a ``/plan`` phase to a ``/do`` phase.

    ``plan_content`` is the plan text the model produced.
    ``messages_before_plan`` is the conversation state before /plan.
    ``plan_messages`` is the full interaction history of the /plan step.
    """

    plan_content: str
    messages_before_plan: list  # list[Message]
    plan_messages: list  # list[Message]


# ── Agent Loop engine ────────────────────────────────────────────────

class AgentLoop:
    """ReAct-style autonomous loop that drives an LLM provider with
    tool access until the task is done or a stopping condition fires.

    Usage::

        loop = AgentLoop(provider, tools, mode=AgentMode.FULL)
        for event in loop.run(messages, thinking=True):
            ui_consume(event)
    """

    def __init__(
        self,
        provider: "BaseProvider",
        tools: ToolRegistry | ToolRegistryView,
        mode: AgentMode = AgentMode.FULL,
        config: AgentConfig | None = None,
        builder: SystemPromptBuilder | None = None,
        project_metadata: dict | None = None,
        engine: PermissionEngine | None = None,
        context_manager: ContextManager | None = None,
        append_messages: Optional[Callable[[list[Message]], None]] = None,
        prompt_context_provider: Optional[Callable[[AgentMode, int], dict]] = None,
        tool_view_provider: Optional[Callable[[AgentMode, int], ToolRegistryView]] = None,
        hook_engine: Any = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        request_snapshot_callback: Optional[Callable[..., None]] = None,
        non_interactive_permissions: bool = False,
        cwd: Optional[Path] = None,
        file_cache: Optional[FileContentCache] = None,
    ):
        self.provider = provider
        self.tools = tools
        self.mode = mode
        self.config = config or AgentConfig()
        self.builder = builder
        self.project_metadata = project_metadata or {}
        self.engine = engine
        self.context_manager = context_manager or ContextManager(provider)
        self.append_messages = append_messages
        self.prompt_context_provider = prompt_context_provider
        self.tool_view_provider = tool_view_provider
        self.hook_engine = hook_engine
        self.cancel_check = cancel_check
        self.request_snapshot_callback = request_snapshot_callback
        self.non_interactive_permissions = non_interactive_permissions
        self.cwd = normalize_cwd(cwd)
        self.file_cache = file_cache or FileContentCache()

    def _append_messages(self, messages: list[Message], additions: list[Message]) -> None:
        """Append through Session when present, preserving standalone behavior."""
        if not additions:
            return
        if self.append_messages is not None:
            self.append_messages(additions)
        else:
            messages.extend(additions)

    # ── Public API ───────────────────────────────────────────────────

    def run(
        self,
        messages: list[Message],
        thinking: bool = False,
    ) -> Generator[AgentEvent, None, None]:
        """Run the Agent Loop, yielding AgentEvents for the UI layer.

        Args:
            messages: Conversation history (will be mutated in place).
            thinking: Whether to enable extended thinking (Claude only).

        Yields:
            AgentEvent — text, tool_call, tool_result, usage, progress,
                         done, or error.
        """
        iteration = 0
        unknown_tool_count = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_thinking_tokens = 0
        total_cache_creation_tokens = 0
        total_cache_read_tokens = 0
        final_content = ""

        # ── Main ReAct loop ──────────────────────────────────────────
        while True:
            if self.cancel_check is not None and self.cancel_check():
                yield AgentEvent(
                    "done",
                    json.dumps({
                        "stop_reason": StopReason.USER_CANCELLED.value,
                        "usage": {
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "thinking_tokens": total_thinking_tokens,
                            "cache_creation_input_tokens": total_cache_creation_tokens,
                            "cache_read_input_tokens": total_cache_read_tokens,
                        },
                    }),
                )
                return
            iteration += 1
            yield AgentEvent("progress", f"Round {iteration}...")

            if self.hook_engine is not None:
                advance = getattr(self.hook_engine, "advance_agent_round", None)
                if advance is not None:
                    advance(iteration, self.mode.value)
                self.hook_engine.dispatch(
                    self.hook_engine.make_event(
                        HookEventName.MESSAGE_MODEL_REQUEST,
                        message_role="model",
                        message_content=[
                            {"role": item.role, "content": item.content}
                            for item in messages
                        ],
                        message_stage="before_request",
                    )
                )

            # ── Build system prompt (if a builder is wired up) ────────
            stable_prompt: str | None = None
            extra_msgs: list[Message] = []

            if self.builder is not None:
                ctx: dict[str, object] = {
                    "mode": self.mode,
                    "iteration": iteration,
                    "project_metadata": self.project_metadata,
                }
                if self.prompt_context_provider is not None:
                    ctx.update(self.prompt_context_provider(self.mode, iteration) or {})
                if self.hook_engine is not None:
                    ctx["hook_prompts"] = self.hook_engine.persistent_prompts()
                stable_prompt, extra_msgs = self.builder.build(ctx)

                # Mode-instruction injection with frequency control
                if should_inject_full_mode_instruction(iteration):
                    mode_text = make_mode_instruction(self.mode, full=True)
                else:
                    mode_text = make_mode_instruction(self.mode, full=False)
                if mode_text:
                    extra_msgs.append(make_whisper_message(mode_text))
                if self.hook_engine is not None:
                    pending_hook_prompts = self.hook_engine.consume_request_prompts()
                    if pending_hook_prompts:
                        extra_msgs.append(
                            make_whisper_message(
                                "[hook]\n" + "\n\n".join(pending_hook_prompts)
                            )
                        )

            iteration_tools = self._get_iteration_tools(iteration)
            active_tools = self._get_active_tools(iteration_tools)
            prior_result_paths = list(self.context_manager.state.last_result_paths)
            preparation = self.context_manager.prepare_before_request(
                messages,
                tools=active_tools,
                system_prompt=stable_prompt,
                transient_messages=extra_msgs,
            )
            if prior_result_paths and not self.context_manager.state.last_result_paths:
                self.context_manager.state.last_result_paths = prior_result_paths
            if preparation.blocked:
                yield AgentEvent("error", preparation.diagnostic.message)
                yield AgentEvent(
                    "done",
                    json.dumps({
                        "stop_reason": StopReason.ERROR.value,
                        "usage": {
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "thinking_tokens": total_thinking_tokens,
                            "cache_creation_input_tokens": total_cache_creation_tokens,
                            "cache_read_input_tokens": total_cache_read_tokens,
                        },
                    }),
                )
                return

            # Whisper messages are only present for this provider request and
            # are never persisted into the main history or a summary input.
            prepared_messages = list(preparation.messages)
            call_messages = list(extra_msgs) + prepared_messages
            if self.request_snapshot_callback is not None:
                try:
                    self.request_snapshot_callback(
                        messages=list(prepared_messages),
                        system_prompt=stable_prompt,
                        tool_view=iteration_tools,
                        mode=self.mode,
                        iteration=iteration,
                    )
                except Exception:
                    pass
            collector = StreamCollector()
            provider_error = False

            try:
                for stream_event in self.provider.stream_chat(
                    call_messages,
                    thinking=thinking,
                    tools=active_tools,
                    system=stable_prompt,
                ):
                    if self.cancel_check is not None and self.cancel_check():
                        yield AgentEvent(
                            "done",
                            json.dumps({
                                "stop_reason": StopReason.USER_CANCELLED.value,
                                "usage": {
                                    "input_tokens": total_input_tokens,
                                    "output_tokens": total_output_tokens,
                                    "thinking_tokens": total_thinking_tokens,
                                    "cache_creation_input_tokens": total_cache_creation_tokens,
                                    "cache_read_input_tokens": total_cache_read_tokens,
                                },
                            }),
                        )
                        return
                    event_type = stream_event.type
                    event_content = stream_event.content

                    if event_type == "text":
                        collector.add_text(event_content)
                        yield AgentEvent("text", event_content)

                    elif event_type in ("thinking", "thinking_delta"):
                        collector.add_thinking(event_content)
                        yield AgentEvent("thinking", event_content)

                    elif event_type == "tool_call":
                        try:
                            tc = json.loads(event_content)
                        except json.JSONDecodeError:
                            tc = {"id": "?", "name": "?", "arguments": {}}
                        collector.add_tool_call(tc)
                        yield AgentEvent("tool_call", event_content)

                    elif event_type == "done":
                        # Parse usage from done content
                        if event_content:
                            try:
                                data = json.loads(event_content)
                                usage = data.get("usage", {})
                                if usage:
                                    collector.set_usage(
                                        input_tokens=usage.get("input_tokens", 0),
                                        output_tokens=usage.get("output_tokens", 0),
                                        thinking_tokens=usage.get("thinking_tokens", 0),
                                        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
                                        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
                                    )
                            except json.JSONDecodeError:
                                pass

                    elif event_type == "error":
                        provider_error = True
                        yield AgentEvent("error", event_content)

            except Exception as exc:
                provider_error = True
                yield AgentEvent("error", f"Provider error: {exc}")

            # ── Accumulate totals ────────────────────────────────────
            total_input_tokens += collector.input_tokens
            total_output_tokens += collector.output_tokens
            total_thinking_tokens += collector.thinking_tokens
            total_cache_creation_tokens += collector.cache_creation_input_tokens
            total_cache_read_tokens += collector.cache_read_input_tokens

            if not provider_error and self.hook_engine is not None:
                self.hook_engine.dispatch(
                    self.hook_engine.make_event(
                        HookEventName.MESSAGE_ASSISTANT_COMPLETED,
                        message_role="assistant",
                        message_content={
                            "text": collector.full_text,
                            "tool_calls": list(collector.tool_calls),
                        },
                        message_stage="completed",
                    )
                )

            # ── Check: provider error — stop ─────────────────────────
            if provider_error:
                yield AgentEvent(
                    "done",
                    json.dumps({
                        "stop_reason": StopReason.PROVIDER_ERROR.value,
                        "usage": {
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "thinking_tokens": total_thinking_tokens,
                            "cache_creation_input_tokens": total_cache_creation_tokens,
                            "cache_read_input_tokens": total_cache_read_tokens,
                        },
                    }),
                )
                return

            self.context_manager.record_usage(
                collector.input_tokens,
                collector.output_tokens,
                collector.thinking_tokens,
                prepared_messages,
                system_prompt=stable_prompt,
                tools=active_tools,
                transient_messages=extra_msgs,
            )

            # ── No tool calls → model is done ────────────────────────
            if not collector.has_tool_calls():
                final_content = collector.full_text
                # Append final assistant message
                additions = [Message(role="assistant", content=final_content)]
                # If there was thinking content, append it
                if collector.full_thinking and thinking:
                    additions.append(Message(role="thinking", content=collector.full_thinking))
                self._append_messages(messages, additions)
                yield AgentEvent(
                    "usage",
                    json.dumps({
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "thinking_tokens": total_thinking_tokens,
                        "cache_creation_input_tokens": total_cache_creation_tokens,
                        "cache_read_input_tokens": total_cache_read_tokens,
                    }),
                )
                yield AgentEvent(
                    "done",
                    json.dumps({
                        "stop_reason": StopReason.COMPLETED.value,
                        "usage": {
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "thinking_tokens": total_thinking_tokens,
                            "cache_creation_input_tokens": total_cache_creation_tokens,
                            "cache_read_input_tokens": total_cache_read_tokens,
                        },
                    }),
                )
                return

            # ── Has tool calls → execute ─────────────────────────────
            assistant_text = collector.full_text
            tool_calls = list(collector.tool_calls)

            # Check unknown tool threshold
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                if not iteration_tools.get(tool_name):
                    unknown_tool_count += 1
                else:
                    unknown_tool_count = 0  # reset on a known tool

            if unknown_tool_count >= self.config.unknown_tool_threshold:
                # Still append whatever we have as assistant message
                if assistant_text:
                    self._append_messages(messages, [Message(role="assistant", content=assistant_text)])
                yield AgentEvent(
                    "error",
                    f"Stopping: model made {unknown_tool_count} consecutive "
                    f"unknown tool calls.",
                )
                yield AgentEvent(
                    "done",
                    json.dumps({
                        "stop_reason": StopReason.UNKNOWN_TOOL.value,
                        "usage": {
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "thinking_tokens": total_thinking_tokens,
                            "cache_creation_input_tokens": total_cache_creation_tokens,
                            "cache_read_input_tokens": total_cache_read_tokens,
                        },
                    }),
                )
                return

            # ── Execute tools ────────────────────────────────────────
            executed = self._execute_tools(tool_calls, iteration_tools)

            # Build assistant message with tool_calls metadata
            assistant_msg = Message(
                role="assistant",
                content=assistant_text,
            )
            assistant_msg.tool_calls = [
                {
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["arguments"],
                }
                for tc, _ in executed
            ]
            pending_messages = [assistant_msg]

            # Append thinking if any
            if collector.full_thinking and thinking:
                pending_messages.append(
                    Message(role="thinking", content=collector.full_thinking)
                )

            # Build tool result messages first, then externalize oversized
            # output before mutating the conversation history.
            pending_tool_messages: list[tuple[dict, dict, Message]] = []
            for tc, result in executed:
                result_dict = result.to_dict()
                tool_message = Message(
                    role="tool",
                    content=(
                        result_dict.get("output", "")
                        or result_dict.get("error", "")
                    ),
                    tool_call_id=tc["id"],
                )
                pending_messages.append(tool_message)
                pending_tool_messages.append((tc, result_dict, tool_message))

            self.context_manager.store_oversized_tool_results(
                list(messages) + pending_messages
            )
            self._append_messages(messages, pending_messages)

            # Append tool result events after their safe history form exists.
            for tc, result_dict, _ in pending_tool_messages:
                yield AgentEvent(
                    "tool_result",
                    json.dumps({
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "result": result_dict,
                    }),
                )

            # Also yield aggregated usage for this round
            yield AgentEvent(
                "usage",
                json.dumps({
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "thinking_tokens": total_thinking_tokens,
                    "cache_creation_input_tokens": total_cache_creation_tokens,
                    "cache_read_input_tokens": total_cache_read_tokens,
                }),
            )

            # ── Check max iterations ────────────────────────────────
            if iteration >= self.config.max_iterations:
                yield AgentEvent(
                    "done",
                    json.dumps({
                        "stop_reason": StopReason.MAX_ITERATIONS.value,
                        "usage": {
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "thinking_tokens": total_thinking_tokens,
                            "cache_creation_input_tokens": total_cache_creation_tokens,
                            "cache_read_input_tokens": total_cache_read_tokens,
                        },
                    }),
                )
                return

            # Otherwise: continue the loop for another iteration

    # ── Tool helpers ─────────────────────────────────────────────────

    def _get_iteration_tools(self, iteration: int) -> ToolRegistryView:
        if self.tool_view_provider is not None:
            return self.tool_view_provider(self.mode, iteration)
        return self.tools.snapshot()

    def _get_active_tools(self, view: ToolRegistryView) -> list[dict]:
        """Return tool definitions for the current mode.

        In PLAN mode only read-only tools are exposed.
        """
        if self.mode == AgentMode.PLAN:
            # Filter the registry to read-only tools
            all_api_tools = view.to_api_tools(
                api_format=self.provider.config.protocol
            )
            readable = set(self.config.read_tools) | {"load_skill"}
            return [
                t for t in all_api_tools
                if t.get("name") in readable
                # OpenAI format nests the name under "function"
                or t.get("function", {}).get("name") in readable
            ]
        return view.to_api_tools(
            api_format=self.provider.config.protocol
        )

    @staticmethod
    def _partition_tools(
        tool_calls: list[dict],
        read_tools: set[str],
    ) -> tuple[list[dict], list[dict]]:
        """Split tool calls into read (safe to parallelise) and write groups."""
        reads: list[dict] = []
        writes: list[dict] = []
        for tc in tool_calls:
            if tc.get("name") in read_tools:
                reads.append(tc)
            else:
                writes.append(tc)
        return reads, writes

    def _execute_single_tool(
        self,
        tc: dict,
        view: ToolRegistryView,
    ) -> tuple[dict, ToolResult]:
        """Execute one tool and return (tool_call_info, result)."""
        tool_name = tc.get("name", "")
        arguments = tc.get("arguments", {})

        tool = view.get(tool_name)
        if tool:
            execute = tool.execute
            parameters = inspect.signature(execute).parameters
            if "cwd" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            ):
                result = execute(
                    arguments,
                    cwd=self.cwd,
                    file_cache=self.file_cache,
                )
            else:
                # Third-party/fake tools from the pre-cwd API remain usable;
                # all bundled tools implement the explicit contract above.
                result = execute(arguments)
        else:
            result = ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}.",
            )
        return tc, result

    def _execute_tools(
        self,
        tool_calls: list[dict],
        view: ToolRegistryView,
    ) -> list[tuple[dict, ToolResult]]:
        """Execute a batch of tool calls.

        Read tools (safe, no side-effects) run concurrently via a
        thread pool. Write tools (with side-effects) run serially.
        """
        # Preflight in model order so Hook and permission semantics are
        # deterministic even when read tools later execute concurrently.
        ordered: list[tuple[dict, ToolResult | None]] = []
        executable: list[dict] = []
        for tc in tool_calls:
            tool_name = tc.get("name", "")
            arguments = tc.get("arguments", {})
            if not view.get(tool_name):
                ordered.append((
                    tc,
                    ToolResult(success=False, error=f"Unknown tool: {tool_name}."),
                ))
                continue
            if self.hook_engine is not None:
                hook_result = self.hook_engine.before_tool(
                    tc.get("id", ""),
                    tool_name,
                    arguments,
                    {},
                )
                if hook_result.intercepted:
                    ordered.append((
                        tc,
                        ToolResult(
                            success=False,
                            output="",
                            error=f"[Hook denied] {hook_result.reason}",
                        ),
                    ))
                    continue
            if self.engine is not None and tool_name != "load_skill":
                try:
                    check = self.engine.check(tool_name, arguments, cwd=self.cwd)
                except TypeError:
                    # Keep small test/fake permission engines compatible with
                    # the old two-argument hook while production engines use
                    # the explicit workspace root.
                    check = self.engine.check(tool_name, arguments)
                if check.allowed is not True:
                    ordered.append((
                        tc,
                        ToolResult(
                            success=False,
                            output="",
                            error=(
                                f"[Permission denied] {check.reason}\n\n"
                                + (
                                    "This operation is unavailable; try a different approach."
                                    if self.non_interactive_permissions
                                    else "You can ask the user to adjust permissions or try a different approach."
                                )
                            ),
                        ),
                    ))
                    continue
            ordered.append((tc, None))
            executable.append(tc)

        read_calls, write_calls = self._partition_tools(
            executable, self.config.read_tools
        )
        completed: dict[int, ToolResult] = {}

        # ── Read tools — concurrent ──────────────────────────────────
        if read_calls:
            with ThreadPoolExecutor(max_workers=len(read_calls)) as pool:
                futures = {
                    pool.submit(self._execute_single_tool, tc, view): tc
                    for tc in read_calls
                }
                for future in as_completed(futures):
                    try:
                        finished_tc, finished_result = future.result()
                        completed[id(finished_tc)] = finished_result
                    except Exception as exc:
                        tc = futures[future]
                        completed[id(tc)] = ToolResult(
                            success=False,
                            error=f"Execution error: {exc}",
                        )

        # ── Write tools — serial ─────────────────────────────────────
        for tc in write_calls:
            try:
                _, result = self._execute_single_tool(tc, view)
                completed[id(tc)] = result
            except Exception as exc:
                completed[id(tc)] = ToolResult(
                    success=False,
                    error=f"Execution error: {exc}",
                )

        results: list[tuple[dict, ToolResult]] = []
        for tc, preflight_result in ordered:
            result = preflight_result or completed[id(tc)]
            results.append((tc, result))
            if self.hook_engine is not None:
                self.hook_engine.dispatch(
                    self.hook_engine.make_event(
                        HookEventName.TOOL_AFTER,
                        tool_call_id=tc.get("id", ""),
                        tool_name=tc.get("name", ""),
                        tool_arguments=tc.get("arguments", {}),
                        tool_result=result.to_dict(),
                    )
                )
        return results
