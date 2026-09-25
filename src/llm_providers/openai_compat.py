import asyncio
import json
import logging
from typing import Any

import httpx

from mensarium.contracts.llm import (
    ChatRequest,
    Message,
    ModelInfo,
    ModelResponse,
    ProposedToolCall,
    ProviderHealth,
    TokenUsage,
    ToolDefinition,
)
from mensarium.llm_providers.base import LLMError

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def wire_name(name: str) -> str:
    return name.replace(".", "__")


def domain_name(name: str) -> str:
    return name.replace("__", ".")


def _to_wire(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content or ""}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": wire_name(tc["name"]), "arguments": tc["arguments"]},
            }
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    return out


class OpenAICompatibleProvider:
    """Ollama Cloud, local Ollama and llama.cpp all expose an OpenAI-compatible /v1 API."""

    def __init__(
        self,
        name: str,
        base_url: str,
        default_model: str,
        api_key: str | None = None,
        timeout_s: int = 90,
        max_retries: int = 2,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=timeout_s)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                resp = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as e:
                if attempt >= self.max_retries:
                    raise LLMError(f"transport error: {e}") from e
            else:
                if resp.status_code < 400:
                    return resp.json()
                if resp.status_code not in RETRY_STATUS or attempt >= self.max_retries:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            attempt += 1
            await asyncio.sleep(min(2**attempt, 10))

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/models")
        return [ModelInfo(id=m["id"]) for m in data.get("data", [])]

    async def healthcheck(self) -> ProviderHealth:
        try:
            models = await self.list_models()
        except LLMError as e:
            return ProviderHealth(ok=False, detail=str(e))
        return ProviderHealth(ok=True, detail=f"{len(models)} models available")

    async def chat(
        self,
        request: ChatRequest,
        *,
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
    ) -> ModelResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "system", "content": request.system}]
            + [_to_wire(m) for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": wire_name(t.name), "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        if response_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": response_schema}}
        data = await self._request("POST", "/chat/completions", json=body, timeout=request.timeout_s)
        return self._parse(data)

    @staticmethod
    def _parse(data: dict[str, Any]) -> ModelResponse:
        try:
            choice = data["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected provider response: {str(data)[:300]}") from e
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            raw = fn.get("arguments") or "{}"
            args, err = None, None
            if isinstance(raw, dict):
                args, raw = raw, json.dumps(raw)
            else:
                try:
                    parsed = json.loads(raw)
                    args = parsed if isinstance(parsed, dict) else None
                    err = None if args is not None else "arguments must be a JSON object"
                except json.JSONDecodeError as e:
                    err = str(e)
            calls.append(
                ProposedToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=domain_name(fn.get("name", "")),
                    arguments=args,
                    raw_arguments=raw,
                    parse_error=err,
                )
            )
        usage = data.get("usage")
        finish = choice.get("finish_reason") or "stop"
        return ModelResponse(
            text=msg.get("content"),
            tool_calls=calls,
            finish_reason="tool_calls" if calls else ("length" if finish == "length" else "stop"),
            usage=TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0)
            )
            if usage
            else None,
            raw_provider_response=data,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
