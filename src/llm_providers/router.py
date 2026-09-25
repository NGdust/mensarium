import asyncio
from typing import Any

from mensarium.contracts.llm import ChatRequest, ModelInfo, ModelResponse, ProviderHealth, ToolDefinition
from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider

RETIRE_AFTER_S = 600


class ProviderRouter:
    """The active provider behind a stable object, so the provider can change while the Core runs."""

    def __init__(self, provider: OpenAICompatibleProvider) -> None:
        self.current = provider
        self._retiring: set[asyncio.TimerHandle] = set()

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

    def swap(self, provider: OpenAICompatibleProvider) -> None:
        """Requests already in flight finish on the old client, which is closed a while later."""
        old, self.current = self.current, provider
        loop = asyncio.get_running_loop()
        handle = loop.call_later(RETIRE_AFTER_S, lambda: asyncio.ensure_future(old.aclose()))
        self._retiring.add(handle)

    async def list_models(self) -> list[ModelInfo]:
        return await self.current.list_models()

    async def chat(
        self, request: ChatRequest, *, tools: list[ToolDefinition], response_schema: dict[str, Any] | None = None
    ) -> ModelResponse:
        return await self.current.chat(request, tools=tools, response_schema=response_schema)

    async def healthcheck(self) -> ProviderHealth:
        return await self.current.healthcheck()

    async def aclose(self) -> None:
        for handle in self._retiring:
            handle.cancel()
        await self.current.aclose()
