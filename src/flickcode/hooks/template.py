"""Strict {{dot.path}} template expansion."""

from __future__ import annotations

import re
from typing import Any, Mapping

from flickcode.matching import FieldNotFound, resolve_field, stable_text

_REFERENCE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*}}")


class HookTemplateError(ValueError):
    pass


def references(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(match.group(1) for match in _REFERENCE.finditer(value))
        if "{{" in value or "}}" in value:
            stripped = _REFERENCE.sub("", value)
            if "{{" in stripped or "}}" in stripped:
                raise HookTemplateError("invalid Hook template expression")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            found.update(references(key))
            found.update(references(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(references(item))
    return found


def expand_string(template: str, context: Mapping[str, Any]) -> str:
    references(template)

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        try:
            return stable_text(resolve_field(context, path))
        except FieldNotFound as exc:
            raise HookTemplateError(f"unknown Hook template variable: {path}") from exc

    return _REFERENCE.sub(replace, template)


def expand(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        return expand_string(value, context)
    if isinstance(value, Mapping):
        return {
            expand_string(str(key), context): expand(item, context)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [expand(item, context) for item in value]
    if isinstance(value, tuple):
        return tuple(expand(item, context) for item in value)
    return value
