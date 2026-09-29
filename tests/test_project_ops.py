import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mensarium.agent_core.context import build_system_prompt
from mensarium.agent_core.profile import builtin_profiles
from mensarium.client.config import ClientConfig
from mensarium.client.projects import ProjectHost
from mensarium.client.tools import Executor, ToolError
from mensarium.contracts.projects import ProjectOp
from mensarium.contracts.protocol import TargetPolicy


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
        self.sent: list[dict] = []

    async def send(self, msg: dict) -> None:
        self.sent.append(msg)

    async def op(self, name: str, task_id: str = "", **args: object) -> dict:
        req = ProjectOp(request_id="r", target_id="device", project_id="prj_1", task_id=task_id, op=name,
                        args={**self.args, **args}, issued_at="", expires_at="", nonce="")
        status = await self.host.op(req, send=self.send)
        return status.model_dump()

    async def snapshot(self, known: dict[str, str] | None = None, bundle: bool = True) -> dict:
        from mensarium.contracts.projects import ProjectSnapshot
        req = ProjectSnapshot(request_id="s", target_id="device", project_id="prj_1", source_path=str(self.repo), kind="repo",
                              known=known or {}, bundle=bundle, issued_at="", expires_at="", nonce="")
        return (await self.host.snapshot(req, send=self.send)).model_dump()

    def bundle_heads(self, request_id: str) -> str:
        import base64
        path = Path(self.tmp.name) / "up.bundle"
        path.write_bytes(b"".join(base64.b64decode(m["data"]) for m in self.sent if m["request_id"] == request_id))
        return git(self.repo, "bundle", "list-heads", str(path))

    async def test_snapshot_ships_only_moved_refs_and_reports_main(self) -> None:
        self.assertIsNone((await self.snapshot(bundle=False))["bundle"])
        self.assertEqual(self.sent, [])
        first = await self.snapshot()
        self.assertEqual(first["state"], "ok", first["detail"])
        self.assertEqual(first["main"], "main")
        self.assertEqual(set(first["bundle"]["refs"]), {"refs/heads/main", "refs/heads/feature/login", "refs/mensarium/snapshot"})
        self.assertIn("refs/mensarium/snapshot", self.bundle_heads("s"))
        self.sent.clear()
        (self.repo / "app.py").write_text("print('again')\n")
        git(self.repo, "commit", "-qam", "again")
        second = await self.snapshot(known=first["refs"])
        self.assertEqual(second["state"], "ok", second["detail"])
        self.assertEqual(set(second["bundle"]["refs"]), {"refs/heads/feature/login", "refs/mensarium/snapshot"})
        self.assertEqual(second["bundle"]["prerequisites"], sorted({first["refs"]["refs/heads/feature/login"]}))
        self.assertEqual((await self.snapshot(known=second["refs"]))["state"], "unchanged")

    async def test_snapshot_bundle_falls_back_to_full_when_known_is_gone(self) -> None:
        first = await self.snapshot()
        gone = dict.fromkeys(first["refs"], "0" * 40)
        self.sent.clear()
        (self.repo / "app.py").write_text("print('rewritten')\n")
        git(self.repo, "commit", "-qam", "rewritten")
        status = await self.snapshot(known=gone)
        self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual(status["bundle"]["prerequisites"], [])

    async def test_commit_ships_the_branch_once_per_head(self) -> None:
        status = await self.op("checkout", "task_c", branch="mensarium/c-1", start="default")
        base = status["head_sha"]
        self.assertIsNone((await self.op("commit", "task_c", message="turn", base_sha=base, branch="mensarium/c-1", known_head=None))["bundle"])
        wt = Path(os.environ["MENSARIUM_HOME"]) / "projects" / "prj_1" / "wt" / "task_c"
        (wt / "app.py").write_text("changed\n")
        self.sent.clear()
        status = await self.op("commit", "task_c", message="turn", base_sha=base, branch="mensarium/c-1", known_head=None)
        self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual(status["bundle"]["refs"], {"refs/heads/mensarium/c-1": status["head_sha"]})
        self.assertIn("refs/heads/mensarium/c-1", self.bundle_heads("r"))
        again = await self.op("commit", "task_c", message="turn", base_sha=base, branch="mensarium/c-1", known_head=status["head_sha"])
        self.assertIsNone(again["bundle"])

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
        status = await self.op("commit", "task_r", message="turn", base_sha=base)
        self.assertEqual(status["data"]["stat"], {"files": 2, "added": 2, "deleted": 1})
        (wt / "app.py").unlink()
        for path in ("app.py", "new.txt"):
            status = await self.op("revert", "task_r", base_sha=base, path=path)
            self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual((wt / "app.py").read_text(), "print('hi')\n")
        self.assertFalse((wt / "new.txt").exists())
        self.assertEqual((await self.op("diff", "task_r", base_sha=base))["data"]["files"], [])
        self.assertEqual((await self.op("revert", "task_r", base_sha=base, path=".env"))["state"], "error")

    async def fetch_into(self, role: str, refs: dict[str, str], bundle_refs: list[str], request_id: str = "f1") -> dict:
        from mensarium.shared import bundles
        path = Path(self.tmp.name) / "down.bundle"
        git(self.repo, "bundle", "create", str(path), *bundle_refs)
        for part in bundles.chunks(path):
            self.host.receive_chunk({"type": "project.bundle", "request_id": request_id, "project_id": "prj_1", "seq": 0, "data": part})
        info = bundles.describe(path, {r: git(self.repo, "rev-parse", r) for r in bundle_refs}, [])
        req = ProjectOp(request_id=request_id, target_id="device", project_id="prj_1", task_id="", op="fetch",
                        args={"role": role, "bundle": info.model_dump(), "refs": refs, **({} if role == "executor" else self.args)}, issued_at="", expires_at="", nonce="")
        return (await self.host.op(req, send=self.send)).model_dump()

    async def test_executor_fetches_into_repo_git_and_checks_out_from_a_sha(self) -> None:
        main = git(self.repo, "rev-parse", "main")
        status = await self.fetch_into("executor", {"refs/heads/main": "refs/devices/tgt_src/heads/main"}, ["refs/heads/main"])
        self.assertEqual(status["state"], "ok", status["detail"])
        bare = Path(os.environ["MENSARIUM_HOME"]) / "projects" / "prj_1" / "repo.git"
        self.assertEqual(git(bare, "rev-parse", "refs/devices/tgt_src/heads/main"), main)
        status = await self.op("checkout", "task_e", role="executor", branch="mensarium/e-1", start=main, base_name="main")
        self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual((status["head_sha"], status["data"]["base"]), (main, "main"))
        wt = Path(os.environ["MENSARIUM_HOME"]) / "projects" / "prj_1" / "wt" / "task_e"
        self.assertEqual((wt / "app.py").read_text(), "print('hi')\n")
        self.assertEqual((await self.op("checkout", "task_x", role="executor", branch="mensarium/x-1", start="0" * 40))["state"], "error")
        status = await self.op("remove", "task_e", role="executor", branch="mensarium/e-1", delete_branch=True)
        self.assertEqual(status["state"], "ok", status["detail"])
        self.assertFalse(wt.exists())
        status = await self.op("remove", "", role="executor", delete_repo=True)
        self.assertFalse(bare.exists())

    async def test_fetch_into_the_source_takes_a_free_branch_and_refuses_a_checked_out_one(self) -> None:
        main = git(self.repo, "rev-parse", "main")
        status = await self.fetch_into("source", {"refs/heads/main": "refs/heads/mensarium/d-1"}, ["refs/heads/main"], request_id="f0")
        self.assertEqual(status["state"], "ok", status["detail"])
        self.assertEqual(git(self.repo, "rev-parse", "refs/heads/mensarium/d-1"), main)
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"), "feature/login")
        await self.op("checkout", "task_s", branch="mensarium/s-1", start="default")
        status = await self.fetch_into("source", {"refs/heads/mensarium/s-1": "refs/heads/mensarium/s-1"}, ["refs/heads/main"], request_id="f2")
        self.assertEqual(status["state"], "error")
        self.assertIn("checked out", status["detail"])
        status = await self.fetch_into("source", {"refs/heads/main": "refs/heads/main"}, ["refs/heads/main"], request_id="f3")
        self.assertEqual(status["state"], "error")

    def test_workdir_may_be_a_project_folder_inside_the_roots(self) -> None:
        executor = self.host.executor
        self.assertEqual(executor.workdir(str(self.repo)), self.repo.resolve())
        with self.assertRaises(ToolError):
            executor.workdir(tempfile.gettempdir())

    def test_prompt_tells_an_inplace_chat_it_works_in_the_users_checkout(self) -> None:
        project = {"name": "demo", "kind": "repo", "source": "mac:/w/demo", "workdir": "/w/demo", "branch": "", "base": "", "instructions": "", "inplace": True}
        prompt = build_system_prompt(builtin_profiles()[0], "mac", "macos", TargetPolicy(roots=["/w"], command_allowlist=[]), [], project=project)
        self.assertIn("you work right in the user's own checkout", prompt)
        self.assertNotIn("your worktree", prompt)

    def test_prompt_names_the_executor_and_warns_about_a_remote_snapshot(self) -> None:
        project = {"name": "demo", "kind": "repo", "source": "mac:/w/demo", "workdir": "/p/wt/t", "branch": "mensarium/x-1", "base": "snapshot@abc", "instructions": "",
                   "inplace": False, "executor": "server", "remote": True, "snapshot_at": "2026-09-29T10:00:00Z"}
        prompt = build_system_prompt(builtin_profiles()[0], "server", "linux", TargetPolicy(roots=["/p"], command_allowlist=[]), [], project=project)
        self.assertIn("- runs on: server", prompt)
        self.assertIn("snapshot taken 2026-09-29T10:00:00Z", prompt)
        folder = build_system_prompt(builtin_profiles()[0], "server", "linux", TargetPolicy(roots=["/p"], command_allowlist=[]), [], project={**project, "kind": "folder", "snapshot_at": ""})
        self.assertIn("device snapshot. Changes", folder)
        self.assertIn("your changes reach the device", folder)
        self.assertNotIn("snapshot taken", build_system_prompt(builtin_profiles()[0], "mac", "macos", TargetPolicy(roots=["/p"], command_allowlist=[]), [], project={**project, "remote": False}))


