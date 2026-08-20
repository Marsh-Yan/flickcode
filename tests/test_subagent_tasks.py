from __future__ import annotations

import threading
import tempfile
import time
import unittest
from pathlib import Path

from flickcode.agent import AgentMode, StopReason
from flickcode.config import ProviderConfig
from flickcode.permissions.models import PermissionMode
from flickcode.providers.base import Message
from flickcode.subagents.foreground import ForegroundControl
from flickcode.subagents.models import AgentInvocationType, AgentUsage, SubAgentExecutionResult, SubAgentLaunchSpec, SubAgentTaskState
from flickcode.subagents.notifications import NotificationInbox
from flickcode.subagents.result_store import SubAgentResultStore
from flickcode.subagents.tasks import SubAgentTaskManager
from flickcode.tools import create_default_registry


def spec(task_id):
    return SubAgentLaunchSpec(
        task_id=task_id, parent_session_id="parent", invocation_type=AgentInvocationType.FORK,
        role=None, task="work", messages=(Message(role="user", content="work"),), system_prompt="prompt",
        mode=AgentMode.FULL, provider_config=ProviderConfig("p", "openai", "m", "http://x", "k"),
        tool_view=create_default_registry().snapshot(), permission_mode=PermissionMode.DEFAULT,
        max_turns=2, thinking=False, forced_background=True,
    )


class SubAgentTaskManagerTests(unittest.TestCase):
    def setUp(self):
        Path(".tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=".tmp")
        self.inbox = NotificationInbox()
        self.store = SubAgentResultStore(16, 200, Path(self.temp.name))
        self.foreground = ForegroundControl()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_background_completion_result_and_notification(self):
        def runner(_spec, _token):
            return SubAgentExecutionResult(SubAgentTaskState.COMPLETED, "a complete result larger than inline", "done", AgentUsage(input_tokens=3), StopReason.COMPLETED)
        manager = SubAgentTaskManager(runner, self.inbox, self.store, self.foreground, max_workers=1, max_pending=1)
        task_id = manager.new_task_id()
        manager.submit(spec(task_id), True)
        deadline = time.monotonic() + 2
        while manager.status(task_id).state not in {SubAgentTaskState.COMPLETED, SubAgentTaskState.FAILED} and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(manager.result(task_id).result, "a complete result larger than inline")
        self.assertEqual([n.task_id for n in self.inbox.drain()], [task_id])
        self.assertFalse(self.inbox.drain())
        manager.close()

    def test_foreground_manual_detach_preserves_future(self):
        release = threading.Event()
        def runner(_spec, token):
            release.wait(1)
            return SubAgentExecutionResult(SubAgentTaskState.COMPLETED, "ok", "ok", AgentUsage(), StopReason.COMPLETED)
        manager = SubAgentTaskManager(runner, self.inbox, self.store, self.foreground, foreground_timeout=2)
        task_id = manager.new_task_id()
        manager.submit(spec(task_id), False)
        timer = threading.Timer(.05, lambda: self.foreground.request_detach(task_id))
        timer.start()
        detached = manager.wait_or_detach(task_id)
        self.assertTrue(detached.background)
        self.assertIn(detached.state, {SubAgentTaskState.QUEUED, SubAgentTaskState.RUNNING})
        release.set()
        manager.close()
        timer.cancel()


if __name__ == "__main__":
    unittest.main()
