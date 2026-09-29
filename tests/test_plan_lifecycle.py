import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from mensarium.core.db import Database
from mensarium.core.events import EventBus
from mensarium.core.orchestrator import Orchestrator
from mensarium.core.repo import Repo
from mensarium.shared.timeutil import now_iso


class PlanLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "test.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.repo = Repo(self.db)
        self.plan = [{"title": "Old task", "status": "in_progress"}]
        await self.repo.create_task({"id": "chat", "workspace_id": "ws", "profile_id": "profile",
                                     "target_id": "device", "input": "old request", "status": "FAILED",
                                     "plan": self.plan, "trace_id": "trace", "created_at": now_iso(), "updated_at": now_iso()})
        self.core = Orchestrator.__new__(Orchestrator)
        self.core.repo, self.core.bus = self.repo, EventBus(self.repo)
        self.core.runners, self.core._start = {}, Mock()

    async def test_new_request_clears_saved_plan_before_start(self):
        result = await self.core.post_message("chat", "A different request")
        self.assertEqual(result["plan"], [])
        self.core._start.assert_called_once_with("chat")
        events = await self.repo.list_events("chat")
        self.assertEqual([e["event"] for e in events], ["task.plan", "user.message"])
        self.assertEqual(events[0]["payload"]["items"], [])
        await self.db.close()
        await self.db.connect()
        self.assertEqual((await self.repo.get_task("chat"))["plan"], [])

    async def test_finished_or_failed_turn_clears_plan(self):
        for status in ("SUCCEEDED", "FAILED", "FAILED_RECOVERABLE", "CANCELED"):
            with self.subTest(status=status):
                await self.repo.update_task("chat", {"plan": self.plan})
                await self.core._set_status("chat", status)
                self.assertEqual((await self.repo.get_task("chat"))["plan"], [])
                events = await self.repo.list_events("chat")
                self.assertEqual([e["event"] for e in events[-2:]], ["task.plan", "task.status"])

    async def test_history_is_paged_by_whole_user_turns(self):
        await self.core._set_status("chat", "PAUSED")
        for text in ("first", "second", "third"):
            await self.core.post_message("chat", text)
            await self.core._set_status("chat", "PAUSED")
        events, more = await self.repo.list_history("chat", turns=2)
        self.assertTrue(more)
        self.assertEqual(events[0]["event"], "user.message")
        self.assertEqual([e["payload"]["text"] for e in events if e["event"] == "user.message"], ["second", "third"])
        older, more = await self.repo.list_history("chat", before=events[0]["seq"], turns=2)
        self.assertFalse(more)
        self.assertEqual(older[0]["event"], "task.status")
        self.assertEqual([e["payload"]["text"] for e in older if e["event"] == "user.message"], ["first"])
        self.assertEqual(older[-1]["seq"] + 1, events[0]["seq"])

    async def test_pause_and_resume_keep_current_plan(self):
        await self.core._set_status("chat", "PAUSED")
        self.assertEqual((await self.repo.get_task("chat"))["plan"], self.plan)
        await self.core.resume("chat")
        self.assertEqual((await self.repo.get_task("chat"))["plan"], self.plan)
        self.core._start.assert_called_once_with("chat")

    async def test_new_request_after_pause_clears_plan(self):
        await self.core._set_status("chat", "PAUSED")
        await self.core.post_message("chat", "New task, not resume")
        self.assertEqual((await self.repo.get_task("chat"))["plan"], [])
