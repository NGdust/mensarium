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
class ProjectOpsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_diff_lists_uncommitted_changes_without_secrets(self) -> None:
        status = await self.op("checkout", "task_d", branch="mensarium/d-1", start="default")
        base = status["head_sha"]
        wt = Path(os.environ["MENSARIUM_HOME"]) / "projects" / "prj_1" / "wt" / "task_d"
        (wt / "app.py").write_text("print('hi')\nprint('more')\n")
        (wt / "notes.txt").write_text("a\nb\n")
        (wt / ".env").write_text("API_KEY=test-fixture-only\n")
        status = await self.op("diff", "task_d", base_sha=base)
        self.assertEqual(status["state"], "ok", status["detail"])
        files = {f["path"]: (f["status"], f["added"], f["deleted"]) for f in status["data"]["files"]}
        self.assertEqual(files, {"app.py": ("M", 1, 0), "notes.txt": ("A", 2, 0)})
        patch = (await self.op("diff", "task_d", base_sha=base, path="app.py"))["data"]["patch"]
        self.assertIn("+print('more')", patch)
        self.assertEqual(git(wt, "diff", "--cached", "--name-only"), "")

    async def test_docs_reads_instruction_files_but_not_links(self) -> None:
        (self.repo / "AGENTS.md").write_text("Run make test.\n")
        (self.repo / "CLAUDE.md").symlink_to(self.repo / "app.py")
        status = await self.op("docs")
        self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual([(f["name"], f["text"]) for f in status["data"]["files"]], [("AGENTS.md", "Run make test.\n")])

    async def test_revert_restores_changed_deleted_and_drops_added_files(self) -> None:
        status = await self.op("checkout", "task_r", branch="mensarium/r-1", start="default")
        base = status["head_sha"]
        wt = Path(os.environ["MENSARIUM_HOME"]) / "projects" / "prj_1" / "wt" / "task_r"
        (wt / "app.py").write_text("changed\n")
        (wt / "new.txt").write_text("new\n")
        await self.op("commit", "task_r", message="turn", base_sha=base)
        (wt / "app.py").unlink()
        for path in ("app.py", "new.txt"):
            status = await self.op("revert", "task_r", base_sha=base, path=path)
            self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual((wt / "app.py").read_text(), "print('hi')\n")
        self.assertFalse((wt / "new.txt").exists())
        self.assertEqual((await self.op("diff", "task_r", base_sha=base))["data"]["files"], [])
        self.assertEqual((await self.op("revert", "task_r", base_sha=base, path=".env"))["state"], "error")


if __name__ == "__main__":
    unittest.main()
