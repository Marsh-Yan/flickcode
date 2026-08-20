import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from flickcode.teams.merge import TeamGitIntegrator


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


class TeamMergeTests(unittest.TestCase):
    def test_merge_branch_success(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            git(["init", "-b", "main"], repo)
            env = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, env=env)
            subprocess.run(["git", "commit", "-m", "base"], cwd=str(repo), check=True, env=env, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "worker"], cwd=str(repo), check=True, capture_output=True)
            (repo / "worker.txt").write_text("worker\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, env=env)
            subprocess.run(["git", "commit", "-m", "worker"], cwd=str(repo), check=True, env=env, capture_output=True)
            subprocess.run(["git", "checkout", "main"], cwd=str(repo), check=True, capture_output=True)
            result = TeamGitIntegrator().merge_all(repo, ["worker"])
            self.assertTrue(result.success)
            self.assertFalse(result.rolled_back)
            self.assertTrue((repo / "worker.txt").exists())

    def test_conflict_rolls_back_target_branch(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            git(["init", "-b", "main"], repo)
            env = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
            (repo / "shared.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, env=env)
            subprocess.run(["git", "commit", "-m", "base"], cwd=str(repo), check=True, env=env, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "worker"], cwd=str(repo), check=True, capture_output=True)
            (repo / "shared.txt").write_text("worker\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, env=env)
            subprocess.run(["git", "commit", "-m", "worker"], cwd=str(repo), check=True, env=env, capture_output=True)
            subprocess.run(["git", "checkout", "main"], cwd=str(repo), check=True, capture_output=True)
            (repo / "shared.txt").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, env=env)
            subprocess.run(["git", "commit", "-m", "main"], cwd=str(repo), check=True, env=env, capture_output=True)
            result = TeamGitIntegrator().merge_all(repo, ["worker"])
            self.assertFalse(result.success)
            self.assertTrue(result.rolled_back)
            self.assertEqual((repo / "shared.txt").read_text(encoding="utf-8"), "main\n")
            self.assertEqual(git(["status", "--porcelain"], repo).stdout, "")


if __name__ == "__main__":
    unittest.main()
