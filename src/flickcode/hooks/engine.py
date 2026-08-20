"""Central Hook matcher, dispatcher, prompt state, interception, and diagnostics."""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from flickcode.hooks.actions import (
    ActionExecutor,
    BoundedExecutor,
    parse_intercept,
    prepare_action,
)
from flickcode.hooks.events import build_event
from flickcode.hooks.loader import HookCatalog
from flickcode.hooks.models import (
    HookDiagnostic,
    HookDispatchResult,
    HookEvent,
    HookEventName,
    HookRuleSummary,
    HookStatusSnapshot,
    InterceptDecision,
    ProjectTrust,
)
from flickcode.hooks.prompt_state import PromptState
from flickcode.matching import matches


class HookEngine:
    def __init__(
        self,
        catalog: HookCatalog,
        project_root: Path,
        diagnostic_callback: Optional[Callable[[str], None]] = None,
        *,
        shell_runner=None,
        http_opener=None,
        background: Optional[BoundedExecutor] = None,
    ) -> None:
        self.catalog = catalog
        self.project_root = project_root.resolve()
        self.diagnostic_callback = diagnostic_callback
        self.prompt_state = PromptState()
        self.actions = ActionExecutor(
            self.project_root,
            self.prompt_state,
            shell_runner=shell_runner,
            http_opener=http_opener,
        )
        self.background = background or BoundedExecutor()
        self.project_trust = ProjectTrust.PENDING
        self._lock = threading.RLock()
        self._recent: deque[HookDiagnostic] = deque(maxlen=100)
        self._pending_diagnostics: list[HookDiagnostic] = []
        self._started = False
        self._closed = False
        self._session_id = ""
        self._turn_number = 0
        self._turn_mode = ""

    def start(self, trust_callback=None) -> None:
        with self._lock:
            if self._started or self._closed:
                return
        project_rules = self.catalog.project_rules()
        if project_rules and trust_callback is not None:
            summaries = tuple(
                HookRuleSummary(rule.name or rule.rule_id, rule.action.type.value, rule.event.value)
                for rule in project_rules
            )
            try:
                trusted = bool(trust_callback(self.project_root, summaries))
            except Exception as exc:
                trusted = False
                self._record(HookDiagnostic(f"project Hook trust prompt failed: {exc}"))
            self.project_trust = (
                ProjectTrust.TRUSTED if trusted else ProjectTrust.UNTRUSTED
            )
        elif project_rules:
            self.project_trust = ProjectTrust.UNTRUSTED
            self._record(HookDiagnostic("project Hook rules are not trusted in non-interactive mode"))
        else:
            self.project_trust = ProjectTrust.TRUSTED
        refresh = self.catalog.prepare_refresh(self.project_trust)
        if refresh.candidate is None:
            for diagnostic in refresh.fatal_diagnostics:
                self._record(diagnostic)
        snapshot = self.catalog.commit(refresh)
        for diagnostic in snapshot.diagnostics:
            self._record(diagnostic)
        with self._lock:
            self._started = True

    def dispatch(self, event: HookEvent) -> HookDispatchResult:
        with self._lock:
            if not self._started or self._closed:
                return HookDispatchResult()
            candidates = tuple(
                rule for rule in self.catalog.snapshot.rules
                if rule.event == event.name
            )
        selected = []
        match_diagnostics: list[HookDiagnostic] = []
        for rule in candidates:
            try:
                if matches(rule.condition, event.context):
                    selected.append(rule)
            except Exception as exc:
                diagnostic = self._rule_diagnostic(
                    rule, event, f"condition matching failed: {exc}"
                )
                self._record(diagnostic)
                match_diagnostics.append(diagnostic)
        rules = tuple(selected)
        executed: list[str] = []
        local_diagnostics: list[HookDiagnostic] = list(match_diagnostics)
        for rule in rules:
            if rule.once and self.prompt_state.has_run(rule.rule_id):
                continue
            try:
                action = prepare_action(rule.action, event)
            except Exception as exc:
                diagnostic = self._rule_diagnostic(rule, event, f"template failed: {exc}")
                self._record(diagnostic)
                local_diagnostics.append(diagnostic)
                continue

            if rule.asynchronous:
                accepted = self.background.submit(
                    lambda r=rule, a=action: self.actions.execute(r.rule_id, a, event),
                    lambda future, r=rule, e=event: self._background_done(r, e, future),
                )
                if not accepted:
                    diagnostic = self._rule_diagnostic(rule, event, "background queue is full")
                    self._record(diagnostic)
                    local_diagnostics.append(diagnostic)
                    continue
                if rule.once:
                    self.prompt_state.mark_run(rule.rule_id)
                executed.append(rule.rule_id)
                continue

            if rule.once:
                self.prompt_state.mark_run(rule.rule_id)
            executed.append(rule.rule_id)
            try:
                result = self.actions.execute(rule.rule_id, action, event)
            except Exception as exc:
                result = None
                diagnostic = self._rule_diagnostic(rule, event, f"action failed: {exc}")
                self._record(diagnostic)
                local_diagnostics.append(diagnostic)
            if result is None:
                continue
            status = "completed" if result.success else (result.error or "failed")
            diagnostic = self._rule_diagnostic(
                rule, event, status, result.elapsed_seconds
            )
            self._record(diagnostic, notify=not result.success)
            local_diagnostics.append(diagnostic)
            if event.name == HookEventName.TOOL_BEFORE:
                intercept = parse_intercept(result)
                if intercept.decision == InterceptDecision.DENY:
                    return HookDispatchResult(
                        True,
                        intercept.reason,
                        tuple(executed),
                        tuple(local_diagnostics),
                    )
        return HookDispatchResult(
            False, "", tuple(executed), tuple(local_diagnostics)
        )

    def before_tool(
        self,
        call_id: str,
        name: str,
        arguments: Mapping[str, Any],
        base_context: Mapping[str, Any],
    ) -> HookDispatchResult:
        event = self.make_event(
            HookEventName.TOOL_BEFORE,
            tool_call_id=call_id,
            tool_name=name,
            tool_arguments=arguments,
            **dict(base_context),
        )
        return self.dispatch(event)

    def make_event(self, name: HookEventName, **values) -> HookEvent:
        values.setdefault("session_id", self._session_id)
        values.setdefault("turn_number", self._turn_number)
        values.setdefault("turn_mode", self._turn_mode)
        values.setdefault(
            "config_sources",
            tuple(str(path) for _, path in self.catalog.paths if path.exists()),
        )
        return build_event(name, cwd=self.project_root, **values)

    def begin_session(self, session_id: str, resumed: bool = False) -> None:
        self.prompt_state.begin_session()
        self._session_id = session_id
        event = self.make_event(
            HookEventName.SESSION_RESUMED if resumed else HookEventName.SESSION_STARTED,
            session_state="resumed" if resumed else "new",
        )
        self.dispatch(event)

    def end_session(self, session_id: str, reason: str) -> None:
        if not session_id:
            return
        self.dispatch(
            self.make_event(
                HookEventName.SESSION_ENDING,
                session_id=session_id,
                session_state=reason,
            )
        )
        self.prompt_state.end_session()

    def set_turn(self, number: int, mode: str) -> None:
        self._turn_number = number
        self._turn_mode = mode

    def persistent_prompts(self) -> tuple[str, ...]:
        return self.prompt_state.persistent()

    def consume_request_prompts(self) -> tuple[str, ...]:
        return self.prompt_state.consume_pending()

    def status_snapshot(self) -> HookStatusSnapshot:
        snapshot = self.catalog.snapshot
        return HookStatusSnapshot(
            started=self._started,
            active_rules=len(snapshot.rules),
            skipped_rules=snapshot.skipped_rules,
            project_trust=self.project_trust.value,
            once_count=self.prompt_state.once_count,
            background_count=self.background.active_count,
            overrides=tuple(item.name for item in snapshot.overrides),
            diagnostics=tuple(item.safe_text() for item in self._recent),
        )

    def drain_diagnostics(self) -> tuple[HookDiagnostic, ...]:
        with self._lock:
            result = tuple(self._pending_diagnostics)
            self._pending_diagnostics.clear()
            return result

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.background.close()

    def _background_done(self, rule, event, future) -> None:
        try:
            result = future.result()
            status = "completed" if result.success else (result.error or "failed")
            diagnostic = self._rule_diagnostic(rule, event, status, result.elapsed_seconds)
        except Exception as exc:
            diagnostic = self._rule_diagnostic(rule, event, f"background action failed: {exc}")
        self._record(diagnostic, notify=("completed" not in diagnostic.message))

    def _rule_diagnostic(self, rule, event, message, elapsed=0.0) -> HookDiagnostic:
        return HookDiagnostic(
            message,
            rule_id=rule.rule_id,
            source=rule.source.value,
            event=event.name.value,
            action=rule.action.type.value,
            elapsed_seconds=elapsed,
        )

    def _record(self, diagnostic: HookDiagnostic, notify: bool = True) -> None:
        with self._lock:
            self._recent.append(diagnostic)
            self._pending_diagnostics.append(diagnostic)
        if notify and self.diagnostic_callback is not None:
            self.diagnostic_callback(diagnostic.safe_text())
