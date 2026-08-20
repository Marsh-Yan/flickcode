"""Small, deterministic matching core shared by Hooks and permissions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch
from typing import Any, Collection, Mapping, Optional


class MatchOperator(str, Enum):
    EXACT = "exact"
    NOT = "not"
    REGEX = "regex"
    GLOB = "glob"


class LogicalMode(str, Enum):
    ALL = "all"
    ANY = "any"


@dataclass(frozen=True)
class MatchPredicate:
    field: str
    operator: MatchOperator
    expected: Any

    def __post_init__(self) -> None:
        if not self.field or any(not part for part in self.field.split(".")):
            raise ValueError("match field must be a non-empty dot path")
        if self.operator in (MatchOperator.REGEX, MatchOperator.GLOB):
            if not isinstance(self.expected, str):
                raise ValueError(f"{self.operator.value} expects a string")
        if self.operator == MatchOperator.REGEX:
            re.compile(self.expected)


@dataclass(frozen=True)
class ConditionGroup:
    mode: LogicalMode
    predicates: tuple[MatchPredicate, ...]

    def __post_init__(self) -> None:
        if not self.predicates:
            raise ValueError("condition group must not be empty")


class FieldNotFound(KeyError):
    pass


def resolve_field(context: Mapping[str, Any], path: str) -> Any:
    if not path or any(not part for part in path.split(".")):
        raise FieldNotFound(path)
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise FieldNotFound(path)
        current = current[part]
    return current


def stable_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def match_value(actual: Any, operator: MatchOperator, expected: Any) -> bool:
    if operator == MatchOperator.EXACT:
        return type(actual) is type(expected) and actual == expected
    if operator == MatchOperator.NOT:
        return not (type(actual) is type(expected) and actual == expected)
    if operator == MatchOperator.REGEX:
        return re.search(str(expected), stable_text(actual)) is not None
    if operator == MatchOperator.GLOB:
        return fnmatch(stable_text(actual), str(expected))
    raise ValueError(f"unsupported match operator: {operator}")


def compile_condition(
    raw: Any,
    allowed_fields: Optional[Collection[str]] = None,
) -> Optional[ConditionGroup]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("if must be a mapping")
    modes = [name for name in ("all", "any") if name in raw]
    if len(modes) != 1 or len(raw) != 1:
        raise ValueError("if must contain exactly one of all or any")
    mode = LogicalMode(modes[0])
    entries = raw[modes[0]]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"if.{mode.value} must be a non-empty list")
    allowed = set(allowed_fields or ())
    predicates = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"condition #{index + 1} must be a mapping")
        field = entry.get("field")
        if not isinstance(field, str) or not field:
            raise ValueError(f"condition #{index + 1} requires field")
        if allowed and field not in allowed and not any(
            field.startswith(prefix + ".") for prefix in allowed if prefix.endswith("arguments")
        ):
            raise ValueError(f"field {field!r} is not available for this event")
        operators = [item.value for item in MatchOperator if item.value in entry]
        if len(operators) != 1 or set(entry) != {"field", operators[0]}:
            raise ValueError(f"condition #{index + 1} requires exactly one operator")
        predicates.append(
            MatchPredicate(field, MatchOperator(operators[0]), entry[operators[0]])
        )
    return ConditionGroup(mode, tuple(predicates))


def matches(condition: Optional[ConditionGroup], context: Mapping[str, Any]) -> bool:
    if condition is None:
        return True

    def evaluate(predicate: MatchPredicate) -> bool:
        try:
            actual = resolve_field(context, predicate.field)
        except FieldNotFound:
            return False
        return match_value(actual, predicate.operator, predicate.expected)

    if condition.mode == LogicalMode.ALL:
        return all(evaluate(item) for item in condition.predicates)
    return any(evaluate(item) for item in condition.predicates)
