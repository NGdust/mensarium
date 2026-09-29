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

from mensarium.contracts.projects import ProjectOp, ProjectOpStatus, ProjectSnapshot
from mensarium.contracts.protocol import Capabilities, TargetHello, TargetInfo, TargetPolicy
from mensarium.core.client_hub import ClientConnection, ClientHub
from mensarium.core.db import Database
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
        ws = await self.repo.get_or_create_workspace()
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
