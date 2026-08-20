from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flickcode.agent import AgentMode
from flickcode.providers.base import BaseProvider, Message, StreamEvent
from flickcode.session import Session


class FakeProvider(BaseProvider):
    def stream_chat(self, messages, thinking=False, tools=None, system=None):
        yield StreamEvent("text", "child-or-parent-result")
        yield StreamEvent("done", json.dumps({"usage": {
            "input_tokens": 5,
            "output_tokens": 2,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 4,
        }}))


class SubAgentSessionIntegrationTests(unittest.TestCase):
    def setUp(self):
        Path(".tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.user = self.root / "user"
        self.project.mkdir()
        self.user.mkdir()
        self.config = self.root / "config.yaml"
        self.config.write_text(
            "providers:\n"
            "  - name: fake\n"
            "    protocol: openai\n"
            "    model: fake-model\n"
            "    base_url: http://localhost\n"
            "    api_key: fake\n"
            "context:\n"
            f"  storage_dir: {str(self.project / '.tmp' / 'context').replace(os.sep, '/')}\n",
            encoding="utf-8",
        )
        self.old_cwd = Path.cwd()
        os.chdir(self.project)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def make_session(self):
        with patch("flickcode.session.DEFAULT_CONFIG_DIR", self.user), patch("flickcode.session.create_provider", lambda config: FakeProvider(config)):
            return Session(config_path=str(self.config))

    def test_stable_tool_roles_project_storage_and_background_notification(self):
        session = self.make_session()
        try:
            full = session.skill_runtime.tool_view(AgentMode.FULL)
            plan = session.skill_runtime.tool_view(AgentMode.PLAN)
            self.assertIn("agent", full.list_tools())
            self.assertIn("agent", plan.list_tools())
            schema = session.agent_tool.spec.input_schema
            roles = self.project / ".flickcode" / "agents"
            roles.mkdir(parents=True)
            (roles / "custom.md").write_text(
                "---\nname: custom\ndescription: Custom role\ntools:\n  allow: [read_file]\n  deny: []\nmodel: inherit\nmax_turns: 2\npermission_mode: strict\n---\nCustom prompt",
                encoding="utf-8",
            )
            session.refresh_agent_roles()
            self.assertIn("custom", session.agent_role_catalog.snapshot.effective)
            self.assertEqual(schema, session.agent_tool.spec.input_schema)
            self.assertTrue(str(session.subagent_result_store.root).startswith(str(self.project / ".tmp")))

            session._capture_parent_request_snapshot(
                messages=[Message(role="user", content="prefix")], system_prompt="stable",
                tool_view=full, mode=AgentMode.FULL, iteration=1,
            )
            started = session.agent_tool.execute({
                "operation": "start", "type": "fork", "task": "branch", "background": False,
            })
            self.assertTrue(started.success, started.error)
            payload = json.loads(started.output)
            self.assertTrue(payload["forced_background"])
            task_id = payload["task_id"]
            deadline = time.monotonic() + 2
            while session.subagent_tasks.status(task_id).state.value not in {"completed", "failed"} and time.monotonic() < deadline:
                time.sleep(.01)
            status = session.subagent_tasks.status(task_id)
            self.assertEqual(status.usage.cache_creation_input_tokens, 3)
            self.assertEqual(status.usage.cache_read_input_tokens, 4)
            list(session.agent_chat("next"))
            notifications = [m.content for m in session.messages if "<agent-notification>" in m.content]
            self.assertEqual(len(notifications), 1)
            self.assertIn(task_id, notifications[0])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
