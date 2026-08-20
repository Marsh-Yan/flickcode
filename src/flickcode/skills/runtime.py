"""Active skill state and per-iteration tool visibility."""

from __future__ import annotations

from pathlib import Path
from typing import Collection, List, Optional, Tuple

from flickcode.agent import AgentMode
from flickcode.skills.models import (
    ActivationResult,
    ActiveSkill,
    SkillCatalogCandidate,
    SkillCatalogSnapshot,
    SkillDefinition,
    SkillDiagnostic,
    SkillMode,
    SkillRuntimeCandidate,
    SkillRuntimeSnapshot,
)
from flickcode.skills.script_tool import SkillScriptTool
from flickcode.tools.registry import ToolRegistry, ToolRegistryView


class SkillRuntime:
    """Owns shared activations and builds immutable tool views."""

    READ_TOOL_NAMES = frozenset({"read_file", "glob", "grep"})

    def __init__(
        self,
        catalog: SkillCatalogSnapshot,
        tools: ToolRegistry,
        project_root: Path,
        system_tool_names: Collection[str] = ("load_skill",),
    ) -> None:
        self._tools = tools
        self._project_root = Path(project_root)
        self._system_tool_names = frozenset(system_tool_names)
        self._activation_counter = 0
        allowed = self._default_tool_names()
        self._snapshot = SkillRuntimeSnapshot(
            catalog=catalog,
            active_skills=(),
            allowed_tool_names=frozenset(allowed),
            diagnostics=(),
        )
        self._custom_tool_instances: Tuple[SkillScriptTool, ...] = ()

    @property
    def snapshot(self) -> SkillRuntimeSnapshot:
        return self._snapshot

    def prompt_context(self) -> dict:
        return {
            "skill_catalog": tuple(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "source": skill.source.value,
                }
                for skill in sorted(self._snapshot.catalog.effective.values(), key=lambda item: item.name)
            ),
            "active_skills": self._snapshot.active_skills,
        }

    def activate_shared(self, name: str, user_input: str = "") -> ActivationResult:
        definition = self._snapshot.catalog.effective.get(name)
        if definition is None:
            return self._activation_failure(name, "skill is not available")
        if definition.mode is not SkillMode.SHARED:
            return self._activation_failure(name, "skill uses isolated mode")

        active = list(self._snapshot.active_skills)
        existing_index = next((index for index, item in enumerate(active) if item.definition.name == name), None)
        if existing_index is None:
            self._activation_counter += 1
            order = self._activation_counter
            rebound = False
        else:
            order = active[existing_index].activation_order
            rebound = True
        activated = ActiveSkill(
            definition=definition,
            user_input=user_input,
            rendered_instructions=definition.render(user_input),
            activation_order=order,
        )
        if existing_index is None:
            active.append(activated)
        else:
            active[existing_index] = activated
        active_tuple = tuple(sorted(active, key=lambda item: item.activation_order))
        allowed, instances = self._compute_tools(active_tuple)
        previous_names = self._snapshot.allowed_tool_names
        self._snapshot = SkillRuntimeSnapshot(
            catalog=self._snapshot.catalog,
            active_skills=active_tuple,
            allowed_tool_names=allowed,
            diagnostics=self._snapshot.diagnostics,
        )
        self._custom_tool_instances = instances
        return ActivationResult(
            success=True,
            active_skill=activated,
            changed_tool_names=tuple(sorted(previous_names ^ allowed)),
            rebound=rebound,
        )

    def activate_for_child(self, definition: SkillDefinition, user_input: str = "") -> ActiveSkill:
        """Pre-activate one target definition in an isolated child runtime."""
        self._activation_counter += 1
        active = ActiveSkill(
            definition=definition,
            user_input=user_input,
            rendered_instructions=definition.render(user_input),
            activation_order=self._activation_counter,
        )
        allowed, instances = self._compute_tools((active,))
        self._snapshot = SkillRuntimeSnapshot(
            catalog=self._snapshot.catalog,
            active_skills=(active,),
            allowed_tool_names=allowed,
            diagnostics=self._snapshot.diagnostics,
        )
        self._custom_tool_instances = instances
        return active

    def prepare_reconcile(self, candidate: SkillCatalogCandidate) -> SkillRuntimeCandidate:
        if candidate.previous is not self._snapshot.catalog:
            raise RuntimeError("runtime reconciliation requires the current catalog snapshot")
        retained_invalid = set(candidate.retained_invalid)
        active: List[ActiveSkill] = []
        diagnostics: List[SkillDiagnostic] = list(candidate.current.diagnostics)
        for old in self._snapshot.active_skills:
            current = candidate.current.effective.get(old.definition.name)
            invalid_paths = [
                item.path
                for item in candidate.current.diagnostics
                if item.phase == "parse" and item.skill_name == old.definition.name and item.path is not None
            ]
            old_root = old.definition.package_root or old.definition.entry_path
            old_invalid = any(
                path == old.definition.entry_path
                or (old.definition.package_root is not None and self._is_beneath(path, old_root))
                for path in invalid_paths
            )
            if old.definition.name in retained_invalid and (current is None or old_invalid):
                active.append(old)
                diagnostics.append(
                    SkillDiagnostic(
                        severity="warning",
                        phase="runtime",
                        message=f"active skill {old.definition.name!r} retained its last valid snapshot",
                        path=old.definition.entry_path,
                        skill_name=old.definition.name,
                    )
                )
                continue
            if current is None:
                diagnostics.append(self._deactivation(old, "definition was removed"))
                continue
            if current.mode is not SkillMode.SHARED:
                diagnostics.append(self._deactivation(old, "definition changed to isolated mode"))
                continue
            active.append(
                ActiveSkill(
                    definition=current,
                    user_input=old.user_input,
                    rendered_instructions=current.render(old.user_input),
                    activation_order=old.activation_order,
                )
            )
        active_tuple = tuple(sorted(active, key=lambda item: item.activation_order))
        allowed, instances = self._compute_tools(active_tuple)
        return SkillRuntimeCandidate(
            previous=self._snapshot,
            catalog=candidate.current,
            active_skills=active_tuple,
            allowed_tool_names=allowed,
            custom_tool_instances=instances,
            diagnostics=tuple(diagnostics),
        )

    def commit(self, candidate: SkillRuntimeCandidate) -> SkillRuntimeSnapshot:
        if candidate.previous is not self._snapshot:
            raise RuntimeError("stale skill runtime candidate")
        self._snapshot = SkillRuntimeSnapshot(
            catalog=candidate.catalog,
            active_skills=candidate.active_skills,
            allowed_tool_names=candidate.allowed_tool_names,
            diagnostics=candidate.diagnostics,
        )
        self._custom_tool_instances = tuple(candidate.custom_tool_instances)
        return self._snapshot

    def clear_active(self) -> None:
        self._snapshot = SkillRuntimeSnapshot(
            catalog=self._snapshot.catalog,
            active_skills=(),
            allowed_tool_names=frozenset(self._default_tool_names()),
            diagnostics=self._snapshot.diagnostics,
        )
        self._custom_tool_instances = ()

    def restore_snapshot(self, snapshot: SkillRuntimeSnapshot) -> None:
        """Restore a previously captured immutable snapshot after failed preparation."""
        allowed, instances = self._compute_tools(snapshot.active_skills)
        self._snapshot = SkillRuntimeSnapshot(
            catalog=snapshot.catalog,
            active_skills=snapshot.active_skills,
            allowed_tool_names=allowed,
            diagnostics=snapshot.diagnostics,
        )
        self._custom_tool_instances = instances
        if snapshot.active_skills:
            self._activation_counter = max(
                self._activation_counter,
                max(item.activation_order for item in snapshot.active_skills),
            )

    def tool_view(self, mode: AgentMode = AgentMode.FULL) -> ToolRegistryView:
        allowed = set(self._snapshot.allowed_tool_names)
        if mode is AgentMode.PLAN:
            allowed &= set(self.READ_TOOL_NAMES) | set(self._system_tool_names)
        custom_names = {tool.spec.name for tool in self._custom_tool_instances}
        base_names = allowed - custom_names
        extras = tuple(tool for tool in self._custom_tool_instances if tool.spec.name in allowed)
        return self._tools.snapshot(base_names, extras)

    def _compute_tools(
        self,
        active: Tuple[ActiveSkill, ...],
    ) -> Tuple[frozenset[str], Tuple[SkillScriptTool, ...]]:
        if not active:
            return frozenset(self._default_tool_names()), ()
        allowed = set(self._system_tool_names)
        instances: List[SkillScriptTool] = []
        for item in active:
            allowed.update(item.definition.tool_names)
            instances.extend(
                SkillScriptTool(definition, self._project_root)
                for definition in item.definition.custom_tools
            )
        custom_names = {tool.spec.name for tool in instances}
        self._tools.snapshot(allowed - custom_names, instances)
        return frozenset(allowed), tuple(instances)

    def _default_tool_names(self) -> set[str]:
        names = set(self._tools.list_tools())
        missing_system = set(self._system_tool_names) - names
        if missing_system:
            raise ValueError("System tool(s) are not registered: " + ", ".join(sorted(missing_system)))
        return names | set(self._system_tool_names)

    @staticmethod
    def _activation_failure(name: str, reason: str) -> ActivationResult:
        return ActivationResult(
            success=False,
            diagnostics=(
                SkillDiagnostic(
                    severity="error",
                    phase="activation",
                    message=f"cannot activate skill {name!r}: {reason}",
                    skill_name=name,
                ),
            ),
        )

    @staticmethod
    def _deactivation(active: ActiveSkill, reason: str) -> SkillDiagnostic:
        return SkillDiagnostic(
            severity="warning",
            phase="runtime",
            message=f"active skill {active.definition.name!r} was deactivated: {reason}",
            path=active.definition.entry_path,
            skill_name=active.definition.name,
        )

    @staticmethod
    def _is_beneath(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            return False
