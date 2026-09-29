import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mensarium.contracts.llm import ChatRequest, Message, ModelResponse, ProposedToolCall
from mensarium.llm_providers import cli_provider
from mensarium.llm_providers.base import LLMError
from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider


def answer(session: str, call: str | None = None) -> ModelResponse:
    calls = [ProposedToolCall(id=call, name="files.read", arguments={"path": "a"}, raw_arguments='{"path": "a"}')] if call else []
    return ModelResponse(text="", tool_calls=calls, finish_reason="tool_calls" if call else "stop", raw_provider_response={"session_id": session})


class CliSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = cli_provider.ClaudeCodeProvider("test", "claude", "claude-sonnet-5", max_retries=1)
        self.discard = patch.object(self.provider, "_discard").start()
        self.addCleanup(patch.stopall)
        self.call = patch.object(self.provider, "_call", new_callable=AsyncMock).start()
        self.messages = [Message(role="user", content="first request")]

    async def chat(self, system: str = "system", task: str | None = "task_1", model: str = "claude-sonnet-5") -> None:
        request = ChatRequest(model=model, system=system, messages=list(self.messages), metadata={"task_id": task} if task else {})
        resp = await self.provider.chat(request, tools=[])
        calls = [{"id": c.id, "name": c.name, "arguments": c.raw_arguments} for c in resp.tool_calls]
        self.messages.append(Message(role="assistant", content=resp.text or "", tool_calls=calls or None))
        if calls:
            self.messages.append(Message(role="tool", tool_call_id=calls[0]["id"], content=f"result of {calls[0]['id']}"))
        else:
            self.messages.append(Message(role="user", content="next request"))

    def last(self) -> tuple[str, str | None, bool]:
        args = self.call.call_args
        return args.args[2], args.kwargs["resume"], args.kwargs["persist"]

    async def test_second_step_resumes_with_only_new_messages(self):
        self.call.side_effect = [answer("s1", "call_1"), answer("s1", "call_2")]
        await self.chat()
        prompt, resume, persist = self.last()
        self.assertIn("first request", prompt)
        self.assertEqual((resume, persist), (None, True))
        await self.chat()
        prompt, resume, _ = self.last()
        self.assertEqual(resume, "s1")
        self.assertIn("result of call_1", prompt)
        self.assertNotIn("first request", prompt)
        self.discard.assert_not_called()

    async def test_new_user_turn_after_final_answer_resumes(self):
        self.call.side_effect = [answer("s1"), answer("s1")]
        await self.chat()
        await self.chat()
        prompt, resume, _ = self.last()
        self.assertEqual(resume, "s1")
        self.assertIn("next request", prompt)

    async def test_changed_system_prompt_or_model_starts_new_session(self):
        for change in ({"system": "other"}, {"model": "claude-opus-5"}):
            with self.subTest(change=change):
                self.messages = [Message(role="user", content="first request")]
                self.call.side_effect = [answer("s1", "call_1"), answer("s2", "call_2")]
                await self.chat()
                await self.chat(**change)
                prompt, resume, _ = self.last()
                self.assertIsNone(resume)
                self.assertIn("first request", prompt)
                self.discard.assert_called_with("s1")

    async def test_rewritten_history_starts_new_session(self):
        self.call.side_effect = [answer("s1", "call_1"), answer("s2", "call_2")]
        await self.chat()
        self.messages[0] = Message(role="user", content="compacted request")
        await self.chat()
        self.assertIsNone(self.last()[1])
        self.discard.assert_called_with("s1")

    async def test_failed_resume_retries_in_a_new_session(self):
        self.call.side_effect = [answer("s1", "call_1"), LLMError("no conversation found"), answer("s2", "call_2")]
        with patch.object(cli_provider.asyncio, "sleep", new_callable=AsyncMock):
            await self.chat()
            await self.chat()
        prompt, resume, _ = self.last()
        self.assertIsNone(resume)
        self.assertIn("first request", prompt)
        self.discard.assert_called_with("s1")
        self.assertEqual(self.provider.sessions["task_1"].id, "s2")

    async def test_request_without_task_is_not_persisted(self):
        self.call.side_effect = [answer("s1")]
        await self.chat(task=None)
        self.assertEqual(self.last()[1:], (None, False))
        self.assertEqual(self.provider.sessions, {})


class CliUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_claude_usage_counts_cache_writes(self):
        provider = cli_provider.ClaudeCodeProvider("test", "claude", "claude-sonnet-5")
        result = {"type": "result", "session_id": "s1", "result": '{"type": "final", "tool": "", "arguments": "", "text": "done"}',
                  "usage": {"input_tokens": 3, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 200, "output_tokens": 50}}
        async def fake_exec(args, stdin, timeout_s, env=None, on_line=None):
            self.assertEqual(Path(args[args.index("--system-prompt-file") + 1]).read_text(), "sys")
            return 0, json.dumps(result), ""

        with patch.object(provider, "_exec", side_effect=fake_exec) as execute:
            resp = await provider._call("claude-sonnet-5", "sys", "prompt", 10, resume="s1", persist=True)
        args = execute.call_args.args[0]
        self.assertEqual(args[args.index("--resume") + 1], "s1")
        self.assertNotIn("--system-prompt", args)
        self.assertFalse(Path(args[args.index("--system-prompt-file") + 1]).exists())
        self.assertNotIn("--no-session-persistence", args)
        self.assertEqual(resp.usage.model_dump(), {"prompt_tokens": 1203, "completion_tokens": 50, "cached_tokens": 1000, "cache_write_tokens": 200})
        self.assertEqual(resp.raw_provider_response["session_id"], "s1")

    def test_text_answer_with_braces_in_strings_or_broken_json(self):
        edit = {"type": "tool_call", "tool": "files.edit", "arguments": json.dumps({"path": "a.css", "old": ":root {\n", "new": ":root {\n  --ink: 1;\n"}), "text": ""}
        resp = cli_provider.parse_text_answer("Updating the variables.\n\n" + json.dumps(edit))
        self.assertEqual(resp.tool_calls[0].arguments, {"path": "a.css", "old": ":root {\n", "new": ":root {\n  --ink: 1;\n"})
        broken = '{"type": "tool_call", "tool": "shell.bash", "arguments": "{\\"script\\": "grep x"}", "text": ""}'
        resp = cli_provider.parse_text_answer(broken)
        self.assertEqual(resp.tool_calls[0].name, "shell.bash")
        self.assertIsNotNone(resp.tool_calls[0].parse_error)

    async def test_codex_resume_and_usage(self):
        provider = cli_provider.CodexCliProvider("test", "codex", "")
        provider.models = ["gpt-x"]

        async def fake_exec(args, stdin, timeout_s, env=None):
            Path(args[args.index("--output-last-message") + 1]).write_text('{"type": "final", "tool": "", "arguments": "", "text": "ok"}')
            events = [{"type": "thread.started", "thread_id": "th1"}, {"type": "turn.completed", "usage": {"input_tokens": 900, "cached_input_tokens": 800, "output_tokens": 20}}]
            return 0, "\n".join(json.dumps(e) for e in events), ""

        with patch.object(provider, "_exec", side_effect=fake_exec) as execute:
            fresh = await provider._call("gpt-x", "sys", "prompt", 10, persist=True)
            resumed = await provider._call("gpt-x", "sys", "delta", 10, resume="th1", persist=True)
        first, second = execute.call_args_list
        self.assertNotIn("--ephemeral", first.args[0])
        self.assertIn("## System instructions", first.args[1])
        self.assertEqual(second.args[0][:3], ["exec", "resume", "th1"])
        self.assertEqual(second.args[1], "delta")
        self.assertEqual(fresh.raw_provider_response["session_id"], "th1")
        self.assertEqual(resumed.usage.model_dump(), {"prompt_tokens": 900, "completion_tokens": 20, "cached_tokens": 800, "cache_write_tokens": 0})
        await provider.aclose()

    def test_openai_compatible_cached_tokens(self):
        base = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
        openai = OpenAICompatibleProvider._parse({**base, "usage": {"prompt_tokens": 500, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 400}}})
        llama = OpenAICompatibleProvider._parse({**base, "usage": {"prompt_tokens": 500, "completion_tokens": 5}, "timings": {"cache_n": 300}})
        self.assertEqual((openai.usage.cached_tokens, llama.usage.cached_tokens), (400, 300))


if __name__ == "__main__":
    unittest.main()
