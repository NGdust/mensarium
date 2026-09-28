from collections.abc import Callable
from typing import Any, Protocol

from mensarium.contracts.llm import ChatRequest, ModelInfo, ModelResponse, ProviderHealth, ToolDefinition


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    default_model: str

    @property
    def vision_model(self) -> str | None: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def chat(
        self,
        request: ChatRequest,
        *,
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None,
        on_text: Callable[[str], None] | None = None,
    ) -> ModelResponse: ...

    async def healthcheck(self) -> ProviderHealth: ...
