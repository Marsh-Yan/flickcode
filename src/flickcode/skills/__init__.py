"""Reusable Markdown-defined AI skills with cycle-safe lazy exports."""

from flickcode.skills.models import (
    ActiveSkill,
    ActivationResult,
    ArchivedSkillActivation,
    ChildSessionMetadata,
    SkillCatalogCandidate,
    SkillCatalogSnapshot,
    SkillDefinition,
    SkillDiagnostic,
    SkillExecutionResult,
    SkillInvocation,
    SkillInvocationOrigin,
    SkillMode,
    SkillRuntimeCandidate,
    SkillRuntimeSnapshot,
    SkillSource,
    SkillToolDefinition,
)

_LAZY_EXPORTS = {
    "SkillCatalog": ("flickcode.skills.catalog", "SkillCatalog"),
    "SkillParseError": ("flickcode.skills.parser", "SkillParseError"),
    "SkillParser": ("flickcode.skills.parser", "SkillParser"),
    "SkillStartupError": ("flickcode.skills.validation", "SkillStartupError"),
    "SkillValidator": ("flickcode.skills.validation", "SkillValidator"),
    "SkillRuntime": ("flickcode.skills.runtime", "SkillRuntime"),
    "SkillScriptTool": ("flickcode.skills.script_tool", "SkillScriptTool"),
    "SkillExecutionError": ("flickcode.skills.executor", "SkillExecutionError"),
    "SkillExecutor": ("flickcode.skills.executor", "SkillExecutor"),
    "CompleteTurnSelector": ("flickcode.skills.history", "CompleteTurnSelector"),
    "LoadSkillTool": ("flickcode.skills.load_tool", "LoadSkillTool"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = [
    "ActiveSkill",
    "ActivationResult",
    "ArchivedSkillActivation",
    "ChildSessionMetadata",
    "SkillCatalogCandidate",
    "SkillCatalogSnapshot",
    "SkillDefinition",
    "SkillDiagnostic",
    "SkillExecutionResult",
    "SkillInvocation",
    "SkillInvocationOrigin",
    "SkillMode",
    "SkillRuntimeCandidate",
    "SkillRuntimeSnapshot",
    "SkillSource",
    "SkillToolDefinition",
    *_LAZY_EXPORTS,
]