class ContractHelperTests(unittest.TestCase):
    def test_refs_map_between_device_and_mirror_names(self) -> None:
        from mensarium.contracts.projects import device_ref, mirror_ref
        cases = {"refs/heads/main": "refs/devices/tgt_1/heads/main", "refs/remotes/origin/main": "refs/devices/tgt_1/remotes/origin/main",
                 "refs/mensarium/snapshot": "refs/devices/tgt_1/snapshot", "refs/heads/mensarium/x-1": "refs/heads/mensarium/x-1"}
        for dev, mir in cases.items():
            self.assertEqual(mirror_ref("tgt_1", dev), mir)
            self.assertEqual(device_ref("tgt_1", mir), dev)
        self.assertIsNone(mirror_ref("tgt_1", "refs/tags/v1"))
        self.assertIsNone(device_ref("tgt_1", "refs/devices/tgt_2/heads/main"))

    def test_bundle_chunks_round_trip_and_limit(self) -> None:
        from mensarium.shared import bundles
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "a.bundle", Path(tmp) / "inbox" / "b.bundle"
            src.write_bytes(os.urandom(bundles.CHUNK + 10))
            for part in bundles.chunks(src):
                bundles.append_chunk(dst, part)
            self.assertEqual(dst.read_bytes(), src.read_bytes())
            info = bundles.describe(src, {"refs/heads/x": "abc"}, ["def"])
            self.assertEqual((info.size, info.refs, info.prerequisites), (bundles.CHUNK + 10, {"refs/heads/x": "abc"}, ["def"]))
            bundles.check(dst, info)
            with self.assertRaises(ValueError):
                bundles.check(dst, info.model_copy(update={"size": 1}))


if __name__ == "__main__":
    unittest.main()
