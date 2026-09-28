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

    async def test_new_notes_without_known_links_attach_to_the_center(self):
        await self.memory.ensure_center("About me")
        await self.memory.create(title="atlas", body="Core host.")
        self.assertEqual(wikilinks(await self.memory.attach("forge", "Linux workstation.")), ["About me"])
        self.assertEqual(wikilinks(await self.memory.attach("forge", "Backups go to [[atlas]].")), ["atlas"])
        self.assertEqual(wikilinks(await self.memory.attach("forge", "See [[nowhere]].")), ["nowhere", "About me"])
        self.assertEqual(await self.memory.attach("About me", "Owner."), "Owner.")

    async def test_agent_save_links_an_orphan_note_to_the_center(self):
        await self.memory.ensure_center("About me")
        await self.memory.agent_save("Editor", "Uses vim.", "preference", [], "task_1")
        note = await self.memory.repo.get_note_by_title("Editor")
        self.assertEqual(wikilinks(note["body"]), ["About me"])

    async def test_create_with_link_to_adds_the_link_once(self):
        a = await self.memory.create(title="forge", body="", link_to="atlas")
        b = await self.memory.create(title="pi", body="Near [[atlas]].", link_to="atlas")
        self.assertEqual((wikilinks(a["body"]), wikilinks(b["body"])), (["atlas"], ["atlas"]))

    async def test_empty_center_stays_out_of_the_prompt(self):
        await self.memory.ensure_center("About me")
        await self.memory.create(title="Shell", body="zsh", pinned=True)
        self.assertEqual(await self.memory.context(), "- Shell: zsh")


if __name__ == "__main__":
    unittest.main()
