import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from mensarium.contracts.projects import ProjectError, ProjectOpStatus
from mensarium.core.db import Database
from mensarium.core.events import EventBus
from mensarium.core.orchestrator import Orchestrator
from mensarium.core.repo import Repo
from mensarium.shared.timeutil import now_iso


def status(ok: bool, **extra: object) -> ProjectOpStatus:
    checks = [{"command": "make test", "code": 0 if ok else 2, "output": "ok\n" if ok else "FAILED\n", "duration_ms": 5}]
    return ProjectOpStatus(request_id="r", project_id="prj", task_id="chat", op="check", state="ok", data={"ok": ok, "checks": checks}, **extra)


class ChecksTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "test.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.repo = Repo(self.db)
        self.project = {"id": "prj", "name": "demo", "kind": "repo", "source_target_id": "device", "source_path": "/w/demo", "checks": "make test"}
        await self.repo.create_task({"id": "chat", "workspace_id": "ws", "profile_id": "profile", "target_id": "device", "input": "real request",
                                     "status": "PLANNING", "project_id": "prj", "branch": "mensarium/x-1", "base_sha": "a" * 40, "head_sha": "b" * 40,
                                     "trace_id": "trace", "created_at": now_iso(), "updated_at": now_iso()})
        self.core = Orchestrator.__new__(Orchestrator)
        self.core.repo, self.core.bus, self.core.workspace_id = self.repo, EventBus(self.repo), "ws"
        self.core.runners = {}
        self.core.hub = Mock(hello=Mock(return_value=object()))
        self.core.projects = Mock(check=AsyncMock(side_effect=[status(False), status(True), ProjectError("the device is offline")]))
        self.core.repo.get_project = AsyncMock(return_value=self.project)

    async def test_receipt_is_saved_and_reported_for_failed_passed_and_unavailable_checks(self):
        task = await self.repo.get_task("chat")
        failed = await self.core.run_checks(task, self.project)
        self.assertEqual((failed["ok"], failed["head_sha"], failed["checks"][0]["code"]), (False, "b" * 40, 2))
        self.assertIn("FAILED", self.core.checks_report(failed))
        passed = await self.core.run_checks(task, self.project)
        self.assertTrue(passed["ok"])
        self.assertTrue((await self.repo.get_task("chat"))["checks"]["ok"])
        offline = await self.core.run_checks(task, self.project)
        self.assertEqual((offline["ok"], offline["error"]), (None, "the device is offline"))
        events = await self.repo.list_events("chat")
        self.assertEqual([e["payload"]["ok"] for e in events if e["event"] == "task.check"], [False, True, None])

    async def test_turn_commit_message_skips_the_harness_step(self):
        await self.repo.add_step("chat", "user", {"input": {"text": "real request"}})
        await self.repo.add_step("chat", "user", {"input": {"text": "The harness ran the project checks...", "harness": True}})
        self.core.projects.commit = AsyncMock(return_value=(status(True, head_sha="c" * 40, changed=1), None))
        await self.core._commit_turn("chat")
        self.assertEqual(self.core.projects.commit.await_args.args[2], "mensarium: real request")
