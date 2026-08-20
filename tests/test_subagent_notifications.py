from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flickcode.subagents.result_store import SubAgentResultStore


class SubAgentResultStoreTests(unittest.TestCase):
    def setUp(self):
        Path(".tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=".tmp")

    def tearDown(self):
        self.temp.cleanup()

    def test_externalize_truncate_reject_path_and_cleanup(self):
        store = SubAgentResultStore(4, 10, Path(self.temp.name))
        root = store.root
        inline, path, truncated = store.store("agent-000000000001", "0123456789ABC")
        self.assertEqual(inline, "")
        self.assertTrue(truncated)
        self.assertIn("[truncated", store.read(path))
        with self.assertRaisesRegex(ValueError, "task id"):
            store.store("../escape", "bad")
        store.close()
        self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
