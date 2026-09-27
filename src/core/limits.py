"""Usage limits of the connected providers: passive snapshots from real calls plus periodic polls where a provider
answers without spending quota (Codex app-server, OpenRouter key info)."""

import asyncio
import logging
from typing import Any

from mensarium.contracts.limits import WARN_THRESHOLD, LimitWindow, ProviderLimits
from mensarium.core.providers import Providers
from mensarium.llm_providers.base import LLMError
from mensarium.llm_providers.factory import PROVIDER_KINDS, AnyProvider
from mensarium.llm_providers.router import ProviderRouter
from mensarium.shared.timeutil import now_iso, parse_iso, utcnow

log = logging.getLogger(__name__)

POLL_EVERY_S = 600
FIRST_POLL_DELAY_S = 30
PROBE_EVERY_S = 1800
UNSUPPORTED_NOTE = {
    "ollama_cloud": "Ollama Cloud does not expose usage or limits through its API.",
    "ollama_local": "A local server has no usage limits.",
    "llama_cpp": "A local server has no usage limits.",
    "lmstudio": "A local server has no usage limits.",
}
PASSIVE_NOTE = {
    "openai": "Known after the first request: OpenAI reports limits only in response headers.",
    "openai_compatible": "Known after the first request, if the server sends x-ratelimit headers.",
    "claude_code": "Claude subscription usage is fetched through the OAuth usage API every 30 minutes without generating tokens, including when quota is exhausted.",
}
POLLED_KINDS = {"codex_cli", "openrouter"}
PROBED_KINDS = {"claude_code"}


class LimitsStore:
    def __init__(self, providers: Providers, router: ProviderRouter) -> None:
        self.providers = providers
        self.router = router
        self.snapshots: dict[str, ProviderLimits] = {}
        self.task: asyncio.Task[None] | None = None
        router.on_chat = self.observe

    def observe(self, provider: AnyProvider) -> None:
        windows = getattr(provider, "limits", None)
        if windows is None:
            return
        pid = provider.name
        snap = self._base(pid)
        snap.windows = list(windows)
        snap.checked_at = getattr(provider, "limits_at", None) or now_iso()
        snap.source = getattr(provider, "limits_source", "") or snap.source
        snap.error = None
        self.snapshots[pid] = snap

    def _base(self, pid: str) -> ProviderLimits:
        p = self.providers.cfg.llm.providers.get(pid)
        kind = self.providers.kind(pid, p) if p else pid
        meta = PROVIDER_KINDS.get(kind, {})
        old = self.snapshots.get(pid)
        return ProviderLimits(
            provider_id=pid,
            title=str(meta.get("title", kind)),
            kind=kind,
            active=pid == self.providers.cfg.llm.active_provider,
            supported=kind not in UNSUPPORTED_NOTE,
            note=UNSUPPORTED_NOTE.get(kind) or PASSIVE_NOTE.get(kind, ""),
            source=old.source if old else "",
            checked_at=old.checked_at if old else None,
            windows=list(old.windows) if old else [],
            error=old.error if old else None,
        )

    def view(self) -> dict[str, Any]:
        items = [self._base(pid) for pid in self.providers.cfg.llm.providers]
        self.snapshots = {s.provider_id: s for s in items}
        return {
            "threshold": WARN_THRESHOLD,
            "active": self.providers.cfg.llm.active_provider,
            "providers": [s.model_dump() | {"max_used": s.max_used} for s in items],
        }

    async def refresh(self, pid: str | None = None, *, scheduled: bool = False) -> None:
        """Manual refresh polls every supported provider; the scheduled one skips providers that only report limits
        on real requests, and probes Claude only when its snapshot is older than PROBE_EVERY_S."""
        for candidate in list(self.providers.cfg.llm.providers):
            if pid and candidate != pid:
                continue
            kind = self.providers.kind(candidate, self.providers.cfg.llm.providers[candidate])
            if kind in UNSUPPORTED_NOTE:
                continue
            if scheduled:
                if kind in PROBED_KINDS:
                    if self._age_s(candidate) < PROBE_EVERY_S:
                        continue
                elif kind not in POLLED_KINDS:
                    continue
            await self._refresh_one(candidate, kind)

    def _age_s(self, pid: str) -> float:
        snap = self.snapshots.get(pid)
        if not snap or not snap.checked_at or snap.error:
            return float("inf")
        return (utcnow() - parse_iso(snap.checked_at)).total_seconds()

    async def _refresh_one(self, pid: str, kind: str) -> None:
        snap = self._base(pid)
        if pid == self.router.name:
            client, temporary = self.router.current, False
        else:
            client, temporary = self.providers.client(pid), True
        try:
            windows: list[LimitWindow] | None = await client.fetch_limits()
        except LLMError as e:
            snap.error = str(e)
            snap.checked_at = now_iso()
            self.snapshots[pid] = snap
            log.warning("limits refresh failed", extra={"provider": pid, "error": str(e)})
            return
        finally:
            if temporary:
                await client.aclose()
        if windows is not None:
            self.observe(client)
        else:
            snap.checked_at = now_iso()
            self.snapshots[pid] = snap

    async def run_forever(self) -> None:
        await asyncio.sleep(FIRST_POLL_DELAY_S)
        while True:
            try:
                await self.refresh(scheduled=True)
            except Exception:
                log.exception("limits poll failed")
            await asyncio.sleep(POLL_EVERY_S)

    def start(self) -> None:
        self.task = asyncio.create_task(self.run_forever())

    def stop(self) -> None:
        if self.task:
            self.task.cancel()
