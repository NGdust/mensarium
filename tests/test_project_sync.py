import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium.contracts.projects import ProjectError, ProjectOp, ProjectOpStatus, ProjectSnapshot
from mensarium.contracts.protocol import Capabilities, TargetHello, TargetInfo, TargetPolicy
from mensarium.agent_core.profile import builtin_profiles
from mensarium.core.client_hub import ClientConnection, ClientHub
from mensarium.core.db import Database
from mensarium.core.orchestrator import Orchestrator, TaskError
from mensarium.core.projects import ProjectManager
from mensarium.core.repo import Repo
from mensarium.shared import bundles


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


class FakeHub:
    def __init__(self, repo_path: Path, inbox: Path) -> None:
        self.repo_path, self.inbox = repo_path, inbox
        self.online = {"tgt_src", "tgt_core"}
        self.ops = ["branches", "diff", "docs", "revert", "fetch", "inplace", "bundle"]
        self.sent: list[Any] = []
        self.answers: list[dict[str, Any]] = []

    def is_online(self, target_id: str) -> bool:
        return target_id in self.online

    def hello(self, target_id: str) -> TargetHello | None:
        if target_id not in self.online:
            return None
        caps = Capabilities(tools=[], projects=True, projects_root=f"/home/{target_id}/.mensarium/projects", project_ops=self.ops)
        return TargetHello(target=TargetInfo(id=target_id, name=target_id, platform="linux-x86_64", hostname="h", agent_version="0.77.0"), capabilities=caps, policy=TargetPolicy(roots=["/home"], command_allowlist=[]))

    async def project_request(self, msg: ProjectSnapshot | ProjectOp, timeout_s: float, bundle: Path | None = None) -> dict[str, Any]:
        self.sent.append((msg, bundle))
        answer = self.answers.pop(0)
        if "make_bundle" in answer:
            refs, prereqs = answer.pop("make_bundle")
            path = self.inbox / f"{msg.request_id}.bundle"
            path.parent.mkdir(parents=True, exist_ok=True)
            git(self.repo_path, "bundle", "create", str(path), *refs, *(f"^{p}" for p in prereqs))
            answer["bundle"] = bundles.describe(path, {r: git(self.repo_path, "rev-parse", r) for r in refs}, prereqs).model_dump()
        return {**answer, "request_id": msg.request_id, "project_id": msg.project_id}


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class ProjectSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        env = patch.dict(os.environ, {"MENSARIUM_HOME": str(base / "home")})
        env.start()
        self.addCleanup(env.stop)
        self.repo_path = base / "src"
        self.repo_path.mkdir()
        git(self.repo_path, "init", "-q", "-b", "main")
        (self.repo_path / "a.txt").write_text("one\n")
        git(self.repo_path, "add", ".")
        git(self.repo_path, "commit", "-qm", "one")
        git(self.repo_path, "update-ref", "refs/mensarium/snapshot", "HEAD")
        self.db = Database(base / "core.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.repo = Repo(self.db)
        self.ws = ws = await self.repo.get_or_create_workspace()
        for tid in ("tgt_src", "tgt_core"):
            await self.repo.create_target({"id": tid, "workspace_id": ws, "name": tid, "platform": "linux", "hostname": "h", "status": "online", "public_key": "", "created_at": "2026-01-01T00:00:00Z"})
        self.hub = FakeHub(self.repo_path, base / "home" / "projects" / "core-inbox")
        self.manager = ProjectManager(self.repo, ws, self.hub, 120)  # type: ignore[arg-type]
        self.manager.device_id = "tgt_core"
        self.sync = self.manager.project_sync
        await self.repo.create_project({"id": "prj_1", "workspace_id": ws, "name": "demo", "kind": "repo", "source_target_id": "tgt_src", "source_path": "/home/tgt_src/demo",
                                        "status": "ready", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"})

    async def test_sync_source_fills_the_mirror_incrementally(self) -> None:
        head = git(self.repo_path, "rev-parse", "HEAD")
        git(self.repo_path, "branch", "mensarium/x-1", head)
        chat = "refs/heads/mensarium/x-1"
        self.hub.answers.append({"type": "project.snapshot.status", "state": "ok", "kind": "repo", "head_sha": head, "snapshot_sha": head, "branch": "main", "main": "main",
                                 "refs": {"refs/heads/main": head, "refs/mensarium/snapshot": head, chat: head}, "make_bundle": (["refs/heads/main", "refs/mensarium/snapshot", chat], [])})
        await self.manager.refresh("prj_1")
        self.assertTrue(self.hub.sent[-1][0].bundle)
        mirror = self.sync.mirror("prj_1")
        self.assertEqual(await mirror.refs(), {"refs/devices/tgt_src/heads/main": head, "refs/devices/tgt_src/snapshot": head})
        device = await self.repo.get_project_device("prj_1", "tgt_src")
        assert device is not None
        self.assertEqual((device["role"], device["device_refs"]["refs/heads/main"]), ("source", head))
        self.assertEqual((await self.repo.get_project("prj_1") or {})["main_branch"], "main")
        # Chat branches enter the mirror only through publish; a snapshot never moves them.
        await mirror.update_ref(chat, head)
        (self.repo_path / "a.txt").write_text("two\n")
        git(self.repo_path, "commit", "-qam", "two")
        new = git(self.repo_path, "rev-parse", "HEAD")
        git(self.repo_path, "branch", "-f", "mensarium/x-1", new)
        self.hub.answers.append({"type": "project.snapshot.status", "state": "ok", "kind": "repo", "head_sha": new, "snapshot_sha": head, "branch": "main", "main": "main",
                                 "refs": {"refs/heads/main": new, "refs/mensarium/snapshot": head, chat: new}, "make_bundle": (["refs/heads/main", chat], [head])})
        await self.sync.sync_source(await self.repo.get_project("prj_1") or {})
        self.assertEqual(self.hub.sent[-1][0].known, {"refs/heads/main": head, "refs/mensarium/snapshot": head, chat: head})
        self.assertEqual(await mirror.rev("refs/devices/tgt_src/heads/main"), new)
        self.assertEqual(await mirror.rev(chat), head)
        # The user reset main back and dropped the snapshot ref: no bundle, the mirror follows the refs it already has.
        self.hub.answers.append({"type": "project.snapshot.status", "state": "ok", "kind": "repo", "head_sha": head, "snapshot_sha": head, "branch": "main", "refs": {"refs/heads/main": head}})
        await self.sync.sync_source(await self.repo.get_project("prj_1") or {})
        self.assertEqual(await mirror.refs(), {"refs/devices/tgt_src/heads/main": head, chat: head})
        self.assertEqual(list(self.hub.inbox.iterdir()), [])

    async def test_old_client_stays_without_the_mirror(self) -> None:
        self.hub.ops = ["branches", "diff", "docs", "revert", "fetch", "inplace"]
        head = git(self.repo_path, "rev-parse", "HEAD")
        self.hub.answers.append({"type": "project.snapshot.status", "state": "ok", "kind": "repo", "head_sha": head, "snapshot_sha": head, "refs": {"refs/heads/main": head}})
        await self.sync.sync_source(await self.repo.get_project("prj_1") or {})
        msg = self.hub.sent[-1][0]
        self.assertEqual((msg.known, msg.bundle), ({}, False))
        self.assertFalse(self.sync.mirror("prj_1").exists)
        self.assertIsNone(await self.repo.get_project_device("prj_1", "tgt_src"))

    async def test_publish_stores_the_chat_branch(self) -> None:
        head = git(self.repo_path, "rev-parse", "HEAD")
        git(self.repo_path, "branch", "mensarium/x-1", head)
        path = self.hub.inbox / "pop_1.bundle"
        path.parent.mkdir(parents=True, exist_ok=True)
        git(self.repo_path, "bundle", "create", str(path), "refs/heads/mensarium/x-1")
        status = ProjectOpStatus(request_id="pop_1", project_id="prj_1", task_id="task_1", op="commit", state="ok", head_sha=head,
                                 bundle=bundles.describe(path, {"refs/heads/mensarium/x-1": head}, []))
        await self.sync.mirror("prj_1").init()
        await self.sync.publish(await self.repo.get_project("prj_1") or {}, {"id": "task_1", "target_id": "tgt_src", "branch": "mensarium/x-1", "head_sha": None}, status)
        self.assertEqual(await self.sync.mirror("prj_1").rev("refs/heads/mensarium/x-1"), head)
        self.assertFalse(path.exists())


    async def seed_mirror(self) -> str:
        head = git(self.repo_path, "rev-parse", "HEAD")
        self.hub.answers.append({"type": "project.snapshot.status", "state": "ok", "kind": "repo", "head_sha": head, "snapshot_sha": head, "branch": "main", "main": "main",
                                 "refs": {"refs/heads/main": head, "refs/mensarium/snapshot": head}, "make_bundle": (["refs/heads/main", "refs/mensarium/snapshot"], [])})
        await self.sync.sync_source(await self.repo.get_project("prj_1") or {})
        return head

    async def test_executor_checkout_gets_objects_first(self) -> None:
        head = await self.seed_mirror()
        p = await self.repo.get_project("prj_1") or {}
        self.assertEqual(await self.sync.resolve_base(p, "default"), ("main", "refs/devices/tgt_src/heads/main", head))
        self.assertEqual((await self.sync.resolve_base(p, "snapshot"))[2], head)
        with self.assertRaises(ProjectError):
            await self.sync.resolve_base(p, "nope")
        # The source is off: the chat still starts from the Core's copy.
        self.hub.online.discard("tgt_src")
        self.hub.answers += [{"type": "project.op.status", "task_id": "", "op": "fetch", "state": "ok", "data": {}},
                             {"type": "project.op.status", "task_id": "task_1", "op": "checkout", "state": "ok", "head_sha": head, "data": {"base": "main"}}]
        task = {"id": "task_1", "target_id": "tgt_core", "branch": "mensarium/t-1", "base_ref": "default"}
        status = await self.manager.checkout(p, task)
        self.assertEqual(status.head_sha, head)
        fetch, bundle = self.hub.sent[-2]
        self.assertEqual((fetch.op, fetch.args["role"], list(fetch.args["refs"])), ("fetch", "executor", ["refs/devices/tgt_src/heads/main"]))
        self.assertIsNotNone(bundle)
        self.assertEqual(self.hub.sent[-1][0].args["start"], head)
        self.assertEqual((await self.repo.get_project_device("prj_1", "tgt_core") or {})["known_refs"], {"refs/devices/tgt_src/heads/main": head})
        # The source is back: its snapshot is read first, and the objects are already on the executor.
        self.hub.online.add("tgt_src")
        self.hub.answers += [{"type": "project.snapshot.status", "state": "unchanged", "kind": "repo", "refs": {"refs/heads/main": head, "refs/mensarium/snapshot": head}},
                             {"type": "project.op.status", "task_id": "task_2", "op": "checkout", "state": "ok", "head_sha": head, "data": {"base": "main"}}]
        await self.manager.checkout(p, {**task, "id": "task_2"})
        self.assertEqual([m.op if isinstance(m, ProjectOp) else "snapshot" for m, _ in self.hub.sent[-2:]], ["snapshot", "checkout"])

    async def test_publish_queues_one_delivery_and_hello_delivers(self) -> None:
        head = await self.seed_mirror()
        git(self.repo_path, "checkout", "-q", "-b", "mensarium/t-1")
        (self.repo_path / "b.txt").write_text("chat\n")
        git(self.repo_path, "add", ".")
        git(self.repo_path, "commit", "-qm", "chat")
        chat = git(self.repo_path, "rev-parse", "HEAD")
        git(self.repo_path, "checkout", "-q", "main")
        await self.repo.create_task({"id": "task_1", "workspace_id": "ws", "profile_id": "p", "target_id": "tgt_core", "input": "x", "status": "IDLE", "trace_id": "tr",
                                     "project_id": "prj_1", "branch": "mensarium/t-1", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"})
        task = {"id": "task_1", "target_id": "tgt_core", "branch": "mensarium/t-1", "head_sha": None}
        self.hub.online.discard("tgt_src")
        for request_id in ("pop_2", "pop_3"):
            path = self.hub.inbox / f"{request_id}.bundle"
            git(self.repo_path, "bundle", "create", str(path), "refs/heads/mensarium/t-1", f"^{head}")
            status = ProjectOpStatus(request_id=request_id, project_id="prj_1", task_id="task_1", op="commit", state="ok", head_sha=chat,
                                     bundle=bundles.describe(path, {"refs/heads/mensarium/t-1": chat}, [head]))
            await self.sync.publish(await self.repo.get_project("prj_1") or {}, task, status)
        self.assertEqual(len(await self.repo.list_deliveries(target_id="tgt_src")), 1)
        self.hub.online.add("tgt_src")
        self.hub.answers += [{"type": "project.snapshot.status", "state": "unchanged", "kind": "repo", "refs": {"refs/heads/main": head, "refs/mensarium/snapshot": head}},
                             {"type": "project.op.status", "task_id": "task_1", "op": "fetch", "state": "ok", "data": {}}]
        await self.sync.on_connect("tgt_src")
        self.assertEqual([d["status"] for d in await self.repo.list_deliveries(target_id="tgt_src", statuses=("delivered",))], ["delivered"])
        fetch, bundle = self.hub.sent[-1]
        self.assertEqual((fetch.args["role"], fetch.args["refs"], fetch.args["source_path"]), ("source", {"refs/heads/mensarium/t-1": "refs/heads/mensarium/t-1"}, "/home/tgt_src/demo"))
        # The source already has its own main, so only the chat's commit travels.
        self.assertEqual(fetch.args["bundle"]["prerequisites"], [head])
        self.assertIsNotNone(bundle)

    async def test_create_task_needs_a_snapshot_for_a_remote_executor(self) -> None:
        for profile in builtin_profiles():
            await self.repo.upsert_profile(self.ws, profile.model_dump())
        orch = Orchestrator.__new__(Orchestrator)
        orch.repo, orch.hub, orch.projects, orch.workspace_id = self.repo, self.hub, self.manager, self.ws  # type: ignore[assignment]
        orch._prepare = lambda task_id: None  # type: ignore[method-assign]
        # No snapshot on the Core: a named executor is refused, the implicit Core device gives way to the source.
        with self.assertRaises(TaskError) as ctx:
            await orch.create_task("coding-agent-v1", "tgt_core", "", project_id="prj_1")
        self.assertIn("no snapshot", str(ctx.exception))
        self.assertEqual((await orch.create_task("coding-agent-v1", None, "", project_id="prj_1"))["target_id"], "tgt_src")
        self.assertEqual((await self.manager.view(await self.manager.get("prj_1")))["executor_id"], "tgt_src")
        await self.seed_mirror()
        self.assertEqual((await self.manager.view(await self.manager.get("prj_1")))["executor_id"], "tgt_core")
        task = await orch.create_task("coding-agent-v1", None, "", project_id="prj_1", branch="feature")
        self.assertEqual((task["target_id"], task["branch"]), ("tgt_core", "mensarium/feature"))

class HubChunkTests(unittest.IsolatedAsyncioTestCase):
    async def test_hub_drops_chunks_without_a_waiter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hub = ClientHub(repo=None, signing_key=Ed25519PrivateKey.generate())  # type: ignore[arg-type]
            hub.inbox = Path(tmp) / "inbox"
            conn = ClientConnection(ws=None, target_id="tgt_1", public_key="", hello=None)  # type: ignore[arg-type]
            chunk = {"type": "project.bundle", "request_id": "psn_1", "project_id": "prj_1", "seq": 0, "data": "aGk="}
            await hub._on_message(conn, chunk)
            self.assertFalse((hub.inbox / "psn_1.bundle").exists())
            conn.projects["psn_1"] = asyncio.get_running_loop().create_future()
            await hub._on_message(conn, chunk)
            self.assertEqual((hub.inbox / "psn_1.bundle").read_bytes(), b"hi")


if __name__ == "__main__":
    unittest.main()
