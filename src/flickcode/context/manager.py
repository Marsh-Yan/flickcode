"""Conversation-scoped coordination for context storage and compaction."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from flickcode.context.compactor import ContextCompactor
from flickcode.context.estimator import TokenEstimator
from flickcode.context.models import (
    ContextConfig,
    ContextDiagnostic,
    ContextPreparation,
    ContextState,
    SafetyMode,
)
from flickcode.context.store import ContextStorageError, ResultStore
from flickcode.context.summary import SummaryClient, serialize_history
from flickcode.providers.base import BaseProvider, Message


log = logging.getLogger("flickcode.context")


class ContextManager:
    """Prepare one session's message history before every main API request."""

    def __init__(
        self,
        provider: BaseProvider,
        config: Optional[ContextConfig] = None,
        *,
        store: Optional[ResultStore] = None,
        estimator: Optional[TokenEstimator] = None,
        summary_client: Optional[SummaryClient] = None,
        session_id: Optional[str] = None,
    ):
        self.provider = provider
        self.config = config or ContextConfig()
        self.state = ContextState()
        self.store = store or ResultStore(self.config)
        self.estimator = estimator or TokenEstimator(self.config)
        self.summary_client = summary_client or SummaryClient(provider)
        self.compactor = ContextCompactor(self.config, self.store, self.estimator)
        self.session_id = session_id or uuid.uuid4().hex

    def prepare_before_request(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
        transient_messages: Optional[list[Message]] = None,
        safety_mode: SafetyMode = SafetyMode.AUTOMATIC,
        force_compact: bool = False,
    ) -> ContextPreparation:
        """Apply lightweight reduction, estimate, then summarize if required."""
        light = self.compactor.lighten_tool_results(
            messages,
            session_id=self.session_id,
        )
        if light.changed:
            self.estimator.invalidate(self.state)
        self.state.last_result_paths = list(light.stored_paths)

        estimate = self.estimator.estimate(
            messages,
            self.state,
            system_prompt=system_prompt,
            tools=tools,
            transient_messages=transient_messages,
        )
        budget = self.estimator.request_budget(safety_mode)
        margin = self.estimator.safety_margin(safety_mode)
        requires_summary = force_compact or estimate.input_tokens > budget

        if not requires_summary:
            return self._finish(
                messages,
                changed=light.changed,
                diagnostic=self._diagnostic(
                    action="stored_tool_result" if light.changed else "unchanged",
                    estimate=estimate.input_tokens,
                    budget=budget,
                    margin=margin,
                    stored_paths=light.stored_paths,
                    errors=light.errors,
                    message=(
                        "Stored oversized tool result(s) before the request."
                        if light.changed
                        else "Context is within the request budget."
                    ),
                ),
            )

        if self.state.summary_circuit_open:
            blocked = estimate.input_tokens > budget
            return self._finish(
                messages,
                blocked=blocked,
                changed=light.changed,
                diagnostic=self._diagnostic(
                    action="blocked" if blocked else "circuit_open",
                    estimate=estimate.input_tokens,
                    budget=budget,
                    margin=margin,
                    stored_paths=light.stored_paths,
                    errors=light.errors,
                    message=(
                        "Context exceeds the request budget and summary retries are "
                        "circuit-open. The provider request was not sent."
                        if blocked
                        else "Summary retries are circuit-open; context was not compacted."
                    ),
                ),
            )

        source_messages = list(messages)
        older, recent = self.compactor.select_recent_messages(source_messages)
        if not older:
            blocked = estimate.input_tokens > budget
            return self._finish(
                messages,
                blocked=blocked,
                changed=light.changed,
                diagnostic=self._diagnostic(
                    action="blocked" if blocked else "unchanged",
                    estimate=estimate.input_tokens,
                    budget=budget,
                    margin=margin,
                    stored_paths=light.stored_paths,
                    errors=light.errors,
                    message=(
                        "Context exceeds the request budget, but no earlier messages "
                        "can be summarized without removing the recent minimum."
                        if blocked
                        else "No earlier messages are eligible for manual compaction."
                    ),
                ),
            )

        failures: list[str] = list(light.errors)
        candidates = [(older, recent)]
        minimal_older, minimal_recent = self.compactor.select_recent_messages(
            source_messages,
            target_tokens=0,
        )
        if minimal_recent != recent and minimal_older:
            candidates.append((minimal_older, minimal_recent))

        last_compacted: list[Message] | None = None
        last_summary = None
        last_summary_path = None
        last_estimate = estimate.input_tokens
        for candidate_older, candidate_recent in candidates:
            result = self._summarize_with_retries(candidate_older, failures)
            if result is None:
                break

            summary_path = None
            try:
                summary_path = self.store.store_summary(
                    session_id=self.session_id,
                    summary=result.content,
                )
            except ContextStorageError as exc:
                failures.append(str(exc))

            compacted = self.compactor.build_compacted_messages(
                result.content,
                candidate_recent,
                summary_path=summary_path,
            )
            self.estimator.invalidate(self.state)
            compacted_estimate = self.estimator.estimate(
                compacted,
                self.state,
                system_prompt=system_prompt,
                tools=tools,
                transient_messages=transient_messages,
            )
            last_compacted = compacted
            last_summary = result.content
            last_summary_path = summary_path
            last_estimate = compacted_estimate.input_tokens
            if compacted_estimate.input_tokens <= budget:
                messages[:] = compacted
                self.state.last_summary_path = summary_path
                return self._finish(
                    messages,
                    changed=True,
                    summary_content=result.content,
                    diagnostic=self._diagnostic(
                        action="compacted",
                        estimate=compacted_estimate.input_tokens,
                        budget=budget,
                        margin=margin,
                        stored_paths=light.stored_paths,
                        summary_path=summary_path,
                        errors=failures,
                        message="Context was compacted with a structured summary.",
                    ),
                )

        if last_compacted is not None:
            messages[:] = last_compacted
            self.state.last_summary_path = last_summary_path
            return self._finish(
                messages,
                blocked=True,
                changed=True,
                summary_content=last_summary,
                diagnostic=self._diagnostic(
                    action="blocked",
                    estimate=last_estimate,
                    budget=budget,
                    margin=margin,
                    stored_paths=light.stored_paths,
                    summary_path=last_summary_path,
                    errors=failures,
                    message=(
                        "Context was compressed to the recent-message minimum but still "
                        "exceeds the request budget. The provider request was not sent."
                    ),
                ),
            )

        blocked = estimate.input_tokens > budget
        return self._finish(
            messages,
            blocked=blocked,
            changed=light.changed,
            diagnostic=self._diagnostic(
                action="blocked" if blocked else "summary_failed",
                estimate=estimate.input_tokens,
                budget=budget,
                margin=margin,
                stored_paths=light.stored_paths,
                errors=failures,
                message=(
                    "Context exceeds the request budget and structured summary failed; "
                    "the provider request was not sent."
                    if blocked
                    else "Structured summary failed; original context was retained."
                ),
            ),
        )

    def compact(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
    ) -> ContextPreparation:
        """Manually compact history with the narrower user-requested margin."""
        return self.prepare_before_request(
            messages,
            tools=tools,
            system_prompt=system_prompt,
            safety_mode=SafetyMode.MANUAL,
            force_compact=True,
        )

    def store_oversized_tool_results(
        self,
        messages: list[Message],
    ) -> ContextDiagnostic:
        """Externalize tool output before caller appends it to main history."""
        outcome = self.compactor.lighten_tool_results(
            messages,
            session_id=self.session_id,
        )
        if outcome.changed:
            self.estimator.invalidate(self.state)
        self.state.last_result_paths = list(outcome.stored_paths)
        estimate = self.estimator.estimate(messages, self.state)
        diagnostic = self._diagnostic(
            action="stored_tool_result" if outcome.changed else "unchanged",
            estimate=estimate.input_tokens,
            budget=self.estimator.request_budget(SafetyMode.AUTOMATIC),
            margin=self.estimator.safety_margin(SafetyMode.AUTOMATIC),
            stored_paths=outcome.stored_paths,
            errors=outcome.errors,
            message=(
                "Stored oversized tool result(s)."
                if outcome.changed
                else "No oversized tool result needed storage."
            ),
        )
        self.state.last_diagnostic = diagnostic
        return diagnostic

    def record_usage(
        self,
        input_tokens: int,
        output_tokens: int = 0,
        thinking_tokens: int = 0,
        message_snapshot: Optional[list[Message]] = None,
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        transient_messages: Optional[list[Message]] = None,
    ) -> None:
        """Record only usage returned by a main provider request."""
        if input_tokens <= 0:
            return
        self.state.last_output_tokens = max(0, output_tokens)
        self.state.last_thinking_tokens = max(0, thinking_tokens)
        snapshot = message_snapshot if message_snapshot is not None else []
        self.estimator.record_usage(
            self.state,
            input_tokens,
            snapshot,
            system_prompt=system_prompt,
            tools=tools,
            transient_messages=transient_messages,
        )

    def reset_summary_circuit(self) -> None:
        """Explicitly restore summary attempts after a user-directed reset."""
        self.state.summary_failure_count = 0
        self.state.summary_circuit_open = False

    def _summarize_with_retries(self, messages: list[Message], failures: list[str]):
        """Return one formal summary while enforcing the shared failure circuit."""
        remaining_attempts = max(
            0,
            self.config.summary_max_retries - self.state.summary_failure_count,
        )
        for attempt in range(1, remaining_attempts + 1):
            result = self.summary_client.summarize(serialize_history(messages))
            result.attempts = attempt
            if result.success:
                self.state.summary_failure_count = 0
                self.state.summary_circuit_open = False
                return result
            self.state.summary_failure_count += 1
            failures.append(result.error or "Summary request failed.")
            if self.state.summary_failure_count >= self.config.summary_max_retries:
                self.state.summary_circuit_open = True
                return None
        return None

    def _diagnostic(
        self,
        *,
        action: str,
        estimate: int,
        budget: int,
        margin: int,
        stored_paths: list,
        message: str,
        summary_path=None,
        errors: Optional[list[str]] = None,
    ) -> ContextDiagnostic:
        return ContextDiagnostic(
            action=action,
            estimated_input_tokens=estimate,
            context_window_tokens=self.config.context_window_tokens,
            safety_margin_tokens=margin,
            request_budget_tokens=budget,
            stored_paths=list(stored_paths),
            summary_path=summary_path,
            message=message,
            errors=list(errors or []),
        )

    def _finish(
        self,
        messages: list[Message],
        *,
        blocked: bool = False,
        changed: bool = False,
        diagnostic: ContextDiagnostic,
        summary_content: Optional[str] = None,
    ) -> ContextPreparation:
        self.state.last_diagnostic = diagnostic
        log.debug(
            "context action=%s estimated=%s budget=%s margin=%s stored=%d "
            "summary_path=%s errors=%d blocked=%s",
            diagnostic.action,
            diagnostic.estimated_input_tokens,
            diagnostic.request_budget_tokens,
            diagnostic.safety_margin_tokens,
            len(diagnostic.stored_paths),
            diagnostic.summary_path,
            len(diagnostic.errors),
            blocked,
        )
        return ContextPreparation(
            messages=messages,
            blocked=blocked,
            diagnostic=diagnostic,
            changed=changed,
            summary_content=summary_content,
        )
