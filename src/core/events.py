import asyncio
from collections import defaultdict
from typing import Any

from mensarium.core.repo import Repo
from mensarium.shared.timeutil import now_iso

DRAFT_FLUSH_S = 0.08


def live_record(task_id: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A live-only event: not stored, so it has no seq and replays never show it."""
    return {"seq": None, "event": event, "task_id": task_id, "payload": payload, "created_at": now_iso()}


class EventBus:
    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        # sub-agent task id -> parent task id: a child's events are mirrored into the parent's stream as agent.event
        self.parents: dict[str, str] = {}
        self.drafts: dict[str, Draft] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subs[task_id].add(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs[task_id].discard(q)
        if not self._subs[task_id]:
            self._subs.pop(task_id, None)

    async def emit(self, task_id: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = await self.repo.add_event(task_id, event, payload)
        self._deliver(task_id, record)
        if parent := self.parents.get(task_id):
            await self.emit(parent, "agent.event", {"agent_id": task_id, "event": event, "payload": payload})
        return record

    def publish(self, task_id: str, event: str, payload: dict[str, Any]) -> None:
        self._deliver(task_id, live_record(task_id, event, payload))

    def _deliver(self, task_id: str, record: dict[str, Any]) -> None:
        for q in list(self._subs.get(task_id, ())):
            if not q.full():
                q.put_nowait(record)

    def draft(self, task_id: str, request: int) -> "Draft":
        self.drafts[task_id] = Draft(self, task_id, request)
        return self.drafts[task_id]


class Draft:
    """The answer the model is writing for the llm.request with seq `request`. It reaches live subscribers as
    llm.delta events a little batched; the stored llm.response that follows replaces it."""

    def __init__(self, bus: EventBus, task_id: str, request: int) -> None:
        self.bus, self.task_id, self.request = bus, task_id, request
        self.text = ""
        self.sent = 0
        self._flush: asyncio.TimerHandle | None = None

    def feed(self, piece: str) -> None:
        self.text += piece
        if self._flush is None and not self.text.lstrip().startswith("{"):  # "{" opens a tool call written as JSON
            self._flush = asyncio.get_running_loop().call_later(DRAFT_FLUSH_S, self.flush)

    def flush(self) -> None:
        self._flush = None
        if self.sent < len(self.text):
            self.bus.publish(self.task_id, "llm.delta", {"request": self.request, "offset": self.sent, "text": self.text[self.sent :]})
            self.sent = len(self.text)

    def snapshot(self) -> dict[str, Any]:
        """What was sent so far, as one live event for a subscriber that joined mid-answer."""
        return live_record(self.task_id, "llm.delta", {"request": self.request, "offset": 0, "text": self.text[: self.sent]})

    def close(self) -> None:
        if self._flush:
            self._flush.cancel()
        if self.bus.drafts.get(self.task_id) is self:
            del self.bus.drafts[self.task_id]
