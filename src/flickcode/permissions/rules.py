"""Three-layer configurable rule engine.

Rules live in YAML files at three levels (closest wins):

    1.  Local   — ``.flick/permissions.local.yaml`` (not versioned)
    2.  Project — ``.flick/permissions.yaml`` (versioned, team-shared)
    3.  User    — ``~/.flickcode/permissions.yaml`` (personal default)

Each file has the same structure::

    rules:
      execute_command:
        - pattern: "git *"
          action: allow
      read_file:
        - pattern: "src/**"
          action: allow
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from flickcode.matching import MatchOperator, match_value

USER_CONFIG_DIR = Path.home() / ".flickcode"
USER_LEVEL = USER_CONFIG_DIR / "permissions.yaml"
PROJECT_LEVEL = Path.cwd() / ".flick" / "permissions.yaml"
LOCAL_LEVEL = Path.cwd() / ".flick" / "permissions.local.yaml"


@dataclass
class Rule:
    """A single permission rule parsed from YAML."""

    tool: str       # e.g. "execute_command"
    pattern: str    # e.g. "git *"
    action: str     # "allow" | "deny"
    source: str     # "user" | "project" | "local"

    def matches(self, tool_name: str, params: dict) -> bool:
        """Return True when this rule applies to *tool_name* + *params*.

        The pattern is matched against the first string-typed parameter
        of the tool call (typically the ``command`` or ``path`` value).
        """
        if self.tool != tool_name:
            return False
        if self.pattern == "*":
            return True
        # Match against the first string parameter value
        for v in params.values():
            if isinstance(v, str) and match_value(
                v, MatchOperator.GLOB, self.pattern
            ):
                return True
        return False


_RULES_CACHE: list[Rule] | None = None
"""In-memory cache of all merged rules (rebuilt on each load())."""


def load() -> list[Rule]:
    """Load rules from all three levels, merged into a single list.

    Rules are ordered **lowest priority first** (user < project < local)
    so that callers can iterate front-to-back and stop on the first
    match (which will be the highest-priority one).
    """
    global _RULES_CACHE
    _RULES_CACHE = _merge_rules()
    return _RULES_CACHE


def invalidate_cache() -> None:
    """Drop the cached rules so the next load() re-reads from disk."""
    global _RULES_CACHE
    _RULES_CACHE = None


def _merge_rules() -> list[Rule]:
    """Read the three YAML files and return a merged rule list.

    Order: user first, then project, then local.
    """
    rules: list[Rule] = []

    for source, path in [("user", USER_LEVEL),
                         ("project", PROJECT_LEVEL),
                         ("local", LOCAL_LEVEL)]:
        if not path.exists():
            continue
        try:
            data = _read_yaml(path)
        except Exception:
            continue  # skip corrupt files silently
        if not data:
            continue
        file_rules = data.get("rules", {})
        for tool_name, entries in file_rules.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                pattern = entry.get("pattern", "*")
                action = entry.get("action", "deny")
                rules.append(Rule(
                    tool=tool_name,
                    pattern=pattern,
                    action=action,
                    source=source,
                ))

    return rules


def evaluate(
    tool_name: str,
    params: dict,
    rules: list[Rule] | None = None,
) -> Rule | None:
    """Find the highest-priority rule matching the call.

    Iterates the rule list **backwards** (local last = highest priority)
    and returns the first match, or *None* when no rule applies.

    Args:
        tool_name: The tool being called (e.g. ``"execute_command"``).
        params:    The arguments dict passed to the tool.
        rules:     Optional pre-loaded rule list.  Loads fresh when None.

    Returns:
        The matching ``Rule``, or *None* if no rule matched.
    """
    if rules is None:
        rules = load()
    # Iterate in reverse: local (highest priority) first
    for rule in reversed(rules):
        if rule.matches(tool_name, params):
            return rule
    return None


def persist(action: str, tool: str, pattern: str) -> None:
    """Append one rule to the **local** permissions file.

    This is used by the 'Allow forever' HITL path::

        persist("allow", "execute_command", "npm *")

    Creates the file and parent directories if they do not exist.
    """
    LOCAL_LEVEL.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if LOCAL_LEVEL.exists():
        with open(LOCAL_LEVEL, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    rules = existing.setdefault("rules", {})
    entries = rules.setdefault(tool, [])
    entries.append({"pattern": pattern, "action": action})

    with open(LOCAL_LEVEL, "w", encoding="utf-8") as f:
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

    invalidate_cache()


def _read_yaml(path: Path) -> dict:
    """Safely read a YAML file and return its contents as a dict."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}
