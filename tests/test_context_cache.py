import json
import random
import unittest

from mensarium.agent_core.context import build_messages
from mensarium.shared.toolargs import parse_tool_arguments

TOKENS = 12000
BUDGET = TOKENS * 4


def make_steps(turns: int, seed: int = 1) -> list[dict]:
    rnd = random.Random(seed)
    steps = [{"id": "s0", "kind": "user", "input": {"text": "Fix the build and report."}, "output": {}}]
    for n in range(turns):
        call = f"call_{n}"
        if n % 5 == 0:
            name, args = "files.write", {"path": f"src/f{n}.py", "content": "x = 1\n" * rnd.randint(200, 900)}
        else:
            name, args = "shell.bash", {"script": f"grep -rn item{n} src | head -50"}
        steps.append({"id": f"l{n}", "kind": "llm", "input": {}, "output": {"text": f"step {n}", "tool_calls": [{"id": call, "name": name, "arguments": json.dumps(args)}]}})
        steps.append({"id": f"t{n}", "kind": "tool", "input": {"llm_call_id": call, "tool": name}, "output": {"content": "o" * rnd.randint(200, 6000), "summary": f"{name} ok"}})
        if n == turns // 2:
            steps.append({"id": f"u{n}", "kind": "user", "input": {"text": "Also update the changelog."}, "output": {}})
    return steps


def chars(messages) -> int:
    return sum(len(m.content) for m in messages if isinstance(m.content, str)) + sum(
        len(tc["arguments"]) for m in messages for tc in m.tool_calls or []
    )


class ContextCacheTests(unittest.TestCase):
    def requests(self, steps):
        return [build_messages(steps[:i], TOKENS) for i, s in enumerate(steps) if s["kind"] == "llm"] + [build_messages(steps, TOKENS)]

    def test_requests_extend_the_previous_one_between_compactions(self):
        requests = self.requests(make_steps(80))
        rewrites = 0
        for prev, cur in zip(requests, requests[1:], strict=False):
            dumped_prev = [m.model_dump_json() for m in prev]
            if [m.model_dump_json() for m in cur[: len(prev)]] != dumped_prev:
                rewrites += 1
        self.assertGreater(rewrites, 0)
        self.assertLessEqual(rewrites, len(requests) // 4)

    def test_history_stays_within_budget(self):
        for messages in self.requests(make_steps(80)):
            self.assertLessEqual(chars(messages), BUDGET)

    def test_user_messages_survive_dropping_old_steps(self):
        messages = build_messages(make_steps(80), TOKENS)
        texts = [m.content for m in messages if m.role == "user"]
        self.assertIn("Fix the build and report.", texts)
        self.assertIn("Also update the changelog.", texts)
        self.assertTrue(any("were dropped from the context" in t for t in texts))
        self.assertEqual(messages[0].content, "Fix the build and report.")

    def test_old_tool_arguments_are_compacted_into_valid_json(self):
        steps = make_steps(40)
        compacted = [
            json.loads(tc["arguments"])
            for messages in self.requests(steps)
            for m in messages
            for tc in m.tool_calls or []
            if tc["name"] == "files.write" and "chars elided" in tc["arguments"]
        ]
        self.assertTrue(compacted)
        self.assertTrue(all(a["path"].startswith("src/f") and a["content"].endswith("chars elided)") for a in compacted))
        messages = build_messages(steps, TOKENS)
        self.assertEqual(messages[-2].tool_calls[0]["arguments"], steps[-2]["output"]["tool_calls"][0]["arguments"])

    def test_every_tool_call_keeps_its_result(self):
        messages = build_messages(make_steps(80), TOKENS)
        calls = [tc["id"] for m in messages for tc in m.tool_calls or []]
        results = [m.tool_call_id for m in messages if m.role == "tool"]
        self.assertEqual(calls, results)

    def test_short_history_is_sent_in_full(self):
        steps = make_steps(3)
        messages = build_messages(steps, TOKENS)
        self.assertEqual([m.content for m in messages if m.role == "tool"], [s["output"]["content"] for s in steps if s["kind"] == "tool"])


class ToolArgumentsTests(unittest.TestCase):
    def test_object_encoded_twice_is_unwrapped(self):
        args, raw, err = parse_tool_arguments(json.dumps(json.dumps({"path": "a.js", "old": "x", "new": "y"})))
        self.assertEqual(args, {"path": "a.js", "old": "x", "new": "y"})
        self.assertEqual(json.loads(raw), args)
        self.assertIsNone(err)

    def test_non_object_is_an_error(self):
        self.assertEqual(parse_tool_arguments("[1, 2]")[2], "arguments must be a JSON object")
        self.assertEqual(parse_tool_arguments(json.dumps("plain text"))[0], None)
        self.assertIsNotNone(parse_tool_arguments("{broken")[2])

    def test_dict_passes_through(self):
        args, raw, err = parse_tool_arguments({"path": "é"})
        self.assertEqual((args, raw, err), ({"path": "é"}, '{"path": "é"}', None))


if __name__ == "__main__":
    unittest.main()
