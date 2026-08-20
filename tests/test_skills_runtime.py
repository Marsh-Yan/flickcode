from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flickcode.agent import AgentMode
from flickcode.prompt import ActiveSkillsSection, SkillCatalogSection, SystemPromptBuilder
from flickcode.skills import SkillCatalog, SkillRuntime
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.registry import ToolRegistry


class NamedTool(BaseTool):
    def __init__(self, name: str) -> None:
        self.spec = ToolSpec(name=name, description=f"Tool {name}", input_schema={"type": "object", "properties": {}})

    def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, output=self.spec.name)


def registry(*names: str) -> ToolRegistry:
    result = ToolRegistry()
    for name in names:
        result.register_instance(NamedTool(name))
    return result


def write_skill(root: Path, name: str, tools: list[str], body: str = "Handle {{input}}") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.md"
    tool_yaml = "\n".join(f"  - {tool}" for tool in tools)
    path.write_text(
        f"---\nname: {name}\ndescription: {name} description\ntools:\n{tool_yaml}\nmode: shared\n---\n{body}",
        encoding="utf-8",
    )
    return path


class ToolRegistryViewTests(unittest.TestCase):
    def test_snapshot_is_filtered_stable_and_schema_is_defensive(self) -> None:
        tools = registry("zeta", "alpha")
        view = tools.snapshot({"zeta", "alpha"})
        self.assertEqual(view.list_tools(), ["alpha", "zeta"])
        anthropic = view.to_api_tools("anthropic")
        anthropic[0]["input_schema"]["properties"]["mutated"] = {"type": "string"}
        self.assertNotIn("mutated", view.to_api_tools("anthropic")[0]["input_schema"]["properties"])
        self.assertEqual(view.to_api_tools("openai")[0]["function"]["name"], "alpha")
        self.assertFalse(hasattr(view, "register_instance"))

    def test_snapshot_rejects_missing_and_extra_conflicts(self) -> None:
        tools = registry("alpha")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            tools.snapshot({"missing"})
        with self.assertRaisesRegex(ValueError, "conflicts"):
            tools.snapshot(set(), (NamedTool("alpha"),))
        with self.assertRaisesRegex(ValueError, "Duplicate extra"):
            tools.snapshot(set(), (NamedTool("extra"), NamedTool("extra")))


class SkillRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.project = base / "project"
        self.catalog = SkillCatalog(self.project, base / "user", base / "builtin")
        self.tools = registry("read_file", "write_file", "execute_command", "load_skill")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def runtime(self) -> SkillRuntime:
        return SkillRuntime(self.catalog.snapshot, self.tools, self.project.parent)

    def test_initial_state_uses_default_tools_and_catalog_only_prompt(self) -> None:
        write_skill(self.project, "inspect", ["read_file"])
        self.catalog.refresh()
        runtime = self.runtime()
        self.assertEqual(set(runtime.tool_view().list_tools()), set(self.tools.list_tools()))
        context = runtime.prompt_context()
        self.assertEqual(context["active_skills"], ())
        self.assertEqual(context["skill_catalog"][0]["name"], "inspect")

    def test_shared_activation_unions_whitelists_and_rebinding_keeps_order(self) -> None:
        write_skill(self.project, "inspect", ["read_file"], "Inspect {{input}}")
        write_skill(self.project, "change", ["write_file"], "Change {{input}}")
        self.catalog.refresh()
        runtime = self.runtime()
        first = runtime.activate_shared("inspect", "one")
        second = runtime.activate_shared("change", "two")
        rebound = runtime.activate_shared("inspect", "three")
        self.assertTrue(first.success and second.success and rebound.success)
        self.assertTrue(rebound.rebound)
        self.assertEqual([item.definition.name for item in runtime.snapshot.active_skills], ["inspect", "change"])
        self.assertEqual(runtime.snapshot.active_skills[0].rendered_instructions, "Inspect three")
        self.assertEqual(set(runtime.tool_view().list_tools()), {"read_file", "write_file", "load_skill"})
        self.assertEqual(set(runtime.tool_view(AgentMode.PLAN).list_tools()), {"read_file", "load_skill"})

    def test_invalid_active_edit_retains_last_valid_snapshot(self) -> None:
        path = write_skill(self.project, "inspect", ["read_file"], "Old {{input}}")
        self.catalog.refresh()
        runtime = self.runtime()
        runtime.activate_shared("inspect", "value")
        path.write_text("---\nname: inspect\ndescription: Broken\ntools: nope\nmode: shared\n---\nBody", encoding="utf-8")
        candidate = self.catalog.prepare_refresh()
        prepared = runtime.prepare_reconcile(candidate)
        self.assertEqual(prepared.active_skills[0].rendered_instructions, "Old value")
        self.catalog.commit(candidate)
        runtime.commit(prepared)
        self.assertTrue(any("last valid snapshot" in item.message for item in runtime.snapshot.diagnostics))

    def test_deleted_active_skill_is_deactivated(self) -> None:
        path = write_skill(self.project, "inspect", ["read_file"])
        self.catalog.refresh()
        runtime = self.runtime()
        runtime.activate_shared("inspect")
        path.unlink()
        candidate = self.catalog.prepare_refresh()
        prepared = runtime.prepare_reconcile(candidate)
        self.assertEqual(prepared.active_skills, ())
        self.assertEqual(prepared.allowed_tool_names, frozenset(self.tools.list_tools()))

    def test_invalid_active_override_does_not_rebind_to_lower_fallback(self) -> None:
        builtin = self.catalog._roots[next(source for source in self.catalog._roots if source.value == "builtin")]
        write_skill(builtin, "inspect", ["write_file"], "Builtin {{input}}")
        path = write_skill(self.project, "inspect", ["read_file"], "Project {{input}}")
        self.catalog.refresh()
        runtime = self.runtime()
        runtime.activate_shared("inspect", "value")
        path.write_text(
            "---\nname: inspect\ndescription: Broken\ntools: nope\nmode: shared\n---\nBody",
            encoding="utf-8",
        )
        candidate = self.catalog.prepare_refresh()
        self.assertEqual(candidate.current.effective["inspect"].source.value, "builtin")
        prepared = runtime.prepare_reconcile(candidate)
        self.assertEqual(prepared.active_skills[0].rendered_instructions, "Project value")
        self.assertEqual(prepared.allowed_tool_names, frozenset({"read_file", "load_skill"}))

    def test_prompt_sections_keep_catalog_shallow_and_active_sop_pinned(self) -> None:
        write_skill(self.project, "inspect", ["read_file"], "SECRET SOP {{input}}")
        self.catalog.refresh()
        runtime = self.runtime()
        builder = SystemPromptBuilder()
        builder.add_section(ActiveSkillsSection())
        builder.add_section(SkillCatalogSection())
        shallow, _ = builder.build(runtime.prompt_context())
        self.assertIn("inspect description", shallow)
        self.assertNotIn("SECRET SOP", shallow)
        runtime.activate_shared("inspect", "request")
        full, _ = builder.build(runtime.prompt_context())
        self.assertLess(full.index("SECRET SOP request"), full.index("Available Skills"))


if __name__ == "__main__":
    unittest.main()
