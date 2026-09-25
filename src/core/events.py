import asyncio
from collections import defaultdict
from typing import Any

from mensarium.core.repo import Repo


class EventBus:
    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        # sub-agent task id -> parent task id: a child's events are mirrored into the parent's stream as agent.event
        self.parents: dict[str, str] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subs[task_id].add(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs[task_id].discard(q)
        if not self._subs[task_id]:
            self._subs.pop(task_id, None)

    async def emit(self, task_id: str, event: str, payload: dict[str, Any]) -> None:
        record = await self.repo.add_event(task_id, event, payload)
        for q in list(self._subs.get(task_id, ())):
            if not q.full():
                q.put_nowait(record)
        if parent := self.parents.get(task_id):
            await self.emit(parent, "agent.event", {"agent_id": task_id, "event": event, "payload": payload})
