import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import httpx

from mensarium.contracts.limits import LimitWindow
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
from mensarium.shared.timeutil import now_iso, utcnow

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def _parse_duration(text: str) -> float | None:
    """OpenAI reset headers look like "1s", "6m0s", "1h2m3.5s"."""
    if not text:
        return None
    total, num = 0.0, ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in "hms" and num:
            total += float(num) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
        else:
            return None
    return total if not num else None


def wire_name(name: str) -> str:
    return name.replace(".", "__")


def domain_name(name: str) -> str:
    return name.replace("__", ".")


def _to_wire(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content if m.content is not None else ""}
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
        vision_model: str | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.vision_model = vision_model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=timeout_s)
        self.limits: list[LimitWindow] | None = None
        self.limits_at: str | None = None
        self.limits_source = ""
        self._model_limits: dict[str, list[LimitWindow]] = {}

    async def _request(self, method: str, path: str, model: str | None = None, **kwargs: Any) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                resp = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as e:
                if attempt >= self.max_retries:
                    raise LLMError(f"transport error: {e}") from e
            else:
                if model and "x-ratelimit-limit-tokens" in resp.headers:
                    self._note_headers(model, resp.headers)
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
        data = await self._request("POST", "/chat/completions", model=request.model, json=body, timeout=request.timeout_s)
        return self._parse(data)

    def _note_headers(self, model: str, headers: httpx.Headers) -> None:
        """OpenAI-style x-ratelimit-* headers: per-model requests and tokens per window, reset given as "6m0s"."""
        windows = []
        for what in ("requests", "tokens"):
            limit, remaining = headers.get(f"x-ratelimit-limit-{what}"), headers.get(f"x-ratelimit-remaining-{what}")
            if not limit or remaining is None or not limit.isdigit():
                continue
            total, left = int(limit), int(remaining) if remaining.isdigit() else 0
            reset_s = _parse_duration(headers.get(f"x-ratelimit-reset-{what}", ""))
            windows.append(LimitWindow(
                label=f"{what} per minute", model=model,
                used_percent=round((total - left) / total * 100, 1) if total else 0.0,
                resets_at=(utcnow() + timedelta(seconds=reset_s)).isoformat() if reset_s is not None else None,
                detail=f"{total - left:,} of {total:,}".replace(",", " "),
            ))
        if windows:
            self._model_limits[model] = windows
            self.limits = [w for ws in self._model_limits.values() for w in ws]
            self.limits_at, self.limits_source = now_iso(), "x-ratelimit headers"

    async def fetch_limits(self) -> list[LimitWindow] | None:
        """OpenRouter exposes the key's credit usage; other HTTP providers only report limits on real calls."""
        if "openrouter.ai" not in self.base_url:
            return None
        data = (await self._request("GET", "/key")).get("data") or {}
        usage, limit = float(data.get("usage") or 0), data.get("limit")
        window = LimitWindow(
            label="credits", used_percent=round(usage / float(limit) * 100, 1) if limit else 0.0,
            detail=f"${usage:.2f} of ${float(limit):.2f}" if limit else f"${usage:.2f} spent, no limit set",
        )
        self.limits, self.limits_at, self.limits_source = [window], now_iso(), "openrouter /key"
        return self.limits

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
