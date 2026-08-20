"""Dynamic slash commands generated from a committed Skill catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from flickcode.agent import AgentMode
from flickcode.commands.models import CommandResult, CommandSpec, CommandType, InteractionMode
from flickcode.commands.registry import CommandRegistry
from flickcode.skills.models import SkillCatalogSnapshot


@dataclass(frozen=True)
class SkillCommandCandidate:
    previous_generation: int
    catalog_generation: int
    specs: Tuple[CommandSpec, ...]


class SkillCommandManager:
    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry
        self._generation = 0

    def prepare(self, catalog: SkillCatalogSnapshot) -> SkillCommandCandidate:
        specs = tuple(self._make_spec(skill) for skill in sorted(catalog.effective.values(), key=lambda item: item.name))
        # Validate without changing the live dynamic index.
        probe = CommandRegistry()
        for spec in self.registry.stable(include_hidden=True):
            probe.register(spec)
        for spec in specs:
            probe.register(spec)
        probe.validate()
        return SkillCommandCandidate(self._generation, catalog.generation, specs)

    def commit(self, candidate: SkillCommandCandidate) -> None:
        if candidate.previous_generation != self._generation:
            raise RuntimeError("stale Skill command candidate")
        self.registry.replace_dynamic(candidate.specs)
        self._generation = candidate.catalog_generation

    @staticmethod
    def _make_spec(skill) -> CommandSpec:
        def run(context):
            mode = AgentMode.PLAN if context.ui.get_mode() is InteractionMode.PLAN else AgentMode.FULL
            context.ui.run_skill(skill.name, context.arguments, mode)
            return CommandResult(agent_sent=True)

        mode_label = skill.mode.value
        return CommandSpec(
            name=skill.name,
            description=f"{skill.description} ({mode_label} Skill)",
            usage=f"/{skill.name} [input]",
            argument_hint="optional raw Skill input",
            command_type=CommandType.PROMPT,
            handler=run,
        )
