from typing import Any, Protocol

from mensarium.contracts.llm import ChatRequest, ModelInfo, ModelResponse, ProviderHealth, ToolDefinition


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    base_url: str
    default_model: str

    async def list_models(self) -> list[ModelInfo]: ...

    async def chat(
        self,
        request: ChatRequest,
        *,
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None,
    ) -> ModelResponse: ...

    async def healthcheck(self) -> ProviderHealth: ...
