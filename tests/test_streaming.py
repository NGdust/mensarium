import asyncio
import json
import unittest
from unittest.mock import Mock, patch

import httpx

from mensarium.contracts.llm import ChatRequest, Message
from mensarium.core.events import DRAFT_FLUSH_S, EventBus
from mensarium.llm_providers.base import LLMError
from mensarium.llm_providers.cli_provider import AnswerStream, ClaudeCodeProvider, partial_json_string
from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider


def sse(*chunks: dict) -> bytes:
    return b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


def delta(**d: object) -> dict:
    return {"choices": [{"index": 0, "delta": d, "finish_reason": None}]}


class OpenAIStreamTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, *responses: httpx.Response) -> tuple[OpenAICompatibleProvider, list[dict]]:
        bodies: list[dict] = []
        queue = list(responses)

        def handle(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return queue.pop(0)

        p = OpenAICompatibleProvider("test", "http://llm/v1", "m", max_retries=1)
        p._client = httpx.AsyncClient(base_url=p.base_url, transport=httpx.MockTransport(handle))
        self.addAsyncCleanup(p.aclose)
        return p, bodies

    async def chat(self, p: OpenAICompatibleProvider, pieces: list[str] | None) -> object:
        request = ChatRequest(model="m", system="s", messages=[Message(role="user", content="hi")])
        return await p.chat(request, tools=[], on_text=pieces.append if pieces is not None else None)

    async def test_chunks_are_handed_on_and_folded_into_one_response(self):
        body = sse(
            delta(role="assistant", content="Reading "),
            delta(content="the file"),
            delta(tool_calls=[{"index": 0, "id": "call_1", "type": "function", "function": {"name": "files__read", "arguments": '{"pa'}}]),
            delta(tool_calls=[{"index": 0, "function": {"arguments": 'th": "a"}'}}]),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 4}}},
        )
        p, bodies = self.provider(httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
        pieces: list[str] = []
        resp = await self.chat(p, pieces)
        self.assertEqual(pieces, ["Reading ", "the file"])
        self.assertEqual(resp.text, "Reading the file")
        self.assertEqual([(c.id, c.name, c.arguments) for c in resp.tool_calls], [("call_1", "files.read", {"path": "a"})])
        self.assertEqual(resp.finish_reason, "tool_calls")
        self.assertEqual((resp.usage.prompt_tokens, resp.usage.cached_tokens), (10, 4))
        self.assertTrue(bodies[0]["stream"])
        self.assertEqual(bodies[0]["stream_options"], {"include_usage": True})

    async def test_without_a_callback_nothing_is_streamed(self):
        answer = {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}
        p, bodies = self.provider(httpx.Response(200, json=answer))
        resp = await self.chat(p, None)
        self.assertEqual(resp.text, "hello")
        self.assertFalse(bodies[0]["stream"])

    async def test_server_that_ignores_stream_still_answers(self):
        answer = {"choices": [{"message": {"content": "whole"}, "finish_reason": "stop"}]}
        p, _ = self.provider(httpx.Response(200, json=answer))
        pieces: list[str] = []
        resp = await self.chat(p, pieces)
        self.assertEqual((resp.text, pieces), ("whole", []))

    async def test_error_status_is_retried_before_any_text(self):
        ok = httpx.Response(200, content=sse(delta(content="fine")), headers={"content-type": "text/event-stream"})
        p, bodies = self.provider(httpx.Response(503, text="busy"), ok)
        pieces: list[str] = []
        with patch("asyncio.sleep"):
            resp = await self.chat(p, pieces)
        self.assertEqual((resp.text, pieces, len(bodies)), ("fine", ["fine"], 2))

    async def test_error_chunk_fails_the_call(self):
        body = sse(delta(content="par"), {"error": {"message": "overloaded"}})
        p, _ = self.provider(httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
        with self.assertRaisesRegex(LLMError, "overloaded"):
            await self.chat(p, [])


class CliAnswerStreamTests(unittest.IsolatedAsyncioTestCase):
    def test_partial_json_string(self):
        self.assertEqual(partial_json_string(""), "")
        self.assertEqual(partial_json_string('line\\none'), "line\none")
        self.assertEqual(partial_json_string('ends with \\'), "ends with ")
        self.assertEqual(partial_json_string('cut \\u04'), "cut ")
        self.assertEqual(partial_json_string('smile \\ud83d'), "smile ")
        self.assertEqual(partial_json_string('say \\"hi\\"", "x": 1}'), 'say "hi"')
        self.assertEqual(partial_json_string("raw\nnewline"), "raw\nnewline")

    def test_only_the_text_field_is_handed_on(self):
        pieces: list[str] = []
        stream = AnswerStream(pieces.append)
        answer = '{"type": "final", "tool": "", "arguments": "{\\"text\\": \\"no\\"}", "text": "Привет,\\n мир"}'
        for i in range(0, len(answer), 3):
            stream.feed(answer[i : i + 3])
        self.assertEqual("".join(pieces), "Привет,\n мир")

    async def test_exec_hands_on_stdout_lines_as_they_arrive(self):
        p = ClaudeCodeProvider("test", "/bin/sh", "m")
        self.addAsyncCleanup(p.aclose)
        lines: list[str] = []
        code, out, err = await p._exec(["-c", "cat; echo second; echo oops >&2"], "first\n", 10, on_line=lines.append)
        self.assertEqual((code, lines, out, err), (0, ["first\n", "second\n"], "first\nsecond\n", "oops\n"))


class DraftTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = EventBus(Mock())
        self.q = self.bus.subscribe("task")

    def live(self) -> list[dict]:
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return out

    async def test_chunks_are_batched_into_live_events(self):
        draft = self.bus.draft("task", 7)
        draft.feed("Hel")
        draft.feed("lo")
        self.assertEqual(self.live(), [])
        await asyncio.sleep(DRAFT_FLUSH_S * 2)
        draft.feed(" world")
        await asyncio.sleep(DRAFT_FLUSH_S * 2)
        events = self.live()
        self.assertEqual([e["seq"] for e in events], [None, None])
        self.assertEqual([e["payload"] for e in events], [
            {"request": 7, "offset": 0, "text": "Hello"},
            {"request": 7, "offset": 5, "text": " world"},
        ])
        self.assertEqual(self.bus.drafts["task"].snapshot()["payload"], {"request": 7, "offset": 0, "text": "Hello world"})
        draft.close()
        self.assertNotIn("task", self.bus.drafts)

    async def test_tool_call_written_as_json_is_not_streamed(self):
        draft = self.bus.draft("task", 1)
        draft.feed('  {"type": "tool_call"')
        await asyncio.sleep(DRAFT_FLUSH_S * 2)
        self.assertEqual(self.live(), [])

    async def test_close_drops_a_pending_batch(self):
        draft = self.bus.draft("task", 1)
        draft.feed("text")
        draft.close()
        await asyncio.sleep(DRAFT_FLUSH_S * 2)
        self.assertEqual(self.live(), [])


if __name__ == "__main__":
    unittest.main()
