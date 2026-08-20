from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from flickcode.agent import AgentMode
from flickcode.hooks import HookCatalog, HookEngine, HookEventName
from flickcode.subagents.hooks import SubAgentHookScope
from flickcode.subagents.models import AgentInvocationType


class SubAgentHookScopeTests(unittest.TestCase):
    def test_prompt_and_identity_state_are_task_local(self):
        Path(".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=".tmp") as raw:
            root = Path(raw)
            project, user = root / "project", root / "user"
            project.mkdir()
            user.mkdir()
            (user / "hooks.yaml").write_text(
                "hooks:\n  - event: message.model_request\n    action: {type: prompt, content: child}\n",
                encoding="utf-8",
            )
            parent = HookEngine(HookCatalog(project, user), project)
            parent.start()
            parent.begin_session("parent")
            spec = SimpleNamespace(
                task_id="agent-000000000001", parent_session_id="parent", mode=AgentMode.FULL,
                invocation_type=AgentInvocationType.FORK, role=None, forced_background=True,
            )
            scope = SubAgentHookScope(parent, spec)
            event = scope.make_event(HookEventName.MESSAGE_MODEL_REQUEST)
            scope.dispatch(event)
            self.assertEqual(scope.consume_request_prompts(), ("child",))
            self.assertEqual(parent.consume_request_prompts(), ())
            self.assertEqual(event.context["agent"]["task_id"], spec.task_id)
            self.assertEqual(event.context["agent"]["kind"], "subagent")
            scope.close_scope()
            parent.close()


if __name__ == "__main__":
    unittest.main()
