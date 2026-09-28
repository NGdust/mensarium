import tempfile
import unittest
from pathlib import Path

from mensarium.agent_core.context import build_system_prompt, context_parts, context_usage
from mensarium.agent_core.profile import builtin_profiles
from mensarium.contracts.llm import Message, ToolDefinition
from mensarium.contracts.protocol import TargetPolicy
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

    async def llm(self, task_id, provider, model, usage, context=None):
        await self.repo.add_step(task_id, "llm", {"input": {"context": context}, "output": {"text": ""}, "provider": provider,
                                                  "model_id": model, "usage": usage})

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

    async def test_last_llm_step_is_the_chats_own(self):
        await self.llm("chat", "claude_code", "claude-fable-5-1", {"prompt_tokens": 700}, {"parts": [], "history_budget": 0})
        await self.llm("agent", "claude_code", "claude-fable-5-1", {"prompt_tokens": 900})
        step = await self.repo.last_llm_step("chat")
        self.assertEqual((step["usage"]["prompt_tokens"], step["input"]["context"]["history_budget"]), (700, 0))

    async def test_task_without_model_calls(self):
        self.assertEqual(await self.repo.usage_by_model(["chat"]), [])
        self.assertIsNone(await self.repo.last_llm_step("chat"))


class ContextBreakdownTests(unittest.TestCase):
    def test_parts_add_up_to_the_request(self):
        instructions = [("AGENTS.md", "how to work", "Be brief.")]
        skills = [("review", "Review a diff")]
        memory = "- editor: vim\n- shell: zsh"
        policy = TargetPolicy(roots=["/work"], command_allowlist=[])
        system = build_system_prompt(builtin_profiles()[0], "device", "linux", policy, [], skills, memory, instructions=instructions)
        tools = [ToolDefinition(name=n, description="d", parameters={}) for n in ("files.read", "files.write", "github.search")]
        messages = [Message(role="user", content="hello"), Message(role="assistant", content="hi")]
        ctx = context_parts(system, tools, {"github.search"}, messages, instructions, skills, memory, 1000)
        parts = {p["key"]: p for p in ctx["parts"]}
        self.assertEqual(sum(p["chars"] for k, p in parts.items() if k not in ("tools", "plugins", "messages")), len(system))
        self.assertEqual((parts["tools"]["count"], parts["plugins"]["count"], parts["memory"]["count"]), (2, 1, 2))
        self.assertEqual(parts["messages"]["chars"], len("hello") + len("hi"))
        self.assertEqual(ctx["history_budget"], 4000)
        bare = context_parts("prompt", [], set(), [], [], [], None, 1000)
        self.assertEqual([p["chars"] for p in bare["parts"]], [6, 0, 0, 0, 0, 0, 0])

    def test_usage_scales_to_the_reported_input(self):
        ctx = {"parts": [{"key": "system", "chars": 3000}, {"key": "tools", "chars": 1000, "count": 5}, {"key": "messages", "chars": 4000}],
               "history_budget": 12000}
        usage = context_usage(ctx, 4000)
        self.assertEqual([p["tokens"] for p in usage["parts"]], [1500, 500, 2000])
        self.assertEqual((usage["tokens"], usage["limit"], usage["history_limit"], usage["estimated"]), (4000, 8000, 6000, False))
        self.assertEqual(usage["parts"][1]["count"], 5)
        estimate = context_usage({**ctx, "history_budget": 2000}, 0)
        self.assertEqual((estimate["tokens"], estimate["limit"], estimate["estimated"]), (2000, 2000, True))


if __name__ == "__main__":
    unittest.main()
