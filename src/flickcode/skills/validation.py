"""Cross-skill startup and refresh validation."""

from __future__ import annotations

from pathlib import Path
from typing import Collection, Dict, Iterable, List, Set, Tuple

from flickcode.skills.models import SkillCatalogSnapshot, SkillDefinition, SkillDiagnostic


class SkillStartupError(ValueError):
    def __init__(self, diagnostics: Iterable[SkillDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__("skill startup validation failed:\n" + "\n".join(item.message for item in self.diagnostics))


class SkillValidator:
    """Validates names that can only be checked after all tools are known."""

    SYSTEM_TOOL_NAMES = frozenset({"load_skill"})

    def validate_startup(
        self,
        snapshot: SkillCatalogSnapshot,
        global_tool_names: Collection[str],
        reserved_command_names: Collection[str],
    ) -> None:
        diagnostics = self.diagnostics(snapshot, global_tool_names, reserved_command_names)
        if diagnostics:
            raise SkillStartupError(diagnostics)

    def diagnostics(
        self,
        snapshot: SkillCatalogSnapshot,
        global_tool_names: Collection[str],
        reserved_command_names: Collection[str],
    ) -> Tuple[SkillDiagnostic, ...]:
        errors: List[SkillDiagnostic] = []
        global_names = set(global_tool_names) | set(self.SYSTEM_TOOL_NAMES)
        reserved = set(reserved_command_names)
        custom_owners: Dict[str, List[SkillDefinition]] = {}

        for skill in snapshot.effective.values():
            if skill.name in reserved:
                errors.append(self._error(skill, f"skill name {skill.name!r} conflicts with a reserved command"))
            for tool in skill.custom_tools:
                custom_owners.setdefault(tool.name, []).append(skill)

        for tool_name, owners in sorted(custom_owners.items()):
            if tool_name in global_names:
                for owner in owners:
                    errors.append(self._error(owner, f"custom tool {tool_name!r} conflicts with a global tool"))
            if len(owners) > 1:
                owner_names = ", ".join(sorted(owner.name for owner in owners))
                for owner in owners:
                    errors.append(self._error(owner, f"custom tool {tool_name!r} has multiple owners: {owner_names}"))

        all_custom = set(custom_owners)
        for skill in sorted(snapshot.effective.values(), key=lambda item: item.name):
            own_custom = {tool.name for tool in skill.custom_tools}
            for tool_name in skill.tool_names:
                if tool_name in global_names or tool_name in own_custom:
                    continue
                if tool_name in all_custom:
                    message = f"skill {skill.name!r} cannot use custom tool {tool_name!r} owned by another skill"
                else:
                    message = f"skill {skill.name!r} references unknown tool {tool_name!r}"
                errors.append(self._error(skill, message))
        return tuple(errors)

    @staticmethod
    def _error(skill: SkillDefinition, message: str) -> SkillDiagnostic:
        return SkillDiagnostic(
            severity="error",
            phase="validation",
            message=f"{message} ({skill.source.value}: {skill.entry_path})",
            path=skill.entry_path,
            skill_name=skill.name,
        )

