import tempfile
import unittest
from pathlib import Path

from flickcode.teams.backends import BackendSelector, MemberLaunch
from flickcode.teams.models import MemberBackendKind, TeamMemberRecord, utc_now
from flickcode.teams.pane import PaneAdapter, PaneHandle


class FakePane(PaneAdapter):
    name = "fake"

    def __init__(self, available=True):
        self.available = available
        self.events = []

    def probe(self):
        return self.available, "fake pane"

    def start(self, command, *, cwd):
        self.events.append(("start", tuple(command), Path(cwd)))
        return PaneHandle(self.name, "fake-handle", 1)

    def wake(self, handle, reason="mailbox"):
        self.events.append(("wake", handle.handle, reason))
        return True

    def stop(self, handle):
        self.events.append(("stop", handle.handle))


class TeamBackendTests(unittest.TestCase):
    def test_selector_reports_explicit_fallback_reason(self):
        selector = BackendSelector(pane_adapters={"fake": FakePane(False)})
        selected = selector.choose([MemberBackendKind.PANE, MemberBackendKind.IN_PROCESS])
        self.assertEqual(selected.backend, MemberBackendKind.IN_PROCESS)
        self.assertFalse(selected.probes[0][1])
        self.assertIn("selected in_process", selected.reason)

    def test_pane_adapter_start_wake_stop(self):
        fake = FakePane(True)
        selector = BackendSelector(pane_adapters={"fake": fake})
        member = TeamMemberRecord("member-1", "worker", "team-1", "builder", Path.cwd(), MemberBackendKind.PANE, created_at=utc_now(), updated_at=utc_now())
        handle = selector.backend(MemberBackendKind.PANE).start(member, MemberLaunch(("worker",), Path.cwd()))
        self.assertTrue(selector.backend(MemberBackendKind.PANE).wake(handle))
        selector.backend(MemberBackendKind.PANE).stop(handle)
        self.assertEqual([item[0] for item in fake.events], ["start", "wake", "stop"])


if __name__ == "__main__":
    unittest.main()
