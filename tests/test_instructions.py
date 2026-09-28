import tempfile
import unittest
from pathlib import Path

from mensarium.agent_core.context import INSTRUCTION_FILE_CHARS, build_system_prompt
from mensarium.agent_core.profile import builtin_profiles
from mensarium.contracts.protocol import TargetPolicy
from mensarium.core.instructions import FILES, InstructionError, InstructionStore, default_text


class InstructionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = InstructionStore(Path(self.tmp.name) / "instructions")

    def test_defaults_are_used_until_the_user_writes_a_file(self):
        items = self.store.all()
        self.assertEqual([i["name"] for i in items], ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md"])
        self.assertTrue(all(not i["custom"] and i["content"] == default_text(i["name"]) for i in items))
        self.assertIn("Mensarium", default_text("IDENTITY.md"))
        self.assertEqual([name for name, _, _ in self.store.prompt_files()], list(FILES))

    def test_save_normalizes_text_and_empty_brings_the_default_back(self):
        item = self.store.save("SOUL.md", "Be direct.\r\n\r\n  ")
        self.assertTrue(item["custom"])
        self.assertEqual(item["content"], "Be direct.\n")
        self.assertIn(("SOUL.md", FILES["SOUL.md"], "Be direct."), self.store.prompt_files())
        item = self.store.save("SOUL.md", "  \n")
        self.assertFalse(item["custom"])
        self.assertEqual(item["content"], default_text("SOUL.md"))
        self.assertFalse((self.store.folder / "SOUL.md").exists())

    def test_rejects_other_names(self):
        for name in ("MEMORY.md", "../config.yaml", "agents.md"):
            with self.subTest(name=name), self.assertRaises(InstructionError):
                self.store.save(name, "x")


class PromptTests(unittest.TestCase):
    def prompt(self, instructions):
        return build_system_prompt(builtin_profiles()[0], "mac", "darwin", TargetPolicy(roots=["/w"], command_allowlist=[]),
                                   ["files.read"], instructions=instructions)

    def test_block_lists_files_with_their_purpose(self):
        prompt = self.prompt([("AGENTS.md", "how to work", "Answer in Russian."), ("USER.md", "who", "Vlad, GMT+3")])
        self.assertIn("## Instructions from the user", prompt)
        self.assertIn("### AGENTS.md (how to work)\nAnswer in Russian.\n", prompt)
        self.assertIn("### USER.md (who)\nVlad, GMT+3\n", prompt)
        self.assertGreater(prompt.index("## Instructions from the user"), prompt.index("## Access mode"))
        for empty in ([], None):
            self.assertNotIn("## Instructions from the user", self.prompt(empty))

    def test_long_file_is_cut_with_a_note(self):
        prompt = self.prompt([("USER.md", "who", "x" * (INSTRUCTION_FILE_CHARS + 5))])
        self.assertIn(f"[cut here: the file is longer than {INSTRUCTION_FILE_CHARS} characters]", prompt)
        self.assertNotIn("x" * (INSTRUCTION_FILE_CHARS + 1), prompt)
