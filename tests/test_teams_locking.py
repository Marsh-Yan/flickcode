import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from flickcode.teams.locking import FileLock, LockTimeoutError


class TeamLockingTests(unittest.TestCase):
    def test_exclusive_lock_and_timeout(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "lock"
            first = FileLock(path, retry_seconds=0.05, stale_seconds=60)
            first.acquire()
            try:
                with self.assertRaises(LockTimeoutError):
                    FileLock(path, retry_seconds=0.03, stale_seconds=60).acquire()
            finally:
                first.release()
            second = FileLock(path, retry_seconds=0.05, stale_seconds=60).acquire()
            second.release()
            self.assertFalse(path.exists())

    def test_stale_lock_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "lock"
            path.write_text(json.dumps({"token": "old"}), encoding="utf-8")
            old = time.time() - 10
            os.utime(path, (old, old))
            lock = FileLock(path, retry_seconds=0.1, stale_seconds=0.01).acquire()
            lock.release()
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
