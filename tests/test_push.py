import asyncio
import unittest
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec

from mensarium.contracts.push import PushSubscription
from mensarium.core.push import PushManager, b64, encrypt, unb64


class PushCryptoTest(unittest.TestCase):
    def test_rfc8291_example(self) -> None:
        key = ec.derive_private_key(int.from_bytes(unb64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
        body = encrypt(
            b"When I grow up, I want to be a watermelon",
            "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
            "BTBZMqHH6r4Tts7J_aSIgg",
            salt=unb64("DGv6ra1nlYgDCS1FRnbzlw"),
            key=key,
        )
        self.assertEqual(
            b64(body),
            "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl"
            "7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
        )


class FakeRepo:
    def __init__(self, tasks: dict[str, dict[str, Any]]) -> None:
        self.tasks = tasks
        sub = PushSubscription(endpoint="https://push.example/1", p256dh="k", auth="a", lang="ru", created_at="now")
        self.kv: dict[str, Any] = {"push": {"subscriptions": [sub.model_dump()]}}

    async def get_setting(self, key: str) -> Any:
        return self.kv.get(key)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self.tasks.get(task_id)


class FakeBus:
    def __init__(self) -> None:
        self.parents = {"task_child": "task_parent"}
        self.listeners: list[Any] = []


class PushRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_sub_agent_approval_goes_to_parent_and_automation_results_stay_quiet(self) -> None:
        repo = FakeRepo({"task_parent": {"input": "Fix the build\nmore"}, "task_auto": {"input": "Daily", "automation_id": "aut_1"}})
        m = PushManager.__new__(PushManager)
        m.repo, m.bus, m.pending = repo, FakeBus(), set()  # type: ignore[assignment]
        sent: list[dict[str, Any]] = []

        async def send(sub: PushSubscription, message: dict[str, Any], urgent: bool = False) -> None:
            sent.append(message)

        m.send = send  # type: ignore[method-assign]
        approval = {"tool_call": {"display": "rm -rf build"}}
        m.on_event("task_child", "tool_call.pending_approval", approval)
        m.on_event("task_parent", "agent.event", {"event": "tool_call.pending_approval", "payload": approval})
        m.on_event("task_auto", "task.final", {"text": "report"})
        m.on_event("task_auto", "tool_call.pending_approval", approval)
        await asyncio.gather(*m.pending)
        self.assertEqual([(s["title"], s["body"]) for s in sent], [
            ("Fix the build", "Нужно подтверждение: rm -rf build"),
            ("Daily", "Нужно подтверждение: rm -rf build"),
        ])
