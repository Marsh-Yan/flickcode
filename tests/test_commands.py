"""Unit tests for the framework-neutral slash command core."""

from __future__ import annotations

import unittest

from flickcode.agent import AgentMode
from flickcode.commands import (
    CommandParser,
    CommandRegistrationError,
    CommandRegistry,
    CommandResult,
    CommandSpec,
    CommandType,
    InMemoryCommandUI,
    InputRouter,
    InteractionMode,
)


def handler(result=None):
    def _run(context):
        context.ui.show_message(f"ran {context.spec.name}:{context.arguments}")
        return result or CommandResult()

    return _run


def spec(name="status", *, aliases=(), hidden=False, command_type=CommandType.LOCAL, run=None):
    return CommandSpec(
        name=name,
        aliases=aliases,
        description=f"Show {name}",
        usage=f"/{name}",
        command_type=command_type,
        hidden=hidden,
        handler=run or handler(),
    )


class ModelTests(unittest.TestCase):
    def test_command_spec_rejects_invalid_words_and_metadata(self):
        with self.assertRaises(ValueError):
            spec("bad name")
        with self.assertRaises(ValueError):
            spec("/bad")
        with self.assertRaises(ValueError):
            CommandSpec(
                name="bad",
                description="",
                usage="/bad",
                handler=handler(),
            )

    def test_interaction_mode_labels(self):
        self.assertEqual(InteractionMode.DEFAULT.label, "[DEFAULT]")
        self.assertEqual(InteractionMode.PLAN.label, "[PLAN]")


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = CommandParser()

    def test_empty_and_normal_text_are_not_commands(self):
        self.assertIsNone(self.parser.parse(""))
        self.assertIsNone(self.parser.parse("  \n"))
        self.assertIsNone(self.parser.parse("hello /status"))

    def test_command_name_is_case_insensitive_and_arguments_preserve_internal_space(self):
        parsed = self.parser.parse("  /STATUS arg  text  ")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.name, "status")
        self.assertEqual(parsed.arguments, "arg  text")
        self.assertTrue(parsed.is_command)

    def test_multiline_arguments_are_preserved(self):
        parsed = self.parser.parse("/review first line\nsecond line")
        self.assertEqual(parsed.name, "review")
        self.assertEqual(parsed.arguments, "first line\nsecond line")

    def test_missing_command_name_is_an_error(self):
        parsed = self.parser.parse("/   ")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.name, "")
        self.assertIsNotNone(parsed.error)


class RegistryTests(unittest.TestCase):
    def test_register_resolve_alias_and_case(self):
        registry = CommandRegistry()
        command = spec("status", aliases=("st",))
        registry.register(command)
        registry.validate()
        self.assertIs(registry.resolve("status"), command)
        self.assertIs(registry.resolve("/STATUS"), command)
        self.assertIs(registry.resolve("ST"), command)

    def test_all_help_and_completion_filter_hidden_commands(self):
        registry = CommandRegistry()
        registry.register(spec("status", aliases=("st",)))
        registry.register(spec("secret", hidden=True))
        self.assertEqual([item.name for item in registry.all()], ["status"])
        self.assertIn("/status", registry.help_for())
        self.assertNotIn("/secret", registry.help_for())
        self.assertEqual(registry.completions("st"), ("/status",))
        self.assertEqual(registry.completions("se"), ())
        self.assertIn("/status", registry.help_for("ST"))

    def test_collisions_fail_during_registration(self):
        registry = CommandRegistry()
        registry.register(spec("status", aliases=("st",)))
        with self.assertRaises(CommandRegistrationError):
            registry.register(spec("STATUS"))
        with self.assertRaises(CommandRegistrationError):
            registry.register(spec("other", aliases=("ST",)))
        with self.assertRaises(CommandRegistrationError):
            registry.register(spec("local", aliases=("LOCAL",)))


class UIProtocolTests(unittest.TestCase):
    def test_in_memory_ui_records_required_operations(self):
        ui = InMemoryCommandUI()
        ui.show_message("message")
        ui.show_progress("progress")
        ui.show_error("error")
        ui.set_mode(InteractionMode.PLAN)
        ui.send_user_message("task", AgentMode.PLAN)
        ui.refresh_status()
        ui.clear_display()
        self.assertEqual(ui.mode, InteractionMode.PLAN)
        self.assertEqual(ui.sent_messages, [("task", AgentMode.PLAN)])
        self.assertEqual(ui.refresh_count, 1)
        self.assertEqual(ui.clear_count, 1)


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.registry = CommandRegistry()
        self.called = []

        def run(context):
            self.called.append((context.spec.name, context.arguments))
            return CommandResult()

        self.registry.register(spec("status", run=run))
        self.router = InputRouter(self.registry)
        self.ui = InMemoryCommandUI()
        self.session = object()

    def test_local_command_is_dispatched_without_agent(self):
        result = self.router.handle("/STATUS arg", session=self.session, ui=self.ui)
        self.assertTrue(result.handled)
        self.assertEqual(self.called, [("status", "arg")])
        self.assertEqual(self.ui.sent_messages, [])

    def test_unknown_slash_input_does_not_fall_back_to_agent(self):
        result = self.router.handle("/missing text", session=self.session, ui=self.ui)
        self.assertTrue(result.handled)
        self.assertTrue(self.ui.errors)
        self.assertIn("/help", self.ui.errors[-1])
        self.assertEqual(self.ui.sent_messages, [])

    def test_normal_text_uses_current_interaction_mode(self):
        self.router.handle("  hello  ", session=self.session, ui=self.ui)
        self.assertEqual(self.ui.sent_messages, [("  hello  ", AgentMode.FULL)])
        self.ui.set_mode(InteractionMode.PLAN)
        self.router.handle("continue", session=self.session, ui=self.ui)
        self.assertEqual(self.ui.sent_messages[-1], ("continue", AgentMode.PLAN))

    def test_empty_text_is_ignored(self):
        result = self.router.handle(" \n ", session=self.session, ui=self.ui)
        self.assertFalse(result.handled)
        self.assertEqual(self.called, [])
        self.assertEqual(self.ui.sent_messages, [])

    def test_handler_errors_are_user_errors_and_do_not_escape(self):
        def broken(context):
            raise RuntimeError("broken")

        registry = CommandRegistry()
        registry.register(spec("broken", run=broken))
        router = InputRouter(registry)
        result = router.handle("/broken", session=self.session, ui=self.ui)
        self.assertIsNotNone(result.error)
        self.assertIn("broken", self.ui.errors[-1])

    def test_mode_change_refreshes_status(self):
        def switch(context):
            context.ui.set_mode(InteractionMode.PLAN)
            return CommandResult(mode_changed=True)

        registry = CommandRegistry()
        registry.register(spec("plan", command_type=CommandType.UI_STATE, run=switch))
        router = InputRouter(registry)
        router.handle("/plan", session=self.session, ui=self.ui)
        self.assertEqual(self.ui.mode, InteractionMode.PLAN)
        self.assertEqual(self.ui.refresh_count, 1)


if __name__ == "__main__":
    unittest.main()
