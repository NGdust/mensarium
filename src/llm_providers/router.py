import asyncio
from collections.abc import Callable
from typing import Any

from mensarium.contracts.llm import ChatRequest, ModelInfo, ModelResponse, ProviderHealth, ToolDefinition
from mensarium.llm_providers.cli_provider import CliProvider
from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider

AnyProvider = OpenAICompatibleProvider | CliProvider

RETIRE_AFTER_S = 600


class ProviderRouter:
    """The default provider behind a stable object, so it can change while the Core runs,
    plus lazily built clients of the other providers for chats that picked them."""

    def __init__(self, provider: AnyProvider, build: Callable[[str], AnyProvider]) -> None:
        self.current = provider
        self.build = build
        self.others: dict[str, AnyProvider] = {}
        self._retiring: set[asyncio.TimerHandle] = set()
        self.on_chat: Callable[[AnyProvider], None] | None = None

    @property
    def name(self) -> str:
        return self.current.name

    @property
    def base_url(self) -> str:
        return self.current.base_url

    @property
    def default_model(self) -> str:
        return self.current.default_model

    @default_model.setter
    def default_model(self, value: str) -> None:
        self.current.default_model = value

    @property
    def vision_model(self) -> str | None:
        return self.current.vision_model

    def get(self, pid: str | None = None) -> AnyProvider:
        if not pid or pid == self.current.name:
            return self.current
        if pid not in self.others:
            self.others[pid] = self.build(pid)
        return self.others[pid]

    def _retire(self, old: AnyProvider) -> None:
        loop = asyncio.get_running_loop()
        handle = loop.call_later(RETIRE_AFTER_S, lambda: asyncio.ensure_future(old.aclose()))
        self._retiring.add(handle)

    def swap(self, provider: AnyProvider) -> None:
        """Requests already in flight finish on the old client, which is closed a while later."""
        old, self.current = self.current, provider
        self._retire(old)
        self.drop(provider.name)

    def drop(self, pid: str) -> None:
        """Forget a non-default client after its settings changed or it was removed."""
        if old := self.others.pop(pid, None):
            self._retire(old)

    async def list_models(self) -> list[ModelInfo]:
        return await self.current.list_models()

    async def chat(
        self,
        request: ChatRequest,
        *,
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
        provider_id: str | None = None,
    ) -> ModelResponse:
        provider = self.get(provider_id)
        try:
            return await provider.chat(request, tools=tools, response_schema=response_schema)
        finally:
            if self.on_chat:
                self.on_chat(provider)

    async def healthcheck(self) -> ProviderHealth:
        return await self.current.healthcheck()

    async def aclose(self) -> None:
        for handle in self._retiring:
            handle.cancel()
        await self.current.aclose()
        for other in self.others.values():
            await other.aclose()
