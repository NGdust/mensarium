import tempfile
import unittest
from pathlib import Path

from mensarium.core.db import Database
from mensarium.core.memory import Memory, NoteError, wikilinks
from mensarium.core.repo import Repo


class MemoryCenterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "test.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.memory = Memory(Repo(self.db))

    async def test_center_is_created_once_and_pinned(self):
        self.assertIsNone(await self.memory.center())
        first = await self.memory.ensure_center("About me")
        again = await self.memory.ensure_center("Something else")
        self.assertEqual(first["id"], again["id"])
        self.assertEqual((first["kind"], bool(first["pinned"]), first["importance"]), ("person", True, 10))
        self.assertEqual((await self.memory.graph(False))["center"], first["id"])

    async def test_center_adopts_an_existing_note_and_can_move(self):
        me = await self.memory.create(title="About me", body="Writes Python.")
        center = await self.memory.ensure_center("About me")
        self.assertEqual(center["id"], me["id"])
        other = await self.memory.create(title="homelab", body="Compose stacks.")
        await self.memory.set_center(other["id"])
        self.assertEqual((await self.memory.center())["id"], other["id"])
        with self.assertRaises(NoteError):
            await self.memory.set_center("mem_missing")

    async def test_notes_join_topics_and_leave_them_when_the_topic_goes(self):
        code = await self.memory.ensure_topic("Mensarium", "The harness itself.")
        self.assertEqual((await self.memory.ensure_topic("Mensarium"))["id"], code["id"])
        note = await self.memory.create(title="Release flow", body="Bump, push, CI tags.", kind="howto", topic_id=code["id"])
        with self.assertRaises(NoteError):
            await self.memory.create(title="Loose", body="", topic_id=note["id"])
        self.assertEqual([(t["title"], t["count"]) for t in await self.memory.topics()], [("Mensarium", 1)])
        web = await self.memory.create(title="Light theme", body="", tags=["mensarium", "web"], topic_id=code["id"])
        await self.memory.create(title="Mobile layout", body="", tags=["web", "css"], topic_id=code["id"])
        rows = await self.memory.notes()
        groups = self.memory.groups(rows)
        self.assertEqual((groups[web["id"]], groups[note["id"]]), ("web", None))
        self.assertEqual(self.memory.path(web, rows, groups), "Mensarium › web › Light theme")
        await self.memory.repo.delete_note(code["id"])
        self.assertIsNone((await self.memory.repo.get_note(note["id"]))["topic_id"])

    async def test_agent_save_files_under_a_topic_and_refuses_reports(self):
        await self.memory.ensure_topic("MySky")
        self.assertIn("Saved", await self.memory.agent_save("MT-1 alerts", "Slack alert on bad prices.", "task", [], "task_1", topic="MySky"))
        note = await self.memory.repo.get_note_by_title("MT-1 alerts")
        self.assertEqual(note["topic_id"], (await self.memory.repo.get_note_by_title("MySky"))["id"])
        self.assertIn("Too long", await self.memory.agent_save("MT-1 alerts", "x" * 1501, "task", [], "task_1"))
        self.assertEqual(await self.memory.agent_save("Editor", "Uses vim.", "preference", [], "task_1", topic="Habits"), "Saved new note 'Editor'.")
        self.assertEqual([t["title"] for t in await self.memory.topics()], ["Habits", "MySky"])

    async def test_tidy_ops_merge_retire_and_resolve_ghosts(self):
        keep = await self.memory.create(title="Releases", body="Push to main. [[Old releases]]", source="dream")
        await self.memory.create(title="Old releases", body="Tag by hand.", source="dream", tags=["git"])
        await self.memory.create(title="Log", body="Sees [[Old releases]] and [[Nowhere]].", source="dream")
        self.assertEqual((await self.memory.apply_op({"action": "merge", "title": "Releases", "from": ["Old releases"], "body": "CI tags after a push to main."}))["action"], "merged")
        merged = await self.memory.repo.get_note(keep["id"])
        self.assertEqual((merged["body"], merged["tags"]), ("CI tags after a push to main.", ["git"]))
        self.assertIsNone(await self.memory.repo.get_note_by_title("Old releases"))
        self.assertEqual(wikilinks((await self.memory.repo.get_note_by_title("Log"))["body"]), ["Releases", "Nowhere"])
        self.assertEqual(await self.memory.ghosts(), {"Nowhere": ["Log"]})
        await self.memory.apply_op({"action": "resolve_ghost", "title": "Nowhere", "into": "Releases"})
        self.assertEqual(await self.memory.ghosts(), {})
        await self.memory.apply_op({"action": "retire", "title": "Log"})
        self.assertEqual([n["title"] for n in await self.memory.notes()], ["Releases"])
        self.assertEqual(len(await self.memory.notes(archived=True)), 2)

    async def test_create_with_link_to_adds_the_link_once(self):
        a = await self.memory.create(title="forge", body="", link_to="atlas")
        b = await self.memory.create(title="pi", body="Near [[atlas]].", link_to="atlas")
        self.assertEqual((wikilinks(a["body"]), wikilinks(b["body"])), (["atlas"], ["atlas"]))

    async def test_empty_center_stays_out_of_the_prompt_and_topics_come_first(self):
        await self.memory.ensure_center("About me")
        await self.memory.create(title="Shell", body="zsh", pinned=True)
        self.assertEqual(await self.memory.context(), "- Shell: zsh")
        await self.memory.ensure_topic("Mac", "The owner's laptop.")
        self.assertEqual(await self.memory.context(), "- [topic] Mac: The owner's laptop.\n- Shell: zsh")


if __name__ == "__main__":
    unittest.main()
