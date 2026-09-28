import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mensarium.client.config import ClientConfig
from mensarium.client.projects import ProjectHost
from mensarium.client.tools import Executor
from mensarium.contracts.projects import ProjectOp


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class ProjectBranchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = base / "work" / "demo"
        self.repo.mkdir(parents=True)
        home = patch.dict(os.environ, {"MENSARIUM_HOME": str(base / "home")})
        home.start()
        self.addCleanup(home.stop)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("print('hi')\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        git(self.repo, "checkout", "-qb", "feature/login")
        (self.repo / "app.py").write_text("print('login')\n")
        git(self.repo, "commit", "-qam", "login")
        cfg = ClientConfig(server="http://localhost", ws_url="ws://localhost", target_id="device", workspace_id="workspace",
                           name="test", core_public_key="", core_fingerprint="test", roots=[str(base / "work")], command_allowlist=[])
        self.host = ProjectHost(Executor(cfg))
        self.args = {"source_path": str(self.repo), "kind": "repo"}

    async def op(self, name: str, task_id: str = "", **args: object) -> dict:
        req = ProjectOp(request_id="r", target_id="device", project_id="prj_1", task_id=task_id, op=name,
                        args={**self.args, **args}, issued_at="", expires_at="", nonce="")
        status = await self.host.op(req)
        return status.model_dump()

    async def test_branches_list_main_and_current(self) -> None:
        status = await self.op("branches")
        self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual({b["name"] for b in status["data"]["branches"]}, {"main", "feature/login"})
        self.assertEqual(status["data"]["default"], "main")
        self.assertEqual(status["data"]["current"], "feature/login")

    async def test_checkout_starts_from_main_a_branch_or_under_a_new_name(self) -> None:
        main, feature = git(self.repo, "rev-parse", "main"), git(self.repo, "rev-parse", "feature/login")
        cases = [("task_a", "mensarium/a-1", "default", main, "main"), ("task_b", "mensarium/b-1", "feature/login", feature, "feature/login"),
                 ("task_c", "feat-x", "default", main, "main")]
        for task_id, branch, start, sha, base in cases:
            with self.subTest(branch=branch):
                status = await self.op("checkout", task_id, branch=branch, start=start)
                self.assertEqual(status["state"], "ok", status["detail"])
                self.assertEqual((status["head_sha"], status["data"]["base"]), (sha, base))
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"), "feature/login")
        self.assertIn("feat-x", git(self.repo, "branch", "--list", "feat-x"))

    async def test_checkout_refuses_bad_names_and_missing_bases(self) -> None:
        for branch, start in (("bad..name", "default"), ("-x", "default"), ("mensarium/c-1", "nope")):
            with self.subTest(branch=branch, start=start):
                status = await self.op("checkout", "task_x", branch=branch, start=start)
                self.assertEqual(status["state"], "error")


if __name__ == "__main__":
    unittest.main()
