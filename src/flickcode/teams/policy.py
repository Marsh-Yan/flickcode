"""Team identity and coordinator tool policy."""

from __future__ import annotations

import os
from typing import Iterable, Mapping, Optional


TEAM_LEAD_TOOL = "team_lead"
TEAM_TASK_TOOL = "team_tasks"
TEAM_MESSAGE_TOOL = "team_message"
TEAM_TOOLS = frozenset({TEAM_LEAD_TOOL, TEAM_TASK_TOOL, TEAM_MESSAGE_TOOL})
WRITE_TOOLS = frozenset({"write_file", "edit_file"})


def coordinator_active(config_enabled: bool, environ: Optional[Mapping[str, str]] = None) -> bool:
    values = os.environ if environ is None else environ
    return bool(config_enabled) and values.get("FLICKCODE_COORDINATOR") == "1"


class TeamToolPolicy:
    def lead_names(self, base_names: Iterable[str], *, coordinator: bool = False) -> frozenset[str]:
        names = set(base_names) | set(TEAM_TOOLS)
        if coordinator:
            names -= WRITE_TOOLS
        return frozenset(names)

    def member_names(self, base_names: Iterable[str]) -> frozenset[str]:
        names = set(base_names) | {TEAM_TASK_TOOL, TEAM_MESSAGE_TOOL}
        names.discard(TEAM_LEAD_TOOL)
        names.discard("agent")
        names.discard("load_skill")
        return frozenset(names)

    def allowed(self, *, identity: str, tool_name: str, coordinator: bool = False) -> bool:
        if identity == "lead":
            if coordinator and tool_name in WRITE_TOOLS:
                return False
            return tool_name in TEAM_TOOLS or tool_name not in {"__unknown__"}
        if identity == "member":
            return tool_name in {TEAM_TASK_TOOL, TEAM_MESSAGE_TOOL} or tool_name not in {TEAM_LEAD_TOOL, "agent", "load_skill"}
        return tool_name not in TEAM_TOOLS

