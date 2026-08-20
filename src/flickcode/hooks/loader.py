"""Three-level YAML loading, trust filtering, overrides, and snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from flickcode.hooks.events import event_schema
from flickcode.hooks.models import (
    HookDiagnostic,
    HookEventName,
    HookOverride,
    HookRefresh,
    HookRule,
    HookSnapshot,
    HookSource,
    HttpAction,
    ProjectTrust,
    PromptAction,
    ShellAction,
    SubAgentAction,
)
from flickcode.hooks.validation import validate_template_fields
from flickcode.matching import compile_condition


class HookCatalog:
    def __init__(self, project_root: Path, user_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.user_root = user_root.resolve()
        self.paths = (
            (HookSource.USER, self.user_root / "hooks.yaml"),
            (HookSource.PROJECT, self.project_root / ".flick" / "hooks.yaml"),
            (HookSource.LOCAL, self.project_root / ".flick" / "hooks.local.yaml"),
        )
        self.snapshot = HookSnapshot()

    def prepare_refresh(
        self,
        project_trust: ProjectTrust = ProjectTrust.UNTRUSTED,
    ) -> HookRefresh:
        parsed: list[HookRule] = []
        diagnostics: list[HookDiagnostic] = []
        fatal: list[HookDiagnostic] = []
        for source, path in self.paths:
            rules, errors, root_error = self._read_file(source, path)
            parsed.extend(rules)
            diagnostics.extend(errors)
            if root_error is not None:
                fatal.append(root_error)
        if fatal:
            return HookRefresh(self.snapshot, None, tuple(fatal))

        trusted = [
            rule for rule in parsed
            if rule.source != HookSource.PROJECT
            or project_trust == ProjectTrust.TRUSTED
        ]
        skipped_untrusted = sum(
            1 for rule in parsed
            if rule.source == HookSource.PROJECT
            and project_trust != ProjectTrust.TRUSTED
        )
        merged: list[HookRule] = []
        named: dict[str, HookRule] = {}
        overrides: list[HookOverride] = []
        for rule in trusted:
            if rule.name and rule.name in named:
                previous = named[rule.name]
                merged.remove(previous)
                overrides.append(
                    HookOverride(rule.name, previous.source, rule.source)
                )
            if rule.name:
                named[rule.name] = rule
            merged.append(rule)
        candidate = HookSnapshot(
            generation=self.snapshot.generation + 1,
            rules=tuple(merged),
            diagnostics=tuple(diagnostics),
            overrides=tuple(overrides),
            skipped_rules=len(diagnostics) + skipped_untrusted,
        )
        return HookRefresh(self.snapshot, candidate)

    def commit(self, refresh: HookRefresh) -> HookSnapshot:
        if refresh.candidate is not None:
            self.snapshot = refresh.candidate
        return self.snapshot

    def project_rules(self) -> tuple[HookRule, ...]:
        rules, _, _ = self._read_file(
            HookSource.PROJECT,
            self.project_root / ".flick" / "hooks.yaml",
        )
        return tuple(rules)

    def _read_file(
        self,
        source: HookSource,
        path: Path,
    ) -> tuple[list[HookRule], list[HookDiagnostic], Optional[HookDiagnostic]]:
        if not path.exists():
            return [], [], None
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            diagnostic = HookDiagnostic(
                f"cannot parse {path}: {exc}", source=source.value, fatal=True
            )
            return [], [], diagnostic
        if raw is None:
            raw = {}
        if not isinstance(raw, dict) or not isinstance(raw.get("hooks", []), list):
            diagnostic = HookDiagnostic(
                f"{path} root must contain a hooks list",
                source=source.value,
                fatal=True,
            )
            return [], [], diagnostic
        rules: list[HookRule] = []
        diagnostics: list[HookDiagnostic] = []
        for index, entry in enumerate(raw.get("hooks", [])):
            try:
                rules.append(self._parse_rule(entry, source, path, index))
            except Exception as exc:
                diagnostics.append(
                    HookDiagnostic(
                        str(exc),
                        rule_id=f"{source.value}:{path.name}:{index + 1}",
                        source=source.value,
                    )
                )
        return rules, diagnostics, None

    @staticmethod
    def _parse_rule(
        raw: Any,
        source: HookSource,
        path: Path,
        index: int,
    ) -> HookRule:
        if not isinstance(raw, dict):
            raise ValueError("rule must be a mapping")
        allowed = {"name", "event", "if", "action", "once", "async"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError("unsupported rule field(s): " + ", ".join(unknown))
        try:
            event = HookEventName(raw["event"])
        except KeyError as exc:
            raise ValueError("rule requires event") from exc
        except ValueError as exc:
            raise ValueError(f"unsupported event: {raw.get('event')}") from exc
        action_raw = raw.get("action")
        if not isinstance(action_raw, dict):
            raise ValueError("rule requires one action mapping")
        action = HookCatalog._parse_action(action_raw)
        condition = compile_condition(raw.get("if"), event_schema(event))
        name = raw.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValueError("name must be a non-empty string")
        once = raw.get("once", False)
        asynchronous = raw.get("async", False)
        if not isinstance(once, bool) or not isinstance(asynchronous, bool):
            raise ValueError("once and async must be booleans")
        if event == HookEventName.TOOL_BEFORE and asynchronous:
            raise ValueError("tool.before rules cannot be async")
        validate_template_fields(event, action_raw)
        rule_id = name or f"{source.value}:{path.name}:{index + 1}"
        return HookRule(
            rule_id, name, event, condition, action, once, asynchronous,
            source, path, index,
        )

    @staticmethod
    def _parse_action(raw: dict[str, Any]):
        kind = raw.get("type")
        if kind == "shell":
            allowed = {"type", "command", "cwd", "env", "timeout"}
            HookCatalog._reject_unknown(raw, allowed)
            env = raw.get("env", {})
            if not isinstance(env, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items()
            ):
                raise ValueError("shell env must map strings to strings")
            return ShellAction(
                raw.get("command", ""),
                raw.get("cwd"),
                env,
                raw.get("timeout", 30),
            )
        if kind == "prompt":
            HookCatalog._reject_unknown(raw, {"type", "content"})
            return PromptAction(raw.get("content", ""))
        if kind == "http":
            allowed = {"type", "url", "method", "headers", "body", "timeout"}
            HookCatalog._reject_unknown(raw, allowed)
            headers = raw.get("headers", {})
            if not isinstance(headers, dict) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in headers.items()
            ):
                raise ValueError("http headers must map strings to strings")
            return HttpAction(
                raw.get("url", ""),
                raw.get("method", "POST"),
                headers,
                raw.get("body"),
                raw.get("timeout", 10),
            )
        if kind == "subagent":
            HookCatalog._reject_unknown(raw, {"type", "task"})
            return SubAgentAction(raw.get("task", ""))
        raise ValueError(f"unsupported action type: {kind}")

    @staticmethod
    def _reject_unknown(raw: dict[str, Any], allowed: set[str]) -> None:
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError("unsupported action field(s): " + ", ".join(unknown))
