import tempfile
import unittest
from pathlib import Path

from mensarium.core.db import Database
from mensarium.core.repo import Repo
from mensarium.shared.timeutil import now_iso


class TaskUsageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "test.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.repo = Repo(self.db)
        for task_id, parent in (("chat", None), ("agent", "chat")):
            await self.repo.create_task({"id": task_id, "workspace_id": "ws", "profile_id": "profile", "target_id": "device",
                                         "input": "request", "status": "SUCCEEDED", "trace_id": "trace", "parent_id": parent,
                                         "created_at": now_iso(), "updated_at": now_iso()})

    async def llm(self, task_id, provider, model, usage):
        await self.repo.add_step(task_id, "llm", {"output": {"text": ""}, "provider": provider, "model_id": model, "usage": usage})

    async def test_usage_is_summed_per_model_with_sub_agents(self):
        await self.llm("chat", "claude_code", "claude-fable-5-1", {"prompt_tokens": 1000, "completion_tokens": 10, "cached_tokens": 900, "cache_write_tokens": 100})
        await self.llm("agent", "claude_code", "claude-fable-5-1", {"prompt_tokens": 500, "completion_tokens": 5, "cached_tokens": 0, "cache_write_tokens": 500})
        await self.llm("chat", "ollama_cloud", "gpt-oss:120b", {"prompt_tokens": 300, "completion_tokens": 3})
        await self.llm("chat", "ollama_cloud", "gpt-oss:120b", None)
        rows = await self.repo.usage_by_model(["chat", "agent"])
        by_model = {r["model"]: r for r in rows}
        fable = by_model["claude-fable-5-1"]
        self.assertEqual((fable["calls"], fable["prompt_tokens"], fable["cached_tokens"], fable["cache_write_tokens"], fable["completion_tokens"]), (2, 1500, 900, 600, 15))
        oss = by_model["gpt-oss:120b"]
        self.assertEqual((oss["calls"], oss["prompt_tokens"], oss["cached_tokens"]), (2, 300, 0))
        self.assertEqual(rows[-1]["model"], "gpt-oss:120b")
        self.assertEqual(await self.repo.last_prompt_tokens(["chat", "agent"]), 0)
        await self.llm("agent", "claude_code", "claude-fable-5-1", {"prompt_tokens": 700})
        self.assertEqual(await self.repo.last_prompt_tokens(["chat", "agent"]), 700)

    async def test_task_without_model_calls(self):
        self.assertEqual(await self.repo.usage_by_model(["chat"]), [])
        self.assertEqual(await self.repo.last_prompt_tokens(["chat"]), 0)


if __name__ == "__main__":
    unittest.main()
