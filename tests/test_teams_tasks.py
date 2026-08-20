import tempfile
import unittest
from pathlib import Path

from flickcode.teams.models import TeamTaskState
from flickcode.teams.store import TeamStore
from flickcode.teams.tasks import TaskStore


class TeamTaskTests(unittest.TestCase):
    def test_dependencies_block_until_parent_completes(self):
        with tempfile.TemporaryDirectory() as root:
            team = TeamStore(Path(root)).create("alpha", "lead")
            tasks = TaskStore(team)
            first = tasks.create_task("prepare")
            second = tasks.create_task("build", dependency_ids=[first.task_id])
            self.assertEqual(second.state, TeamTaskState.BLOCKED)
            tasks.start_task(first.task_id)
            tasks.complete_task(first.task_id, "ready")
            self.assertEqual(tasks.ready_tasks()[0].task_id, second.task_id)
            tasks.start_task(second.task_id)
            self.assertEqual(tasks.complete_task(second.task_id).state, TeamTaskState.COMPLETED)

    def test_unknown_and_cyclic_dependencies_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            team = TeamStore(Path(root)).create("alpha", "lead")
            tasks = TaskStore(team)
            with self.assertRaises(ValueError):
                tasks.create_task("bad", dependency_ids=["missing"])
            first = tasks.create_task("first")
            second = tasks.create_task("second", dependency_ids=[first.task_id])
            with self.assertRaises(ValueError):
                tasks.update_task(first.task_id, dependency_ids=[second.task_id])


if __name__ == "__main__":
    unittest.main()
