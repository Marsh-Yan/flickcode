"""Cross-field validation helpers for parsed Hook rules."""

from __future__ import annotations

from typing import Any

from flickcode.hooks.events import event_schema
from flickcode.hooks.models import HookEventName
from flickcode.hooks.template import HookTemplateError, references


def validate_template_fields(event: HookEventName, value: Any) -> None:
    allowed = event_schema(event)
    for path in references(value):
        if path in allowed:
            continue
        if any(
            path.startswith(prefix + ".")
            for prefix in ("tool.arguments", "tool.result")
            if prefix in allowed
        ):
            continue
        raise HookTemplateError(
            f"template variable {path!r} is not available for {event.value}"
        )
